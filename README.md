# Video Công Thức

Công cụ Windows quét video Facebook, lọc chỉ số viral, phân tích công thức bằng Jev/LLM và xuất Excel. Giao diện HTML/CSS/JS chạy trong cửa sổ pywebview, dùng Microsoft Edge WebView2 Runtime. Chạy từ mã nguồn cần Python 3.11, Internet và `ffmpeg.exe` trong PATH. WebView2 thường có sẵn trên Windows 10/11 có Edge; nếu thiếu, cài [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). Hướng dẫn người dùng: [docs/HUONG-DAN.md](docs/HUONG-DAN.md); đặc tả: [docs/PLAN-JEV.md](docs/PLAN-JEV.md).

## Cấu trúc thư mục

- `backend/main.py`: điểm vào cửa sổ pywebview, kiểm tra bộ cài/WebView2 và xác nhận khi đóng lúc đang quét.
- `backend/core/`: cấu hình, dữ liệu và tiện ích nền tảng; `backend/services/`: pipeline, dịch vụ AI và xuất Excel.
- `backend/collectors/`: thu thập Facebook, phụ đề và chuẩn bị trình duyệt; `backend/assets/`: tài nguyên ứng dụng.
- `backend/api/__init__.py`: cầu nối `Bridge` giữa JavaScript và Python, kèm hộp thoại chọn/lưu tệp của Windows. Các mô-đun `app_state`, `services`, `channels`, `taxonomy`, `logs`, `scan`, `results` xử lý từng nhóm chức năng; `common` chứa tiện ích chung.
- `frontend/index.html`, `frontend/css/`: giao diện và kiểu hiển thị; `frontend/js/main.js`: khung ứng dụng, điều hướng và nhật ký; `api.js`, `store.js`: gọi cầu nối và quản lý trạng thái.
- `frontend/js/components/`: thành phần dùng chung; `frontend/js/pages/settings/`, `scan/`, `results/`: các trang Cài đặt, Chạy quét và Kết quả.
- `frontend/js/mock/`: dữ liệu và hành vi mô phỏng (`index.js`, `app.js`, `settings.js`, `scan.js`, `results.js`) để xem giao diện bằng trình duyệt, không chạy quét thật.
- `config/`: mẫu cấu hình; `data/`, `output/`, `profile/`: dữ liệu khi chạy từ mã nguồn (gitignore).
- `tests/`: kiểm thử; `tools/`: công cụ thu fixture.
- `docs/`: hướng dẫn người dùng (Markdown + PDF, ảnh trong `docs/img/`) và đặc tả.
- `build.ps1`, `VideoCongThuc.spec`: đóng gói exe.

## Thiết lập (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

`requirements.txt` ghim phiên bản đã kiểm thử để bản build lặp lại được. Khi Facebook đổi định dạng khiến yt-dlp lỗi, nâng riêng `yt-dlp` lên bản mới, chạy lại `pytest` rồi cập nhật số phiên bản trong tệp.

Nhập key Jev, Deepgram, LLM và endpoint/model LLM trong tab **Cài đặt**; không ghi key vào mã nguồn hay tệp cấu hình. Đăng nhập Facebook bằng tài khoản phụ trước khi quét.

Trình duyệt quét dùng Edge nếu có. Nếu không có Edge, ứng dụng chuẩn bị Chromium khi mở lần đầu. WebView2 là bộ máy hiển thị cửa sổ ứng dụng, khác với trình duyệt dùng để quét.

## Chạy và kiểm thử

```powershell
python -m backend.main
# Hoặc chạy pipeline từ dòng lệnh:
python -m backend.services.pipeline

pytest
# Thu fixture Facebook để cập nhật parser (cần đăng nhập):
python tools/capture_feed.py
```

Fixture thật có thể chứa dữ liệu riêng; giữ trong `tests/fixtures/live/` đã được gitignore và loại bỏ cookie/thông tin cá nhân trước khi chia sẻ.

### Xem trước giao diện khi phát triển

Frontend dùng JavaScript thuần, không cần bước build. Chạy một máy chủ tĩnh từ thư mục repo, ví dụ:

```powershell
python -m http.server -d frontend
```

Mở `http://localhost:8000/index.html?mock=1`. Có thể dùng máy chủ tĩnh khác và thêm `?mock=1` vào đường dẫn `/index.html`. Chế độ này dùng dữ liệu mô phỏng, không gọi dịch vụ AI, không đăng nhập Facebook và không chạy quét thật. Để dùng đầy đủ cầu nối Python và hộp thoại tệp của Windows, chạy `python -m backend.main`.

## Mã nguồn tham khảo

`reference/` không nằm trong Git hay bản phát hành. Khi cần đối chiếu, clone các repository trong bảng PLAN §11 vào `reference/<tên-repo>/` và checkout đúng commit đã ghi. Repo không có LICENSE chỉ được đọc, không sao chép; giữ ghi nhận bản quyền của các phần được phép sử dụng trong `THIRD_PARTY_NOTICES.txt`.

## Đóng gói Windows

Sau khi thiết lập `.venv` và ffmpeg trong PATH, chạy tại repo:

```powershell
.\build.ps1
```

Script dùng `VideoCongThuc.spec` để build **onedir**, chép đúng các mẫu `config/`, hướng dẫn và notices, kèm ffmpeg rồi tạo `dist/VideoCongThuc.zip`. Cạnh `VideoCongThuc.exe` chỉ có `HUONG-DAN.pdf` và các thư mục dữ liệu; mã, DLL, assets, ffmpeg, hướng dẫn Markdown và notices nằm trong `app/` (`config.BUNDLE_DIR`). `HUONG-DAN.pdf` được kèm nếu có. Không đóng gói `reference/`, `.venv` hay dữ liệu/phiên đăng nhập đang dùng; `data/`, `output/`, `profile/` trong bản ZIP là thư mục rỗng. Nếu một bản ứng dụng trong `dist/VideoCongThuc/` đã có dữ liệu người dùng, script từ chối ghi đè: chuyển nguyên bản đó ra ngoài `dist/` trước khi build lại.
