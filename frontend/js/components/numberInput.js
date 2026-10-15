import { el, bindField } from "./dom.js";
import { num } from "../format.js";
/** @param {{label?:string,value?:number|null,min?:number,max?:number,step?:number,thousands?:boolean,hint?:string,disabled?:boolean,onChange?:Function}} options; onChange receives number|null. */
export function numberInput({ label, value = null, min, max, step = 1, thousands = false, hint, disabled = false, onChange } = {}) {
  const input = el("input", "input");
  input.type = thousands ? "text" : "number";
  input.inputMode = step < 1 ? "decimal" : "numeric";
  input.disabled = disabled;
  if (min !== undefined)
    input.min = min;
  if (max !== undefined)
    input.max = max;
  input.step = step;
  const read = () => {
    const v = thousands ? input.value.replaceAll(".", "").replace(",", ".") : input.value;
    return v.trim() === "" || !Number.isFinite(Number(v)) ? null : Number(v);
  };
  const write = (v) => {
    input.value = v === null || v === undefined ? "" : thousands ? num(v) : v;
  };
  write(value);
  if (thousands) {
    input.addEventListener("focus", () => {
      const v = read();
      input.value = v === null ? "" : String(v).replace(".", ",");
    });
    input.addEventListener("blur", () => write(read()));
  }
  return bindField(el("div", "field", input), input, { label, hint, onChange, read, write });
}
