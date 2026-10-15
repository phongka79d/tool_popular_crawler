import {el} from '../../components/dom.js';
import {alert, barChart, expander, metric} from '../../components/index.js';
import {num, dec} from '../../format.js';

// The shared chart has compact axes but no separate tooltip/page formatter.
function rankedChart(items) {
  const data = items.slice(0, 10);
  const chart = barChart({data, horizontal:true, compact:true, height:Math.max(240, data.length * 34 + 48)});
  chart.querySelectorAll('svg rect').forEach((mark, index) => {
    const item = data[index];
    const text = `${item.label} · Kênh: ${item.page || '—'} · ${num(item.value)}`;
    mark.setAttribute('aria-label', text);
    mark.querySelector('title').textContent = text;
    const show = () => { chart.querySelector('.chart-tooltip').textContent = text; };
    mark.addEventListener('pointermove', show);
    mark.addEventListener('focus', show);
  });
  return chart;
}

export function renderSummary(summary) {
  if (!summary) return alert({message:'Không đọc được thống kê của file này. Bạn vẫn có thể lưu bản sao hoặc mở bằng Excel.'});
  const metricLabel = summary.metric_label || (summary.kind === 'post' ? 'Tương tác' : 'Lượt xem');
  const body = el('div', 'stack',
    el('div', 'results-metrics',
      metric({label:'Nội dung đã xuất', value:num(summary.count)}),
      metric({label:'Kênh có kết quả', value:num(summary.pages)}),
      metric({label:`Tổng ${metricLabel.toLocaleLowerCase('vi')}`, value:num(summary.reach)}),
      metric({label:'Điểm công thức TB', value:dec(summary.avg_score, 1)})
    )
  );
  const usage = summary.usage;
  if (usage) body.append(el('p', 'hint results-usage', `Model: ${usage.llm_model || '—'} · LLM: ${num(usage.llm_tokens ?? 0)} token · Jev: ${num(usage.jev_tokens ?? 0)} token · Deepgram: ${dec(usage.deepgram_minutes ?? 0, 2)} phút`));
  if (summary.created) body.append(el('p', 'hint', `Xuất lúc ${summary.created}`));
  if (summary.count === 0) {
    body.append(alert({message:'File không có nội dung đạt ngưỡng. Thử giảm ngưỡng lọc hoặc mở rộng số ngày quét.'}));
    return body;
  }
  const top = el('section', 'stack', el('h3', '', `Top 10 theo ${metricLabel.toLocaleLowerCase('vi')}`));
  top.append(summary.top?.length ? rankedChart(summary.top) : el('p', 'hint', `Chưa có số liệu ${metricLabel.toLocaleLowerCase('vi')} để vẽ biểu đồ.`));
  const topics = el('section', 'stack', el('h3', '', 'Nội dung theo chủ đề'),
    barChart({data:summary.topics || [], horizontal:true, integer:true, height:Math.max(240, (summary.topics?.length || 0) * 34 + 48)}));
  const distribution = el('section', 'stack', el('h3', '', 'Phân bố điểm công thức'),
    summary.has_scores ? barChart({data:summary.distribution || [], integer:true, height:220}) : el('p', 'hint', 'Chưa có điểm công thức để vẽ biểu đồ.'));
  body.append(expander({title:'Biểu đồ kết quả', open:true, body:el('div', 'stack', el('div', 'results-chart-grid', top, topics), distribution)}));
  return body;
}
