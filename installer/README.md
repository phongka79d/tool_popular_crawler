# Bộ cài Video Công Thức

## Tạo bản phát hành

Trên Windows 64-bit, chuẩn bị môi trường `.venv` và các phụ thuộc build của dự án, Inno Setup 6 (`winget install --id JRSoftware.InnoSetup -e`), cùng `docs/HUONG-DAN.pdf`. Chạy từ thư mục gốc:

```powershell
.\build.ps1
```

Script tải FFmpeg 9.0.2 **release essentials**, kiểm tra SHA256 đã ghim rồi chỉ lấy `bin/ffmpeg.exe`; không dùng FFmpeg trong PATH. ZIP tải về và EXE được lưu ở `build/ffmpeg-cache/` để tái sử dụng. Nếu báo sai SHA256, xóa ZIP cache được chỉ rõ rồi chạy lại; không bỏ qua kiểm tra.

Kết quả: `dist/VideoCongThuc.zip` (bản portable) và `dist/VideoCongThuc-Setup.exe`. Phiên bản lấy từ `git describe --tags --always`, hoặc ngày build khi không có Git metadata. Nhà phát hành có thể đổi qua `#define AppPublisher` trong `VideoCongThuc.iss` (hoặc `/DAppPublisher=...` khi gọi ISCC trực tiếp).

## Cài đặt và dữ liệu

Bộ cài chỉ dành cho Windows 64-bit, không cần quyền quản trị. Mặc định cài vào `%LOCALAPPDATA%\Programs\VideoCongThuc`, nơi tài khoản hiện tại có quyền ghi. Có lối tắt Start menu, tài liệu PDF và tùy chọn biểu tượng Desktop (mặc định bật). Inno Setup hiện không kèm tiếng Việt; các màn hình chính được Việt hóa trên bộ thông báo nền tiếng Anh. Ứng dụng cần [Microsoft Edge WebView2 Runtime](https://go.microsoft.com/fwlink/p/?LinkId=2124703).

Khi nâng cấp, trình cài đặt dùng Restart Manager để yêu cầu đóng ứng dụng đang chạy, thay toàn bộ `app/`, nhưng chỉ thêm mẫu `config/` chưa tồn tại. Không đóng gói nội dung `data/`, `output/`, `profile/`. Script từ chối build nếu các thư mục này trong bản portable ở `dist/VideoCongThuc` không rỗng; hãy chuyển bản đang sử dụng ra ngoài `dist/` trước.

Gỡ cài đặt **luôn giữ nguyên** `config/`, `data/`, `output/`, `profile/`, không hỏi xóa dữ liệu. Nếu muốn xóa hẳn dữ liệu cá nhân, người dùng tự sao lưu rồi xóa các thư mục còn lại sau khi gỡ ứng dụng.
