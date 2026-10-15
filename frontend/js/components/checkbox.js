import { el, bindField } from "./dom.js";
/** @param {{label:string,checked?:boolean,value?:boolean,disabled?:boolean,hint?:string,onChange?:Function}} options */
export function checkbox({ label, checked = false, value = checked, disabled = false, hint, onChange } = {}) {
  const input = el("input");
  input.type = "checkbox";
  input.checked = value;
  input.disabled = disabled;
  const root = el("div", "field", el("label", "checkbox", input, label));
  return bindField(root, input, { hint, onChange, event: "change", read: () => input.checked, write: (v) => {
    input.checked = Boolean(v);
  } });
}
