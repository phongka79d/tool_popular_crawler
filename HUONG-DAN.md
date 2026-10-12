# Video Công Thức — hướng dẫn nhanh

## 1. Mở ứng dụng
Giải nén toàn bộ `VideoCongThuc.zip` vào thư mục có quyền ghi (ví dụ trong Documents), **không chạy trực tiếp trong ZIP**. Mở thư mục `VideoCongThuc`, bấm `VideoCongThuc.exe`; giao diện mở trên trình duyệt của máy. Giữ cửa sổ chương trình mở trong lúc dùng. Cần Internet; lần đầu Chromium được tải về (khoảng 150 MB). Model chuyển thoại dự phòng chỉ tải khi cần dùng.

## 2. Tab Cài đặt
- Nhập **3 API key**: Jev, Deepgram và LLM. Với LLM, điền thêm endpoint tương thích OpenAI và tên model do nhà cung cấp cung cấp. Bấm **Kiểm tra và lưu** cho từng dịch vụ; kiểm tra có thể phát sinh một lượng phí nhỏ. Key được lưu qua Windows Credential Manager, không ghi vào tệp cấu hình.
- Nhập danh sách URL kênh Facebook, mỗi dòng một URL, rồi lưu. Điền thông tin page của mình để gợi ý phù hợp với người xem.
- Bấm **Đăng nhập Facebook**, tự đăng nhập và hoàn tất xác minh trong cửa sổ trình duyệt hiện ra. **Nên dùng tài khoản phụ**, không dùng tài khoản quản trị quan trọng; chỉ thu thập nội dung được phép truy cập và tuân thủ quy định Facebook. Nếu phiên hết hạn hoặc gặp checkpoint, trở lại đây đăng nhập lại.

(Ảnh: tab Cài đặt)

## 3. Tab Chạy quét
Kiểm tra cả 3 đèn key đều sẵn sàng. Chọn số ngày, Reels/Video/Tất cả, follower tối thiểu của kênh và preset ngưỡng viral (hoặc tự nhập ngưỡng). Bấm **Chạy**, theo dõi tiến trình và thông báo. Bấm **Dừng** khi cần ngừng; chờ ứng dụng kết thúc xử lý đang chạy. Nếu key lỗi hoặc hết hạn mức, sửa ở Cài đặt rồi chạy lại; dữ liệu đã xử lý được lưu trong cache.

(Ảnh: tab Chạy quét)

## 4. Tab Kết quả
Chọn file Excel để tải hoặc mở thư mục `output/`. File `cong-thuc_YYYY-MM-DD_HHmm.xlsx` có bảng video/công thức, tổng hợp và nhật ký chạy. Đọc nhật ký khi một kênh bị bỏ qua hoặc thiếu chỉ số. Gợi ý AI cần được kiểm tra trước khi sử dụng, đặc biệt nội dung sức khỏe và quảng cáo.

(Ảnh: tab Kết quả)

## 5. Bảo mật và thay đổi Facebook
**Không chia sẻ thư mục `profile/` hoặc `data/`**: chúng chứa phiên đăng nhập/cookie Facebook, cache và dữ liệu riêng. Không gửi API key hay ảnh chụp ô key. Khi cần gửi chương trình cho người khác, gửi bản ZIP sạch do người phát triển cung cấp, không nén lại thư mục đang sử dụng.

Nếu Facebook đổi giao diện hoặc cấu trúc dữ liệu khiến quét không ra video: dừng quét, đóng ứng dụng và sao lưu `config/selectors.json` cùng `config/graphql_paths.json`. Nhờ người phát triển cung cấp bản cập nhật: `selectors.json` chứa bộ chọn giao diện, `graphql_paths.json` chứa đường dẫn tới trường dữ liệu GraphQL. Thay đúng hai tệp trong `config/`, giữ định dạng JSON hợp lệ, mở lại rồi thử một kênh. Không đoán đường dẫn, không gửi cookie/profile để nhờ sửa; nếu chưa có bản cập nhật, gửi thông báo lỗi đã loại bỏ dữ liệu riêng.
