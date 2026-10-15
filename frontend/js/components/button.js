import { el } from "./dom.js";
import { icon as svgIcon } from "../icons.js";
import { spinner } from "./spinner.js";
/** @param {{label?:string,variant?:'primary'|'secondary'|'ghost'|'danger',size?:'small'|'medium'|'large',icon?:string|Node,loading?:boolean,disabled?:boolean,onClick?:Function,title?:string,type?:string}} options */
export function button({ label = "", variant = "secondary", size = "medium", icon, loading = false, disabled = false, onClick, title, type = "button" } = {}) {
  const b = el("button", `button ${variant} ${size}`);
  b.type = type;
  if (title)
    b.title = title;
  if (label)
    b.setAttribute("aria-label", label);
  if (onClick)
    b.addEventListener("click", onClick);
  let busy = loading;
  b.setLoading = (value) => {
    busy = Boolean(value);
    b.disabled = disabled || busy;
    b.setAttribute("aria-busy", String(busy));
    b.replaceChildren();
    if (busy)
      b.append(spinner());
    else if (icon)
      b.append(typeof icon === "string" ? svgIcon(icon) : icon);
    if (label)
      b.append(document.createTextNode(label));
  };
  b.setLoading(loading);
  return b;
}
