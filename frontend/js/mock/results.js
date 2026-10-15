import {appState} from './app.js';

const query = new URLSearchParams(location.search);
const folder = 'C:\\Video Công Thức\\output';
const files = query.get('mockResults') === 'empty' ? [] : [
  {name:'video_2026-10-15_0930.xlsx', modified:'15/10/2026 09:30', modified_ts:1792031400, size_text:'186 KB'},
  {name:'bai_dang_2026-10-14_1600.xlsx', modified:'14/10/2026 16:00', modified_ts:1791968400, size_text:'92 KB'},
  {name:'video_chua_co_diem_2026-10-13.xlsx', modified:'13/10/2026 10:15', modified_ts:1791861300, size_text:'74 KB'},
  {name:'video_khong_dat_nguong_2026-10-12.xlsx', modified:'12/10/2026 11:00', modified_ts:1791777600, size_text:'18 KB'},
  {name:'ket_qua_cu_2026-10-10.xlsx', modified:'10/10/2026 08:45', modified_ts:1791596700, size_text:'38 KB'}
];
const titles = [
  '3 thói quen buổi sáng giúp bạn khỏe hơn',
  'Hiểu đúng về vitamin và cách bổ sung',
  'Một phút nhận biết dấu hiệu cần đi khám',
  'Bữa ăn cân bằng cho cả gia đình',
  'Những câu hỏi thường gặp ở nhà thuốc',
  'Mẹo đọc nhãn sản phẩm dễ hiểu',
  'Chăm sóc sức khỏe khi thời tiết thay đổi',
  'Giải đáp hiểu lầm về giấc ngủ',
  'Câu chuyện nhỏ từ quầy thuốc',
  'Cách xây dựng thói quen uống đủ nước'
];
const pages = ['Sống Khỏe Mỗi Ngày', 'Góc Dược Sĩ', 'Nhà Thuốc Gia Đình', 'Chuyện Sức Khỏe'];
const topicLabels = ['Kiến thức sức khỏe', 'Hỏi đáp', 'Dinh dưỡng', 'Thói quen sống'];

function sampleSummary(kind, count, created, withScores = true) {
  const post = kind === 'post';
  const items = Array.from({length:count}, (_, i) => ({
    label:`${i + 1}. ${titles[i % titles.length]}${i >= 10 ? ' · Phần 2' : ''}`,
    value:Math.round((post ? 18400 : 1260000) / (1 + i * 0.42)),
    page:pages[i % pages.length], topic:topicLabels[i % topicLabels.length],
    score:withScores ? [92, 88, 84, 81, 77, 75, 71, 68, 62, 58, 45, 34, 18][i % 13] : null
  }));
  const scores = items.filter(item => item.score !== null).map(item => item.score);
  const buckets = [
    {label:'Dưới 20', value:scores.filter(score => score < 20).length},
    {label:'20–39', value:scores.filter(score => score >= 20 && score < 40).length},
    {label:'40–59', value:scores.filter(score => score >= 40 && score < 60).length},
    {label:'60–79', value:scores.filter(score => score >= 60 && score < 80).length},
    {label:'Từ 80', value:scores.filter(score => score >= 80).length}
  ];
  return {
    kind, metric_label:post ? 'Tương tác' : 'Lượt xem', count,
    pages:new Set(items.map(item => item.page)).size,
    reach:count ? items.reduce((sum, item) => sum + item.value, 0) : null,
    avg_score:scores.length ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length * 10) / 10 : null,
    usage:{llm_model:'gemini-2.5-flash', llm_tokens:count * 3280, jev_tokens:count * 460, deepgram_minutes:post ? 0 : Math.round(count * 1.82 * 100) / 100},
    created, top:items.slice(0, 10).map(({label, value, page}) => ({label, value, page})),
    topics:topicLabels.map(label => ({label, value:items.filter(item => item.topic === label).length})).filter(item => item.value),
    distribution:buckets, has_scores:scores.length > 0
  };
}

const summaries = {
  'video_2026-10-15_0930.xlsx':sampleSummary('video', 24, '15/10/2026 09:30'),
  'bai_dang_2026-10-14_1600.xlsx':sampleSummary('post', 18, '14/10/2026 16:00'),
  'video_chua_co_diem_2026-10-13.xlsx':sampleSummary('video', 9, '13/10/2026 10:15', false),
  'video_khong_dat_nguong_2026-10-12.xlsx':sampleSummary('video', 0, '12/10/2026 11:00'),
  'ket_qua_cu_2026-10-10.xlsx':null
};
const missing = () => ({ok:false, error:'Không tìm thấy file Excel đã chọn.'});
const exists = name => files.some(file => file.name === name);
appState.guide.has_result = files.length > 0;

/** Share newly exported mock files with the scan preview, including after deletion. */
export function registerScanResult({name, count, kind}) {
  const now = new Date();
  const modified = new Intl.DateTimeFormat('vi-VN', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:false}).format(now);
  const existing = files.findIndex(file => file.name === name);
  if (existing >= 0) files.splice(existing, 1);
  files.unshift({name, modified, modified_ts:now.getTime() / 1000, size_text:'126 KB'});
  summaries[name] = sampleSummary(kind, count, modified);
  appState.guide.has_result = true;
}

export default {
  list_results:async () => ({ok:true, folder, files:structuredClone(files)}),
  get_result_summary:async name => exists(name) ? {ok:true, summary:structuredClone(summaries[name])} : missing(),
  delete_result:async name => {
    const index = files.findIndex(file => file.name === name);
    if (index < 0) return missing();
    files.splice(index, 1);
    delete summaries[name];
    appState.guide.has_result = files.length > 0;
    return {ok:true, message:`Đã xóa file ${name}.`};
  },
  open_result:async name => exists(name) ? {ok:true, message:'Bản xem thử: file sẽ được mở bằng Excel trong ứng dụng trên máy.'} : missing(),
  open_output_folder:async () => ({ok:true, message:'Bản xem thử: thư mục kết quả sẽ mở trong ứng dụng trên máy.'}),
  save_result_as:async name => !exists(name) ? missing() : query.get('mockSaveCancelled') === '1' ? {ok:true, cancelled:true} : {ok:true, message:'Bản xem thử: đã mô phỏng lưu bản sao Excel.'}
};
