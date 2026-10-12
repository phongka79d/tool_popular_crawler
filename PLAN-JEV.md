# Kế hoạch xây tool: Lấy video có công thức thành công (Jev + LLM)

Oct 11, 2026 · @Thu Nhẫn

## 1. Mục tiêu và phạm vi

Tool chạy trên máy cá nhân, quét video Facebook của các kênh tham khảo, giữ lại video vượt ngưỡng viral, rồi dùng Jev gắn nhãn công thức và LLM viết gợi ý nhân bản. Kết quả là một file Excel để đội content nghiên cứu và làm lại theo cách của page mình.

Người làm: Phan Tuấn Phong. Người dùng: nhân sự content/marketing, không cần biết code.

- **Bản 1 làm:** Facebook (Reels + video thường), Windows, 1 người dùng/1 máy.
- **Bản 1 chưa làm:** TikTok, Live, chạy theo lịch, nhiều tài khoản.

| Loại | Nội dung | Nhập khi nào |
| --- | --- | --- |
| Cấu hình | Danh sách kênh, API key Jev, API key Deepgram, endpoint + key + model LLM | 1 lần, lưu lại |
| Đăng nhập | Phiên Facebook (khuyên dùng nick phụ) | 1 lần, lưu profile trình duyệt |
| Tham số mỗi lần chạy | Số ngày quét, định dạng video, ngưỡng chỉ số | Mỗi lần chạy |
| Đầu ra | File Excel 3 sheet + thư mục log | Sau mỗi lần chạy |

## 2. Kiến trúc và luồng xử lý

Code lo thu thập dữ liệu và mọi phép tính. Jev đưa ra các quyết định có nhãn: gắn công thức, chấm điểm, kiểm tra. LLM chỉ làm phần viết chữ.

&#91;embedded content: luồng xử lý · 7 bước, chia vai Code / Jev / LLM\]

Thứ tự này giúp giữ chi phí thấp: video bị loại ở bước 2 sẽ không tốn thời gian chuyển thoại, không tốn lượt gọi Jev và LLM.

## 3. Công nghệ, thư mục, cấu hình

Viết bằng Python 3.11, vì SDK chính thức của Jev (`typesafe-sdk`) yêu cầu Python 3.10 trở lên.

| Việc | Thư viện |
| --- | --- |
| Điều khiển trình duyệt, giữ phiên đăng nhập | `playwright` (persistent context) |
| Tải video, tách audio | `yt-dlp` + `ffmpeg` |
| Chuyển thoại | `Deepgram Nova-3 qua REST API (model nova-3, language vi); dự phòng:` `faster-whisper` chạy máy |
| Gọi Jev | `typesafe-sdk` (`TypeSafeClient`, `Choice`, `Score`, `Noul`) |
| Gọi LLM | `openai` với `base_url` trỏ tới endpoint của mình |
| Cache, chống quét trùng | `sqlite3` (có sẵn) |
| Xuất Excel | `openpyxl` |
| Giao diện | `streamlit` (web UI chạy cục bộ) hoặc `customtkinter` |
| Đóng gói | `PyInstaller` |

Cấu trúc thư mục:

```
video-cong-thuc/
├─ app.py                # giao diện + nút Chạy
├─ pipeline.py           # điều phối các bước
├─ collectors/
│  ├─ facebook.py        # quét page, lấy chỉ số
│  └─ transcript.py      # tải audio + chuyển thoại
├─ filters.py            # lọc viral bằng code
├─ jev_client.py         # bộ câu hỏi Jev
├─ llm_client.py         # prompt + gọi LLM
├─ export_excel.py
├─ db.py                 # SQLite cache
├─ config/
│  ├─ channels.txt       # mỗi dòng 1 link page
│  ├─ settings.json      # key, endpoint, model, ngưỡng mặc định
│  ├─ taxonomy.json      # danh mục nhãn cho Jev
│  └─ selectors.json     # selector Facebook, sửa khi FB đổi giao diện
├─ profile/              # phiên đăng nhập Facebook
├─ data/cache.db
└─ output/               # file Excel + log
```

Mẫu `settings.json`:

```json
{
  "jev": {"model": "jev-1.13", "yes_threshold": 0.5, "min_confidence": 0.6},
  "llm": {"base_url": "https://.../v1", "model": ""},
  "stt": {"provider": "deepgram", "model": "nova-3", "language": "vi",
          "keyterms_file": "config/keyterms.txt", "fallback": "local_whisper"},
  "scan": {"min_page_followers": 100000, "delay_min_s": 3, "delay_max_s": 8,
           "max_videos_per_page": 200},
  "my_page": {"name": "Thế Thảo Pharma", "audience": "Chủ nhà thuốc, dược sĩ"}
}
```

API key không nằm trong file này. Key được lưu riêng trong Windows Credential Manager (xem mục 9).

Ghim cứng phiên bản Jev (`jev-1.13`) thay vì `jev-latest`, để nhãn không đổi giữa các lần chạy khi hãng ra bản mới.

## 4. Thu thập dữ liệu Facebook và thoại

Dùng Playwright mở trình duyệt với profile đã đăng nhập, vào từng page, cuộn tab Reels/Video và lấy chỉ số từ dữ liệu GraphQL mà Facebook trả về cho trình duyệt; đọc chữ trên giao diện chỉ là dự phòng (chi tiết ở mục 11.2). Không dùng Graph API vì không lấy được chỉ số video của page mình không quản lý.

**Đăng nhập lần đầu:** tool mở Chromium hiển thị (headful), người dùng tự đăng nhập, tool kiểm tra đã thấy avatar thì lưu profile vào `profile/`. Lần sau chạy ẩn (headless) với profile đó. Nếu phát hiện trang checkpoint hoặc trang đăng nhập thì dừng và báo người dùng đăng nhập lại.

**Mỗi page lấy:**

| Trường | Cách lấy |
| --- | --- |
| Tên page, số follower | Trang chủ page; chuyển "12K", "1,2 Tr" thành số bằng hàm `parse_count()` |
| Danh sách video | Tab Reels và tab Video, cuộn tới khi gặp video cũ hơn số ngày quét |
| Link, ngày đăng | Thuộc tính link + tooltip ngày; chuẩn hóa về ISO bằng code |
| View, cảm xúc, bình luận, chia sẻ | Lấy từ GraphQL khi cuộn (mục 11.2); thiếu chỉ số nào thì gọi yt-dlp cho video đó (mục 11.3) |
| Caption | Khối text bài đăng, bấm "Xem thêm" trước khi đọc |
| Thời lượng | Thẻ video hoặc metadata từ `yt-dlp` |

**Quy tắc an toàn tài khoản:**

- Nghỉ ngẫu nhiên 3–8 giây giữa các thao tác, 30–60 giây giữa các page.
- Tối đa 200 video/page/lần chạy (chỉnh trong `settings.json`).
- Mọi selector nằm trong `selectors.json`. Facebook đổi giao diện thì sửa file này, không build lại.
- Mỗi page lỗi thì ghi log và chạy page tiếp theo, không dừng cả lượt.

**Chuyển thoại** (chỉ cho video đã qua bộ lọc ở mục 5):

Dùng **Deepgram Nova-3** (bản xử lý file ghi sẵn). Nova-3 hỗ trợ tiếng Việt với mã `vi`. Tài khoản mới được tặng $200 credit, không cần thẻ.

1. `yt-dlp -x --audio-format mp3` tải audio về thư mục tạm.
2. Gửi file tới `POST https://api.deepgram.com/v1/listen` với tham số `model=nova-3`, `language=vi`, `smart_format=true`, header `Authorization: Token <API_KEY>`.
3. Nạp thuật ngữ dược từ `config/keyterms.txt` (tên hoạt chất, GPP, thông tư, tên nhóm thuốc) qua tham số `keyterm`. Tuần 3 cần test xem tính năng này có cải thiện tiếng Việt không. Nếu không, bỏ tham số và sửa lỗi chính tả thường gặp bằng bảng thay thế trong code.
4. Lấy chữ ở `results.channels[0].alternatives[0].transcript` và số giây ở `metadata.duration`. Lưu vào SQLite theo link video, rồi xóa file audio.
5. Lỗi xác thực hoặc hết credit: nếu đã bật `fallback` thì chuyển sang `faster-whisper` chạy máy; nếu không thì ghi "Chưa lấy được thoại" và chạy tiếp.
6. Video không có thoại (chỉ nhạc nền): ghi "Không có thoại" để Jev và LLM dùng caption.

```python
import requests

def transcribe_deepgram(path, stt, keyterms):
    params = [("model", stt["model"]), ("language", stt["language"]), ("smart_format", "true")]
    params += [("keyterm", k) for k in keyterms]
    with open(path, "rb") as f:
        r = requests.post("https://api.deepgram.com/v1/listen", params=params,
                          headers={"Authorization": f"Token {stt['api_key']}",
                                   "Content-Type": "audio/mpeg"},
                          data=f, timeout=300)
    r.raise_for_status()
    j = r.json()
    text = j["results"]["channels"][0]["alternatives"][0]["transcript"]
    return text, j["metadata"]["duration"]
```

**Chi phí:** Nova-3 xử lý file tính $0,0043/phút, cộng keyterm $0,0013/phút, tổng khoảng $0,0056/phút. $200 credit đủ cho khoảng 35.000 phút âm thanh. Nếu mỗi lần chạy có khoảng 200 phút thoại, credit dùng được khoảng 170 lần chạy.

## 5. Bộ lọc chỉ số viral (code thuần)

Toàn bộ phép tính và so sánh ngày làm bằng code. Tài liệu của Jev nói rõ model này không đáng tin với số học, đếm và so sánh ngày, nên không đưa bước này cho Jev.

Các chỉ số tính cho mỗi video:

- `ratio_follow = view / follower_page`
- `ratio_median = view / trung_vị_view_các_video_của_page_trong_đợt_quét`
- `engagement = (cảm_xúc + bình_luận + chia_sẻ) / view`
- `share_rate = chia_sẻ / view`

Người dùng chọn 1 preset hoặc tự nhập ngưỡng. Nhiều điều kiện được kết hợp bằng AND:

**Bộ lọc quy mô page (chạy trước bộ lọc video):** chỉ xét page có từ 100.000 follower trở lên. Tool đọc số follower ngay khi vào page. Page dưới ngưỡng thì bỏ qua luôn, không cuộn video, nên quét nhanh hơn và ít thao tác trên Facebook hơn. Mức này đổi được ở tab Chạy quét (`min_page_followers`); đặt 0 để tắt.

**Bộ lọc video:**

| Preset | Điều kiện | Dùng khi |
| --- | --- | --- |
| Viral tuyệt đối | view ≥ 50.000 | Quét kênh nhỏ, muốn lấy rộng |
| Vượt tệp follower | ratio\_follow ≥ 5 | Tìm video lan ra ngoài tệp |
| Bùng nổ mạnh | ratio\_follow ≥ 10 | Chỉ lấy video nổ thật sự |
| Nổ bất thường của kênh (khuyên dùng) | ratio\_median ≥ 3 | So kênh với chính nó, kênh lớn kênh nhỏ đều công bằng |
| Nội dung đáng chia sẻ | share\_rate ≥ 1% và view ≥ 10.000 | Tìm nội dung hữu ích, dễ nhân bản cho B2B |
| Tự nhập | Người dùng nhập từng ngưỡng | Thử nghiệm |

Kết quả bước này là danh sách video "đạt ngưỡng". Chỉ danh sách này mới đi tiếp sang chuyển thoại, Jev và LLM, nhờ vậy tiết kiệm thời gian và chi phí API.

Cần ít nhất 5 video của page trong đợt quét thì mới tính `ratio_median`. Ít hơn thì để trống cột này và ghi chú trong log.

## 6. Tích hợp Jev

Mỗi video gọi Jev **đúng 1 lần**, gửi kèm toàn bộ câu hỏi. Jev trả lời các câu hỏi song song và độc lập trên cùng một state, nên thêm câu hỏi gần như không làm chậm. Endpoint là `POST https://api.typesafe.ai/v1/systemone`, xác thực bằng `Authorization: Bearer <API_KEY>`. SDK đọc biến môi trường `TYPESAFE_API_KEY`.

**State gửi đi: gọn và có tên trường.** Jev giảm độ chính xác khi state dài và có nhiều chi tiết thừa, nên code cắt sẵn trước khi gửi:

```python
state = {
    "hook": hook_3s(words) or caption[:200],   # câu mở đầu, khoảng 3 giây đầu
    "caption": caption[:1500],
    "transcript": transcript[:3000],
    "my_page": "Page B2B dược: khách là chủ nhà thuốc, dược sĩ"
}
```

**Bộ câu hỏi** (danh mục nhãn lưu trong `taxonomy.json`; mỗi Choice luôn có option `khac`):

| Khóa | Loại | Câu hỏi | Nhãn / mức |
| --- | --- | --- | --- |
| `topic` | Choice | Chủ đề chính của `caption` và `transcript` thuộc nhóm nào? | phap\_ly\_gpp, ban\_hang\_tu\_van, kien\_thuc\_benh, kien\_thuc\_thuoc, kinh\_doanh\_van\_hanh, khach\_hang\_tinh\_huong, cong\_nghe\_ai, doi\_song\_suc\_khoe, khac |
| `hook_type` | Choice | Câu `hook` thuộc kiểu mở đầu nào? | cau\_hoi, canh\_bao\_sai\_lam, con\_so\_danh\_sach, xung\_dot\_tranh\_cai, ke\_chuyen, bi\_mat\_tiet\_lo, loi\_ich\_truc\_tiep, khac |
| `structure` | Choice | `transcript` được sắp xếp theo cấu trúc nào? | van\_de\_giai\_phap, liet\_ke\_meo, truoc\_sau, tinh\_huong\_hoi\_dap, ke\_chuyen\_bai\_hoc, huong\_dan\_tung\_buoc, khac |
| `cta` | Choice | Kêu gọi hành động ở cuối là gì? | binh\_luan, inbox\_nhan\_tai\_lieu, luu\_chia\_se, theo\_doi\_page, mua\_lien\_he, khong\_co |
| `hook_strength` | Score | Câu `hook` giữ người xem lại mạnh đến đâu? | 0 Nhạt · 1 Có tò mò · 2 Rất cuốn |
| `relevant` | Noul | Nội dung có liên quan trực tiếp tới nghề dược hoặc kinh doanh nhà thuốc không? |  |
| `replicable` | Noul | `my_page` có làm lại được ý tưởng này với nội dung của mình không? |  |
| `risk_absolute` | Noul | Có câu khẳng định tuyệt đối hoặc cam kết chữa khỏi bệnh không? |  |
| `risk_compare` | Noul | Có so sánh, chê bai đối thủ hoặc thương hiệu cụ thể không? |  |

Viết câu hỏi thật cụ thể, gọi tên trường bằng dấu backtick. Jev hiểu câu hỏi theo nghĩa đen, không tự suy ra ý ngầm.

**Code mẫu:**

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

client = TypeSafeClient(model=cfg["jev"]["model"])

def ask_jev(state, tax):
    questions = {
        "topic": Choice(
            instructions="Chủ đề chính của `caption` và `transcript` thuộc nhóm nào?",
            criteria=tax["topic"]),          # dict: mã nhãn -> mô tả tiếng Việt
        "hook_type": Choice(
            instructions="Câu `hook` thuộc kiểu mở đầu nào?",
            criteria=tax["hook_type"]),
        "hook_strength": Score(
            instructions="Câu `hook` giữ người xem lại mạnh đến đâu?",
            criteria=["Nhạt, không gợi tò mò", "Có gợi tò mò", "Rất cuốn, khó lướt qua"]),
        "relevant": Noul(
            instructions="`caption` hoặc `transcript` có liên quan trực tiếp tới nghề dược hoặc kinh doanh nhà thuốc không?"),
        "replicable": Noul(
            instructions="Page mô tả trong `my_page` có làm lại được ý tưởng này với nội dung của mình không?"),
        # ... structure, cta, risk_absolute, risk_compare
    }
    return client.system_one(state=state, questions=questions)
```

**Đọc kết quả bằng code:**

- Choice/Score trả về `confidence`. Nếu `confidence < min_confidence` (mặc định 0,6) thì ghi nhãn kèm hậu tố "(chưa chắc)" để người xem kiểm tra lại.
- Noul trả về xác suất 0–1. Đổi thành Có/Không bằng ngưỡng `yes_threshold` (mặc định 0,5), đồng thời giữ cả số gốc trong Excel.
- Video có `relevant < 0,5` thì vẫn ghi vào Excel, nhưng **không gọi LLM** (để tiết kiệm chi phí).
- **Điểm công thức** tính bằng code, đổi trọng số trong `settings.json` mà không phải sửa câu hỏi:

```
diem = 40·min(ratio_median/5, 1) + 25·replicable + 20·(hook_strength/2) + 15·relevant
```

**Kiểm thử trước khi giao:** Jev 1.13 có xu hướng nghiêng về option đứng đầu danh sách. Khi test, đảo thứ tự option trong `taxonomy.json` rồi chạy lại 30 video mẫu; nhãn nào đổi thì viết lại mô tả của nhãn đó cho rõ hơn. Lỗi 429/529 thì SDK tự thử lại; bắt `RateLimitError` để ghi log.

## 7. Tích hợp LLM (endpoint OpenAI)

LLM chỉ viết chữ. Nhãn Jev đã gắn được đưa vào prompt làm khung, để phần chữ bám đúng công thức và không tự đặt lại tên nhóm.

**Gọi API:**

```python
from openai import OpenAI
llm = OpenAI(base_url=cfg["llm"]["base_url"], api_key=cfg["llm"]["api_key"])

resp = llm.chat.completions.create(
    model=cfg["llm"]["model"],
    temperature=0.4,
    response_format={"type": "json_object"},   # bỏ dòng này nếu endpoint không hỗ trợ
    messages=[{"role": "system", "content": SYSTEM},
              {"role": "user", "content": user_prompt(video, jev_labels)}])
```

**Prompt hệ thống (rút gọn):**

```text
Bạn là biên tập viên content cho page B2B ngành dược (khách: chủ nhà thuốc, dược sĩ).
Đầu vào: caption, transcript và các nhãn đã gắn (chủ đề, kiểu hook, cấu trúc, CTA).
Giữ đúng các nhãn đó, không đặt nhãn mới. Viết tiếng Việt tự nhiên, không khẳng định tuyệt đối,
không so sánh đối thủ, không chép nguyên câu của video gốc.
Trả về JSON đúng các khóa:
{"chu_de_bai": "<= 12 chữ",
 "tom_tat": "2-3 câu",
 "hook_goc": "câu mở đầu của video",
 "ly_do_viral": "1-2 câu, giả thuyết",
 "goi_y_nhan_ban": [{"hook_moi": "", "y_tuong": ""}, ... 3 mục]}
```

**Xử lý lỗi:** JSON không parse được thì gọi lại 1 lần kèm câu "Chỉ trả JSON". Vẫn lỗi thì ghi chữ thô vào cột Ghi chú. Nếu endpoint không hỗ trợ `response_format`, code tự cắt đoạn từ dấu `{` đầu tiên tới dấu `}` cuối cùng rồi parse.

**Jev kiểm tra lại từng gợi ý** (1 lượt gọi cho cả 3 gợi ý của một video):

| Khóa | Loại | Câu hỏi |
| --- | --- | --- |
| `giu_cong_thuc_i` | Score 0–2 | `hook_moi` có cùng kiểu hook và cùng cấu trúc với video gốc không? |
| `chep_nguyen_i` | Noul | `y_tuong` có lặp lại gần nguyên văn câu chữ của `transcript` gốc không? |
| `rui_ro_i` | Noul | Gợi ý có khẳng định tuyệt đối hoặc cam kết chữa bệnh không? |

Gợi ý có `giu_cong_thuc < 1`, hoặc `chep_nguyen > 0,5`, hoặc `rui_ro > 0,5` sẽ bị loại. Nếu cả 3 gợi ý đều bị loại thì gọi LLM viết lại tối đa 1 lần, sau đó ghi những gợi ý còn đạt.

**Tổng hợp cuối lượt:** code đếm nhãn Jev theo nhóm (số video, view trung bình, điểm công thức trung bình), rồi gửi bảng đếm này cho LLM viết 5–7 dòng nhận xét "công thức đang thắng" vào Sheet 2. Chỉ gửi bảng số đã tính sẵn, không gửi toàn bộ transcript.

## 8. Đầu ra Excel

Tên file: `output/cong-thuc_YYYY-MM-DD_HHmm.xlsx`. Sheet 1 sắp xếp theo Điểm công thức giảm dần, có bật bộ lọc ở dòng tiêu đề và cố định cột STT, Kênh.

**Sheet 1 – Chi tiết video**

| Nhóm | Cột | Nguồn |
| --- | --- | --- |
| Định danh | STT, Kênh, Follower kênh, Ngày đăng, Định dạng, Thời lượng (giây), Link bài | Thu thập |
| Chỉ số | View, Cảm xúc, Bình luận, Chia sẻ, View/Follower, Hệ số so trung vị kênh, Tỷ lệ tương tác, Tỷ lệ share | Thu thập + code |
| Nội dung | Chủ đề bài, Tóm tắt, Caption, Nội dung thoại, Hook gốc | LLM + thu thập |
| Công thức | Nhóm chủ đề, Kiểu hook, Độ mạnh hook, Cấu trúc, CTA | Jev |
| Đánh giá | Liên quan ngành (%), Làm lại được (%), Điểm công thức (0–100), Cờ rủi ro | Jev + code |
| Nhân bản | Lý do viral, Gợi ý 1, Gợi ý 2, Gợi ý 3 | LLM (đã qua Jev kiểm tra) |
| Khác | Ghi chú (nhãn chưa chắc, lỗi lấy thoại) | Code |

**Sheet 2 – Tổng hợp công thức:** 2 bảng đếm (Nhóm chủ đề × số video, view trung bình, điểm trung bình; Kiểu hook × các chỉ số tương tự) và đoạn nhận xét do LLM viết.

**Sheet 3 – Nhật ký:** thời gian chạy, tham số đã chọn, số video đã quét/đạt ngưỡng/đã phân tích theo từng kênh, lỗi theo kênh, page bị bỏ qua vì dưới ngưỡng follower, lượng token Jev và LLM, số phút Deepgram đã dùng (lấy từ trường `usage` mà Jev trả về).

Định dạng: cột chữ dài bật wrap text và rộng 60; số có dấu phân cách hàng nghìn; tỷ lệ hiển thị %; dòng có Cờ rủi ro tô nền vàng nhạt.

## 9. Giao diện, đóng gói, cài đặt

Giao diện là trang web chạy cục bộ (Streamlit), tự mở trên trình duyệt khi bấm file chạy. Có 3 tab:

1. **Cài đặt** (bắt buộc ở lần mở đầu tiên): nếu còn thiếu key, tool mở thẳng màn hình này và chưa cho dùng tab khác. Có ô nhập API key Jev, API key Deepgram, và endpoint + key + model LLM; mỗi loại có nút "Kiểm tra và lưu". Cùng tab này có ô nhập danh sách kênh và nút "Đăng nhập Facebook".
2. **Chạy quét:** số ngày (7/14/30/tự nhập), định dạng (Reels, Video, Tất cả), follower tối thiểu của page (mặc định 100.000), preset ngưỡng video hoặc tự nhập, nút Chạy. Đầu tab có 3 đèn trạng thái key (Jev, Deepgram, LLM). Có thanh tiến trình theo từng kênh và nút Dừng.
3. **Kết quả:** danh sách file Excel đã xuất, nút mở thư mục.

**Đóng gói cho Windows:**

- PyInstaller build thành thư mục `VideoCongThuc/` chứa `VideoCongThuc.exe`, kèm `ffmpeg.exe` và thư mục `config/` mẫu.
- Chromium của Playwright tự tải ở lần chạy đầu (khoảng 150 MB), có màn hình báo đang tải.
- Model `faster-whisper` cũng tải ở lần dùng đầu, chỉ khi bật chế độ dự phòng chạy máy.
- Nén thành 1 file ZIP. Người dùng chỉ cần giải nén, chạy `VideoCongThuc.exe`, rồi làm theo tab Cài đặt.

**Quản lý API key**

Người dùng nhập key 1 lần, tool lưu lại cho các lần sau. Key được lưu vào Windows Credential Manager qua thư viện `keyring`, không lưu dạng chữ thường trong file. Vì vậy thư mục tool có thể gửi cho người khác mà không lộ key. Người dùng đổi key bất cứ lúc nào ở tab Cài đặt. Giao diện và log chỉ hiện 4 ký tự cuối của key (ví dụ ••••a91f), không bao giờ in cả key.

Key được kiểm tra vào 3 thời điểm:

1. Khi bấm "Kiểm tra và lưu": tool gọi thử mỗi dịch vụ một lượt rất nhỏ và chỉ lưu khi gọi thành công. Jev: 1 câu Noul ngắn. Deepgram: 1 file âm thanh mẫu dài 1 giây đóng sẵn trong tool. LLM: 1 tin nhắn "ping" với `max_tokens=1`.
2. Mỗi lần bấm Chạy: kiểm tra lại cả 3 key trước khi mở Facebook. Key nào lỗi thì đèn chuyển đỏ, hiện lý do, và tool không chạy.
3. Trong lúc chạy: xử lý lỗi theo bảng dưới. Video đã xử lý vẫn nằm trong cache, nên chạy lại sau khi sửa key không mất công.

| Lỗi | Thông báo cho người dùng | Tool xử lý |
| --- | --- | --- |
| Key sai, hết hạn hoặc bị thu hồi (HTTP 401/403) | "API key \[Jev/Deepgram/LLM\] không hợp lệ. Vào Cài đặt để nhập lại." | Chưa chạy thì chặn. Đang chạy thì tạm dừng và lưu tiến độ |
| Hết credit hoặc hết hạn mức | "Tài khoản \[tên dịch vụ\] đã hết credit/hạn mức." | Jev: tạm dừng. Deepgram: chuyển sang chạy máy nếu bật dự phòng, nếu không thì để trống cột thoại. LLM: hỏi người dùng muốn chạy tiếp không có gợi ý hay tạm dừng |
| Endpoint hoặc tên model LLM sai (404) | "Không tìm thấy endpoint hoặc model LLM. Kiểm tra lại địa chỉ và tên model." | Chặn trước khi chạy |
| Gọi quá nhanh (429; Jev có thêm 529) | Không báo, chỉ ghi log | Tự thử lại với thời gian chờ tăng dần. Quá 5 lần thì xử lý như lỗi hết hạn mức |
| Mất mạng, quá thời gian chờ | "Không kết nối được tới \[tên dịch vụ\]." | Thử lại 3 lần rồi tạm dừng |

Thông báo hiện bằng hộp thoại tiếng Việt và ghi vào Sheet 3. Thư mục `profile/` chứa phiên đăng nhập Facebook; dặn người dùng không gửi thư mục này cho người khác.

Kèm theo file `HUONG-DAN.pdf` 1 trang có ảnh chụp 3 tab giao diện.

## 10. Lộ trình, nghiệm thu, rủi ro

Dự kiến khoảng 4 tuần cho 1 người làm. Mỗi giai đoạn chạy được thật thì mới sang giai đoạn sau.

1. **Tuần 1 – Thu thập + lọc:** đăng nhập, quét 3 kênh mẫu, lọc theo preset, xuất Excel chỉ có số liệu và caption.
2. **Tuần 2 – Jev:** soạn `taxonomy.json` cùng đội content, ráp bộ câu hỏi, tính điểm công thức, test đảo thứ tự option trên 30 video.
3. **Tuần 3 – Thoại + LLM:** chuyển thoại, prompt LLM, vòng Jev kiểm tra gợi ý, Sheet 2 tổng hợp.
4. **Tuần 4 – Giao diện + đóng gói:** Streamlit 3 tab, build exe, viết hướng dẫn, cho 2 người không biết code thử cài.

**Checklist nghiệm thu:**

- [ ] Cài trên máy mới từ file ZIP trong dưới 10 phút, không phải gõ lệnh
- [ ] Lần mở đầu tiên bắt nhập đủ 3 loại key; lần sau không phải nhập lại
- [ ] Nhập sai một key thì tool báo đúng key nào lỗi và không cho chạy
- [ ] Đăng nhập Facebook 1 lần, các lần sau chạy không phải đăng nhập lại
- [ ] Page dưới 100.000 follower bị bỏ qua và được ghi trong Sheet 3
- [ ] Quét 10 kênh × 30 ngày không bị checkpoint, kênh lỗi không làm dừng cả lượt
- [ ] Số view/chia sẻ trong Excel khớp với Facebook trên 20 video lấy ngẫu nhiên (sai lệch dưới 5%)
- [ ] Nhãn Jev đúng ít nhất 80% trên 30 video do đội content gắn tay
- [ ] Lần chạy thứ 2 không gọi lại Jev/LLM cho video đã có trong cache
- [ ] Không có gợi ý nào chép nguyên văn hoặc khẳng định chữa bệnh lọt vào Excel

**Rủi ro và cách xử lý:**

| Rủi ro | Cách xử lý |
| --- | --- |
| Facebook đổi giao diện, tool không đọc được số | Selector nằm trong `selectors.json`; Phong cập nhật file và gửi lại, không build lại exe |
| Nick bị checkpoint | Dùng nick phụ, giãn cách ngẫu nhiên, giới hạn số video mỗi lượt, phát hiện checkpoint thì dừng |
| Jev gắn nhãn tiếng Việt chưa chuẩn | Test trên 30 video ở tuần 2; mô tả nhãn trong `taxonomy.json` viết cụ thể, có ví dụ |
| Jev đang ở giai đoạn early access, giá hoặc giới hạn có thể đổi | Ghim phiên bản model, ghi `usage` vào Sheet 3 để theo dõi chi phí |
| Hết $200 credit Deepgram | Chỉ chuyển thoại video đạt ngưỡng, cache transcript; theo dõi số phút ở Sheet 3; hết credit thì nạp thêm hoặc chuyển sang chạy máy |
| Bị hiểu là sao chép nội dung | Tool chỉ xuất ý tưởng; vòng Jev chặn gợi ý gần nguyên văn; dặn đội không tải lại video người khác |

**Tài liệu tham khảo**

- [Jev – Quick start](https://docs.typesafe.ai/introduction/quickstart)
- [Jev – API reference](https://docs.typesafe.ai/api.md)
- [Jev 1.13 – các điểm yếu đã biết](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- [Danh mục tài liệu Jev (cookbooks, patterns)](https://docs.typesafe.ai/llms.txt)

## 11. Phụ lục cho Agent: mã nguồn tham khảo trên GitHub

Agent đọc phụ lục này trước khi viết từng module. Mỗi mục ghi rõ repo, file, hàm cần đọc, phần nên mượn và phần không được làm theo. Các repo dưới đây đã được tải về và đọc code trực tiếp ngày 11/10/2026; số commit ghi trong bảng để agent mở đúng phiên bản đã đọc.

**Quy tắc bản quyền:** repo có license MIT thì được chép code, nhưng phải giữ dòng bản quyền của tác giả trong file `THIRD_PARTY_NOTICES.txt`. Repo không có file LICENSE thì chỉ được đọc để hiểu cách làm, sau đó tự viết lại, không chép code.

| Repo | Commit đã đọc | License | Dùng cho module |
| --- | --- | --- | --- |
| [winhtuan/crawler-social](https://github.com/winhtuan/crawler-social) | 5e8934f (10/09/2026) | Không có file LICENSE: chỉ đọc | B. Lấy video và chỉ số qua GraphQL, đăng nhập, cuộn trang |
| [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | 8973412 (10/10/2026) | Unlicense (public domain) | C. Metadata từng video, tải audio |
| [mohdtalal3/facebook\_post\_comment\_scraper](https://github.com/mohdtalal3/facebook_post_comment_scraper) | 0c33360 (07/10/2026) | MIT | B. Nhận diện reel/video; I. Đóng gói exe |
| [kevinzg/facebook-scraper](https://github.com/kevinzg/facebook-scraper) | 567711f (30/10/2023) | MIT | C. Đọc file cookie; D. Đổi số viết tắt |
| [shaikhsajid1111/facebook\_page\_scraper](https://github.com/shaikhsajid1111/facebook_page_scraper) | dd691c6 (14/07/2024) | MIT | Chỉ tham khảo vòng lặp quét, không dùng làm nền |
| [typesafe-ai/skills](https://github.com/typesafe-ai/skills) | 65a39f3 (12/09/2026) | MIT | F. Hướng dẫn chính thức dùng Jev cho agent |
| [Mharis-code/videoanalyzer](https://github.com/Mharis-code/videoanalyzer) | aa0c88a (10/06/2026) | MIT | E. Tách audio, thử lại khi lỗi; G. Khung phân tích công thức |
| [JeremySNR/clip-forge](https://github.com/JeremySNR/clip-forge) | 5fbd6cf (05/10/2026) | MIT | C. Cookie cho yt-dlp trên Windows; F. Bộ tiêu chí viral; I. Che key |
| [TopStriker33/vyralforge](https://github.com/TopStriker33/vyralforge) | b57d96b (19/05/2026) | MIT | G. Danh sách công thức hook, lớp chặn từ cấm; H. SQLite |
| [JayWebtech/autoshorts](https://github.com/JayWebtech/autoshorts) | f17b04c (02/08/2026) | Không có file LICENSE: chỉ đọc | E. Đọc timestamp từng từ của Deepgram; I. Màn hình nhập key lần đầu |

Không có repo nào làm sẵn trọn tool này. Hai repo nặng ký nhất cho phần khó là **crawler-social** (do người Việt viết, chạy trên Facebook tiếng Việt, cập nhật tháng 9/2026) và **yt-dlp**.

### 11.1 Module A – Đăng nhập Facebook 1 lần

- **crawler-social `tools/login.py`** (chỉ đọc): mở trình duyệt có giao diện, người dùng tự đăng nhập (kể cả 2FA), xác nhận xong thì gọi `context.storage_state(path=...)` để lưu phiên. README của repo ghi rõ: không đăng nhập thì chỉ lấy được khoảng 2 bài.
- **crawler-social `src/crawlfb/stealth.py`**: sau mỗi lần chạy, ghi đè lại `storage_state` để giữ phiên mới nhất; hàm `_convert_cookie_editor` chuyển file cookie xuất từ tiện ích trình duyệt sang định dạng Playwright. Tool có thể dùng như phương án thứ hai khi người dùng không đăng nhập được trong cửa sổ tool.
- **Áp dụng:** giữ thiết kế profile Playwright ở mục 4, thêm bước kiểm tra cookie `c_user` và `xs` có tồn tại sau khi đăng nhập. Thiếu thì coi như chưa đăng nhập.

### 11.2 Module B – Lấy danh sách video và chỉ số (phần khó nhất)

**Cách làm nên theo:** không đọc chữ trên giao diện, mà "nghe" các phản hồi GraphQL Facebook gửi về trình duyệt trong lúc cuộn trang. Số liệu ở đó là số nguyên chính xác, không phải dạng "1,2 Tr".

- **crawler-social `src/crawlfb/intercept.py`** (chỉ đọc, tự viết lại):
  - Lớp `FeedInterceptor` gắn `page.on("response", ...)`, chỉ xử lý URL chứa `/api/graphql/` có status 200.
  - `split_json_values()`: một phản hồi GraphQL của Facebook chứa nhiều JSON nối liền nhau, nên `resp.json()` sẽ lỗi "Extra data". Hàm này tách bằng `json.JSONDecoder().raw_decode` trong vòng lặp.
  - `extract_stories()`: duyệt đệ quy toàn bộ JSON, gom các node có `__typename == "Story"` và có `post_id`, bỏ trùng theo `post_id`.
  - `flatten()`: nội dung bài ở `comet_sections.content.story.message.text`; ngày đăng là `creation_time` (giây unix); link ở `permalink_url`; reel nhận diện bằng `"/reel/" in permalink_url`.
  - `_feedback()`: đường dẫn tới khối chỉ số là `comet_sections.feedback.story.story_ufi_container.story.feedback_context.feedback_target_with_context.comet_ufi_summary_and_actions_renderer.feedback`.
  - `_views()`: lấy `video_view_count`; không có thì `video_view_count_renderer.feedback.video_view_count`; cuối cùng là `play_count`.
  - `_share_count()` và `_comment_count()`: mỗi chỉ số có 2 đường dẫn, một cho lúc đã đăng nhập (`adaptive_ufi_action_renderers[i].feedback...`), một cho lúc chưa đăng nhập.
  - `_reaction_counts()`: đổi cảm xúc theo ID cố định, dự phòng theo tên tiếng Việt (Thích, Yêu thích, Thương thương, Haha, Wow, Buồn, Phẫn nộ).
- **crawler-social `src/crawlfb/paginate.py`** → `collect_posts()`: mỗi vòng cuộn xuống cuối trang, lăn chuột thêm một đoạn, rồi `page.wait_for_response(lambda r: "/api/graphql/" in r.url, timeout=8000)` thay vì chờ mù. `update_stall()` dừng khi nhiều vòng liền không có bài mới; có trần số vòng cuộn để không treo. **Tool thêm 1 điều kiện dừng:** gặp bài có `creation_time` cũ hơn số ngày quét (so sánh trong code).
- **crawler-social `src/crawlfb/humanizer.py`**: nghỉ 3 ± 2 giây, tối thiểu 0,5 giây. Phần "Anti-ban" trong README: mỗi lần 1 page, không chạy song song, giữ nguyên độ trễ, dùng lại cùng một phiên đăng nhập.
- **crawler-social `docs/adr/0002-exclude-reels.md`**: trang `/reel/<id>` không hiện đủ bình luận, phải đổi sang `/watch/?v=<id>`. Repo này lấy reel xuất hiện trong dòng thời gian của page, **không** quét riêng tab Reels.
- **mohdtalal3 `scraper/extractors.py`** (MIT): `is_reel_or_video_post()` nhận diện video qua `attachments[].media.__typename == "Video"` hoặc `attachments[].styles.attachment.media`, có xét cả `all_subattachments`. `extract_share_count()` thử thêm `i18n_share_count` khi không có số nguyên.

**Không làm theo:**

- mohdtalal3 `scraper/page_posts.py` gọi thẳng GraphQL bằng `doc_id` cố định và token `fb_dtsg`. `doc_id` đổi theo phiên bản Facebook, nên cách này dễ gãy hơn cách nghe phản hồi trong trình duyệt.
- shaikhsajid1111 `element_finder.py` đọc cảm xúc qua `aria-label` tiếng Anh ("Like", "Love"), nên sẽ sai trên Facebook tiếng Việt.

**Lưu ý khi tải trang lần đầu:** công cụ `tools/capture_feed.py` của crawler-social ghi chú rằng khi mới tải trang, lô bài đầu tiên được Facebook nhúng sẵn trong HTML chứ không gửi qua `/api/graphql/`; GraphQL chỉ xuất hiện khi cuộn. Vì vậy parser phải đọc cả JSON trong các thẻ `<script data-sjs>` của HTML ban đầu, theo cách yt-dlp làm ở mục 11.3, nếu không sẽ mất các video mới nhất.

**Việc agent phải làm trước khi viết module này:**

- [ ] Đăng nhập nick phụ, mở tab Reels và tab Video của 1 page mẫu, lưu toàn bộ phản hồi `/api/graphql/` ra `tests/fixtures/` (crawler-social có `tools/capture_feed.py` cho việc tương tự). Tab Reels có thể dùng cấu trúc JSON khác dòng thời gian; phải kiểm tra trên fixture thật.
- [ ] Đặt mọi đường dẫn JSON vào `config/graphql_paths.json`, bên cạnh `selectors.json`. Facebook đổi cấu trúc thì sửa file, không build lại.
- [ ] Viết test cho `flatten()` chạy trên fixture, để biết ngay khi Facebook đổi cấu trúc.

### 11.3 Module C – Bổ sung chỉ số từng video bằng yt-dlp, và cookie

yt-dlp đã có sẵn bộ đọc trang video Facebook. Dùng nó làm nguồn dự phòng khi GraphQL thiếu một chỉ số, và dùng chính nó để tải audio.

- **yt-dlp `yt_dlp/extractor/facebook.py`** (public domain):
  - `FacebookIE._extract_from_url()` đọc JSON trong các thẻ `<script data-sjs>`, theo đường `require → __bbox → result.data`.
  - Lấy được: `view_count` (regex `viewCount` hoặc `video_view_count`), `comment_count` (`feedback.total_comment_count`), `repost_count` tức lượt chia sẻ (`share_count_reduced`), `timestamp`, `duration`, `description`, `uploader_id`. Lưu ý: `like_count` là `likers.count`, không phải tổng các loại cảm xúc.
  - `FacebookReelIE` đổi link `/reel/<id>` thành `m.facebook.com/watch/?v=<id>` rồi mới đọc.
- **Cách gọi trong tool:** dùng yt-dlp như thư viện Python, không gọi lệnh ngoài:

```python
import yt_dlp
opts = {"cookiefile": "data/fb_cookies.txt", "skip_download": True, "quiet": True}
with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info(video_url, download=False)
# info["view_count"], info["comment_count"], info["repost_count"], info["timestamp"], info["duration"]
```

- **Cookie cho yt-dlp trên Windows, xem clip-forge `src/main/pipeline/ytdlp.ts`** (MIT): các hàm `cookieArgs()`, `isDpapiDecryptError()`, `cookieDpapiErrorHint()` ghi nhận rằng trên Windows, `--cookies-from-browser chrome/edge` thường thất bại vì Chrome mã hóa cookie riêng cho ứng dụng. **Áp dụng:** tool không đọc cookie từ Chrome của người dùng. Sau khi đăng nhập, xuất cookie từ profile Playwright (`context.cookies()`) ra file định dạng Netscape `data/fb_cookies.txt` rồi đưa vào `cookiefile`. File này chứa phiên đăng nhập, phải nằm cùng chỗ với `profile/` và không được gửi cho người khác.
- **clip-forge `src/main/cookies.ts`** → `isNetscapeCookiesFile()`: kiểm tra một file có đúng định dạng Netscape không.
- **kevinzg `facebook_scraper/utils.py`** → `parse_cookie_file()` (MIT): đọc được cả 3 kiểu file cookie (Netscape, JSON của EditThisCookie, JSON của Cookie Quick Manager). Chép được nếu muốn cho người dùng nạp file cookie thay vì đăng nhập trong tool.

### 11.4 Module D – Chuẩn hóa số và ngày

- **kevinzg `utils.py` → `convert_numeric_abbr()`** và **shaikhsajid1111 `scraping_utilities.py` → `__value_to_float()`** chỉ hiểu `k` và `m`. Hàm của shaikhsajid1111 còn có nhánh `m` bị lặp (lỗi). **Không chép.** Tự viết `parse_count()` hiểu thêm "N", "nghìn", "Tr", "triệu", dấu phẩy thập phân kiểu Việt ("1,2 Tr" = 1.200.000) và dấu chấm phân cách hàng nghìn ("12.345"), có test cho từng kiểu.
- Ưu tiên số nguyên từ GraphQL (mục 11.2) hoặc yt-dlp (mục 11.3). `parse_count()` chỉ dùng khi buộc phải đọc chữ trên giao diện.
- **Ngày đăng:** dùng `creation_time` (GraphQL) hoặc `timestamp` (yt-dlp), cả hai là giây unix. Đổi sang giờ Việt Nam trong code. Không parse chữ kiểu "3 ngày trước"; `parse_datetime()` của kevinzg (dùng thư viện `dateparser`) chỉ là dự phòng cuối cùng.

### 11.5 Module E – Tách audio và chuyển thoại Deepgram

- **videoanalyzer `scripts/whisper.py` → `extract_audio()`** (MIT): lệnh ffmpeg `-vn -acodec libmp3lame -ar 16000 -ac 1 -b:a 64k` cho file mono 16 kHz khoảng 480 kB mỗi phút. Dùng lệnh này trước khi gửi Deepgram để tải lên nhanh hơn. Hàm còn kiểm tra file ra rỗng để phát hiện video không có tiếng.
- **videoanalyzer `scripts/whisper.py` → `_post_whisper()`** (MIT): mẫu thử lại khớp đúng bảng lỗi ở mục 9. Lỗi 4xx khác 429 thì dừng ngay vì thử lại không giúp gì. Lỗi 429 thì đọc header `Retry-After` (hàm `_retry_after()`), không có thì chờ tăng gấp đôi. Lỗi mạng thì chờ tăng dần. Tối đa 4 lần. Áp dụng cho cả Deepgram, Jev và LLM.
- **videoanalyzer `scripts/download.py` → `download_url()`**: gọi yt-dlp với `--no-playlist`; yt-dlp có thể trả mã lỗi vì phụ đề hỏng dù video đã tải xong, nên coi "có file" là thành công.
- **autoshorts `src-tauri/src/transcription.rs` → `normalize_deepgram()`** (chỉ đọc): Deepgram trả về từng từ kèm thời điểm ở `results.channels[0].alternatives[0].words[]`, mỗi từ có `punctuated_word`, `start`, `end` (giây). **Áp dụng:** lấy hook = các từ có `start < 3.0` (nối lại, nới tới hết câu nếu câu chưa kết thúc), thay cho việc cắt 200 ký tự đầu như mục 6. Repo này dùng `model=nova-2`; tool dùng `nova-3` với `language=vi` như mục 4.

### 11.6 Module F – Tích hợp Jev

- **typesafe-ai/skills `skills/typesafe-ai/SKILL.md`** (MIT, của chính hãng TypeSafe): agent **phải cài skill này trước khi viết code Jev**, bằng `npx skills add typesafe-ai/skills --skill typesafe-ai` hoặc `claude plugin marketplace add typesafe-ai/skills` rồi `claude plugin install typesafe@typesafe-ai`. Các nguyên tắc trong skill áp thẳng vào tool:
  - Đọc tài liệu trực tiếp tại `docs.typesafe.ai/llms.txt`; thêm `.md` vào đường dẫn trang để lấy bản Markdown. Không tự đoán chi tiết theo phiên bản.
  - Mỗi câu hỏi là một phán đoán hẹp. State là JSON có tên trường, câu hỏi gọi tên trường bằng dấu backtick.
  - Choice luôn có lựa chọn "không khớp" (trong tool là `khac`).
  - Nhiều nhãn có thể cùng đúng thì dùng một Noul cho mỗi nhãn, không ép vào một Choice.
  - Quy tắc kiểu "chỉ cần một vi phạm là chặn" thì dùng các Noul riêng, không cộng điểm. Cờ rủi ro ở mục 6 đã làm đúng như vậy.
  - Gửi mọi câu hỏi độc lập trên cùng một state trong một lượt gọi.
  - Ngưỡng confidence phải đo trên dữ liệu thật của mình, không lấy số trong cookbook.
  - Lưu kết quả thô. Đổi trọng số Điểm công thức thì không cần gọi lại Jev. **Áp dụng:** lưu nguyên JSON `answers` của Jev vào SQLite (mục 11.8).
- **Cookbook nên đọc:** `patterns/composite-scoring` (Điểm công thức), `cookbooks/citation_check` (kiểm gợi ý có chép nguyên văn không), `cookbooks/classifying_rag_passages` (lọc video lạc đề trước khi gọi LLM).
- **clip-forge `src/main/pipeline/highlights.ts` → hằng `SYSTEM_PROMPT`** (MIT): bộ tiêu chí viral dựa trên nghiên cứu của Berger và Milkman (2012). Gồm 5 phần: sức hút của hook (0–30), cảm xúc mạnh như ngạc nhiên, thích thú, lo lắng, phẫn nộ (0–25), giá trị dùng được ngay (0–20), cấu trúc hook → phát triển → kết thúc trọn ý (0–15), khả năng được chia sẻ (0–9). **Áp dụng:** không đưa cả bảng này vào một câu hỏi. Tách thành các câu Score riêng cho Jev (`cam_xuc_manh`, `gia_tri_thuc_tien`, `ket_thuc_tron_y`, `kha_nang_chia_se`), rồi cộng trọng số trong code như công thức ở mục 6.

### 11.7 Module G – Danh mục công thức (`taxonomy.json`) và prompt LLM

- **videoanalyzer `SKILL.md`, Step 4 "Produce the Analysis"** (MIT): khung phân tích một video gồm:
  - Góc nhìn: "Nhiều người nghĩ…" đối lại "Thực tế là…".
  - Hook: câu nói, hình ảnh đi kèm, loại hook, và một **mẫu hook điền chỗ trống** để làm lại.
  - Các nhịp kể chuyện theo mốc thời gian.
  - CTA: lời kêu gọi, vị trí (đầu, giữa, cuối), cơ chế (mồi bình luận, inbox nhận tài liệu, lưu, chia sẻ).
  - 3–5 hành động làm lại cụ thể cho riêng video đó, không phải lời khuyên chung.
  - Quy tắc: không bịa nội dung không có trong thoại hoặc caption.
  - **Áp dụng:** thêm vào JSON của LLM ở mục 7 các khóa `goc_nhin`, `mau_hook_dien_cho_trong`, `vi_tri_cta`. Danh sách loại hook trong file (Authority, Question, Pattern Interrupt, Shock, Promise, Story Open, Curiosity Gap) dùng để rà lại `taxonomy.json`.
- **vyralforge `analyzer/hooks.py`** (MIT):
  - Hằng `KNOWN_FORMULAS`: POV first-person, Transformation timeline, Forbidden knowledge, Identity callout, Curiosity gap, Direct command, Hot take, X for 30 days, Reveal-first, Specificity number. Việt hóa các loại hợp với ngành dược để bổ sung nhãn `hook_type`, ví dụ "gọi đúng đối tượng" ("Chủ nhà thuốc nào cũng…"), "bí mật nghề", "con số cụ thể".
  - Hàm `_first_lines()` lấy dòng đầu caption (200 ký tự) cộng 30 từ đầu transcript. Dùng làm dự phòng khi Deepgram không có timestamp (mục 11.5).
- **vyralforge `planner/llm_brain.py` → `_strip_fences()`**: bỏ khối \`\`\`json bao quanh trước khi parse. Thêm vào bước xử lý lỗi JSON ở mục 7.
- **vyralforge `config.py` (khối `compliance`) và `planner/generate_week.py` → `_validate_compliance()`**: chặn gợi ý chứa từ cấm bằng code, trước cả bước Jev. **Áp dụng:** thêm `config/ban_words.txt` cho ngành dược (ví dụ "khỏi hẳn", "100%", "tốt nhất", "cam kết", "đặc trị") do đội pháp chế duyệt. Quét gợi ý của LLM bằng code; dính từ cấm thì loại luôn, không tốn lượt gọi Jev.

### 11.8 Module H – SQLite cache

- **vyralforge `database/schema.sql`** (MIT): bảng `posts` có `owner_followers`, `caption`, `transcript`, `posted_at`, `play_count`, `comment_count`, `share_count`, `video_duration`, `url`, kèm index theo điểm và theo ngày đăng. Chép làm khung, đổi tên cột theo mục 8. Thêm 3 bảng: `pages` (follower, lần quét gần nhất), `jev_answers` (JSON thô theo video và phiên bản model), `llm_outputs`.
- **vyralforge `database/db.py`** (MIT): hàm `conn()` dùng contextmanager tự commit và đóng kết nối; `upsert_post()` dùng `INSERT ... ON CONFLICT(id) DO UPDATE` để chạy lại chỉ cập nhật số liệu. Chép được gần như nguyên văn.
- **Không dùng `vyralforge/analyzer/viral_score.py`**: công thức dựa trên tín hiệu thuật toán Instagram. Chỉ mượn ý chuẩn hóa điểm theo phân vị thứ 95 nếu cần đưa Điểm công thức về thang 0–100.

### 11.9 Module I – Giao diện, API key, đóng gói

- **clip-forge `src/main/settings.ts`** (MIT):
  - `maskKey()` chỉ hiện vài ký tự đầu và cuối của key.
  - `getSettings()` trả về cờ `keyStorageSecure` để giao diện báo cho người dùng khi máy không mã hóa được key.
  - **Áp dụng với Python:** dùng `keyring`; nếu backend của `keyring` lỗi thì hiện cảnh báo, không âm thầm lưu dạng chữ thường.
- **autoshorts `src/main.tsx`** (chỉ đọc): màn hình hướng dẫn lần đầu mở app; dòng cảnh báo ngay trên màn hình khi thiếu key (ví dụ thiếu key Deepgram thì báo chuyển thoại sẽ không chạy); nút đặt lại toàn bộ cấu hình. Chỉ học cách bố trí, tự viết.
- **mohdtalal3 `.github/workflows/build.yml`** (MIT): build exe Windows bằng `pyinstaller --onefile --noconfirm --add-data "web/templates;web/templates" --add-data "web/static;web/static"`. App là Flask, tự mở trình duyệt và tự chọn cổng trống khi cổng mặc định bận; `web/routes/api_settings.py` lưu cài đặt. **Lưu ý cho Phong:** đây là mẫu đã chạy được trên Windows. Nếu đóng gói Streamlit (mục 9) gặp khó, chuyển giao diện sang Flask hoặc FastAPI với HTML đơn giản theo mẫu repo này.

### 11.10 Checklist của Agent trước khi code

- [ ] Clone các repo trong bảng đầu mục 11, đúng commit đã ghi, vào thư mục `reference/`. Không đưa thư mục này vào bản phát hành.
- [ ] Cài skill TypeSafe (mục 11.6) và đọc `docs.typesafe.ai/llms.txt`.
- [ ] Lưu fixture GraphQL thật của tab Reels và tab Video (mục 11.2) trước khi viết parser.
- [ ] Code chép từ repo MIT: ghi tên repo, commit và dòng bản quyền vào `THIRD_PARTY_NOTICES.txt`.
- [ ] crawler-social và autoshorts không có license: chỉ đọc, tự viết lại.
- [ ] Đường dẫn JSON và selector của Facebook không viết cứng trong code; đặt trong `config/`.
