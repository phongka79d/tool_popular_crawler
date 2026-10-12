# Video Công Thức

Công cụ Windows quét video Facebook, lọc chỉ số viral, phân tích công thức bằng Jev/LLM và xuất Excel. Yêu cầu Python 3.11, Internet và `ffmpeg.exe` trong PATH. Hướng dẫn người dùng: [HUONG-DAN.md](HUONG-DAN.md); đặc tả: [PLAN-JEV.md](PLAN-JEV.md).

## Thiết lập (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Nhập key Jev, Deepgram, LLM và endpoint/model LLM trong tab **Cài đặt**; không ghi key vào mã nguồn hay tệp cấu hình. Đăng nhập Facebook bằng tài khoản phụ trước khi quét.

## Chạy và kiểm thử

```powershell
streamlit run app.py
# Hoặc chạy pipeline từ dòng lệnh:
python pipeline.py

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

Script dùng `VideoCongThuc.spec` để build **onedir**, chép đúng các mẫu `config/`, hướng dẫn và notices, kèm ffmpeg rồi tạo `dist/VideoCongThuc.zip`. `HUONG-DAN.pdf` được kèm nếu có. Không đóng gói `reference/`, `.venv` hay dữ liệu/phiên đăng nhập đang dùng; `data/`, `output/`, `profile/` trong bản ZIP là thư mục rỗng. Nếu một bản ứng dụng trong `dist/VideoCongThuc/` đã có dữ liệu người dùng, script từ chối ghi đè: chuyển nguyên bản đó ra ngoài `dist/` trước khi build lại.
