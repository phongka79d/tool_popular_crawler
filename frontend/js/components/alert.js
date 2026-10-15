import { el } from "./dom.js";
import { icon } from "../icons.js";
/** @param {{message?:string,title?:string,variant?:'info'|'success'|'warning'|'error',list?:string[],body?:Node}} options */
export function alert({ message, title, variant = "info", list = [], body } = {}) {
  const content = el("div");
  if (title)
    content.append(el("strong", "", title));
  if (message)
    content.append(el("div", "", message));
  if (list.length)
    content.append(el("ul", "", list.map((s) => el("li", "", s))));
  if (body)
    content.append(body);
  const root = el("div", `alert ${variant}`, icon(variant === "success" ? "check" : "info"), content);
  root.setAttribute("role", variant === "error" ? "alert" : "status");
  return root;
}
