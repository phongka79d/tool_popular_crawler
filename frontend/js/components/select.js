import { el, bindField } from "./dom.js";
/** @param {{label?:string,options:Array<string|{id?:string,value?:string,label:string}>,value?:string,searchable?:boolean,hint?:string,disabled?:boolean,onChange?:Function}} options; wrapper exposes .input/.value and .setOptions(options). */
export function select({ label, options = [], value, searchable = false, hint, disabled = false, onChange } = {}) {
  const root = el("div", "field"), area = el("div", searchable ? "search-select" : ""), input = el("select", "input");
  input.disabled = disabled;
  let all = options, selected = value;
  const key = (o) => typeof o === "object" ? String(o.value ?? o.id) : String(o);
  const name = (o) => typeof o === "object" ? o.label : String(o);
  const search = el("input", "input");
  search.type = "search";
  search.placeholder = "Gõ để lọc danh sách…";
  search.setAttribute("aria-label", `Lọc ${label || "danh sách"}`);
  search.disabled = disabled;
  const render = () => {
    const query = search.value.toLocaleLowerCase("vi");
    const filtered = all.filter((o) => name(o).toLocaleLowerCase("vi").includes(query));
    input.replaceChildren();
    for (const o of filtered) {
      const option = el("option", "", name(o));
      option.value = key(o);
      input.append(option);
    }
    if (filtered.some((o) => key(o) === String(selected)))
      input.value = String(selected);
    else if (searchable)
      input.selectedIndex = -1;
  };
  if (searchable) {
    input.size = 6;
    area.append(search);
    search.addEventListener("input", render);
  }
  area.append(input);
  root.append(area);
  render();
  if (!searchable && selected === undefined)
    selected = input.value;
  input.addEventListener("change", (e) => {
    selected = input.value;
    onChange?.(selected, e);
  });
  root.setOptions = (opts) => {
    all = opts;
    render();
  };
  return bindField(root, input, { label, hint, read: () => selected ?? input.value, write: (v) => {
    selected = v;
    render();
  } });
}
