import { el, append } from "./dom.js";
/** @param {{title?:string,subtitle?:string,actions?:Node|Node[],body?:Node|string|Node[]}} options */
export function card({ title, subtitle, actions, body } = {}) {
  const c = el("section", "card");
  if (title || subtitle || actions) {
    const text = el("div");
    if (title)
      text.append(el("h2", "", title));
    if (subtitle)
      text.append(el("p", "card-subtitle", subtitle));
    c.append(el("header", "card-header", text, el("div", "row", actions)));
  }
  c.body = el("div", "card-body");
  append(c.body, body);
  c.append(c.body);
  return c;
}
