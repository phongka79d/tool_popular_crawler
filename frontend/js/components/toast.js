import { el } from "./dom.js";
import { icon } from "../icons.js";
import { button } from "./button.js";
let stack;
/** @param {string|{message:string,variant?:'success'|'error'|'info',duration?:number}} message @param {{variant?:string,duration?:number}|string} options; returns toast element with .close(). */
export function toast(message, options = {}) {
  if (typeof options === "string")
    options = { variant: options };
  if (typeof message === "object") {
    options = message;
    message = options.message;
  }
  const { variant = "info", duration = 4500 } = options;
  if (!stack?.isConnected) {
    stack = el("div", "toast-stack");
    stack.setAttribute("aria-live", "polite");
    stack.setAttribute("aria-label", "Thông báo");
    document.body.append(stack);
  }
  const root = el("div", `toast ${variant}`, icon(variant === "success" ? "check" : "info"), el("span", "", message));
  let timer;
  root.close = () => {
    clearTimeout(timer);
    root.remove();
  };
  root.append(button({ label: "Đóng", icon: "close", variant: "ghost", size: "small", onClick: root.close }));
  stack.append(root);
  if (duration > 0)
    timer = setTimeout(root.close, duration);
  return root;
}
for (const variant of ["success", "error", "info"])
  toast[variant] = (message, options = {}) => toast(message, { ...options, variant });
