import {card} from '../../components/card.js';
import {emptyState} from '../../components/emptyState.js';
/** Mount the settings page into el with the shared application context. */
export function mount(el,ctx){el.replaceChildren(card({title:'Cài đặt',body:emptyState({title:'Đang xây dựng',message:'Kết nối dịch vụ AI và chuẩn bị kênh quét tại đây.'})}));}
