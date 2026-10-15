import { appState } from "./app.js";
const clone = (value) => structuredClone(value);
const providers = [{ label: "OpenRouter", url: "https://openrouter.ai/api/v1" }, { label: "OpenAI", url: "https://api.openai.com/v1" }, { label: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai/" }, { label: "Anthropic (Claude)", url: "https://api.anthropic.com/v1/" }];
const custom = "Khác (tự nhập)";
const initialServices = [
  { name: "jev", label: "Jev", role: "Gắn nhãn chủ đề, kiểu hook và cấu trúc cho từng video hoặc bài đăng.", key_help: "Key lấy từ tài khoản Jev. Key chỉ được lưu sau khi kiểm tra thành công.", configured: true, saved_mask: "••••demo", model: "jev-classify-2", needs_model: false },
  { name: "deepgram", label: "Deepgram", role: "Chuyển lời nói trong video thành chữ.", key_help: "Key lấy từ trang quản lý API key của Deepgram. Key chỉ được lưu sau khi kiểm tra thành công.", configured: false, saved_mask: null, model: "", needs_model: false, deepgram: { language: "vi", auto_language: true } },
  { name: "llm", label: "LLM", role: "Viết phân tích và gợi ý nhân bản. Dùng endpoint tương thích OpenAI.", key_help: "API key của nhà cung cấp đã chọn. Key chỉ được lưu sau khi kiểm tra thành công.", configured: appState.guide.configured.llm, saved_mask: appState.guide.configured.llm ? "••••demo" : null, model: appState.guide.configured.llm ? "openai/gpt-4.1-mini" : "", needs_model: false, llm: { base_url: providers[0].url, provider_label: "OpenRouter" } }
];
if (new URLSearchParams(location.search).get("mockFresh") === "1")
  for (const service of initialServices)
    Object.assign(service, { configured: false, saved_mask: null, model: "" });
let services = clone(initialServices), channelsText = ["# Các page công khai cần theo dõi", "https://www.facebook.com/TheThaoPharma", "https://www.facebook.com/nhathuoclongchau", "https://www.facebook.com/FPTShopOnline", "https://www.facebook.com/coccocbrowser", "https://www.facebook.com/vietnamairlines", "https://www.facebook.com/highlandscoffeevietnam", "https://www.facebook.com/PNJ.COM.VN", "https://www.facebook.com/Biti.s.official"].join(`
`);
let loginUntil = 0, loginNotice = null, reset = false;
const languages = [{ code: "vi", label: "Tiếng Việt" }, { code: "en", label: "Tiếng Anh" }, { code: "multi", label: "Đa ngôn ngữ" }];
const modelLists = {
  jev: [{ id: "jev-classify-2", label: "jev-classify-2", detail: "Phân loại nội dung tiếng Việt · phát hành 2026-08-12" }, { id: "jev-classify-1", label: "jev-classify-1", detail: "Model ổn định, tiết kiệm · phát hành 2025-11-01" }, { id: "jev-classify-pro", label: "jev-classify-pro", detail: "Hiểu ngữ cảnh chuyên sâu · phát hành 2026-09-20" }],
  deepgram: ["nova-3-general", "nova-3-medical", "nova-2-general", "nova-2-meeting", "enhanced-general"].map((id, i) => ({ id, label: id, architecture: i < 2 ? "nova-3" : i < 4 ? "nova-2" : "enhanced", languages: clone(i === 1 ? [languages[1]] : languages) })),
  llm: Array.from({ length: 300 }, (_, i) => {
    const family = ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4", "google/gemini-2.5-flash", "meta-llama/llama-3.3-70b", "deepseek/deepseek-chat"][i % 5];
    const id = i < 5 ? family : `${family}-preview-${String(Math.floor(i / 5)).padStart(2, "0")}`;
    return { id, label: `${id} · giá vào ${(0.1 + i % 8 * 0.2).toFixed(2)} · ra ${(0.4 + i % 7 * 0.4).toFixed(2)} USD / 1 triệu token · ngữ cảnh 128.000 token` };
  })
};
const defaultTaxonomy = { ok: true, intro: [
  "Tên hiển thị: chữ bạn thấy trong Excel. Đổi tên không làm Jev chấm lại.",
  "Mô tả cho Jev: viết cụ thể, có ví dụ thật và ranh giới với nhãn gần giống. Mô tả mơ hồ khiến Jev hay ghi (chưa chắc).",
  "Thêm dòng để thêm lựa chọn mới; xóa dòng để nội dung rơi vào nhãn gần nhất hoặc Khác.",
  "Thêm, xóa hoặc sửa mô tả rồi Lưu nhãn khiến lần quét sau Jev chấm lại mọi nội dung, tốn thêm một ít phí Jev.",
  "Nhãn không ảnh hưởng tới lượt xem, ngưỡng lọc hay các câu chấm điểm khác."
], groups: [
  { id: "topic", title: "Nhóm chủ đề", note: "Video/bài nói về chuyện gì? Kết quả ở cột Nhóm chủ đề trong Excel.", fixed: ["Khác"], rows: [{ code: "kien_thuc", name: "Kiến thức", description: "Giải thích kiến thức hoặc hướng dẫn thực hành, ví dụ cách đọc nhãn thuốc." }, { code: "san_pham", name: "Sản phẩm", description: "Giới thiệu công dụng, so sánh hoặc trải nghiệm sản phẩm cụ thể." }, { code: "doi_song", name: "Đời sống", description: "Chia sẻ trải nghiệm, chuyện nghề và tình huống thường ngày." }] },
  { id: "hook_type", title: "Kiểu hook", note: "Câu mở đầu thuộc kiểu nào? LLM giữ kiểu hook khi viết gợi ý nhân bản.", fixed: ["Không có", "Khác"], rows: [{ code: "cau_hoi", name: "Câu hỏi", description: "Mở bằng câu hỏi trực tiếp, ví dụ Bạn có đang uống thuốc sai cách?" }, { code: "canh_bao", name: "Cảnh báo", description: "Nêu nguy cơ hoặc sai lầm để người xem chú ý." }, { code: "bat_ngo", name: "Bất ngờ", description: "Mở đầu bằng sự thật trái kỳ vọng hoặc kết quả khó tin." }] },
  { id: "structure", title: "Cấu trúc", note: "Nội dung được sắp xếp theo trình tự nào (mở – thân – kết)?", fixed: ["Không có", "Khác"], rows: [{ code: "van_de_giai_phap", name: "Vấn đề – giải pháp", description: "Nêu vấn đề, giải thích nguyên nhân rồi đề xuất cách giải quyết." }, { code: "danh_sach", name: "Danh sách", description: "Trình bày nhiều mẹo hoặc bước theo thứ tự, ví dụ 3 điều cần nhớ." }] },
  { id: "cta", title: "CTA", note: "Cuối video/bài kêu gọi người xem làm gì?", fixed: ["Không có", "Khác"], rows: [{ code: "binh_luan", name: "Bình luận", description: "Đề nghị trả lời câu hỏi hoặc để lại ý kiến ở bình luận." }, { code: "theo_doi", name: "Theo dõi", description: "Kêu gọi theo dõi trang để xem thêm nội dung." }, { code: "mua_hang", name: "Mua hàng", description: "Kêu gọi mua, đặt hàng hoặc nhắn tin tư vấn sản phẩm." }] }
] };
let taxonomy = clone(defaultTaxonomy);
function updateApp() {
  const configured = Object.fromEntries(services.map((s) => [s.name, s.configured]));
  const missing = services.filter((s) => s.name !== "deepgram" && !s.configured).map((s) => s.label);
  appState.guide.configured = configured;
  appState.guide.missing = missing;
  appState.scan_locked = missing.length > 0;
  appState.guide.setup_done = !missing.length && appState.guide.channel_count > 0 && appState.guide.fb_ready;
  appState.journey[0].state = missing.length ? "current" : "done";
  appState.journey[1].state = missing.length ? "pending" : appState.guide.setup_done ? "done" : "current";
  appState.next_step = missing.length ? { text: "Kết nối Jev và LLM để mở khóa bước quét.", page: "settings" } : appState.guide.setup_done ? { text: "Đã chuẩn bị xong. Chọn bộ lọc và bắt đầu lần quét đầu tiên.", page: "scan" } : { text: "Lưu danh sách kênh và đăng nhập Facebook để chuẩn bị quét.", page: "settings" };
}
function finishLogin() {
  if (loginUntil && Date.now() >= loginUntil) {
    loginUntil = 0;
    appState.logging_in = false;
    appState.busy = Boolean(appState.guide.running);
    appState.guide.fb_ready = true;
    loginNotice = "Đã đăng nhập Facebook và lưu phiên.";
    updateApp();
  }
}
function problems(text) {
  return text.split(/\r?\n/).flatMap((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith("#"))
      return [];
    if (line.includes("/groups/"))
      return [`Dòng ${i + 1}: Không hỗ trợ nhóm Facebook; hãy dùng link trang chính của page.`];
    try {
      const url = new URL(line);
      if (!/^https?:$/.test(url.protocol) || !/(^|\.)facebook\.com$/i.test(url.hostname) || !url.pathname.replace(/\//g, ""))
        throw Error();
    } catch {
      return [`Dòng ${i + 1}: Link page Facebook không hợp lệ.`];
    }
    return [];
  });
}
const countChannels = (text) => text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")).length;
const wait = () => new Promise((resolve) => setTimeout(resolve, 350));
export default {
  get_services: async () => ({ ok: true, storage_secure: appState.storage_secure, llm_providers: clone(providers), custom_label: custom, services: clone(services) }),
  connect_service: async (name, key = "", base_url = "") => {
    await wait();
    const service = services.find((s) => s.name === name);
    if (!service)
      return { ok: false, error: "Dịch vụ không hợp lệ." };
    if (!key.trim() && !service.saved_mask)
      return { ok: false, error: "Vui lòng nhập API key trước khi kết nối." };
    if (name === "llm" && !/^https?:\/\/[^\s/]+/.test(base_url))
      return { ok: false, error: "Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://." };
    const models = modelLists[name];
    const recommended = { jev: "jev-classify-2", deepgram: "nova-3-general", llm: "google/gemini-2.5-flash" }[name];
    return { ok: true, models: clone(models), count: models.length, default_id: models.find((m) => m.id === service.model)?.id || recommended, recommended_id: recommended, ...name === "deepgram" ? { default_language: "vi" } : {} };
  },
  save_service: async (name, key = "", selection = {}) => {
    await wait();
    const service = services.find((s) => s.name === name);
    if (!service)
      return { ok: false, error: "Dịch vụ không hợp lệ." };
    if (!appState.storage_secure)
      return { ok: false, error: "Không thể lưu API key: kho bảo mật chưa khả dụng. Hãy bật Windows Credential Manager." };
    if (!key.trim() && !service.saved_mask)
      return { ok: false, error: "Vui lòng nhập API key trước khi kiểm tra." };
    if (!modelLists[name].some((m) => m.id === selection.model))
      return { ok: false, error: "Vui lòng chọn model trước khi kiểm tra." };
    if (name === "llm" && !/^https?:\/\/[^\s/]+/.test(selection.base_url || ""))
      return { ok: false, error: "Địa chỉ endpoint phải bắt đầu bằng https:// hoặc http://." };
    if (name === "deepgram" && !modelLists.deepgram.find((m) => m.id === selection.model).languages.some((l) => l.code === selection.language))
      return { ok: false, error: "Hãy chọn ngôn ngữ được model hỗ trợ." };
    service.saved_mask = "••••demo";
    service.model = selection.model;
    service.configured = true;
    service.needs_model = false;
    if (name === "llm")
      service.llm = { base_url: selection.base_url, provider_label: providers.find((p) => p.url.replace(/\/$/, "") === selection.base_url.replace(/\/$/, ""))?.label || custom };
    if (name === "deepgram")
      service.deepgram = { language: selection.language, auto_language: Boolean(selection.auto_language) };
    updateApp();
    return { ok: true, message: `Đã kiểm tra và lưu cấu hình ${service.label}.` };
  },
  check_keys: async (require_deepgram = true) => ({ ok: true, status: Object.fromEntries(services.filter((s) => require_deepgram || s.name !== "deepgram").map((s) => [s.name, s.configured || !reset && s.name === "deepgram" ? null : "Chưa cấu hình API key và model."])) }),
  reset_configuration: async () => {
    services = services.map((s) => ({ ...s, configured: false, saved_mask: null, model: "", needs_model: false, ...s.name === "llm" ? { llm: { base_url: "", provider_label: providers[0].label } } : {}, ...s.name === "deepgram" ? { deepgram: { language: "vi", auto_language: true } } : {} }));
    channelsText = "";
    reset = true;
    appState.guide.channel_count = 0;
    updateApp();
    return { ok: true, message: "Đã đặt lại API key, cài đặt và danh sách kênh. Dữ liệu và phiên Facebook được giữ nguyên." };
  },
  get_channels: async () => ({ ok: true, text: channelsText, count: countChannels(channelsText), problems: problems(channelsText) }),
  save_channels: async (text) => {
    const errors = problems(text);
    if (errors.length)
      return { ok: false, error: "Chưa lưu. Sửa các dòng không hợp lệ.", problems: errors };
    channelsText = text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean).join(`
`);
    const count = countChannels(channelsText);
    appState.guide.channel_count = count;
    updateApp();
    return { ok: true, count, message: `Đã lưu ${count} kênh cần quét.` };
  },
  start_login: async () => {
    finishLogin();
    if (appState.busy)
      return { ok: false, error: "Ứng dụng đang bận. Hãy chờ hoàn tất trước khi đăng nhập." };
    loginUntil = Date.now() + 3000;
    appState.logging_in = true;
    appState.busy = true;
    setTimeout(finishLogin, 3000);
    return { ok: true };
  },
  get_login_state: async () => {
    finishLogin();
    const notice = loginNotice;
    loginNotice = null;
    return { ok: true, logging_in: Boolean(loginUntil), fb_ready: appState.guide.fb_ready, message: null, notice };
  },
  pick_cookie_file_and_import: async () => {
    appState.guide.fb_ready = true;
    updateApp();
    return { ok: true, message: "Bản xem thử: đã nạp phiên Facebook từ file cookie mẫu." };
  },
  get_taxonomy: async () => clone(taxonomy),
  save_taxonomy: async (groups) => {
    for (const group of taxonomy.groups) {
      const rows = groups[group.id];
      if (!Array.isArray(rows) || rows.length < 2)
        return { ok: false, error: `${group.title}: cần ít nhất 2 nhãn.` };
      if (rows.some((r) => !r.name?.trim() || !r.description?.trim()))
        return { ok: false, error: `${group.title}: hãy điền tên và mô tả cho mọi nhãn.` };
      if (new Set(rows.map((r) => r.name.trim().toLocaleLowerCase("vi"))).size !== rows.length)
        return { ok: false, error: `${group.title}: tên nhãn không được trùng nhau.` };
    }
    taxonomy.groups = taxonomy.groups.map((g) => ({ ...g, rows: groups[g.id].map((r, i) => ({ ...r, code: r.code || `${g.id}_custom_${i + 1}`, name: r.name.trim(), description: r.description.trim() })) }));
    return { ok: true, message: "Đã lưu nhãn phân loại Jev." };
  },
  reset_taxonomy: async () => {
    taxonomy = clone(defaultTaxonomy);
    return { ok: true, message: "Đã khôi phục nhãn mặc định." };
  }
};
