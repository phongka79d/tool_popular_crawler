# Video Công Thức — hướng dẫn nhanh

## 1. Mở ứng dụng
Giải nén toàn bộ `VideoCongThuc.zip` vào thư mục có quyền ghi (ví dụ trong Documents), **không chạy trực tiếp trong ZIP**. Mở thư mục `VideoCongThuc`, bấm `VideoCongThuc.exe`; giao diện mở trên trình duyệt của máy. Giữ cửa sổ đen (console) mở trong lúc dùng. Máy không cần cài Python hay thư viện gì thêm; cần Internet. **Lần đầu mở**, ứng dụng tự tải trình duyệt Chromium (khoảng 150 MB, tiến độ hiện ở cửa sổ đen) vào ngay thư mục ứng dụng. Model chuyển thoại dự phòng (faster-whisper) tự tải vào thư mục `models/` khi cần dùng lần đầu.

## 2. Tab Cài đặt
- Đầu tab có danh sách việc cần làm (✓ là đã xong). Mục **1. Dịch vụ AI** có Jev, Deepgram và LLM, mỗi dịch vụ làm 2 bước:
  - **Bước 1 · Kết nối**: dán API key (LLM: chọn nhà cung cấp hoặc tự nhập endpoint tương thích OpenAI) rồi bấm **Kết nối**. Ứng dụng hỏi thẳng máy chủ của dịch vụ để lấy danh sách model; key sai sẽ báo lỗi ngay.
  - **Bước 2 · Chọn model**: chọn model trong danh sách (Deepgram: chọn thêm ngôn ngữ, mặc định tiếng Việt; LLM: gõ để tìm model, giá USD / 1 triệu token hiện kèm nếu nhà cung cấp công bố). Bấm **Kiểm tra và lưu**; kiểm tra có thể phát sinh một lượng phí nhỏ. Key được lưu qua Windows Credential Manager, không ghi vào tệp cấu hình.
- Nhập danh sách URL kênh Facebook, mỗi dòng một URL, rồi bấm **Lưu danh sách kênh**. Tên page và khách hàng mục tiêu của page mình (dùng để chấm "làm lại được" và viết gợi ý) nằm ở mục `my_page` trong `config/settings.json`; nhờ người phát triển sửa nếu cần.
- Nếu không đăng nhập được trong cửa sổ của tool, mở mục **Không đăng nhập được? Nạp file cookie** và nạp file cookie xuất bằng tiện ích Cookie-Editor từ tài khoản phụ.
- Bấm **Đăng nhập Facebook**, tự đăng nhập và hoàn tất xác minh trong cửa sổ trình duyệt hiện ra. **Nên dùng tài khoản phụ**, không dùng tài khoản quản trị quan trọng; chỉ thu thập nội dung được phép truy cập và tuân thủ quy định Facebook. Nếu phiên hết hạn hoặc gặp checkpoint, trở lại đây đăng nhập lại.

![Tab Cài đặt](docs/img/tab-cai-dat.png)

## 3. Tab Chạy quét
Tab chỉ mở khi đã lưu đủ 3 dịch vụ AI. Kiểm tra cả 3 dịch vụ đều hiện ✓. Chọn số ngày, Reels/Video/Tất cả, follower tối thiểu của kênh và preset ngưỡng viral (hoặc tự nhập ngưỡng). Bấm **Chạy**, theo dõi tiến trình và thông báo. Bấm **Dừng** khi cần ngừng; chờ ứng dụng kết thúc xử lý đang chạy. Nếu key lỗi hoặc hết hạn mức, sửa ở Cài đặt rồi chạy lại; dữ liệu đã xử lý được lưu trong cache.

![Tab Chạy quét: ✗ cho biết dịch vụ nào lỗi, tool sẽ không chạy](docs/img/tab-chay-quet.png)

## 4. Tab Kết quả
Chọn file Excel để tải hoặc mở thư mục `output/`. File `cong-thuc_YYYY-MM-DD_HHmm.xlsx` có bảng video/công thức, tổng hợp và nhật ký chạy. Đọc nhật ký khi một kênh bị bỏ qua hoặc thiếu chỉ số. Gợi ý AI cần được kiểm tra trước khi sử dụng, đặc biệt nội dung sức khỏe và quảng cáo.

![Tab Kết quả](docs/img/tab-ket-qua.png)

## 5. Bảo mật và thay đổi Facebook
**Không chia sẻ thư mục `profile/` hoặc `data/`**: chúng chứa phiên đăng nhập/cookie Facebook, cache và dữ liệu riêng. Không gửi API key hay ảnh chụp ô key. Khi cần gửi chương trình cho người khác, gửi bản ZIP sạch do người phát triển cung cấp, không nén lại thư mục đang sử dụng.

Nếu Facebook đổi giao diện hoặc cấu trúc dữ liệu khiến quét không ra video: dừng quét, đóng ứng dụng và sao lưu `config/selectors.json` cùng `config/graphql_paths.json`. Nhờ người phát triển cung cấp bản cập nhật: `selectors.json` chứa bộ chọn giao diện, `graphql_paths.json` chứa đường dẫn tới trường dữ liệu GraphQL. Thay đúng hai tệp trong `config/`, giữ định dạng JSON hợp lệ, mở lại rồi thử một kênh. Không đoán đường dẫn, không gửi cookie/profile để nhờ sửa; nếu chưa có bản cập nhật, gửi thông báo lỗi đã loại bỏ dữ liệu riêng.
