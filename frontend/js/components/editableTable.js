import { el } from "./dom.js";
import { button } from "./button.js";
/** @param {{columns?:Array<{key:string,label:string,placeholder?:string}>,rows?:object[],onChange?:Function,disabled?:boolean,addLabel?:string}} options; .getRows() returns copies of current rows. */
export function editableTable({ columns = [{ key: "code", label: "Mã" }, { key: "name", label: "Tên" }, { key: "description", label: "Mô tả" }], rows = [], onChange, disabled = false, addLabel = "Thêm dòng" } = {}) {
  let data = rows.map((r) => ({ ...r }));
  const root = el("div", "stack editable-table"), body = el("tbody"), table = el("table"), header = el("tr");
  columns.forEach((c) => header.append(el("th", "", c.label)));
  header.append(el("th", "", ""));
  table.append(el("thead", "", header), body);
  const notify = () => onChange?.(root.getRows());
  const draw = () => {
    body.replaceChildren();
    data.forEach((row, i) => {
      const tr = el("tr");
      columns.forEach((c) => {
        const input = el("input", "input");
        input.value = row[c.key] ?? "";
        input.placeholder = c.placeholder || "";
        input.disabled = disabled;
        input.setAttribute("aria-label", `${c.label} · dòng ${i + 1}`);
        input.addEventListener("input", () => {
          row[c.key] = input.value;
          notify();
        });
        tr.append(el("td", "", input));
      });
      tr.append(el("td", "", button({ label: "Xóa", icon: "trash", variant: "ghost", size: "small", disabled, onClick: () => {
        data.splice(i, 1);
        draw();
        notify();
      } })));
      body.append(tr);
    });
  };
  root.getRows = () => data.map((r) => ({ ...r }));
  Object.defineProperty(root, "value", { get: root.getRows });
  root.append(el("div", "table-scroll", table), el("div", "", button({ label: addLabel, icon: "plus", disabled, onClick: () => {
    data.push(Object.fromEntries(columns.map((c) => [c.key, ""])));
    draw();
    notify();
    body.lastElementChild?.querySelector("input")?.focus();
  } })));
  draw();
  return root;
}
