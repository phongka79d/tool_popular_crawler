import { el } from "./dom.js";
/** @param {{label:string,value:string|number,hint?:string}} options */
export function metric({ label, value = "—", hint } = {}) {
  return el("div", "metric", el("div", "muted", label), el("div", "metric-value", value ?? "—"), hint ? el("div", "hint", hint) : null);
}
