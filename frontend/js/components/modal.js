import { el, append } from "./dom.js";
import { button } from "./button.js";
const openModals = [];
/** @param {{title:string,body?:Node|string,footer?:Node|Node[],onClose?:Function,closeOnOverlay?:boolean}} options; appends overlay, returns it with .close()/.body/.footer. */
export function modal({ title, body, footer, onClose, closeOnOverlay = true } = {}) {
  const previous = document.activeElement, overlay = el("div", "modal-overlay"), dialog = el("section", "modal"), heading = el("h2", "", title);
  heading.id = `modal-title-${++modal.id}`;
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", heading.id);
  dialog.tabIndex = -1;
  const close = () => {
    if (!overlay.isConnected)
      return;
    overlay.remove();
    document.removeEventListener("keydown", keydown);
    openModals.splice(openModals.indexOf(overlay), 1);
    if (!openModals.length)
      document.body.style.overflow = modal.previousOverflow;
    previous?.focus();
    onClose?.();
  };
  const keydown = (e) => {
    if (openModals.at(-1) !== overlay)
      return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    }
    if (e.key === "Tab") {
      const focusable = [...dialog.querySelectorAll("button,input,select,textarea,a[href],[tabindex]")].filter((n) => !n.disabled && n.tabIndex >= 0 && n.getClientRects().length);
      if (!focusable.length) {
        e.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  overlay.body = el("div", "modal-body");
  overlay.footer = el("footer", "modal-footer");
  append(overlay.body, body);
  append(overlay.footer, footer);
  dialog.append(el("header", "modal-header", heading, button({ label: "Đóng", icon: "close", variant: "ghost", size: "small", onClick: close })), overlay.body, overlay.footer);
  overlay.append(dialog);
  overlay.close = close;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay && closeOnOverlay)
      close();
  });
  if (!openModals.length) {
    modal.previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  openModals.push(overlay);
  document.body.append(overlay);
  document.addEventListener("keydown", keydown);
  queueMicrotask(() => dialog.querySelector("button")?.focus());
  return overlay;
}
modal.id = 0;
/** @param {string} message @param {{danger?:boolean,title?:string,confirmLabel?:string}} options Resolves false on any dismissal. */
export function confirm(message, { danger = false, title = "Xác nhận", confirmLabel = "Xác nhận" } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled)
        return;
      settled = true;
      resolve(value);
    };
    const m = modal({ title, body: el("p", "", message), onClose: () => finish(false), footer: [button({ label: "Hủy", onClick: () => m.close() }), button({ label: confirmLabel, variant: danger ? "danger" : "primary", onClick: () => {
      finish(true);
      m.close();
    } })] });
  });
}
