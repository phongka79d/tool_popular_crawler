import {card} from '../../components/card.js';
import {emptyState} from '../../components/emptyState.js';
/** Mount the scan page into el with the shared application context. */
export function mount(el,ctx){el.replaceChildren(card({title:'Chạy quét',body:emptyState({title:'Đang xây dựng',message:'Thiết lập bộ lọc và bắt đầu khám phá nội dung nổi bật.'})}));}
