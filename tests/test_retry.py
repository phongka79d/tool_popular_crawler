"""Offline tests for retry.py: fake sleep, fake exceptions that carry status codes."""
from __future__ import annotations

import types

import pytest
import requests

from errors import AuthError, NetworkError, NotFoundError, QuotaError
from retry import classify_status, parse_retry_after, with_retry


class ApiStatusError(Exception):
    """Mimics openai/typesafe APIStatusError: `.status_code`, `.body`, `.response.headers`."""

    def __init__(self, status_code: int, headers: dict | None = None, body=None) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body
        self.response = types.SimpleNamespace(status_code=status_code, headers=headers or {})


class RateLimitError(Exception):
    """typesafe-style error without a status attribute; only the class name identifies it."""


class AuthenticationError(Exception):
    """typesafe-style 401 identified by class name only."""


class APITimeoutError(Exception):
    """openai/typesafe timeout."""


class APIConnectionError(Exception):
    """openai/typesafe connection failure."""


def requests_error(status: int, headers: dict | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    return requests.HTTPError(f"{status} error", response=response)


class Flaky:
    """Raises queued errors in order, then returns `result`. With `always`, raises that error on every call."""

    def __init__(
        self,
        *errors: BaseException,
        result: str = "ok",
        always: BaseException | None = None,
    ) -> None:
        self.queue = list(errors)
        self.result = result
        self.always = always
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.always is not None:
            raise self.always
        if self.queue:
            raise self.queue.pop(0)
        return self.result


@pytest.fixture
def sleeps() -> list[float]:
    return []


def run(fn: Flaky, sleeps: list[float], service: str = "jev", **kwargs) -> str:
    return with_retry(fn, service=service, sleep=sleeps.append, **kwargs)


@pytest.mark.parametrize("make_error", [lambda: ApiStatusError(401), lambda: requests_error(401)],
                         ids=["openai-style", "requests"])
def test_401_maps_to_auth_error_without_retry(make_error, sleeps):
    fn = Flaky(always=make_error())
    with pytest.raises(AuthError) as info:
        run(fn, sleeps)
    assert info.value.service == "jev"
    assert str(info.value) == "API key [Jev] không hợp lệ. Vào Cài đặt để nhập lại."
    assert fn.calls == 1
    assert sleeps == []


def test_403_maps_to_auth_error(sleeps):
    fn = Flaky(always=ApiStatusError(403))
    with pytest.raises(AuthError):
        run(fn, sleeps)
    assert fn.calls == 1


def test_404_maps_to_not_found_with_llm_message(sleeps):
    fn = Flaky(always=ApiStatusError(404))
    with pytest.raises(NotFoundError) as info:
        run(fn, sleeps, service="llm")
    assert str(info.value) == "Không tìm thấy endpoint hoặc model LLM. Kiểm tra lại địa chỉ và tên model."
    assert fn.calls == 1
    assert sleeps == []


def test_402_maps_to_quota_error_without_retry(sleeps):
    fn = Flaky(always=ApiStatusError(402))
    with pytest.raises(QuotaError) as info:
        run(fn, sleeps, service="deepgram")
    assert str(info.value) == "Tài khoản [Deepgram] đã hết credit/hạn mức."
    assert fn.calls == 1
    assert sleeps == []


def test_429_honors_retry_after_then_succeeds(sleeps):
    fn = Flaky(ApiStatusError(429, {"Retry-After": "7"}))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [7.0]
    assert fn.calls == 2


def test_429_from_requests_honors_retry_after(sleeps):
    fn = Flaky(requests_error(429, {"Retry-After": "2"}))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [2.0]


def test_retry_after_header_name_is_case_insensitive(sleeps):
    fn = Flaky(ApiStatusError(429, {"retry-after": "3"}))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [3.0]


def test_429_without_retry_after_doubles_delay(sleeps):
    fn = Flaky(ApiStatusError(429), ApiStatusError(429), ApiStatusError(429))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [1.0, 2.0, 4.0]
    assert fn.calls == 4


def test_six_consecutive_429_raise_quota_error(sleeps):
    fn = Flaky(always=ApiStatusError(429))
    with pytest.raises(QuotaError) as info:
        run(fn, sleeps)
    assert fn.calls == 6
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert str(info.value) == "Tài khoản [Jev] đã hết credit/hạn mức."


def test_529_shares_the_rate_budget(sleeps):
    fn = Flaky(always=ApiStatusError(529))
    with pytest.raises(QuotaError):
        run(fn, sleeps)
    assert fn.calls == 6


def test_rate_retry_budget_is_configurable(sleeps):
    fn = Flaky(always=ApiStatusError(429))
    with pytest.raises(QuotaError):
        run(fn, sleeps, max_rate_retries=2)
    assert fn.calls == 3
    assert sleeps == [1.0, 2.0]


def test_out_of_credit_429_is_quota_error_without_retry(sleeps):
    body = {"error": {"code": "insufficient_quota"}}
    fn = Flaky(always=ApiStatusError(429, body=body))
    with pytest.raises(QuotaError):
        run(fn, sleeps)
    assert fn.calls == 1
    assert sleeps == []


def test_typesafe_rate_limit_without_status_is_retried(sleeps):
    fn = Flaky(RateLimitError("slow down"))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [1.0]


def test_typesafe_authentication_error_maps_to_auth_error(sleeps):
    fn = Flaky(always=AuthenticationError("bad key"))
    with pytest.raises(AuthError):
        run(fn, sleeps)
    assert fn.calls == 1


def test_class_named_not_found_without_status_maps_to_not_found(sleeps):
    sdk_not_found = type("NotFoundError", (Exception,), {})
    fn = Flaky(always=sdk_not_found("no such model"))
    with pytest.raises(NotFoundError):
        run(fn, sleeps, service="llm")
    assert fn.calls == 1


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: APITimeoutError("timed out"),
        lambda: requests.exceptions.Timeout("timed out"),
        lambda: requests.exceptions.ReadTimeout("read timed out"),
    ],
    ids=["openai-typesafe", "requests-timeout", "requests-read-timeout"],
)
def test_timeout_retried_three_times_then_network_error(make_error, sleeps):
    fn = Flaky(always=make_error())
    with pytest.raises(NetworkError) as info:
        run(fn, sleeps)
    assert fn.calls == 4  # first call + 3 retries
    assert sleeps == [1.0, 2.0, 4.0]
    assert str(info.value) == "Không kết nối được tới [Jev]."


def test_connection_errors_recover_on_retry(sleeps):
    fn = Flaky(requests.exceptions.ConnectionError("connection reset"), APIConnectionError("dns"))
    assert run(fn, sleeps) == "ok"
    assert sleeps == [1.0, 2.0]


def test_5xx_exhausts_to_network_error(sleeps):
    fn = Flaky(always=ApiStatusError(503))
    with pytest.raises(NetworkError):
        run(fn, sleeps)
    assert fn.calls == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_400_is_reraised_immediately(sleeps):
    error = ApiStatusError(400)
    fn = Flaky(always=error)
    with pytest.raises(ApiStatusError) as info:
        run(fn, sleeps)
    assert info.value is error
    assert fn.calls == 1
    assert sleeps == []


def test_unrelated_exception_is_not_retried(sleeps):
    fn = Flaky(always=ValueError("bad input"))
    with pytest.raises(ValueError):
        run(fn, sleeps)
    assert fn.calls == 1
    assert sleeps == []


def test_service_error_from_fn_passes_through_untouched(sleeps):
    error = NetworkError("llm", "Không kết nối được tới [LLM].")
    fn = Flaky(always=error)
    with pytest.raises(NetworkError) as info:
        run(fn, sleeps, service="llm")
    assert info.value is error
    assert fn.calls == 1
    assert sleeps == []


def test_success_on_first_call_does_not_sleep(sleeps):
    fn = Flaky(result="xong")
    assert run(fn, sleeps) == "xong"
    assert fn.calls == 1
    assert sleeps == []


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, "", AuthError),
        (403, "", AuthError),
        (402, "", QuotaError),
        (404, "", NotFoundError),
        (429, "", None),
        (429, "insufficient_quota", QuotaError),
        (529, "", None),
        (500, "", NetworkError),
        (503, "", NetworkError),
        (400, "", None),
        (422, "", None),
        (200, "", None),
    ],
)
def test_classify_status_table(status, body, expected):
    error = classify_status("jev", status, body)
    if expected is None:
        assert error is None
    else:
        assert type(error) is expected
        assert error.service == "jev"


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("5", 5.0), (" 2.5 ", 2.5), ("-3", 0.0), ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0)],
)
def test_parse_retry_after_seconds_and_past_dates(raw, seconds):
    assert parse_retry_after(raw) == seconds


@pytest.mark.parametrize("raw", ["soon", "inf", "nan"])
def test_parse_retry_after_rejects_unreadable_values(raw):
    assert parse_retry_after(raw) is None
