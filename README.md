# Video Công Thức

Công cụ Windows tìm video thường, Reel và bài đăng nổi bật trên các page Facebook, lọc chỉ số, phân tích công thức bằng Jev/LLM và xuất Excel. Giao diện chạy trong cửa sổ riêng, không cần biết lập trình.

## Cài đặt cho người dùng

Yêu cầu: **Windows 10/11 64-bit**, Internet và [Microsoft Edge WebView2 Runtime](https://go.microsoft.com/fwlink/p/?LinkId=2124703) (thường đã có). Bản đóng gói không cần Python.

1. Chạy **`VideoCongThuc-Setup.exe`** (khoảng 90 MB). Cài theo tài khoản Windows hiện tại, không cần quyền quản trị; mặc định ở `%LOCALAPPDATA%\Programs\VideoCongThuc`. Mở từ Start menu hoặc biểu tượng Desktop tùy chọn; Start menu có lối tắt hướng dẫn PDF.
2. Nếu SmartScreen hiện **Windows protected your PC**, chỉ khi đã xác minh nguồn tệp: **More info → Run anyway**. Bộ cài chưa ký số nên có thể bị cảnh báo; không tắt bảo vệ Windows.
3. Hoặc dùng **`VideoCongThuc.zip`** (khoảng 123 MB): giải nén toàn bộ rồi mở `VideoCongThuc.exe`. Không chạy trong ZIP hoặc chép riêng EXE ra ngoài.

**Nâng cấp:** chạy Setup mới lên bản cũ; bộ cài yêu cầu đóng ứng dụng và thay `app/`, giữ `config/`, `data/`, `output/`, `profile/`. **Gỡ cài đặt** qua Windows Settings → Apps cũng luôn giữ bốn thư mục dữ liệu này. Nên đóng ứng dụng và sao lưu trước khi nâng cấp/chuyển máy.

## Sử dụng nhanh

1. Mở ứng dụng; chờ chuẩn bị trình duyệt quét tự động ở lần đầu.
2. Tab **Cài đặt**: lấy key Jev (tài khoản Jev/typesafe), Deepgram và một nhà cung cấp LLM. Với mỗi dịch vụ: dán key → **Kết nối** → giữ model **Đề xuất** → **Kiểm tra và lưu**. Chỉ đổi model trong phần **Nâng cao**. Key chỉ lưu trong Windows Credential Manager.
3. Nhập mỗi dòng một link page Facebook → **Lưu danh sách kênh**. Không hỗ trợ nhóm. Đăng nhập Facebook bằng tài khoản phụ; nếu cần dùng **Không đăng nhập được? Nạp file cookie**.
4. Tab **Chạy quét**: chọn ngày đăng, Video/Bài đăng, Video thường/Reel, thời lượng và ngưỡng lọc. Đọc tóm tắt, kiểm tra key, xác nhận lưu ý lần đầu rồi **Bắt đầu quét**. Bài đăng không cần Deepgram. Khi Deepgram hết credit, video tương ứng không có bản chép lời: nạp thêm/đổi key rồi quét lại.
5. Theo dõi tiến độ, câu hỏi cần xử lý và lượng dùng dịch vụ. Nghỉ **30–60 giây giữa các kênh là có chủ ý**, không phải bị treo. Dùng **Dừng quét** và chờ lưu xong nếu muốn ngừng.
6. Tab **Kết quả**: chọn file để xem thống kê/biểu đồ, **Mở bằng Excel**, **Lưu bản sao…** hoặc **Mở thư mục**. Nút **Nhật ký** ở góc trên giúp tra lỗi.

**[Hướng dẫn chi tiết có ảnh (Markdown)](docs/HUONG-DAN.md) · [Tải/đọc hướng dẫn PDF](docs/HUONG-DAN.pdf)** — gồm cách lấy key, cài đặt, giải thích tùy chọn quét, các trang tính Excel và xử lý lỗi.

**Bảo mật:** không chia sẻ `profile/`, `data/fb_cookies.txt`, key hoặc bản sao thư mục đang dùng. Chỉ thu thập nội dung được phép, tuân thủ điều khoản Facebook và kiểm tra gợi ý AI trước khi sử dụng. Dịch vụ AI có phí riêng; nên thử ít kênh trước.

## Dành cho người phát triển

Chạy từ mã nguồn cần Python 3.11, Internet và `ffmpeg.exe` trong PATH. Đặc tả: [docs/PLAN-JEV.md](docs/PLAN-JEV.md).

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

Xem **[installer/README.md](installer/README.md)** để chuẩn bị phụ thuộc build, tạo `VideoCongThuc-Setup.exe`/ZIP và hiểu cơ chế nâng cấp, giữ dữ liệu. Điểm vào build là `.\build.ps1`; cấu hình đóng gói nằm trong `VideoCongThuc.spec`. Không đóng gói dữ liệu hay phiên Facebook đang sử dụng.

### Tạo lại hướng dẫn

Khi máy chủ mock đã phục vụ `frontend/` tại `http://127.0.0.1:8765/`, chạy:

```powershell
.\.venv\Scripts\python tools/make_guide_images.py
.\.venv\Scripts\python tools/make_guide_pdf.py
```

Ảnh dùng dữ liệu mô phỏng và chú thích đỏ đánh số; không nhập key thật. Script PDF dùng Chromium của Playwright, tự dùng bộ chuyển Markdown tối giản nếu chưa có gói `markdown`, không cài thêm phụ thuộc.
