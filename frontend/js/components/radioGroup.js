import { el } from "./dom.js";
/** @param {{label?:string,options:Array<string|{id?:string,value?:string,label:string}>,value?:string,disabled?:boolean,onChange?:Function}} options */
export function radioGroup({ label, options = [], value, disabled = false, onChange } = {}) {
  const root = el("div", "field"), group = el("div", "radio-pills");
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-label", label || "Lựa chọn");
  if (label)
    root.append(el("span", "field-label", label));
  root.append(group);
  const entries = options.map((o) => typeof o === "object" ? { ...o, value: String(o.value ?? o.id) } : { label: o, value: String(o) });
  let current = value ?? entries[0]?.value;
  const buttons = [];
  const update = () => buttons.forEach((b, i) => {
    const active = entries[i].value === current;
    b.setAttribute("aria-checked", String(active));
    b.tabIndex = active ? 0 : -1;
  });
  entries.forEach((o, i) => {
    const b = el("button", "", o.label);
    b.type = "button";
    b.disabled = disabled;
    b.setAttribute("role", "radio");
    b.addEventListener("click", () => {
      current = o.value;
      update();
      onChange?.(current);
    });
    b.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key))
        return;
      e.preventDefault();
      const j = (i + (["ArrowRight", "ArrowDown"].includes(e.key) ? 1 : -1) + buttons.length) % buttons.length;
      buttons[j].click();
      buttons[j].focus();
    });
    buttons.push(b);
    group.append(b);
  });
  Object.defineProperty(root, "value", { get: () => current, set: (v) => {
    current = v;
    update();
  } });
  update();
  return root;
}
