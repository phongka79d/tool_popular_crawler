export const dash = "—";
const valid = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
export const num = (v) => valid(v) ? new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(v)) : dash;
export const dec = (v, digits = 2) => valid(v) ? new Intl.NumberFormat("vi-VN", { maximumFractionDigits: digits }).format(Number(v)) : dash;
export function compact(v) {
  if (!valid(v))
    return dash;
  const n = Number(v), a = Math.abs(n);
  return a >= 1e9 ? `${dec(n / 1e9, 1)} Tỷ` : a >= 1e6 ? `${dec(n / 1e6, 1)} Tr` : a >= 1000 ? `${dec(n / 1000, 1)} N` : dec(n, 1);
}
/** Format a fraction (0..1) as a percentage. */
export const pct = (v) => valid(v) ? `${dec(Number(v) * 100, 1)}%` : dash;
export function duration(seconds) {
  if (!valid(seconds))
    return dash;
  const s = Math.max(0, Math.floor(Number(seconds))), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return `${h ? `${h}:` : ""}${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
