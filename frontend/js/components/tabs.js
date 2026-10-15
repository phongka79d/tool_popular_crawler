import { el } from "./dom.js";
/** @param {{items:Array<{id:string,label:string}>,value:string,onChange?:Function,label?:string}} options */
export function tabs({ items = [], value, onChange, label = "Trang" } = {}) {
  const root = el("div", "tabs chrome");
  root.setAttribute("role", "tablist");
  root.setAttribute("aria-label", label);
  const buttons = [];
  items.forEach((item) => {
    const b = el("button", "", item.label);
    b.type = "button";
    b.setAttribute("role", "tab");
    b.dataset.id = item.id;
    b.addEventListener("click", () => {
      root.setValue(item.id);
      onChange?.(item.id);
    });
    buttons.push(b);
    root.append(b);
  });
  root.setValue = (v) => {
    value = v;
    buttons.forEach((b) => {
      b.setAttribute("aria-selected", String(b.dataset.id === v));
      b.tabIndex = b.dataset.id === v ? 0 : -1;
    });
  };
  root.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
      return;
    e.preventDefault();
    let i = items.findIndex((item) => item.id === value);
    i = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    buttons[i]?.click();
    buttons[i]?.focus();
  });
  root.setValue(value || items[0]?.id);
  return root;
}
