import { el, append } from "./dom.js";
/** @param {{title:string,body?:Node|string|Node[],open?:boolean,onToggle?:Function}} options */
export function expander({ title, body, open = false, onToggle } = {}) {
  const root = el("details", "expander");
  root.open = open;
  root.body = el("div", "expander-body");
  append(root.body, body);
  root.append(el("summary", "", title), root.body);
  if (onToggle)
    root.addEventListener("toggle", () => onToggle(root.open));
  return root;
}
