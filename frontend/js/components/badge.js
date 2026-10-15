import { el } from "./dom.js";
/** @param {{label?:string,state?:'done'|'current'|'pending'|'success'|'warning'|'error'}} options */
export function badge({ label, state = "pending" } = {}) {
  return el("span", `badge ${state}`, label || ({ done: "✓ Xong", current: "● Đang làm", pending: "○ Chưa làm", success: "Thành công", warning: "Cảnh báo", error: "Có lỗi" }[state] || state));
}
export const statusPill = badge;
