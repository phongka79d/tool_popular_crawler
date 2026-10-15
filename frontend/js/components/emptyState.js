import { el } from "./dom.js";
import { icon as svgIcon } from "../icons.js";
/** @param {{title?:string,message?:string,icon?:string,actions?:Node|Node[]}} options */
export function emptyState({ title = "Chưa có dữ liệu", message, icon = "info", actions } = {}) {
  return el("div", "empty-state", svgIcon(icon, 32), el("h3", "", title), message ? el("p", "", message) : null, actions ? el("div", "row", actions) : null);
}
