const paths = { film: "M4 3h16v18H4z M4 8h16 M4 16h16 M8 3v18 M16 3v18", settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z", scan: "M12 3a9 9 0 1 0 9 9 M12 12l7-7 M12 7a5 5 0 1 0 5 5", results: "M4 3h16v18H4z M4 9h16 M10 9v12", log: "M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5", check: "m5 12 4 4L19 6", close: "m6 6 12 12 M6 18 18 6", arrow: "M4 12h16 m-6-6 6 6-6 6", plus: "M12 4v16 M4 12h16", trash: "M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7", chevron: "m6 9 6 6 6-6", info: "M12 8h.01 M12 11v6 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", lock: "M7 10V7a5 5 0 0 1 10 0v3 M5 10h14v11H5z", folder: "M3 6h7l2 2h9v12H3z", external: "M14 3h7v7 M21 3l-10 10 M10 3H3v18h18v-7", eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0" };
paths.download = "M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5";
/** Inline SVG icon; name is film/settings/scan/results/log/check/close/arrow/plus/trash/etc. */
export function icon(name, size = 18) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  const p = document.createElementNS(svg.namespaceURI, "path");
  p.setAttribute("d", paths[name] || paths.info);
  svg.append(p);
  return svg;
}
