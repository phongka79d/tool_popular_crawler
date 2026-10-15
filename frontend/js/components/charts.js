import { el } from "./dom.js";
import { num, dec, compact as compactNumber } from "../format.js";
import { emptyState } from "./emptyState.js";
const NS = "http://www.w3.org/2000/svg";
const colors = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];
function svgNode(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs))
    n.setAttribute(k, v);
  if (text !== undefined)
    n.textContent = text;
  return n;
}
function chartFrame(height, label) {
  const root = el("div", "chart"), svg = svgNode("svg", { height, role: "img", "aria-label": label }), tip = el("div", "chart-tooltip");
  tip.hidden = true;
  root.append(svg, tip);
  return { root, svg, tip, height };
}
const liveCharts = new Set;
const chartLifecycle = new MutationObserver(() => {
  for (const chart of liveCharts) {
    if (chart.root.isConnected) {
      if (!chart.mounted) {
        chart.mounted = true;
        chart.draw();
      }
    } else if (chart.mounted) {
      chart.observer.disconnect();
      clearTimeout(chart.timer);
      liveCharts.delete(chart);
    }
  }
  if (!liveCharts.size)
    chartLifecycle.disconnect();
});
function responsiveChart(frame, render) {
  const chart = { root: frame.root, mounted: false, timer: null, width: 0 };
  chart.draw = () => {
    if (!chart.root.isConnected)
      return;
    const width = chart.root.getBoundingClientRect().width;
    if (width <= 0 || width === chart.width)
      return;
    chart.width = width;
    frame.tip.hidden = true;
    frame.svg.setAttribute("viewBox", `0 0 ${width} ${frame.height}`);
    frame.svg.replaceChildren();
    render(width);
  };
  chart.observer = new ResizeObserver(() => {
    clearTimeout(chart.timer);
    chart.timer = setTimeout(chart.draw, 80);
  });
  liveCharts.add(chart);
  chartLifecycle.observe(document.documentElement, { childList: true, subtree: true });
  chart.observer.observe(chart.root);
  return chart.root;
}
function tooltip(mark, text, { root, tip }) {
  mark.setAttribute("tabindex", "0");
  mark.setAttribute("role", "img");
  mark.setAttribute("aria-label", text);
  mark.append(svgNode("title", {}, text));
  const show = (e) => {
    tip.textContent = text;
    tip.hidden = false;
    const bounds = root.getBoundingClientRect(), box = mark.getBoundingClientRect();
    const x = e.clientX ?? box.x + box.width / 2, y = e.clientY ?? box.y;
    tip.style.left = `${Math.max(0, Math.min(bounds.width - tip.offsetWidth, x - bounds.left + 8))}px`;
    tip.style.top = `${Math.max(0, y - bounds.top - 34)}px`;
  };
  mark.addEventListener("pointermove", show);
  mark.addEventListener("pointerleave", () => tip.hidden = true);
  mark.addEventListener("focus", show);
  mark.addEventListener("blur", () => tip.hidden = true);
}
function niceMax(value, integer) {
  if (value <= 0)
    return 1;
  const raw = value / 4, power = 10 ** Math.floor(Math.log10(raw)), part = raw / power;
  const step = (part <= 1 ? 1 : part <= 2 ? 2 : part <= 5 ? 5 : 10) * power;
  const unit = integer ? Math.max(1, step) * 4 : step;
  return Math.ceil(value / unit) * unit;
}
function legend(root, names) {
  if (!names.some(Boolean))
    return;
  root.append(el("div", "chart-legend", names.map((name, i) => {
    const swatch = el("i");
    swatch.style.background = colors[i % colors.length];
    return el("span", "", swatch, name);
  })));
}
function categoryLabel(svg, text, attrs, maxWidth) {
  const full = String(text), node = svgNode("text", attrs, full);
  svg.append(node);
  if (node.getComputedTextLength() > maxWidth) {
    let low = 0, high = full.length;
    while (low < high) {
      const mid = Math.ceil((low + high) / 2);
      node.textContent = full.slice(0, mid) + "…";
      if (node.getComputedTextLength() <= maxWidth)
        low = mid;
      else
        high = mid - 1;
    }
    node.textContent = full.slice(0, low) + "…";
  }
  node.append(svgNode("title", {}, full));
  return node;
}
function labelWidth(svg, labels) {
  const probe = svgNode("text");
  svg.append(probe);
  let width = 0;
  for (const label of labels) {
    probe.textContent = String(label);
    width = Math.max(width, probe.getComputedTextLength());
  }
  probe.remove();
  return width;
}
/** @param {{data:Array<{label:string,value:number,series?:string}>,horizontal?:boolean,height?:number,integer?:boolean,compact?:boolean}} options. Axes begin at zero; negative values are clamped to zero. */
export function barChart({ data = [], horizontal = false, height = 240, integer = false, compact = false } = {}) {
  data = data.filter((d) => d.value !== null && Number.isFinite(Number(d.value)));
  if (!data.length)
    return emptyState({ title: "Chưa có dữ liệu biểu đồ" });
  height = Math.max(160, height);
  const frame = chartFrame(height, "Biểu đồ cột"), { root, svg } = frame;
  const labels = [...new Set(data.map((d) => d.label))], series = [...new Set(data.map((d) => d.series || ""))];
  const max = niceMax(Math.max(...data.map((d) => Math.max(0, Number(d.value)))), integer), format = compact ? compactNumber : integer ? num : (v) => dec(v, 2);
  legend(root, series);
  return responsiveChart(frame, (width) => {
    const left = horizontal ? Math.min(width * 0.4, Math.max(64, labelWidth(svg, labels) + 20)) : 64;
    const right = 24, top = 16, bottom = horizontal ? 32 : 58, w = Math.max(1, width - left - right), h = height - top - bottom;
    const tickLimit = horizontal ? w / (labelWidth(svg, [format(max)]) + 12) : 4;
    const tickCount = tickLimit >= 4 ? 4 : tickLimit >= 2 ? 2 : 1;
    const ticks = integer ? Math.min(tickCount, max) : tickCount;
    for (let i = 0;i <= ticks; i++) {
      const v = max * i / ticks, x = horizontal ? left + w * v / max : left, y = horizontal ? top : top + h - h * v / max;
      svg.append(svgNode("line", { x1: x, y1: y, x2: horizontal ? x : left + w, y2: horizontal ? top + h : y, class: "axis" }), svgNode("text", { x: horizontal ? x : left - 10, y: horizontal ? top + h + 20 : y + 4, "text-anchor": horizontal ? "middle" : "end" }, format(v)));
    }
    const band = (horizontal ? h : w) / labels.length, slot = band / series.length;
    const categoryWidth = Math.min(100, labelWidth(svg, labels)), step = horizontal ? 1 : Math.max(1, Math.ceil((categoryWidth + 12) / band));
    labels.forEach((label, i) => {
      if (i % step !== 0)
        return;
      categoryLabel(svg, label, { x: horizontal ? left - 10 : left + (i + 0.5) * band, y: horizontal ? top + (i + 0.5) * band + 4 : top + h + 22, "text-anchor": horizontal ? "end" : "middle" }, horizontal ? left - 20 : Math.min(categoryWidth, band * step - 12));
    });
    for (const d of data) {
      const i = labels.indexOf(d.label), s = series.indexOf(d.series || ""), v = Math.max(0, Number(d.value)), length = (horizontal ? w : h) * v / max;
      const attrs = horizontal ? { x: left, y: top + i * band + s * slot + slot * 0.15, width: length, height: slot * 0.7 } : { x: left + i * band + s * slot + slot * 0.15, y: top + h - length, width: slot * 0.7, height: length };
      const rect = svgNode("rect", { ...attrs, rx: 3, fill: colors[s % colors.length] });
      tooltip(rect, `${d.label}${d.series ? " · " + d.series : ""}: ${format(v)}`, frame);
      svg.append(rect);
    }
  });
}
/** @param {{series:Array<{name:string,points:Array<{x:string|number,y:number}>}>,height?:number}} options. Numeric/time x values are positioned proportionally, categorical x values in input order. */
export function lineChart({ series = [], height = 220 } = {}) {
  series = series.map((s) => ({ ...s, points: s.points.filter((p) => p.y !== null && Number.isFinite(Number(p.y))) }));
  const points = series.flatMap((s) => s.points);
  if (!points.length)
    return emptyState({ title: "Chưa có dữ liệu biểu đồ" });
  height = Math.max(160, height);
  const frame = chartFrame(height, "Biểu đồ đường"), { root, svg } = frame, labels = [...new Set(points.map((p) => p.x))];
  const parseX = (x) => {
    if (typeof x === "number")
      return x;
    if (/^\d{2}:\d{2}:\d{2}$/.test(x)) {
      const [a, b, c] = x.split(":").map(Number);
      return a * 3600 + b * 60 + c;
    }
    const d = Date.parse(x);
    return Number.isFinite(d) ? d : NaN;
  };
  const parsed = labels.map(parseX), numeric = parsed.every(Number.isFinite), minX = numeric ? Math.min(...parsed) : 0, maxX = numeric ? Math.max(...parsed) : Math.max(1, labels.length - 1), maxY = niceMax(Math.max(...points.map((p) => Math.max(0, p.y))), false);
  legend(root, series.map((s) => s.name));
  return responsiveChart(frame, (width) => {
    const left = 64, top = 16, w = Math.max(1, width - left - 24), h = height - 54;
    const xOf = (x) => left + w * (numeric ? (parseX(x) - minX) / (maxX - minX || 1) : labels.indexOf(x) / Math.max(1, labels.length - 1)), yOf = (y) => top + h - h * Math.max(0, y) / maxY;
    for (let i = 0;i <= 4; i++) {
      const y = top + h - h * i / 4;
      svg.append(svgNode("line", { x1: left, y1: y, x2: left + w, y2: y, class: "axis" }), svgNode("text", { x: left - 10, y: y + 4, "text-anchor": "end" }, compactNumber(maxY * i / 4)));
    }
    const ordered = numeric ? [...labels].sort((a, b) => parseX(a) - parseX(b)) : labels;
    const categoryWidth = Math.min(100, labelWidth(svg, labels));
    let previousRight = -1 / 0;
    for (const x of ordered) {
      const position = xOf(x);
      if (position - categoryWidth / 2 < previousRight + 12)
        continue;
      categoryLabel(svg, x, { x: position, y: top + h + 24, "text-anchor": "middle" }, categoryWidth);
      previousRight = position + categoryWidth / 2;
    }
    series.forEach((s, i) => {
      const sorted = numeric ? [...s.points].sort((a, b) => parseX(a.x) - parseX(b.x)) : s.points;
      svg.append(svgNode("polyline", { points: sorted.map((p) => `${xOf(p.x)},${yOf(p.y)}`).join(" "), fill: "none", stroke: colors[i % colors.length], "stroke-width": 2.5, "stroke-linejoin": "round" }));
      for (const p of sorted) {
        const dot = svgNode("circle", { cx: xOf(p.x), cy: yOf(p.y), r: 4, fill: colors[i % colors.length], stroke: "var(--surface)", "stroke-width": 1.5 });
        tooltip(dot, `${s.name} · ${p.x}: ${dec(p.y, 2)}`, frame);
        svg.append(dot);
      }
    });
  });
}
