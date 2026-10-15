let mock = false;
const forced = new URLSearchParams(location.search).get("mock") === "1";
let ready;
function bridge() {
  if (!ready)
    ready = new Promise((resolve) => {
      if (forced) {
        mock = true;
        resolve(null);
        return;
      }
      if (window.pywebview?.api) {
        resolve(window.pywebview.api);
        return;
      }
      let timer;
      const finish = () => {
        clearTimeout(timer);
        window.removeEventListener("pywebviewready", finish);
        const api = window.pywebview?.api;
        mock = !api;
        resolve(api || null);
      };
      window.addEventListener("pywebviewready", finish, { once: true });
      timer = setTimeout(finish, 1000);
    });
  return ready;
}
/** Call the Python bridge or local mock. Bridge failures are returned, never thrown. */
export async function call(method, ...args) {
  try {
    const api = await bridge();
    if (api) {
      if (typeof api[method] !== "function")
        return { ok: false, error: `Chức năng chưa khả dụng: ${method}` };
      return await api[method](...args);
    }
    const { mockApi } = await import("./mock/index.js");
    if (typeof mockApi[method] !== "function")
      return { ok: false, error: `Bản xem thử chưa hỗ trợ: ${method}` };
    return await mockApi[method](...args);
  } catch (error) {
    return { ok: false, error: "Không thể hoàn tất thao tác. Kiểm tra kết nối và thử lại." };
  }
}
export function isMock() {
  return forced || mock;
}
