# Video Công Thức

Công cụ Windows quét video Facebook, lọc chỉ số viral, phân tích công thức bằng Jev/LLM và xuất Excel. Yêu cầu Python 3.11, Internet và `ffmpeg.exe` trong PATH. Hướng dẫn người dùng: [docs/HUONG-DAN.md](docs/HUONG-DAN.md); đặc tả: [docs/PLAN-JEV.md](docs/PLAN-JEV.md).

## Cấu trúc thư mục

- `src/`: mã nguồn (`app.py` giao diện, `pipeline.py`, `collectors/`, …) và `assets/`.
- `config/`: mẫu cấu hình; `data/`, `output/`, `profile/`: dữ liệu khi chạy từ mã nguồn (gitignore).
- `tests/`, `tools/`: kiểm thử và công cụ thu fixture.
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

## Chạy và kiểm thử

```powershell
streamlit run src/app.py
# Hoặc chạy pipeline từ dòng lệnh:
python src/pipeline.py

pytest
# Thu fixture Facebook để cập nhật parser (cần đăng nhập):
python tools/capture_feed.py
```

Fixture thật có thể chứa dữ liệu riêng; giữ trong `tests/fixtures/live/` đã được gitignore và loại bỏ cookie/thông tin cá nhân trước khi chia sẻ.

## Mã nguồn tham khảo

`reference/` không nằm trong Git hay bản phát hành. Khi cần đối chiếu, clone các repository trong bảng PLAN §11 vào `reference/<tên-repo>/` và checkout đúng commit đã ghi. Repo không có LICENSE chỉ được đọc, không sao chép; giữ ghi nhận bản quyền của các phần được phép sử dụng trong `THIRD_PARTY_NOTICES.txt`.

## Đóng gói Windows

Sau khi thiết lập `.venv` và ffmpeg trong PATH, chạy tại repo:

```powershell
.\build.ps1
```

Script dùng `VideoCongThuc.spec` để build **onedir**, chép đúng các mẫu `config/`, hướng dẫn và notices, kèm ffmpeg rồi tạo `dist/VideoCongThuc.zip`. Cạnh `VideoCongThuc.exe` chỉ có `HUONG-DAN.pdf` và các thư mục dữ liệu; mã, DLL, assets, ffmpeg, hướng dẫn Markdown và notices nằm trong `app/` (`config.BUNDLE_DIR`). `HUONG-DAN.pdf` được kèm nếu có. Không đóng gói `reference/`, `.venv` hay dữ liệu/phiên đăng nhập đang dùng; `data/`, `output/`, `profile/` trong bản ZIP là thư mục rỗng. Nếu một bản ứng dụng trong `dist/VideoCongThuc/` đã có dữ liệu người dùng, script từ chối ghi đè: chuyển nguyên bản đó ra ngoài `dist/` trước khi build lại.
