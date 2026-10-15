import { el, append } from "./dom.js";
import { progressBar } from "./progressBar.js";
import { emptyState } from "./emptyState.js";
/** @param {{columns:Array<{key:string,label:string,format?:(value:any,row:object)=>any,type?:'link'|'progress',href?:(row:object)=>string}>,rows:object[],empty?:string}} options */
export function dataTable({ columns = [], rows = [], empty = "Chưa có dữ liệu." } = {}) {
  if (!rows.length)
    return emptyState({ title: empty });
  const table = el("table"), head = el("tr");
  columns.forEach((c) => {
    const th = el("th", "", c.label);
    th.scope = "col";
    head.append(th);
  });
  table.append(el("thead", "", head));
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const c of columns) {
      const td = el("td"), v = row[c.key];
      if (c.type === "progress")
        td.append(progressBar({ value: v }));
      else if (c.type === "link" && v) {
        const href = c.href ? c.href(row) : String(v), a = el("a", "", c.format ? c.format(v, row) : "Mở liên kết");
        if (/^https?:\/\//i.test(href)) {
          a.href = href;
          a.rel = "noopener noreferrer";
        }
        td.append(a);
      } else
        append(td, c.format ? c.format(v, row) : v ?? "—");
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(body);
  return el("div", "table-scroll", table);
}
