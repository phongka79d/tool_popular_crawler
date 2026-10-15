import { el } from "../../components/dom.js";
import { button, card, badge, alert, progressBar, dataTable, expander } from "../../components/index.js";
import { num, duration } from "../../format.js";
import { usagePanel } from "./usage.js";
export function scanProgress(state, logs, actions, view) {
  const root = el("div", "stack");
  if (state.running) {
    const main = card({ title: `Đang quét · ${duration(state.elapsed_s)}` });
    main.body.classList.add("stack");
    main.body.append(progressBar({ value: state.overall, label: `Tiến độ tổng (ước tính) · ${Math.round((state.overall || 0) * 100)}%`, showValue: false }), el("div", "row", (state.stages || []).map((stage) => badge({ label: `${stage.state === "done" ? "✓" : stage.state === "current" ? "●" : "○"} ${stage.label}`, state: stage.state }))), el("p", "hint", "Quét kênh và phân tích có thể chạy song song; bước đang hoạt động có thể thay đổi."));
    if (state.step)
      main.body.append(progressBar({ value: state.step.fraction, label: state.step.label || "Đang chuẩn bị quét…" }));
    const message = el("div", "stack scan-current", el("p", "scan-current-message", state.message || "Đang chuẩn bị quét…"));
    if (state.page_url) {
      const link = el("a", "hint", state.page_url);
      link.href = state.page_url;
      message.append(link);
    }
    main.body.append(message);
    if (state.question) {
      const question = card({ title: "Cần bạn chọn để tiếp tục", body: el("div", "stack", el("p", "", state.question.message), el("div", "row", state.question.options.map((option, index) => button({ label: option.label, variant: index === 0 ? "primary" : "secondary", disabled: state.stopping || actions.pending(), onClick: () => actions.answer(option.id) })))) });
      question.classList.add("scan-question");
      main.body.append(question);
    }
    main.body.append(button({ label: "Dừng quét", variant: "danger", disabled: state.stopping || actions.pending(), onClick: actions.stop }));
    if (state.stopping)
      main.body.append(alert({ message: "Đã yêu cầu dừng. Đang hoàn tất bước hiện tại và lưu kết quả đã xử lý." }));
    root.append(main);
    if (state.channels?.length)
      root.append(card({ title: "Tiến độ từng kênh", body: el("div", "stack", dataTable({ rows: state.channels, columns: [{ key: "name", label: "Kênh" }, { key: "url", label: "Link kênh", format: (url) => button({ label: "Mở kênh", variant: "ghost", size: "small", onClick: () => actions.openUrl(url) }) }, { key: "followers", label: "Follower", format: num }, { key: "status", label: "Trạng thái", format: (status) => badge({ label: status, state: status === "Có lỗi" ? "error" : status === "Đã phân tích" ? "success" : status === "Chờ quét" ? "pending" : "current" }) }, { key: "progress", label: "Tiến độ", type: "progress" }, { key: "found", label: "Tìm thấy", format: num }, { key: "passed", label: "Đạt ngưỡng", format: num }, { key: "analyzed", label: "Đã phân tích", format: num }] }), el("p", "hint", "Số liệu cập nhật khi quét, lọc hoặc phân tích xong từng mục; — là chưa có số liệu.")) }));
    root.append(usagePanel(state, { open: view.charts, onToggle: (value) => view.charts = value }));
    if (logs.length)
      root.append(card({ title: "Diễn biến gần nhất", body: el("pre", "scan-log", logs.slice(-8).join(`
`)) }));
  } else {
    if (state.result) {
      const result = state.result;
      root.append(card({ title: `✅ Quét xong${result.count == null ? "" : ` · ${num(result.count)} ${state.item_label}`}`, subtitle: `File: ${result.name} · tổng thời gian ${duration(result.elapsed_s)}`, body: el("div", "row", button({ label: "Mở file Excel", variant: "primary", icon: "external", disabled: actions.pending(), onClick: () => actions.file("open_result", result.name) }), button({ label: "Lưu bản sao…", icon: "folder", disabled: actions.pending(), onClick: () => actions.file("save_result_as", result.name) }), button({ label: "Xem trong Kết quả", icon: "results", onClick: actions.results }), button({ label: "Quét lần mới", onClick: actions.reset })) }));
    } else if (state.ended_without_result)
      root.append(alert({ message: "Đã kết thúc quét; không có file Excel mới." }), button({ label: "Quét lần mới", onClick: actions.reset }));
    root.append(usagePanel(state, { open: view.charts, onToggle: (value) => view.charts = value }));
  }
  for (const message of new Set(state.errors || []))
    root.append(alert({ variant: "error", message }));
  if (state.errors?.length)
    root.append(el("p", "hint", "Chi tiết kỹ thuật của từng lỗi nằm trong Nhật ký (nút ở góc trên bên phải)."));
  if (logs.length)
    root.append(expander({ title: `Toàn bộ diễn biến lần quét (${num(logs.length)} bước)`, body: el("pre", "scan-log scan-log-full", logs.join(`
`)), open: view.logs, onToggle: (value) => view.logs = value }));
  return root;
}
