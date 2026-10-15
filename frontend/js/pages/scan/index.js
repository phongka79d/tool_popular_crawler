import { el } from "../../components/dom.js";
import { alert, button, spinner } from "../../components/index.js";
import { scanOptions } from "./options.js";
import { scanProgress } from "./progress.js";
/** Mount owns every timer and ignores late responses after navigation. */
export function mount(target, ctx) {
  if (!document.getElementById("scan-page-css")) {
    const link = document.createElement("link");
    link.id = "scan-page-css";
    link.rel = "stylesheet";
    link.href = new URL("../../../css/pages/scan.css", import.meta.url).href;
    document.head.append(link);
  }
  const root = el("div", "scan-page stack"), notice = el("div"), body = el("div", "stack");
  root.append(notice, body);
  target.replaceChildren(root);
  body.append(spinner({ label: "Đang tải lần quét…" }));
  let disposed = false, timer, loadingState = false, pending = false, optionsController = null, optionsData = null, state = null, logs = [], logSince = 0, mode = "loading", starting = false;
  const view = { charts: false, logs: false };
  const app = () => ctx.store.get().app || ctx.store.get().appState || {};
  const busy = () => starting || pending || !!app().busy || !!state?.running;
  function failure(result) {
    if (disposed)
      return;
    notice.replaceChildren(alert({ variant: "error", message: result.error || "Không thể hoàn tất thao tác. Vui lòng thử lại." }));
    ctx.toast(result.error || "Không thể hoàn tất thao tác.", { variant: "error" });
  }
  async function act(method, ...args) {
    if (pending || disposed)
      return null;
    pending = true;
    render();
    const result = await ctx.call(method, ...args);
    pending = false;
    if (disposed)
      return null;
    if (!result.ok)
      failure(result);
    else if (result.message && !result.cancelled)
      ctx.toast(result.message, { variant: "success" });
    render();
    return result;
  }
  const actions = { pending: () => pending, openUrl: async (url) => {
    const result = await ctx.call("open_url", url);
    if (!result.ok)
      failure(result);
  }, stop: async () => {
    const result = await act("stop_scan");
    if (result?.ok) {
      state = { ...state, stopping: true, question: null };
      render();
      await poll();
    }
  }, answer: async (id) => {
    const result = await act("answer_question", id);
    if (result?.ok) {
      state = { ...state, question: null };
      render();
      await poll();
    }
  }, file: (method, name) => act(method, name), results: () => ctx.navigate("results"), reset: () => {
    notice.replaceChildren();
    mode = "options";
    optionsController?.destroy();
    optionsController = null;
    render();
  } };
  function render() {
    if (disposed)
      return;
    if (mode === "options" && optionsData) {
      if (!optionsController)
        optionsController = scanOptions(optionsData, ctx, { onStart: start, isBusy: busy });
      if (body.firstChild !== optionsController.root)
        body.replaceChildren(optionsController.root);
      optionsController.sync();
    } else if (state && (state.running || mode === "finished")) {
      optionsController?.destroy();
      optionsController = null;
      body.replaceChildren(scanProgress(state, logs, actions, view));
    }
  }
  async function start(options) {
    if (busy())
      return;
    starting = true;
    notice.replaceChildren();
    optionsController?.sync();
    const result = await ctx.call("start_scan", options);
    starting = false;
    if (disposed)
      return;
    if (!result.ok) {
      if (result.key_status)
        optionsController?.setKeyStatus(result.key_status);
      failure(result);
      optionsController?.sync();
      return;
    }
    logs = [];
    logSince = 0;
    state = { running: true, elapsed_s: 0, overall: 0, lanes: [], message: "Đang bắt đầu lần quét…", channels: [], log: [], errors: [], item_label: options.kind === "post" ? "bài đăng" : "video" };
    mode = "running";
    render();
    ctx.refreshApp();
    await poll();
  }
  async function poll() {
    clearTimeout(timer);
    if (disposed || loadingState)
      return;
    loadingState = true;
    const result = await ctx.call("get_scan_state", logSince);
    loadingState = false;
    if (disposed)
      return;
    if (!result.ok) {
      failure(result);
      if (state?.running)
        timer = setTimeout(poll, 700);
      return;
    }
    const wasRunning = !!state?.running;
    if (result.log_total < logSince) {
      logs = [];
      logSince = 0;
      state = result;
      timer = setTimeout(poll, 0);
      return;
    }
    logs.push(...result.log || []);
    logSince = result.log_total;
    state = result;
    if (result.running)
      mode = "running";
    else if (wasRunning || mode === "loading" && (result.result || result.ended_without_result))
      mode = "finished";
    else if (mode === "loading")
      mode = "options";
    render();
    if (wasRunning && !result.running) {
      ctx.refreshApp();
      optionsController?.preview();
    }
    if (result.running)
      timer = setTimeout(poll, 700);
  }
  const unsubscribe = ctx.store.subscribe(() => {
    if (disposed)
      return;
    optionsController?.sync();
    if (app().guide?.running && !state?.running && !loadingState)
      poll();
  });
  async function loadOptions() {
    const result = await ctx.call("get_scan_options");
    if (disposed)
      return;
    if (!result.ok) {
      failure(result);
      if (!state?.running)
        body.replaceChildren(button({ label: "Thử tải lại", onClick: loadOptions }));
      return;
    }
    optionsData = result;
    if (mode === "loading" && !loadingState)
      mode = "options";
    render();
  }
  loadOptions();
  poll();
  return () => {
    disposed = true;
    clearTimeout(timer);
    unsubscribe();
    optionsController?.destroy();
  };
}
