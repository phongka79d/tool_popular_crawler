# Video Công Thức — hướng dẫn nhanh

## 1. Mở ứng dụng
1. Giải nén toàn bộ `VideoCongThuc.zip` vào thư mục có quyền ghi, ví dụ trong Documents. **Không chạy trực tiếp trong ZIP**.
2. Mở thư mục `VideoCongThuc`, bấm `VideoCongThuc.exe`. Cạnh file này có `HUONG-DAN.pdf` và các thư mục `config/`, `data/`, `output/`, `profile/`. Thư mục `app/` chứa tệp chương trình, không sửa hay xóa.
3. Giao diện mở trong cửa sổ ứng dụng riêng, không phải tab trình duyệt và không có cửa sổ đen (console). Máy không cần cài Python. Cần Internet và **Microsoft Edge WebView2 Runtime**, thường đã có trên Windows 10/11 có Edge.

Nếu thiếu WebView2 Runtime, ứng dụng hiện hộp thoại báo lỗi kèm địa chỉ tải: [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). Cài Runtime rồi mở lại ứng dụng.

Trình duyệt dùng để quét Facebook được chuẩn bị riêng. Máy có Edge thì không cần tải thêm trình duyệt quét. Máy không có Edge thì lần đầu ứng dụng tự tải Chromium (khoảng 150 MB, vài phút). Cửa sổ ứng dụng vẫn hiện và báo **Đang chuẩn bị trình duyệt quét**; chờ hoàn tất trước khi đăng nhập hoặc quét. Nếu tải thất bại, kiểm tra mạng và dung lượng ổ đĩa rồi mở lại ứng dụng. Model chuyển thoại dự phòng (faster-whisper) tự tải vào thư mục `models/` khi cần dùng lần đầu.

**Đóng cửa sổ là thoát ứng dụng ngay.** Nếu đang quét, ứng dụng hỏi xác nhận trước khi đóng; đồng ý sẽ dừng quét và thoát. Muốn giữ phần kết quả đã xử lý, nên bấm **Dừng quét** và chờ lưu xong trước khi đóng.

**Báo "chưa được giải nén đầy đủ":** bản trong máy thiếu tệp chương trình, không phải máy thiếu thư viện. Bấm chuột phải vào `VideoCongThuc.zip` → **Extract All (Giải nén tất cả)**, giải nén vào thư mục ngắn như `C:\VideoCongThuc`, rồi chạy `VideoCongThuc.exe` trong thư mục đó. Không chạy exe khi đang xem bên trong file ZIP, không chép riêng file exe ra chỗ khác (muốn có biểu tượng trên Desktop thì dùng **Send to → Desktop (create shortcut)**). Nếu phần mềm diệt virus báo hoặc xóa tệp, cho phép thư mục này rồi giải nén lại.

**Nhật ký:** bấm **Nhật ký** ở góc trên bên phải để mở hộp **Nhật ký ứng dụng**. Mặc định bật **Chỉ lỗi và cảnh báo**; tắt để xem các thông báo khác. Thông báo mới nhất ở trên cùng. Chọn **Lần mở trước** nếu có để xem lỗi lần chạy trước. Nhật ký được ghi vào `data/app.log`; API key luôn được che. Khi cần hỗ trợ, bấm **Mở file nhật ký** và chỉ gửi file nhật ký, không gửi cả thư mục `data/`.

## 2. Trang Cài đặt
- Dưới tiêu đề có 3 bước **Dịch vụ AI → Kênh & Facebook → Chạy quét**. Chuyển trang bằng các tab **Cài đặt / Chạy quét / Kết quả**. Thanh **Bước tiếp theo** chỉ việc cần làm; bấm **Đi tới…** nếu cần chuyển sang trang được chỉ dẫn.
- Mục **1 · Dịch vụ AI** có Jev, Deepgram và LLM. Mục đầu tiên chưa cấu hình tự mở; bấm tên dịch vụ để mở hoặc thu gọn. Mỗi dịch vụ làm 2 bước:
  - **Bước 1 · Kết nối**: dán API key rồi bấm **Kết nối** để lấy danh sách model. Với LLM, chọn nhà cung cấp — OpenRouter, OpenAI, Google Gemini, Anthropic (Claude) — hoặc chọn **Khác (tự nhập)** và nhập endpoint tương thích OpenAI. Với Anthropic, dùng API key từ Claude Console (bắt đầu bằng `sk-ant-`). Một số nhà cung cấp cho xem model khi chưa xác nhận key; bước này chưa lưu key.
  - **Bước 2 · Chọn model**: chọn model trong danh sách (Deepgram: mặc định tự nhận tiếng Việt / tiếng Anh; LLM: gõ để tìm model, giá USD / 1 triệu token hiện kèm nếu nhà cung cấp công bố). Bấm **Kiểm tra và lưu**; kiểm tra có thể phát sinh một lượng phí nhỏ. Key được lưu qua Windows Credential Manager, không ghi vào tệp cấu hình.
  - **Deepgram – ngôn ngữ thoại:** bật **Tự nhận biết tiếng Việt / tiếng Anh** để Deepgram nghe audio và chọn ngôn ngữ cho từng video. Nếu độ tin cậy dưới 0,5, tool chép lại một lần bằng tiếng Việt, ghi chú **Không chắc ngôn ngữ thoại, đã dùng tiếng Việt** và tính phí cả hai lượt. Tắt tự nhận biết để dùng **Ngôn ngữ thoại (khi tắt tự nhận biết)** cố định. Nếu hết hạn mức và có bật dự phòng, faster-whisper chạy máy cũng tự nhận ngôn ngữ hoặc dùng ngôn ngữ cố định tương ứng. Thoại đã lưu được dùng lại cùng ngôn ngữ, không chép lại khi đổi cài đặt.
  - **Thoại tiếng Anh:** LLM đã cấu hình tự dịch thêm sang tiếng Việt; cột **Thoại dịch tiếng Việt** giữ bản dịch, còn phân tích vẫn dùng thoại gốc. Bản dịch đã lưu được dùng lại, không tốn token dịch thêm. Lượt dịch mới được cộng vào **Token LLM**; nếu dịch lỗi, tool ghi **Chưa dịch được thoại sang tiếng Việt** và vẫn phân tích video.
- Nhập link trang chính của các page (fanpage) cần quét, mỗi dòng một link (ví dụ `https://www.facebook.com/ten-page`), rồi bấm **Lưu danh sách kênh**. **Không hỗ trợ nhóm (group)**: link nhóm bị báo lỗi khi lưu, và link nhóm đã lưu từ trước bị bỏ qua khi quét. Tên page và khách hàng mục tiêu của page mình (dùng để chấm "làm lại được" và viết gợi ý) nằm ở mục `my_page` trong `config/settings.json`; nhờ người phát triển sửa nếu cần.
- Nếu không đăng nhập được trong cửa sổ của tool, mở **Không đăng nhập được? Nạp file cookie**. Dùng Cookie-Editor trên trình duyệt đã đăng nhập tài khoản phụ để xuất cookie của `facebook.com` ra file JSON hoặc TXT. Bấm **Chọn file cookie…**, chọn file trong hộp chọn tệp của Windows rồi xác nhận mở. Không chia sẻ file cookie cho người khác.
- Bấm **Đăng nhập Facebook**, tự đăng nhập và hoàn tất xác minh trong cửa sổ trình duyệt hiện ra. **Nên dùng tài khoản phụ**, không dùng tài khoản quản trị quan trọng; chỉ thu thập nội dung được phép truy cập và tuân thủ quy định Facebook. Nếu phiên hết hạn hoặc gặp checkpoint, trở lại đây đăng nhập lại.
- Mở **Nhãn phân loại (Jev)** để chỉnh danh sách đáp án mà Jev được chọn. Jev đọc caption và lời thoại của mỗi nội dung đạt ngưỡng rồi chọn **đúng 1 nhãn** trong mỗi bảng:
  - **Chủ đề:** nội dung nói về chuyện gì → cột **Nhóm chủ đề**, dùng để gom nhóm ở trang **Tổng hợp công thức**.
  - **Kiểu hook:** câu mở đầu thuộc kiểu nào → cột **Kiểu hook**; Jev cũng dùng nhãn này để duyệt gợi ý của LLM (gợi ý phải giữ kiểu hook hoặc cấu trúc của video gốc).
  - **Cấu trúc:** nội dung được sắp xếp theo trình tự nào → cột **Cấu trúc**, cũng dùng để duyệt gợi ý.
  - **CTA:** cuối nội dung kêu gọi người xem làm gì → cột **CTA**.

  Mỗi dòng có **Tên hiển thị** (chữ trong Excel; đổi tên không làm Jev chấm lại) và **Mô tả cho Jev** (Jev dựa vào ô này để chọn nhãn: viết cụ thể, có ví dụ, nói rõ ranh giới với nhãn gần giống; mô tả mơ hồ khiến Jev hay ghi **(chưa chắc)**). Thêm dòng để có lựa chọn mới; xóa dòng thì nội dung kiểu đó rơi vào nhãn gần nhất hoặc **Khác**. Mỗi nhóm cần ít nhất hai nhãn, các lựa chọn **Khác / Không có CTA** luôn được giữ; tránh tạo quá nhiều nhãn vì mỗi nhãn chỉ có vài nội dung thì khó thấy xu hướng. Sau khi thêm, xóa hoặc sửa mô tả và bấm **Lưu nhãn**, lần quét tiếp theo Jev **chấm lại mọi nội dung** (kể cả nội dung đã chấm), tốn thêm một ít phí Jev. Nhãn không ảnh hưởng tới lượt xem, việc lọc ngưỡng hay các câu chấm điểm khác (độ mạnh hook, liên quan ngành, rủi ro…). Muốn quay về bộ nhãn ban đầu, đánh dấu xác nhận rồi bấm **Khôi phục nhãn mặc định**.

![Tab Cài đặt](img/tab-cai-dat.png)

## 3. Trang Chạy quét
Nếu thấy **Chạy quét đang khóa**, bấm **Mở Cài đặt** để kết nối và lưu Jev cùng LLM. Quét video cần thêm Deepgram (chép lời); quét bài đăng thì không.

1. Trong **Nội dung nào được quét?**, chọn **7 ngày**, **14 ngày**, **30 ngày** hoặc **Tự nhập** số ngày.
2. Chọn **Loại quét**: **Video** hoặc **Bài đăng** (bài chữ/ảnh, không gồm video). Với Video, đánh dấu ít nhất một ô **Video thường**, **Reel**, **Video (Live)**, **Reel (Live)**. Mặc định chọn Video thường và Reel, không chọn Live.
3. Với video, đặt **Lượt xem tối thiểu** và/hoặc **Lượt xem so với follower (×)** trong **Ngưỡng lọc**. Ví dụ 5× là lượt xem gấp 5 lần số người theo dõi. Khi bật cả hai, chọn **Đạt cả hai điều kiện** hoặc **Đạt một trong hai**. Bài đăng chỉ dùng **Tương tác tối thiểu** (cảm xúc + bình luận + chia sẻ). Nhập 0 để tắt ngưỡng tương ứng.
4. Đặt riêng **Thời lượng Video** và **Thời lượng Reel**, tính bằng giây. Có nút nhanh **≥ 1 phút / ≥ 3 phút** cho Video, **≤ 60 giây / ≤ 90 giây** cho Reel. Nội dung ngoài khoảng bị bỏ trước khi chép lời và phân tích nên không tốn Deepgram/LLM. Video (Live) dùng giới hạn Video; Reel (Live) dùng giới hạn Reel. Mục chưa biết thời lượng vẫn được giữ và có ghi chú. Nhập 0 để bỏ giới hạn đó; lựa chọn được nhớ cho lần sau.
5. Đọc dòng tóm tắt và sửa các lỗi được báo. Ứng dụng kiểm tra key theo loại quét; có thể bấm **Kiểm tra lại**. Lần đầu cần đọc lưu ý và đánh dấu **Tôi đã đọc và tự chịu trách nhiệm**, rồi bấm **Bắt đầu quét**.

**Theo dõi tiến độ:** khung **Đang quét** có các bước **Kiểm tra key → Quét kênh → Lọc nội dung → Phân tích → Xuất Excel**, thanh **Tiến độ tổng (ước tính)** và tiến độ bước hiện tại. Bảng **Tiến độ từng kênh** hiện tên page (sau khi đọc được đầu trang), nút **Mở kênh**, **Follower**, trạng thái, tiến độ, số mục **Tìm thấy**, **Đạt ngưỡng**, **Đã phân tích**; dấu — nghĩa là chưa có số liệu. Quét và phân tích chạy song song nên bước đang hoạt động có thể thay đổi. Khi nghỉ giữa hai kênh hoặc chờ do Facebook giới hạn truy cập, thông báo đếm ngược số giây còn lại. Khung **Diễn biến gần nhất** hiện 8 thông báo mới nhất; mở **Toàn bộ diễn biến lần quét** để xem hết. Nếu hiện **Cần bạn chọn để tiếp tục**, đọc thông báo và bấm cách xử lý phù hợp.

Trong lúc quét, tool mở trình duyệt Edge hoặc Chromium ở ngoài màn hình (vẫn thấy biểu tượng trên thanh tác vụ): không đóng cửa sổ đó. Bấm **Dừng quét** khi cần ngừng; chờ ứng dụng hoàn tất bước hiện tại và lưu phần đã xử lý. Quét xong, bấm **Mở file Excel** để xem báo cáo, **Lưu bản sao…** để chọn nơi lưu trong hộp thoại Windows, hoặc **Xem trong Kết quả** để xem thống kê. Bấm **Quét lần mới** để chọn lại tham số. Nếu key lỗi hoặc hết hạn mức, sửa ở Cài đặt rồi chạy lại; dữ liệu đã xử lý được lưu để dùng lại.

**Số người theo dõi:** tool đọc từ phần đầu trang Facebook, có chờ dữ liệu tải xong. Nếu vẫn báo **chưa đọc được số người theo dõi**, không có nghĩa là kênh có 0 follower: điều kiện tỷ lệ lượt xem/follower không đạt vì thiếu số liệu. Khi chọn **Đạt cả hai điều kiện**, video sẽ bị loại; khi chọn **Đạt một trong hai**, video vẫn có thể qua ngưỡng lượt xem. Nếu chỉ bật tỷ lệ follower thì video không qua lọc; có thể đặt tỷ lệ về 0 và dùng ngưỡng lượt xem.

Khi quét **Bài đăng**, có thể bật **Đọc nội dung ảnh trong bài (AI đọc ảnh)**: tối đa 4 ảnh/bài, tốn thêm khoảng 1.500–2.000 token/ảnh; nội dung được lưu để lần sau không phải đọc lại. Tool kiểm tra model có thực sự nhận ảnh trước khi dùng; nếu không hỗ trợ, đổi model ở Cài đặt (kết quả Excel có cột **Nội dung ảnh** khi đã đọc được ảnh).

**Thời gian:** tùy số kênh, số mục đạt ngưỡng và model AI. Video/bài đạt ngưỡng được phân tích ngay sau khi quét xong kênh đó, trong lúc quét kênh tiếp theo; bài đăng không cần chép lời nên thường nhanh hơn video. **Tab Video xong: thêm 0 video mới** là bình thường khi các video đã có ở tab Reels. Nhiều page chỉ có video dài là **buổi phát trực tiếp đã lưu (Live)**: chúng chỉ được lấy khi đánh dấu **Video (Live)**; nếu chưa chọn, nhật ký ghi rõ **bỏ qua N mục Video (Live) vì chưa chọn Video (Live)**. Video Live chỉ được chép lời 10 phút; nếu mở đầu bằng nhạc chờ, tool tìm đoạn có thoại trong 30 phút đầu. Nếu báo **Không đọc được page**, kiểm tra link và page có công khai không. Nếu báo **trình duyệt của tool đang mở ở nơi khác**, đóng cửa sổ Video Công Thức khác hoặc cửa sổ đăng nhập Facebook rồi quét lại.

**Sử dụng dịch vụ:** số liệu cập nhật khi chạy và giữ lại sau khi kết thúc:
- **LLM:** model, **Lần gọi LLM**, **Token LLM**, token trả về, giây chờ, tốc độ trung bình (token trả về/giây chờ) và số phân tích **Dùng lại**. Thời gian chờ cộng dồn có thể lớn hơn thời gian quét vì các mục chạy song song.
- **Jev:** **Lần gọi Jev**, **Token Jev**. **Deepgram:** **Lần gọi Deepgram**, **Phút Deepgram**.
- **Biểu đồ sử dụng & từng lượt:** token LLM/Jev tích lũy theo thời gian, token và tốc độ LLM từng lượt; bảng ghi token LLM, token trả về, giây chờ, token/giây, token Jev và phút Deepgram cho từng video/bài và lượt **Nhận xét tổng hợp** cuối cùng.

Video/bài đã phân tích trước đó có thể **dùng phân tích LLM đã lưu**, không gọi lại LLM cho phần phân tích đó và không tốn token LLM. Các phần khác, như nhận xét tổng hợp, vẫn có thể phát sinh lần gọi mới.

**Giảm rủi ro tài khoản bị khóa:** tool quét bằng trình duyệt thật, cuộn và nghỉ như người dùng, nghỉ 30–60 giây giữa các kênh, và chỉ dùng cookie tài khoản khi video không xem được ẩn danh. Facebook chủ yếu khóa theo hành vi, nên: dùng tài khoản phụ đã có tuổi và hoạt động bình thường; mỗi lần chỉ quét vài chục kênh, không chạy liên tục nhiều lần trong ngày; không chạy song song trên nhiều máy với cùng tài khoản; không dùng VPN/proxy đổi quốc gia giữa các lần chạy. Gặp checkpoint thì xác minh bằng tay rồi nghỉ vài ngày trước khi quét tiếp.

![Tab Chạy quét: chọn loại quét, ngưỡng lượt xem và tỷ lệ so với follower, cách kết hợp, xác nhận trước khi quét](img/tab-chay-quet.png)

## 4. Trang Kết quả
Chọn **Xem thống kê file** (mặc định file mới nhất) để xem **Nội dung đã xuất**, **Kênh có kết quả**, **Tổng lượt xem** hoặc **Tổng tương tác**, **Điểm công thức TB** và mức dùng AI của file đó trong **Tổng quan kết quả**. Mục **Biểu đồ kết quả** có **Top 10 theo lượt xem** hoặc **Top 10 theo tương tác**, **Nội dung theo chủ đề**, **Phân bố điểm công thức**. Nếu thiếu số liệu, ứng dụng báo chưa có dữ liệu để vẽ biểu đồ tương ứng. Nếu không đọc được thống kê, vẫn có thể mở file hoặc lưu bản sao.

Danh sách **File Excel đã xuất** xếp mới nhất trước:
1. Bấm **Mở** cạnh file để mở bằng Excel.
2. Bấm **Lưu bản sao…** để mở hộp thoại lưu tệp của Windows. Chọn thư mục và tên file rồi bấm lưu; file gốc vẫn nằm trong `output/`.
3. Bấm **Mở thư mục** để xem thư mục `output/`.

Nút thùng rác (**Xóa file**) cạnh mỗi file mở hộp xác nhận ghi tên file. Bấm **Xóa** để xóa, **Hủy** để giữ lại. **File đã xóa không thể khôi phục bằng tool**. Nếu xóa thất bại vì file đang mở hoặc bị khóa, đóng file trong Excel rồi thử lại.

File `cong-thuc_YYYY-MM-DD_HHmm.xlsx` có 3 trang, theo thứ tự; các bảng đều có đường viền ô màu xám nhạt và bật đường lưới:
- **Chi tiết video** hoặc **Chi tiết bài đăng:** mở đầu báo cáo, xếp theo điểm công thức, cột chia nhóm màu, bộ lọc ở dòng tiêu đề, link **Mở bài ↗**, thanh màu cho điểm và ô đỏ khi có cờ rủi ro. Cột **Ngôn ngữ thoại** ngay sau **Nội dung thoại** hiển thị **Tiếng Việt**, **Tiếng Anh** hoặc mã ngôn ngữ khác; để trống khi chưa biết. Cột **Thoại dịch tiếng Việt** ngay sau ngôn ngữ thoại chứa bản dịch, chỉ có khi thoại là tiếng Anh. File bài đăng ẩn cột chỉ dành cho video (lượt xem, thời lượng, thoại, ngôn ngữ thoại và thoại dịch); nếu đã đọc ảnh thì hiện **Nội dung ảnh** thay cho thoại.
- **Tổng hợp công thức:** bảng theo nhóm chủ đề, hook và cấu trúc, cùng nhận xét tổng hợp.
- **Nhật ký:** thời gian, **Kết quả lượt chạy** gồm **Số kênh**, **Số video quét được** (hoặc **Số bài đăng quét được**), **Đạt ngưỡng**, **Đã phân tích**, **Số mục xuất**, **Gợi ý giữ lại**, **Video/bài có gợi ý**; tiếp theo là tham số đã chọn, số liệu từng kênh, mức dùng dịch vụ (**Token Jev**, **Token LLM**, **Phút Deepgram**, **Model LLM**) và thông báo/lỗi.

**Điểm Jev** là trung bình các điểm hook, cảm xúc, giá trị thực tiễn, khả năng chia sẻ Jev chấm. Đọc **Nhật ký** khi kênh bị bỏ qua hoặc thiếu chỉ số. Kiểm tra gợi ý AI trước khi sử dụng, đặc biệt nội dung sức khỏe và quảng cáo.

![Tab Kết quả](img/tab-ket-qua.png)

## 5. Bảo mật và thay đổi Facebook
Công cụ đọc Facebook tự động qua trình duyệt đã đăng nhập, điều mà [Điều khoản Facebook](https://www.facebook.com/terms) hạn chế khi chưa được phép: tài khoản có thể bị checkpoint hoặc khóa, nên dùng tài khoản phụ, chỉ thu thập nội dung bạn được phép truy cập và tự chịu trách nhiệm (ứng dụng yêu cầu xác nhận một lần trước lần quét đầu).

**Không chia sẻ thư mục `profile/` hoặc `data/`**: chúng chứa phiên đăng nhập/cookie Facebook, cache và dữ liệu riêng. Không gửi API key hay ảnh chụp ô key. Khi cần gửi chương trình cho người khác, gửi bản ZIP sạch do người phát triển cung cấp, không nén lại thư mục đang sử dụng.

Nếu Facebook đổi giao diện hoặc cấu trúc dữ liệu khiến quét không ra video: dừng quét, đóng ứng dụng và sao lưu `config/selectors.json` cùng `config/graphql_paths.json`. Nhờ người phát triển cung cấp bản cập nhật: `selectors.json` chứa bộ chọn giao diện, `graphql_paths.json` chứa đường dẫn tới trường dữ liệu GraphQL. Thay đúng hai tệp trong `config/`, giữ định dạng JSON hợp lệ, mở lại rồi thử một kênh. Không đoán đường dẫn, không gửi cookie/profile để nhờ sửa; nếu chưa có bản cập nhật, gửi file `data/app.log` (API key trong đó đã được che).
