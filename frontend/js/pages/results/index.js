import {card} from '../../components/card.js';
import {emptyState} from '../../components/emptyState.js';
/** Mount the results page into el with the shared application context. */
export function mount(el,ctx){el.replaceChildren(card({title:'Kết quả',body:emptyState({title:'Đang xây dựng',message:'Xem thống kê và các file Excel đã xuất tại đây.'})}));}
