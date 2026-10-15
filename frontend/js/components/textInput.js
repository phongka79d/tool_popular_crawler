import { el, bindField } from "./dom.js";
import { button } from "./button.js";
/** @param {{label?:string,value?:string,type?:string,placeholder?:string,hint?:string,disabled?:boolean,onChange?:Function,autocomplete?:string}} options; returns wrapper with .input/.value. */
export function textInput({ label, value = "", type = "text", placeholder = "", hint, disabled = false, onChange, autocomplete = "off" } = {}) {
  const input = el("input", "input");
  Object.assign(input, { value, type, placeholder, disabled, autocomplete });
  const wrap = el("div", "field"), inner = el("div", type === "password" ? "input-wrap" : "", input);
  wrap.append(inner);
  if (type === "password") {
    const show = button({ label: "Hiện", variant: "ghost", size: "small", disabled, onClick: () => {
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      show.textContent = hidden ? "Ẩn" : "Hiện";
      show.setAttribute("aria-pressed", String(hidden));
    } });
    show.setAttribute("aria-label", "Hiện hoặc ẩn mật khẩu");
    show.setAttribute("aria-pressed", "false");
    inner.append(show);
  }
  return bindField(wrap, input, { label, hint, onChange });
}
