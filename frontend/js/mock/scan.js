import { appState } from "./app.js";
import { registerScanResult } from "./results.js";
const stageList = [["keys", "Kiểm tra key"], ["scan", "Quét kênh"], ["filter", "Lọc nội dung"], ["analyze", "Phân tích"], ["export", "Xuất Excel"]];
let acceptedAt = null, readImages = false, session = null;
const defaults = { days: 7, kind: "video", formats: ["video", "reel"], length_limits: { video: [null, null], reel: [null, null] }, min_views: 1e4, min_ratio_follow: 0, match_all: true, min_interactions: 200 };
const terms = { paragraphs: ["Công cụ này đọc Facebook qua trình duyệt đã đăng nhập (thu thập tự động).", "Điều khoản Facebook hạn chế việc thu thập tự động khi chưa được phép."], bullets: ["Tài khoản dùng để quét có thể bị Facebook yêu cầu xác minh (checkpoint) hoặc khóa. Nên dùng tài khoản phụ, không dùng tài khoản chính.", "Chỉ thu thập nội dung bạn được phép truy cập.", "Bạn tự chịu trách nhiệm về việc sử dụng công cụ."], link: { label: "Điều khoản Facebook", url: "https://www.facebook.com/terms" } };
const presets = { min_views: [50000, 1e5], min_ratio_follow: [5, 10], length: { video: [{ label: "≥ 1 phút", min: 60, max: null }, { label: "≥ 3 phút", min: 180, max: null }], reel: [{ label: "≤ 60 giây", min: null, max: 60 }, { label: "≤ 90 giây", min: null, max: 90 }] } };
function preview(options) {
  const problems = [], post = options.kind === "post", parts = [];
  if (!(options.days >= 1))
    problems.push("Số ngày phải lớn hơn 0.");
  if (!post && !options.formats?.length)
    problems.push("Chọn ít nhất một loại video để quét.");
  if ([options.min_views, options.min_ratio_follow, options.min_interactions].some((value) => value < 0))
    problems.push("Ngưỡng tối thiểu không được âm.");
  if (post)
    parts.push(options.min_interactions ? `Giữ bài đăng có ≥ ${Number(options.min_interactions).toLocaleString("vi-VN")} tương tác` : "Không lọc: giữ mọi bài đăng.");
  else {
    const filters = [];
    if (options.min_views > 0)
      filters.push(`≥ ${Number(options.min_views).toLocaleString("vi-VN")} lượt xem`);
    if (options.min_ratio_follow > 0)
      filters.push(`≥ ${options.min_ratio_follow}× follower`);
    parts.push(filters.length ? `Giữ video có ${filters.join(options.match_all ? " VÀ " : " HOẶC ")}` : "Không lọc: giữ mọi video.");
    for (const [kind, label] of [["video", "Video"], ["reel", "Reel"]]) {
      if (!options.formats?.includes(kind))
        continue;
      const [min, max] = options.length_limits?.[kind] || [];
      if (min < 0 || max < 0)
        problems.push(`Thời lượng ${label} không được âm.`);
      if (min && max && min > max)
        problems.push(`Thời lượng tối thiểu ${label} không được lớn hơn tối đa.`);
      if (min || max)
        parts.push(`${label}: ${min ? `≥ ${min} giây` : ""}${min && max ? " và " : ""}${max ? `≤ ${max} giây` : ""}`);
    }
  }
  return { ok: true, summary: parts.join(" · "), problems, can_start: !problems.length && !!acceptedAt && !session?.running };
}
function setApp(running, question = false) {
  appState.busy = running;
  appState.guide.running = running;
  appState.guide.question = question;
  appState.guide.configured.deepgram = true;
  if (running)
    appState.next_step = { text: question ? "Lần quét đang chờ bạn chọn cách tiếp tục." : "Lần quét đang chạy. Theo dõi tiến độ và mức sử dụng dịch vụ.", page: "scan" };
  else
    appState.next_step = { text: "Xem file Excel và phân tích nội dung trong Kết quả.", page: "results" };
}
function empty() {
  return { ok: true, running: false, stopping: false, elapsed_s: 0, item_label: "video", overall: 0, stage: null, stages: stageList.map(([id, label]) => ({ id, label, state: "pending" })), step: null, message: "", page_url: null, channels: [], usage: null, usage_history: [], turns: [], log: [], log_total: 0, errors: [], question: null, result: null, ended_without_result: false };
}
function snapshot(since = 0) {
  if (!session)
    return empty();
  const s = session, now = Date.now();
  let elapsed = (now - s.started - s.pausedMs) / 1000;
  if (!s.answered && elapsed >= 15 && !s.stopping) {
    s.questionAt ??= now;
    elapsed = 15;
  }
  if (s.stopping && now - s.stopAt >= 1000) {
    s.running = false;
    s.ended = true;
    s.finishedElapsed ??= elapsed;
  }
  if (elapsed >= 40) {
    s.running = false;
    s.finishedElapsed ??= 40;
  }
  if (!s.running)
    elapsed = s.finishedElapsed;
  elapsed = Math.max(0, Math.min(40, elapsed));
  const question = s.running && !s.stopping && !s.answered && elapsed >= 15 ? { kind: "slow_channel", message: "Một kênh phản hồi chậm. Bạn muốn tiếp tục chờ hay bỏ qua kênh này?", options: [{ id: "continue", label: "Tiếp tục quét" }, { id: "skip", label: "Bỏ qua kênh này" }] } : null;
  const post = s.options.kind === "post", total = post ? 18 : 24, done = s.running ? Math.min(total, Math.max(0, Math.floor((elapsed - 6) / (31 / total)))) : s.ended ? Math.max(0, Math.floor((elapsed - 6) / (31 / total))) : total;
  const position = !s.running && !s.ended ? 5 : elapsed < 2 ? 0 : elapsed < 12 ? 1 : elapsed < 17 ? 2 : elapsed < 37 ? 3 : 4;
  const stage = position === 5 ? "done" : stageList[position][0], names = ["Bếp Nhà Mình", "Sống Khỏe Mỗi Ngày", "Ý Tưởng Nội Dung"];
  const channels = names.map((name, i) => {
    const start = i * total / 3, found = elapsed >= 3 + i * 4 ? 35 + i * 11 : null, passed = found === null ? null : total / 3, analyzed = Math.max(0, Math.min(total / 3, done - start)), progress = analyzed ? 0.6 + 0.4 * analyzed / (total / 3) : found === null ? 0 : 0.35;
    return { name, url: `https://www.facebook.com/${["BepNhaMinh", "SongKhoeMoiNgay", "YTuongNoiDung"][i]}`, followers: i === 2 && elapsed < 15 ? null : [82000, 125000, 46000][i], status: analyzed === total / 3 ? "Đã phân tích" : analyzed ? "Đang phân tích" : found === null ? "Chờ quét" : "Đã quét", progress, found, passed, analyzed };
  });
  const turns = Array.from({ length: done }, (_, i) => ({ label: `${post ? "Bài đăng" : "Video"} ${i + 1}`, llm_tokens: 1300 + i * 17, llm_output_tokens: 400 + i * 3, llm_seconds: 4 + i % 4, speed: Math.round((400 + i * 3) / (4 + i % 4) * 100) / 100, jev_tokens: 210 + i * 5, deepgram_minutes: post ? 0 : 0.75 + i % 3 / 10 })).reverse();
  const sum = (key) => turns.reduce((n, row) => n + row[key], 0), usage = elapsed < 3 ? null : { llm_model: "gpt-4.1-mini", llm_tokens: sum("llm_tokens"), llm_calls: done, llm_output_tokens: sum("llm_output_tokens"), llm_seconds: sum("llm_seconds"), llm_speed: done ? sum("llm_output_tokens") / sum("llm_seconds") : null, llm_cached: Math.floor(done / 8), jev_tokens: sum("jev_tokens"), jev_calls: done, deepgram_minutes: sum("deepgram_minutes"), deepgram_calls: post ? 0 : done };
  const usage_history = Array.from({ length: done }, (_, i) => {
    const rows = turns.slice(done - i - 1);
    return { t: new Date(s.started + (7 + i) * 1000).toLocaleTimeString("en-GB", { hour12: false }), llm: rows.reduce((n, row) => n + row.llm_tokens, 0), jev: rows.reduce((n, row) => n + row.jev_tokens, 0) };
  });
  const steps = Math.floor(elapsed / 2);
  while (s.tick < steps) {
    s.tick++;
    const second = s.tick * 2;
    const text = second < 4 ? "Đã kiểm tra API key." : second < 12 ? `Đang quét kênh ${Math.min(3, Math.floor(second / 4))}/3. Thu thập nội dung mới.` : second < 18 ? "Đã lọc nội dung theo ngưỡng đã chọn." : second < 38 ? `Đã phân tích ${Math.min(total, Math.floor((second - 6) / (31 / total)))} ${post ? "bài đăng" : "video"}.` : "Đang tổng hợp và xuất Excel.";
    s.log.push(`${new Date(s.started + second * 1000).toLocaleTimeString("en-GB", { hour12: false })}  ${text}`);
  }
  if (!s.running && !s.loggedEnd) {
    s.loggedEnd = true;
    s.log.push(s.ended ? "Đã dừng quét; không có file Excel mới." : "Quét xong. Đã xuất file Excel.");
  }
  setApp(s.running, !!question);
  if (!s.running && !s.ended)
    appState.guide.has_result = true;
  const result = !s.running && !s.ended ? { name: post ? "bai_dang_2026-10-14_1600.xlsx" : "video_2026-10-15_0930.xlsx", count: total, elapsed_s: elapsed } : null;
  if (result && !s.registered) {
    s.registered = true;
    registerScanResult({ name: result.name, count: result.count, kind: post ? "post" : "video" });
  }
  return { ok: true, running: s.running, stopping: s.running && s.stopping, elapsed_s: elapsed, item_label: post ? "bài đăng" : "video", overall: result ? 1 : Math.min(0.97, elapsed / 41), stage, stages: stageList.map(([id, label], i) => ({ id, label, state: i < position ? "done" : i === position ? "current" : "pending" })), step: { fraction: position === 3 ? done / total : Math.min(1, elapsed / 40), label: position === 3 ? `Đã phân tích ${done}/${total} ${post ? "bài đăng" : "video"}` : "Đang xử lý các kênh" }, message: question ? "Đang chờ bạn chọn cách tiếp tục." : result ? "Đã xuất kết quả Excel." : s.stopping ? "Đang hoàn tất bước hiện tại…" : stageList[Math.min(position, 4)][1], page_url: channels[Math.min(2, Math.floor(elapsed / 13))].url, channels, usage, usage_history, turns, log: s.log.slice(Math.max(0, Number(since) || 0)), log_total: s.log.length, errors: [], question, result, ended_without_result: !!s.ended };
}
export default {
  get_scan_options: async () => ({ ok: true, defaults: { ...structuredClone(defaults), read_images: readImages }, kinds: [{ id: "video", label: "Video thường" }, { id: "reel", label: "Reel" }], presets: structuredClone(presets), terms: { ...structuredClone(terms), accepted_at: acceptedAt } }),
  preview_scan: async (options) => preview(options),
  set_read_images: async (enabled) => {
    if (session?.running)
      return { ok: false, error: "Không thể đổi tùy chọn khi đang quét.", enabled: readImages };
    readImages = !!enabled;
    return { ok: true, enabled: readImages, message: readImages ? "Model LLM hỗ trợ đọc ảnh." : "Đã tắt đọc ảnh." };
  },
  accept_terms: async () => ({ ok: true, accepted_at: acceptedAt ??= new Date().toISOString() }),
  start_scan: async (options) => {
    const checked = preview(options);
    if (!checked.can_start)
      return { ok: false, error: checked.problems[0] || (!acceptedAt ? "Vui lòng đọc và xác nhận lưu ý Facebook trước khi quét." : "Một lần quét đang chạy.") };
    Object.assign(defaults, structuredClone(options));
    session = { started: Date.now(), running: true, stopping: false, pausedMs: 0, questionAt: null, answered: false, options: structuredClone(options), log: ["Bắt đầu lần quét mô phỏng."], tick: 0 };
    setApp(true);
    return { ok: true };
  },
  stop_scan: async () => {
    if (session?.running) {
      session.stopping = true;
      session.stopAt = Date.now();
      if (session.questionAt && !session.answered) {
        session.pausedMs += Date.now() - session.questionAt;
        session.answered = true;
      }
    }
    return { ok: true };
  },
  answer_question: async (id) => {
    if (!session?.running || session.answered || !session.questionAt || !["continue", "skip"].includes(id))
      return { ok: false, error: "Lựa chọn không hợp lệ hoặc câu hỏi đã kết thúc." };
    session.pausedMs += Date.now() - session.questionAt;
    session.answered = true;
    session.log.push(id === "skip" ? "Đã chọn bỏ qua kênh phản hồi chậm." : "Đã chọn tiếp tục quét.");
    setApp(true, false);
    return { ok: true };
  },
  get_scan_state: async (since) => snapshot(since)
};
