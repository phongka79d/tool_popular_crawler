import { el, bindField } from "./dom.js";
/** @param {{label?:string,value?:string,placeholder?:string,rows?:number,hint?:string,disabled?:boolean,onChange?:Function}} options */
export function textarea({ label, value = "", placeholder = "", rows = 5, hint, disabled = false, onChange } = {}) {
  const input = el("textarea", "input");
  Object.assign(input, { value, placeholder, rows, disabled });
  return bindField(el("div", "field", input), input, { label, hint, onChange });
}
