import {el} from '../../components/dom.js';
import {alert, button, card, emptyState, select, spinner} from '../../components/index.js';
import {num} from '../../format.js';
import {renderSummary} from './summary.js';

let selectedName = '';

function loadStyles() {
  if (document.getElementById('results-page-styles')) return;
  const link = document.createElement('link');
  link.id = 'results-page-styles';
  link.rel = 'stylesheet';
  link.href = new URL('../../../css/pages/results.css', import.meta.url).href;
  document.head.append(link);
}

/** Mount the library; discard outstanding responses and unsubscribe on navigation. */
export function mount(container, ctx) {
  loadStyles();
  let disposed = false, listRequest = 0, summaryRequest = 0, pending = false;
  let files = [], controls = [], picker = null;
  const stateOf = state => state.app || state.appState || state;
  let app = stateOf(ctx.store.get());
  let hasResult = app.guide?.has_result;
  const blocked = () => Boolean(app.busy || pending);
  const content = el('div', 'stack');
  const summaryCard = card({title:'Tổng quan kết quả'});
  summaryCard.body.setAttribute('aria-live', 'polite');
  const folder = button({label:'Mở thư mục', icon:'folder', onClick:() => perform('open_output_folder', [], folder)});
  const root = el('div', 'results-page stack',
    el('header', 'results-header', el('div', '', el('h2', '', 'Thư viện kết quả'), el('p', 'muted', 'Xem lại nội dung nổi bật và quản lý các file Excel đã xuất.')), folder),
    content);
  container.replaceChildren(root);

  function syncDisabled() {
    folder.disabled = blocked();
    for (const control of controls) control.disabled = blocked();
    if (picker) picker.input.disabled = blocked();
  }

  async function perform(method, args, control, deleting = false) {
    if (disposed || blocked()) return;
    pending = true;
    syncDisabled();
    try {
      if (deleting) {
        const accepted = await ctx.confirm(`Bạn muốn xóa file này? Thao tác này không thể hoàn tác.\n\n${args[0]}`, {danger:true, title:'Xóa file Excel', confirmLabel:'Xóa'});
        if (!accepted || disposed || app.busy) return;
      }
      control.setLoading(true);
      const result = await ctx.call(method, ...args);
      if (disposed) return;
      if (!result?.ok) {
        ctx.toast(result?.error || 'Không thể hoàn tất thao tác. Vui lòng thử lại.', {variant:'error'});
        return;
      }
      if (result.cancelled) return;
      if (result.message) ctx.toast(result.message, {variant:'success'});
      if (deleting) {
        await refresh();
        if (!disposed) await ctx.refreshApp();
      }
    } finally {
      control.setLoading(false);
      pending = false;
      if (!disposed) syncDisabled();
    }
  }

  async function loadSummary() {
    const request = ++summaryRequest, name = selectedName;
    summaryCard.body.replaceChildren(spinner({label:'Đang đọc thống kê…'}));
    const result = await ctx.call('get_result_summary', name);
    if (disposed || request !== summaryRequest || name !== selectedName) return;
    summaryCard.body.replaceChildren(result?.ok ? renderSummary(result.summary) : alert({variant:'error', message:result?.error || 'Không đọc được thống kê của file này.'}));
  }

  function renderFiles(folderPath) {
    controls = [];
    picker = null;
    if (!files.length) {
      ++summaryRequest;
      selectedName = '';
      const scan = button({label:'Chạy lần quét đầu tiên', variant:'primary', icon:'scan', onClick:() => ctx.navigate('scan')});
      controls.push(scan);
      content.replaceChildren(card({body:emptyState({title:'Chưa có kết quả', message:'Chạy lần quét đầu tiên để xem nội dung nổi bật, biểu đồ và tải file Excel tại đây.', icon:'results', actions:scan})}));
      syncDisabled();
      return;
    }
    if (!files.some(file => file.name === selectedName)) selectedName = files[0].name;
    picker = select({label:'Xem thống kê file', options:files.map(file => file.name), value:selectedName,
      hint:'Mặc định là file mới nhất; chọn file khác để so sánh kết quả.',
      onChange:name => {selectedName = name; loadSummary();}});
    const list = el('div', 'results-files');
    for (const file of files) {
      const open = button({label:'Mở', variant:'primary', icon:'external', onClick:() => perform('open_result', [file.name], open)});
      const save = button({label:'Lưu bản sao…', icon:'download', onClick:() => perform('save_result_as', [file.name], save)});
      const remove = button({icon:'trash', variant:'ghost', title:'Xóa file', onClick:() => perform('delete_result', [file.name], remove, true)});
      remove.setAttribute('aria-label', `Xóa file ${file.name}`);
      controls.push(open, save, remove);
      list.append(el('article', 'results-file',
        el('div', 'results-file-info', el('h3', 'results-file-name', file.name), el('p', 'hint', `${file.modified} · ${file.size_text}`)),
        el('div', 'results-file-actions', open, save, remove)));
    }
    content.replaceChildren(picker, summaryCard, card({title:`File Excel đã xuất · ${num(files.length)} file`,
      subtitle:'Mới nhất trước · Mở hoặc lưu bản sao để xem chi tiết và công thức làm lại; xóa file cần xác nhận.', body:list}));
    if (folderPath) content.append(el('p', 'hint results-folder', `Thư mục kết quả: ${folderPath}`));
    syncDisabled();
    loadSummary();
  }

  async function refresh() {
    const request = ++listRequest;
    const result = await ctx.call('list_results');
    if (disposed || request !== listRequest) return;
    if (!result?.ok) {
      const retry = button({label:'Thử lại', onClick:refresh});
      controls = [retry];
      picker = null;
      ++summaryRequest;
      content.replaceChildren(alert({variant:'error', message:result?.error || 'Không đọc được danh sách file Excel.'}), retry);
      syncDisabled();
      return;
    }
    files = [...result.files].sort((a, b) => b.modified_ts - a.modified_ts);
    renderFiles(result.folder);
  }

  content.append(spinner({label:'Đang tải thư viện kết quả…'}));
  syncDisabled();
  const unsubscribe = ctx.store.subscribe(state => {
    app = stateOf(state);
    const nextHasResult = app.guide?.has_result;
    if (nextHasResult !== hasResult) {
      hasResult = nextHasResult;
      refresh();
    }
    syncDisabled();
  });
  refresh();
  return () => {disposed = true; ++listRequest; ++summaryRequest; unsubscribe();};
}
