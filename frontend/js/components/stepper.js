import { el } from "./dom.js";
/** @param {{steps:Array<{title:string,state:'done'|'current'|'pending'}>}} options */
export function stepper({ steps = [] } = {}) {
  const list = el("ol", "stepper chrome");
  list.setAttribute("aria-label", "Các bước thực hiện");
  steps.forEach((s, i) => {
    const li = el("li", `step ${s.state}`, el("span", "step-number", s.state === "done" ? "✓" : i + 1), el("div", "", el("strong", "", s.title.replace(/^\d+\s*·\s*/, "")), el("small", "", { done: "Đã hoàn tất", current: "Bước hiện tại", pending: "Chưa thực hiện" }[s.state])));
    if (s.state === "current")
      li.setAttribute("aria-current", "step");
    list.append(li);
  });
  return list;
}
