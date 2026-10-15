import { el } from "./dom.js";
import { pct } from "../format.js";
/** @param {{value?:number,label?:string,showValue?:boolean}} options; .setValue(value,label?) updates without replacing. */
export function progressBar({ value = 0, label = "", showValue = true } = {}) {
  const root = el("div", "progress"), caption = el("div", "progress-label"), track = el("div", "progress-track"), fill = el("div", "progress-fill");
  track.append(fill);
  root.append(caption, track);
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  root.setValue = (v, text = label) => {
    value = Math.min(1, Math.max(0, Number(v) || 0));
    fill.style.width = `${value * 100}%`;
    track.setAttribute("aria-valuenow", String(Math.round(value * 100)));
    track.setAttribute("aria-label", text || "Tiến độ");
    caption.replaceChildren(el("span", "", text), el("span", "", showValue ? pct(value) : ""));
    caption.hidden = !text && !showValue;
  };
  root.setValue(value);
  return root;
}
