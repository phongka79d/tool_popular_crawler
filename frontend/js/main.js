import { call, isMock } from "./api.js";
import { store } from "./store.js";
import { icon } from "./icons.js";
import { el } from "./components/dom.js";
import { button } from "./components/button.js";
import { card } from "./components/card.js";
import { badge } from "./components/badge.js";
import { stepper } from "./components/stepper.js";
import { tabs } from "./components/tabs.js";
import { alert } from "./components/alert.js";
import { spinner } from "./components/spinner.js";
import { modal, confirm } from "./components/modal.js";
import { toast } from "./components/toast.js";
import { radioGroup } from "./components/radioGroup.js";
import { toggle } from "./components/toggle.js";
const pages = { settings: "Cài đặt", scan: "Chạy quét", results: "Kết quả" };
let current = "settings";
try {
  const saved = localStorage.getItem("vct.page");
  if (pages[saved])
    current = saved;
} catch {}
let appState = null, activePage = null, disposePage = null, pageVersion = 0, mountKey = "", lastShell = "", refreshing = null;
const root = el("main", "app-shell"), header = el("header", "app-header chrome", el("div", "app-icon", icon("film", 26)), el("h1", "", "Video Công Thức"), el("div", "spacer"), button({ label: "Nhật ký", icon: "log", onClick: openLogs })), banners = el("div", "shell-banners"), journey = el("div"), next = el("div"), content = el("section", "page-content");
content.id = "page-content";
content.setAttribute("aria-label", pages[current]);
const nav = tabs({ items: Object.entries(pages).map(([id, label]) => ({ id, label })), value: current, onChange: navigate });
root.append(header, el("p", "app-subtitle", "Tìm video hoặc bài đăng nổi bật trên các kênh Facebook để học công thức nội dung, rồi xuất kết quả ra Excel."), banners, journey, nav, next, content);
document.getElementById("app").append(root);
const ctx = { call, store, toast, confirm, navigate, refreshApp };
function navigate(page) {
  if (!pages[page])
    return;
  current = page;
  try {
    localStorage.setItem("vct.page", page);
  } catch {}
  nav.setValue(page);
  content.setAttribute("aria-label", pages[page]);
  store.set({ page });
  renderNext();
  mountCurrent();
}
function renderNext() {
  next.replaceChildren();
  if (!appState?.next_step)
    return;
  const step = appState.next_step;
  const bar = el("div", "next-step", el("div", "", el("strong", "", "Việc tiếp theo:"), " ", step.text));
  if (step.page !== current && pages[step.page])
    bar.append(button({ label: `Đi tới ${pages[step.page]}`, variant: "primary", icon: "arrow", onClick: () => navigate(step.page) }));
  next.append(bar);
}
function renderShell() {
  if (!appState)
    return;
  const signature = JSON.stringify([appState.storage_secure, appState.browser, appState.journey, appState.next_step]);
  if (signature !== lastShell) {
    lastShell = signature;
    banners.replaceChildren();
    if (!appState.storage_secure)
      banners.append(alert({ variant: "warning", message: "Máy này chưa có kho lưu key an toàn. Hãy bật Windows Credential Manager trước khi lưu key." }));
    if (appState.browser?.error)
      banners.append(alert({ variant: "error", message: appState.browser.error }));
    else if (!appState.browser?.ready) {
      const preparing = alert({ message: "Đang chuẩn bị trình duyệt quét (~150 MB) lần đầu…" });
      preparing.firstElementChild.replaceWith(spinner());
      banners.append(preparing);
    }
    journey.replaceChildren(stepper({ steps: appState.journey || [] }));
    renderNext();
  }
  mountCurrent();
}
async function mountCurrent() {
  if (!appState)
    return;
  const locked = current === "scan" && appState.scan_locked, configured = appState.guide?.configured || {};
  const key = locked ? `scan:locked:${Boolean(configured.jev)}:${Boolean(configured.llm)}` : current;
  if (key === mountKey)
    return;
  mountKey = key;
  const version = ++pageVersion;
  disposePage?.();
  disposePage = null;
  activePage?.unmount?.();
  activePage = null;
  content.replaceChildren();
  if (locked) {
    const body = el("div", "stack lock-card", el("h2", "", "\uD83D\uDD12 Chạy quét đang khóa"), el("div", "row", badge({ label: `${configured.jev ? "✓" : "✗"} Jev`, state: configured.jev ? "success" : "error" }), el("span", "", "·"), badge({ label: `${configured.llm ? "✓" : "✗"} LLM`, state: configured.llm ? "success" : "error" })), el("p", "muted", "Cần kết nối Jev và LLM trước khi chạy quét. Deepgram chỉ cần khi quét video."), el("div", "row", button({ label: "Mở Cài đặt", variant: "primary", icon: "settings", onClick: () => navigate("settings") })));
    content.append(card({ body }));
    return;
  }
  const host = el("div", "stack");
  content.append(host);
  host.append(el("div", "row muted", spinner(), "Đang tải…"));
  try {
    const module = await import(`./pages/${current}/index.js`);
    if (version !== pageVersion)
      return;
    activePage = module;
    host.replaceChildren();
    const cleanup = await module.mount(host, ctx);
    if (version !== pageVersion) {
      if (typeof cleanup === "function")
        cleanup();
      return;
    }
    if (typeof cleanup === "function")
      disposePage = cleanup;
  } catch (error) {
    if (version !== pageVersion)
      return;
    host.replaceChildren(alert({ variant: "error", message: "Không thể tải trang. Vui lòng mở lại ứng dụng." }));
    mountKey = "";
  }
}
async function refreshApp() {
  if (refreshing)
    return refreshing;
  refreshing = (async () => {
    const state = await call("get_app_state");
    if (!state?.ok) {
      if (!appState)
        banners.replaceChildren(alert({ variant: "error", message: state?.error || "Không đọc được trạng thái ứng dụng." }));
      return state;
    }
    appState = state;
    store.set({ app: state, appState: state, isMock: isMock(), page: current });
    renderShell();
    return state;
  })();
  try {
    return await refreshing;
  } finally {
    refreshing = null;
  }
}
async function openLogs() {
  let session = "current", problemsOnly = true, request = 0, closed = false;
  const controls = el("div", "row"), records = el("div"), path = el("div", "hint"), body = el("div", "stack", controls, path, records), m = modal({ title: "Nhật ký ứng dụng", body, onClose: () => {
    closed = true;
    clearInterval(timer);
  } });
  const filter = toggle({ label: "Chỉ lỗi và cảnh báo", checked: true, onChange: (value) => {
    problemsOnly = value;
    load();
  } }), sessions = el("div");
  controls.append(sessions, el("div", "spacer"), filter);
  m.footer.append(button({ label: "Mở file nhật ký", icon: "log", onClick: async () => {
    const result = await call("open_log_file", session);
    if (!result.ok)
      toast.error(result.error);
    else if (result.message)
      toast.info(result.message);
  } }));
  let sessionSignature = "";
  async function load() {
    const id = ++request, result = await call("get_logs", session, problemsOnly);
    if (closed || id !== request)
      return;
    if (!result.ok) {
      records.replaceChildren(alert({ variant: "error", message: result.error }));
      return;
    }
    session = result.session || session;
    const signature = JSON.stringify(result.sessions);
    if (signature !== sessionSignature) {
      sessionSignature = signature;
      sessions.replaceChildren();
      if (result.sessions?.length > 1)
        sessions.append(radioGroup({ label: "Phiên", options: result.sessions.map((s) => ({ value: s.id, label: s.label })), value: session, onChange: (value) => {
          session = value;
          load();
        } }));
    }
    path.textContent = `${result.path || ""} · mới nhất ở trên`;
    if (result.records?.length) {
      const pre = el("pre", "log-lines", result.records.join(`
`));
      records.replaceChildren(pre);
    } else
      records.replaceChildren(alert({ variant: problemsOnly ? "success" : "info", message: problemsOnly ? "Không có lỗi hay cảnh báo nào." : "Nhật ký đang trống." }));
  }
  const timer = setInterval(load, 2000);
  load();
}
document.addEventListener("click", async (e) => {
  const link = e.target.closest?.("a[href]");
  if (!link || !/^https?:\/\//i.test(link.getAttribute("href") || ""))
    return;
  e.preventDefault();
  const result = await call("open_url", link.href);
  if (!result.ok)
    toast.error(result.error);
  else if (result.message)
    toast.info(result.message);
});
store.set({ page: current });
refreshApp();
const poll = setInterval(refreshApp, 1500);
window.addEventListener("beforeunload", () => {
  clearInterval(poll);
  disposePage?.();
  activePage?.unmount?.();
});
