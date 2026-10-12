"""Parse Facebook GraphQL responses and inlined ``data-sjs`` JSON into video records.

Pure functions, no browser. Every JSON path is data in ``config/graphql_paths.json``
(see ``load_paths``); this module only walks those paths.

Behaviour fixed in code, not config:
- A Story node (``__typename`` == story typename with a post_id) is collected once per
  post_id; duplicates fill missing fields without overwriting non-empty values.
  A collected story is not searched further: its nested stories belong to another page.
- Deferred fragments (``@defer`` payloads such as the Reels tab counters) carry no typename,
  only the Story's GraphQL node ``id``; a dict with that id fills the Story the same way.
- Counts are read from the merge of every block that the ``feedback`` paths reach.
- A count that is absent stays None (unknown), never 0, so the caller can fill it from yt-dlp.
- The Videos tab sends channel tiles (renderer typenames in ``channel_video``) whose video node
  is not a Story; each tile becomes one record, merged by video_id with any Story record.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import config
from normalize import parse_count

log = logging.getLogger(__name__)

Key = str | int
Alternatives = list[list[Key]]

_CONFIG_NAME = "graphql_paths.json"
_TYPENAME_KEY = "__typename"  # GraphQL protocol key, not a Facebook field
_NODE_ID_KEY = "id"  # GraphQL protocol key: global node id shared by a Story and its deferred fragments
_WILDCARD = "*"  # path element: every item of a list
_JSON_SPACE = " \r\n\t"
_SJS_RE = re.compile(
    r"<script\b[^>]*?\sdata-sjs(?=[\s/>=])[^>]*>(.*?)</script\s*>",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class ReactionPaths:
    total: Alternatives  # exact total of all reactions, relative to feedback
    edges: Alternatives  # per-type list, relative to feedback
    edge_count: Alternatives  # reaction count of one edge
    edge_id: Alternatives  # reaction type id of one edge
    edge_name: Alternatives  # localized name of one edge (used when the id is unknown)
    approx: Alternatives  # display string such as "4,1 N" (last resort)
    by_id: dict[str, str]  # reaction id -> reaction type
    by_name: dict[str, str]  # localized name -> reaction type


@dataclass(frozen=True)
class ChannelVideoPaths:
    renderer_typenames: list[str]  # Videos-tab tiles that each hold one video node
    video: Alternatives  # relative to the tile: the video node
    video_id: Alternatives  # the rest are relative to the video node
    creation_time: Alternatives
    permalink_url: Alternatives
    message: Alternatives
    views: Alternatives
    feedback: Alternatives  # reactions/comments/shares then use the shared counter paths
    duration_ms: Alternatives
    duration_s: Alternatives

@dataclass(frozen=True)
class GraphqlPaths:
    story_typename: str
    video_typename: str
    post_id: Alternatives  # relative to story
    creation_time: Alternatives  # relative to story, unix seconds
    permalink_url: Alternatives  # relative to story
    fallback_url: str  # used when the story has no permalink; "{video_id}" placeholder
    reel_url_marker: str  # a url containing this marker is a reel
    message: Alternatives  # relative to story, caption text
    feedback: Alternatives  # relative to story, the counter block that the counts start from
    media_typename: Alternatives  # relative to story; a Video media makes the story a video
    video_markers: Alternatives  # relative to feedback; any non-null value marks a video
    duration_ms: Alternatives  # relative to story, milliseconds (preferred)
    duration_s: Alternatives  # relative to story, seconds (fallback)
    views: Alternatives  # relative to feedback
    comments: Alternatives  # relative to feedback
    shares: Alternatives  # relative to feedback
    reactions: ReactionPaths  # relative to feedback
    page_typenames: list[str]  # page header: node typenames to read
    page_name: Alternatives  # relative to a page node
    page_followers: Alternatives  # relative to a page node
    channel_video: ChannelVideoPaths


def load_paths() -> GraphqlPaths:
    """Load config/graphql_paths.json. Read on each call, so edits apply without a rebuild."""
    raw = dict(config.load_json(_CONFIG_NAME))
    raw.pop("_doc", None)
    try:
        reactions = ReactionPaths(**raw.pop("reactions"))
        channel_video = ChannelVideoPaths(**raw.pop("channel_video"))
        return GraphqlPaths(**raw, reactions=reactions, channel_video=channel_video)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{_CONFIG_NAME} sai cấu trúc: {exc}") from exc


def split_json_values(text: str) -> list:
    """Decode every JSON object or array in ``text``, in document order.

    Facebook sends several JSON values back to back with no wrapping array, so
    ``json.loads`` fails with "Extra data". Text between values (for example the
    ``for (;;);`` prefix) is skipped one character at a time. Scalars are dropped.
    """
    decoder = json.JSONDecoder()
    values: list = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in _JSON_SPACE:
            i += 1
            continue
        try:
            value, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(value, (dict, list)):
            values.append(value)
    return values


def extract_stories(obj: Any, paths: GraphqlPaths | None = None) -> list[dict]:
    """Story nodes in first-seen post_id order, with missing fields filled by duplicates
    and by deferred fragments that share the Story's node id.

    ``obj`` is any decoded JSON value, typically the list from ``split_json_values``.
    """
    p = paths if paths is not None else load_paths()
    stories: list[dict] = []
    positions: dict[str, int] = {}
    node_ids: dict[str, int] = {}
    for node in _walk_dicts(obj, stop=lambda d: _story_id(d, p) is not None):
        post_id = _story_id(node, p)
        if post_id is None:
            continue
        if post_id in positions:
            index = positions[post_id]
            stories[index] = _merge_story_fields(stories[index], node)
            continue
        positions[post_id] = len(stories)
        node_id = node.get(_NODE_ID_KEY)
        if isinstance(node_id, str):
            node_ids[node_id] = len(stories)
        stories.append(node)
    if node_ids:
        def fragment_of(d: dict) -> int | None:
            node_id = d.get(_NODE_ID_KEY)
            return node_ids.get(node_id) if isinstance(node_id, str) and _story_id(d, p) is None else None

        # Stop at stories (already collected) and at fragments (merged whole).
        for node in _walk_dicts(obj, stop=lambda d: _story_id(d, p) is not None or fragment_of(d) is not None):
            index = fragment_of(node)
            if index is not None:
                stories[index] = _merge_story_fields(stories[index], node)
    return stories


def _merge_story_fields(first: dict, later: dict) -> dict:
    """Fill empty fields recursively, preserving conflicts and leaving inputs untouched.

    Non-empty lists are kept intact: their positions need not identify the same
    attachments or reactions in different Story projections. Zero and False are
    populated values, not missing counts or flags.
    """
    merged = first
    for key, value in later.items():
        current = first.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            replacement = _merge_story_fields(current, value)
            if replacement is current:
                continue
        elif (
            current is None
            or isinstance(current, str) and not current.strip()
            or isinstance(current, (dict, list)) and not current
        ):
            replacement = value
            if key in first and replacement == current:
                continue
        else:
            continue
        if merged is first:
            merged = first.copy()
        merged[key] = replacement
    return merged


def flatten(story: dict, paths: GraphqlPaths | None = None) -> dict | None:
    """Flatten one Story node into a video or non-video post record.

    Counts that the story does not carry are None (unknown), never 0.
    """
    if not isinstance(story, dict):
        return None
    p = paths if paths is not None else load_paths()
    video_id = _first(story, p.post_id, _as_id)
    if video_id is None:
        return None
    feedback = _merged(story, p.feedback)
    caption = _first(story, p.message, _as_text)
    is_video = _is_video(story, feedback, p)
    if not caption and any(
        node.get("attached_story") or node.get("shared_story")
        or isinstance(node.get("target"), dict) and node["target"].get(_TYPENAME_KEY) == p.story_typename
        for node in _walk_dicts(story)
    ):
        return None
    fallback = p.fallback_url.format(video_id=video_id) if is_video else f"https://www.facebook.com/{video_id}"
    url = _first(story, p.permalink_url, _as_text) or fallback
    if not is_video:
        if not caption:
            return None  # sự kiện, ảnh trống chữ: không có gì để phân tích
        record = _record(video_id, url, _first(story, p.creation_time, _as_int), caption,
                         None, feedback, None, p)
        record["format"] = "post"
        return record
    return _record(video_id, url, _first(story, p.creation_time, _as_int), caption,
                   _first(feedback, p.views, _as_count), feedback,
                   _duration(story, p.duration_ms, p.duration_s), p)


def flatten_channel_video(video: dict, paths: GraphqlPaths | None = None) -> dict | None:
    """Flatten one Videos-tab video node (not a Story) into a video record."""
    if not isinstance(video, dict):
        return None
    p = paths if paths is not None else load_paths()
    c = p.channel_video
    video_id = _first(video, c.video_id, _as_id)
    if video_id is None:
        return None
    feedback = _merged(video, c.feedback)
    url = _first(video, c.permalink_url, _as_text) or p.fallback_url.format(video_id=video_id)
    views = _first(video, c.views, _as_count)
    if views is None:
        views = _first(feedback, p.views, _as_count)
    return _record(video_id, url, _first(video, c.creation_time, _as_int), _first(video, c.message, _as_text),
                   views, feedback, _duration(video, c.duration_ms, c.duration_s), p)


def _merged(node: dict, alternatives: Alternatives) -> dict:
    merged: dict = {}
    for block in _all_values(node, alternatives):
        if isinstance(block, dict):
            merged = _merge_story_fields(merged, block)
    return merged


def _duration(node: dict, ms_paths: Alternatives, s_paths: Alternatives) -> float | None:
    duration_ms = _first(node, ms_paths, _as_number)
    return duration_ms / 1000 if duration_ms is not None else _first(node, s_paths, _as_number)


def _record(video_id: str, url: str, posted_at: int | None, caption: str | None, views: int | None,
            feedback: dict, duration_s: float | None, p: GraphqlPaths) -> dict:
    return {
        "video_id": video_id,
        "url": url,
        "posted_at": posted_at,
        "caption": caption or "",
        "views": views,
        "reactions": _reactions(feedback, p.reactions),
        "comments": _first(feedback, p.comments, _as_count),
        "shares": _first(feedback, p.shares, _as_count),
        "duration_s": duration_s,
        "format": "reel" if p.reel_url_marker in url else "video",
    }


def parse_graphql_response(text: str, paths: GraphqlPaths | None = None) -> list[dict]:
    """Posts and videos from one ``/api/graphql/`` response, one record per video_id."""
    p = paths if paths is not None else load_paths()
    return _videos_from(split_json_values(text), p)


def parse_initial_html(html: str, paths: GraphqlPaths | None = None) -> list[dict]:
    """Posts and videos from the first page load's ``<script data-sjs>`` blobs."""
    p = paths if paths is not None else load_paths()
    return _videos_from(_sjs_values(html), p)


def parse_page_header(html_or_json: str, paths: GraphqlPaths | None = None) -> dict:
    """Best-effort page name and follower count.

    Accepts an HTML page (``data-sjs`` blobs are read) or a raw JSON response.
    Missing fields come back as ``""`` for the name and ``None`` for the followers.
    """
    p = paths if paths is not None else load_paths()
    if _SJS_RE.search(html_or_json):
        values = _sjs_values(html_or_json)
    else:
        values = split_json_values(html_or_json)
    name = ""
    followers: int | None = None
    for node in _walk_dicts(values):
        if node.get(_TYPENAME_KEY) not in p.page_typenames:
            continue
        name = name or _first(node, p.page_name, _as_text) or ""
        if followers is None:
            followers = _first(node, p.page_followers, _as_count)
        if name and followers is not None:
            break
    return {"name": name, "followers": followers}


def _videos_from(values: list, p: GraphqlPaths) -> list[dict]:
    stories = extract_stories(values, p)
    videos = [video for video in (flatten(story, p) for story in stories) if video is not None]
    by_id = {video["video_id"]: video for video in videos}
    tiles = 0
    for tile in _walk_dicts(values):
        if tile.get(_TYPENAME_KEY) not in p.channel_video.renderer_typenames:
            continue
        for node in _all_values(tile, p.channel_video.video):
            record = flatten_channel_video(node, p)
            if record is None:
                continue
            tiles += 1
            existing = by_id.get(record["video_id"])
            if existing is None:
                by_id[record["video_id"]] = record
                videos.append(record)
                continue
            for key, value in record.items():
                if existing.get(key) in (None, "") and value not in (None, ""):
                    existing[key] = value
    log.debug("GraphQL: %d story, %d tile, %d video", len(stories), tiles, len(videos))
    return videos


def _sjs_values(html: str) -> list:
    values: list = []
    for match in _SJS_RE.finditer(html):
        values.extend(split_json_values(match.group(1)))
    return values


def _walk_dicts(root: Any, stop: Callable[[dict], bool] | None = None) -> Iterator[dict]:
    """Yield every dict under ``root`` in document order.

    A dict for which ``stop`` is true is yielded, but its children are not visited.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            if stop is not None and stop(node):
                continue
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))


def _story_id(node: dict, p: GraphqlPaths) -> str | None:
    if node.get(_TYPENAME_KEY) != p.story_typename:
        return None
    return _first(node, p.post_id, _as_id)


def _values(node: Any, path: list[Key]) -> list[Any]:
    """Every non-None value reached by ``path``. ``"*"`` fans out over the items of a list."""
    current = [node]
    for key in path:
        reached: list[Any] = []
        for item in current:
            if key == _WILDCARD:
                if isinstance(item, list):
                    reached.extend(item)
            elif isinstance(item, dict):
                reached.append(item.get(key))
            elif isinstance(item, list) and isinstance(key, int) and -len(item) <= key < len(item):
                reached.append(item[key])
        current = [value for value in reached if value is not None]
    return current


def _all_values(node: Any, alternatives: Alternatives) -> list[Any]:
    return [value for path in alternatives for value in _values(node, path)]


def _first(node: Any, alternatives: Alternatives, convert: Callable[[Any], Any]) -> Any:
    """First value, over the alternative paths in order, that ``convert`` accepts."""
    for path in alternatives:
        for raw in _values(node, path):
            result = convert(raw)
            if result is not None:
                return result
    return None


def _is_video(story: dict, feedback: dict, p: GraphqlPaths) -> bool:
    if p.video_typename in _all_values(story, p.media_typename):
        return True
    return any(_values(feedback, path) for path in p.video_markers)


def _reactions(feedback: dict, r: ReactionPaths) -> int | None:
    total = _first(feedback, r.total, _as_count)
    if total is not None:
        return total
    edges = _first(feedback, r.edges, _as_list)
    if edges:
        by_kind: dict[str, int] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            kind = _reaction_kind(edge, r)
            count = _first(edge, r.edge_count, _as_count)
            if kind is not None and count is not None:
                by_kind[kind] = count
        if by_kind:
            return sum(by_kind.values())
    approx = _first(feedback, r.approx, _as_count)
    if approx is not None:
        return approx
    return 0 if edges == [] else None


def _reaction_kind(edge: dict, r: ReactionPaths) -> str | None:
    reaction_id = _first(edge, r.edge_id, _as_id)
    if reaction_id is not None and reaction_id in r.by_id:
        return r.by_id[reaction_id]
    name = _first(edge, r.edge_name, _as_text)
    if name is None:
        return None
    return r.by_name.get(name.strip())


def _as_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_count(value: Any) -> int | None:
    """An exact integer, or a localized display string such as "1,2 Tr" (via parse_count)."""
    number = _as_int(value)
    if number is not None:
        return number
    if isinstance(value, str) and value.strip():
        return parse_count(value)
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _as_dict(value: Any) -> dict | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list | None:
    return value if isinstance(value, list) else None
