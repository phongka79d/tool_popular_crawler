import { checkbox } from "./checkbox.js";
/** @param {{label:string,checked?:boolean,value?:boolean,disabled?:boolean,hint?:string,onChange?:Function}} options */
export function toggle(options = {}) {
  const root = checkbox(options);
  root.querySelector("label").className = "toggle";
  root.input.setAttribute("role", "switch");
  return root;
}
