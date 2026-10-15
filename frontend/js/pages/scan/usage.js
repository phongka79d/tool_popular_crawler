import { el } from "../../components/dom.js";
import { card, metric, expander, lineChart, barChart, dataTable } from "../../components/index.js";
import { num, dec } from "../../format.js";
export function usagePanel(state, { open = false, onToggle } = {}) {
  const usage = state.usage, root = el("section", "stack");
  root.append(el("h2", "", "Sử dụng dịch vụ"));
  if (!usage) {
    root.append(el("p", "hint", "Chưa phát sinh sử dụng dịch vụ AI trong lần quét này."));
    return root;
  }
  root.append(el("p", "hint", `Model LLM: ${usage.llm_model || "—"}`));
  const llm = card({ title: "LLM · Phân tích nội dung", body: el("div", "stack", el("div", "scan-field-pair", metric({ label: "Token LLM", value: num(usage.llm_tokens) }), metric({ label: "Lần gọi LLM", value: num(usage.llm_calls) })), el("p", "hint", `Trả về: ${num(usage.llm_output_tokens)} token · Chờ: ${dec(usage.llm_seconds, 1)} giây`), el("p", "hint", `Tốc độ: ${dec(usage.llm_speed)} token/giây · Dùng lại: ${num(usage.llm_cached)} phân tích`)) });
  const jev = card({ title: "Jev · Phân loại", body: el("div", "stack", metric({ label: "Token Jev", value: num(usage.jev_tokens) }), el("p", "hint", `Lần gọi Jev: ${num(usage.jev_calls)}`)) });
  const deepgram = card({ title: "Deepgram · Chép lời", body: el("div", "stack", metric({ label: "Phút Deepgram", value: dec(usage.deepgram_minutes) }), el("p", "hint", `Lần gọi Deepgram: ${num(usage.deepgram_calls)}`)) });
  root.append(el("div", "scan-usage-grid", llm, jev, deepgram), el("p", "hint", "Tốc độ = token trả về / thời gian chờ API. Thời gian chờ cộng dồn có thể lớn hơn thời gian quét vì các mục chạy song song. Phân tích dùng lại không tốn token LLM."));
  const charts = el("div", "stack"), history = state.usage_history || [], turns = state.turns || [];
  if (history.length)
    charts.append(el("h3", "", "Token tích lũy theo thời gian"), lineChart({ series: [{ name: "Token LLM", points: history.map((row) => ({ x: row.t, y: row.llm })) }, { name: "Token Jev", points: history.map((row) => ({ x: row.t, y: row.jev })) }], height: 220 }));
  if (turns.length) {
    const latest = turns[0], chronological = [...turns].reverse();
    charts.append(el("p", "hint", `Lượt gần nhất: ${latest.label} · ${num(latest.llm_tokens)} token LLM · ${dec(latest.llm_seconds)} giây · ${dec(latest.speed)} token/giây`), el("div", "scan-chart-grid", el("div", "stack", el("h3", "", "Token từng lượt"), barChart({ data: chronological.flatMap((row) => [{ label: row.label, value: row.llm_tokens, series: "LLM" }, { label: row.label, value: row.jev_tokens, series: "Jev" }]), integer: true })), el("div", "stack", el("h3", "", "Tốc độ LLM từng lượt"), barChart({ data: chronological.filter((row) => row.speed != null).map((row) => ({ label: row.label, value: row.speed })) }))), dataTable({ rows: turns, columns: [{ key: "label", label: "Lượt" }, { key: "llm_tokens", label: "Token LLM", format: num }, { key: "llm_output_tokens", label: "Trả về", format: num }, { key: "llm_seconds", label: "Chờ (giây)", format: (value) => dec(value) }, { key: "speed", label: "Token/giây", format: (value) => dec(value) }, { key: "jev_tokens", label: "Token Jev", format: num }, { key: "deepgram_minutes", label: "Phút Deepgram", format: (value) => dec(value) }] }));
  } else
    charts.append(el("p", "hint", "Số liệu từng lượt sẽ hiện khi phân tích xong video, bài đăng hoặc nhận xét tổng hợp."));
  root.append(expander({ title: "Biểu đồ sử dụng & từng lượt", body: charts, open, onToggle }));
  return root;
}
