import { el } from "../../components/dom.js";
import { button, card, numberInput, checkbox, toggle, radioGroup, alert, expander, badge } from "../../components/index.js";
import { num } from "../../format.js";
/** Local controller keeps input focus while asynchronous previews update only the summary. */
export function scanOptions(data, ctx, { onStart, isBusy }) {
  const values = structuredClone(data.defaults), root = el("div", "stack"), grid = el("div", "scan-options-grid");
  values.length_limits ||= { video: [null, null], reel: [null, null] };
  const left = card({ title: "Nội dung nào được quét?" }), right = card({ title: "Ngưỡng lọc" });
  left.body.classList.add("stack");
  right.body.classList.add("stack");
  grid.append(left, right);
  const content = el("div", "stack"), filters = el("div", "stack"), combination = el("div"), summary = el("p", "scan-summary"), problems = el("div", "stack"), keys = el("div", "stack"), terms = el("div");
  summary.setAttribute("aria-live", "polite");
  let disposed = false, timer, previewId = 0, keyId = 0, canStart = false, checking = false, acting = false, keyStatus = null, keyError = "", customDays = ![7, 14, 30].includes(values.days);
  const start = button({ label: "Bắt đầu quét", variant: "primary", size: "large", icon: "scan", disabled: true, onClick: () => onStart(options()) });
  start.classList.add("scan-start");
  const dayInput = numberInput({ label: "Số ngày", value: values.days, min: 1, onChange: (value) => {
    values.days = value ?? 0;
    preview();
  } });
  dayInput.hidden = !customDays;
  const days = radioGroup({ label: "Nội dung đăng trong", options: [{ id: "7", label: "7 ngày" }, { id: "14", label: "14 ngày" }, { id: "30", label: "30 ngày" }, { id: "custom", label: "Tự nhập" }], value: customDays ? "custom" : String(values.days), onChange: (value) => {
    customDays = value === "custom";
    dayInput.hidden = !customDays;
    values.days = customDays ? dayInput.value ?? 0 : Number(value);
    preview();
  } });
  const kind = radioGroup({ label: "Loại quét", options: [{ id: "video", label: "Video" }, { id: "post", label: "Bài đăng" }], value: values.kind, onChange: (value) => {
    values.kind = value;
    renderContent();
    renderFilters();
    preview();
    checkKeys();
  } });
  left.body.append(days, dayInput, kind, content);
  right.body.append(filters, combination, summary, problems);
  root.append(grid, keys, terms, start);
  function options() {
    data.defaults = structuredClone(values);
    return { days: values.days, kind: values.kind, formats: [...values.formats], length_limits: structuredClone(values.length_limits), min_views: values.min_views, min_ratio_follow: values.min_ratio_follow, match_all: values.match_all, min_interactions: values.min_interactions };
  }
  function locked() {
    return isBusy() || acting;
  }
  function sync() {
    root.querySelectorAll("input,button,select,textarea").forEach((node) => {
      node.disabled = locked();
    });
    start.disabled = locked() || checking || !canStart || !keyStatus || !!keyError || Object.values(keyStatus).some(Boolean);
    const retry = keys.querySelector("button");
    if (retry)
      retry.disabled = locked() || checking;
  }
  function presets(items, choose) {
    return el("div", "row scan-presets", items.map((item) => button({ label: item.label, size: "small", onClick: () => {
      choose(item);
      preview();
    } })));
  }
  function renderContent() {
    content.replaceChildren();
    if (values.kind === "post") {
      const images = toggle({ label: "Đọc nội dung ảnh trong bài (AI đọc ảnh)", checked: values.read_images, hint: "Tốn thêm khoảng 1.500–2.000 token/ảnh, tối đa 4 ảnh/bài.", onChange: async (enabled) => {
        const previous = values.read_images;
        acting = true;
        sync();
        const result = await ctx.call("set_read_images", enabled);
        if (disposed)
          return;
        values.read_images = result.enabled ?? previous;
        data.defaults.read_images = values.read_images;
        images.value = values.read_images;
        acting = false;
        imageNotice.replaceChildren();
        const message = result.error || result.message;
        if (message)
          imageNotice.append(alert({ message, variant: result.ok && (!enabled || result.enabled) ? "success" : "error" }));
        sync();
      } }), imageNotice = el("div");
      content.append(images, imageNotice);
    } else {
      let renderLengths = function() {
        lengths.replaceChildren();
        for (const [base, label] of [["video", "Video"], ["reel", "Reel"]]) {
          if (!values.formats.includes(base))
            continue;
          const limits = values.length_limits[base] || [null, null];
          values.length_limits[base] = limits;
          const fields = ["Tối thiểu", "Tối đa"].map((text, index) => numberInput({ label: `${text} (giây)`, value: limits[index] || 0, min: 0, onChange: (value) => {
            limits[index] = value || null;
            preview();
          } }));
          lengths.append(el("div", "stack scan-length", el("h4", "", `Thời lượng ${label}`), el("div", "scan-field-pair", fields), el("div", "row scan-length-foot", presets(data.presets.length[base], (preset) => {
            limits[0] = preset.min;
            limits[1] = preset.max;
            fields.forEach((field, i) => field.value = limits[i] || 0);
          }), el("span", "hint", "0 = không giới hạn"))));
        }
        sync();
      };
      const formats = el("div", "scan-kind-grid");
      for (const item of data.kinds)
        formats.append(checkbox({ label: item.label, checked: values.formats.includes(item.id), onChange: (checked) => {
          values.formats = checked ? [...values.formats, item.id] : values.formats.filter((id) => id !== item.id);
          renderLengths();
          preview();
        } }));
      const lengths = el("div", "stack");
      content.append(formats, lengths);
      renderLengths();
    }
    sync();
  }
  function renderCombination() {
    combination.replaceChildren();
    if (values.kind === "video" && values.min_views > 0 && values.min_ratio_follow > 0)
      combination.append(radioGroup({ label: "Cách kết hợp", options: [{ id: "all", label: "Đạt cả hai điều kiện" }, { id: "any", label: "Đạt một trong hai" }], value: values.match_all ? "all" : "any", onChange: (value) => {
        values.match_all = value === "all";
        preview();
      } }));
    sync();
  }
  function renderFilters() {
    filters.replaceChildren();
    if (values.kind === "post") {
      filters.append(numberInput({ label: "Tương tác tối thiểu", value: values.min_interactions, min: 0, step: 10, thousands: true, hint: "Cảm xúc + bình luận + chia sẻ. Không biết số liệu thì không đạt; 0 = không lọc.", onChange: (value) => {
        values.min_interactions = value ?? 0;
        preview();
      } }));
    } else {
      for (const [key, label, hint, format, step] of [["min_views", "Lượt xem tối thiểu", "Không biết lượt xem thì không đạt; 0 = không lọc.", num, 1000], ["min_ratio_follow", "Lượt xem so với follower (×)", "Ví dụ 5× = lượt xem gấp 5 lần follower. Không biết follower thì không đạt; 0 = tắt.", (value) => `${value}×`, 1]]) {
        const field = numberInput({ label, value: values[key], min: 0, step, thousands: key === "min_views", hint, onChange: (value) => {
          values[key] = value ?? 0;
          renderCombination();
          preview();
        } });
        filters.append(field, presets(data.presets[key].map((value) => ({ label: format(value), value })), (item) => {
          values[key] = item.value;
          field.value = item.value;
          renderCombination();
        }));
      }
    }
    renderCombination();
    sync();
  }
  function preview() {
    clearTimeout(timer);
    canStart = false;
    sync();
    const id = ++previewId;
    timer = setTimeout(async () => {
      const result = await ctx.call("preview_scan", options());
      if (disposed || id !== previewId)
        return;
      summary.textContent = result.summary || "";
      problems.replaceChildren();
      for (const message of result.problems || [])
        problems.append(alert({ variant: "error", message }));
      if (!result.ok)
        problems.append(alert({ variant: "error", message: result.error }));
      canStart = !!result.ok && !!result.can_start;
      sync();
    }, 250);
  }
  function renderKeys() {
    keys.replaceChildren();
    const names = values.kind === "video" ? ["jev", "deepgram", "llm"] : ["jev", "llm"], labels = { jev: "Jev", deepgram: "Deepgram", llm: "LLM" }, row = el("div", "row");
    for (const name of names) {
      const checked = keyStatus && Object.hasOwn(keyStatus, name), reason = keyStatus?.[name], node = el("div", "scan-key", badge({ label: `${checked ? reason ? "✗" : "✓" : "…"} ${labels[name]}`, state: checked ? reason ? "error" : "success" : "pending" }));
      if (reason)
        node.append(el("span", "hint", reason));
      row.append(node);
    }
    row.append(el("div", "spacer"), button({ label: checking ? "Đang kiểm tra…" : "Kiểm tra lại", size: "small", onClick: checkKeys }));
    keys.append(row);
    const failed = names.filter((name) => keyStatus?.[name]);
    if (failed.length || keyError)
      keys.append(alert({ variant: "error", message: keyError || `Chưa thể chạy quét vì lỗi key ở: ${failed.map((name) => labels[name]).join(", ")}. Sửa trong mục Dịch vụ AI rồi kiểm tra lại.`, body: button({ label: "Đi tới Dịch vụ AI", size: "small", onClick: () => ctx.navigate("settings") }) }));
    sync();
  }
  async function checkKeys() {
    const id = ++keyId;
    checking = true;
    keyStatus = null;
    keyError = "";
    renderKeys();
    const result = await ctx.call("check_keys", values.kind === "video");
    if (disposed || id !== keyId)
      return;
    checking = false;
    keyStatus = result.status || null;
    keyError = result.ok ? "" : result.error || "Không kiểm tra được API key.";
    renderKeys();
  }
  function renderTerms() {
    terms.replaceChildren();
    const notice = el("div", "stack", data.terms.paragraphs.map((text) => el("p", "", text)), el("ul", "", data.terms.bullets.map((text) => el("li", "", text))));
    const link = el("a", "", data.terms.link.label);
    link.href = data.terms.link.url;
    notice.append(el("p", "", "Xem thêm: ", link));
    if (data.terms.accepted_at) {
      const date = new Date(data.terms.accepted_at);
      notice.append(el("p", "hint", `Đã xác nhận lúc ${Number.isNaN(date.valueOf()) ? data.terms.accepted_at : date.toLocaleString("vi-VN")}`));
      terms.append(expander({ title: "Lưu ý khi dùng Facebook (đã xác nhận)", body: notice }));
    } else {
      const accept = checkbox({ label: "Tôi đã đọc và tự chịu trách nhiệm", onChange: async (checked) => {
        if (!checked)
          return;
        acting = true;
        sync();
        const result = await ctx.call("accept_terms");
        if (disposed)
          return;
        acting = false;
        if (result.ok) {
          data.terms.accepted_at = result.accepted_at;
          renderTerms();
          preview();
        } else {
          accept.value = false;
          ctx.toast(result.error, { variant: "error" });
        }
        sync();
      } });
      notice.append(accept);
      const warning = card({ title: "Lưu ý quan trọng trước khi quét", body: notice });
      warning.classList.add("scan-terms");
      terms.append(warning);
    }
    sync();
  }
  renderContent();
  renderFilters();
  renderTerms();
  checkKeys();
  preview();
  return { root, sync, preview, setKeyStatus(status) {
    ++keyId;
    checking = false;
    keyStatus = status;
    keyError = "";
    renderKeys();
  }, destroy() {
    disposed = true;
    ++previewId;
    ++keyId;
    clearTimeout(timer);
  } };
}
