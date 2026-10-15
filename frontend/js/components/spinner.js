import { el } from "./dom.js";
/** @param {{label?:string,size?:number}} options */
export function spinner({ label = "Đang tải", size = 16 } = {}) {
  const root = el("span", "spinner");
  root.style.width = `${size}px`;
  root.style.height = `${size}px`;
  root.setAttribute("role", "status");
  root.setAttribute("aria-label", label);
  return root;
}
