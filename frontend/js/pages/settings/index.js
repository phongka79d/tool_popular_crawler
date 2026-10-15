import {el} from '../../components/dom.js';
import {button, card, statusPill, textarea, alert, expander, editableTable, checkbox, spinner} from '../../components/index.js';
import {serviceCard} from './serviceCard.js';

/** Settings retain unsaved form values while shell state refreshes. */
export function mount(target, ctx) {
  if (!document.getElementById('settings-styles')) {
    const link = document.createElement('link');
    link.id='settings-styles';link.rel='stylesheet';link.href=new URL('../../../css/pages/settings.css', import.meta.url).href;
    document.head.append(link);
  }
  let disposed=false, pending=false, loginBusy=false, loginTimer=null, loginPolling=false, loginState=null;
  let fbReady=Boolean((ctx.store.get().app || ctx.store.get().appState)?.guide?.fb_ready);
  const root=el('div','settings-page stack'), controls=el('fieldset','settings-controls stack');
  const security=el('div'), services=el('div','stack'), channels=el('div'), facebook=el('div'), taxonomy=el('div'), resetErrors=el('div');
  const busyHint=el('div');
  security.hidden=true;busyHint.hidden=true;
  controls.append(security,el('section','stack',el('h2','','1 · Dịch vụ AI'),el('p','hint','Làm lần lượt: nhập key → Kết nối → chọn model → Kiểm tra và lưu.'),services),el('section','stack',el('h2','','2 · Kênh & Facebook'),el('div','settings-connections',channels,facebook)),taxonomy);
  const resetButton=button({label:'Đặt lại toàn bộ cấu hình',variant:'danger',onClick:async()=>{
    if(isBusy()) return;
    const confirmed=await ctx.confirm('Xóa 3 API key, khôi phục cài đặt mặc định và xóa danh sách kênh? Excel, cache và phiên Facebook được giữ nguyên.',{danger:true,title:'Đặt lại cấu hình',confirmLabel:'Đặt lại cấu hình'});
    if(!confirmed || isBusy() || disposed) return;
    await run(resetButton,resetErrors,async()=>{
      const result=await ctx.call('reset_configuration');
      if(result.ok && !disposed) {ctx.toast(result.message,{variant:'success'});await ctx.refreshApp();await loadAll();}
      return result;
    });
  }});
  controls.append(expander({title:'⚠️ Đặt lại cấu hình',body:el('div','stack',el('p','hint','Xóa 3 API key, khôi phục settings.json mặc định và xóa danh sách kênh. Không xóa Excel, cache hay phiên Facebook.'),el('div','row',resetButton),resetErrors)}));
  root.append(el('div','stack',el('h2','','Cài đặt'),el('p','hint','🔒 Key chỉ được lưu trong Windows Credential Manager, không ghi ra file.')),busyHint,controls);
  target.replaceChildren(root);
  const page={ctx,run,alive:()=>!disposed,reloadServices};
  function app(){return ctx.store.get().app || ctx.store.get().appState || {};}
  function isBusy(){return pending || loginBusy || Boolean(app().busy || ctx.store.get().busy);}
  function sync(){
    if(disposed)return;
    controls.disabled=isBusy();
    busyHint.replaceChildren();
    if(app().busy && !loginBusy) busyHint.append(alert({message:'Ứng dụng đang quét hoặc đăng nhập. Bạn có thể xem cấu hình; hãy chờ hoàn tất trước khi thay đổi.'}));
    busyHint.hidden=!busyHint.hasChildNodes();
    if(app().logging_in && !loginBusy){loginBusy=true;scheduleLogin();renderFacebook();controls.disabled=true;}
    if(!loginBusy && fbReady!==Boolean(app().guide?.fb_ready)){fbReady=Boolean(app().guide?.fb_ready);renderFacebook();}
  }
  async function run(control,errorArea,task){
    if(disposed || isBusy())return;
    pending=true;control.setLoading(true);errorArea.replaceChildren();sync();
    try {
      const result=await task();
      if(!disposed && result && !result.ok) errorArea.replaceChildren(alert({variant:'error',message:result.problems?.length?'Chưa lưu. Sửa các dòng sau:':result.error || 'Không thể hoàn tất thao tác.',list:result.problems || []}));
      return result;
    } catch {if(!disposed)errorArea.replaceChildren(alert({variant:'error',message:'Không thể hoàn tất thao tác. Kiểm tra kết nối và thử lại.'}));}
    finally{pending=false;control.setLoading(false);sync();}
  }
  async function reloadServices(){
    const result=await ctx.call('get_services');
    if(disposed)return;
    if(!result.ok){services.replaceChildren(alert({variant:'error',message:result.error}));return;}
    security.replaceChildren();
    if(!result.storage_secure)security.append(alert({variant:'warning',message:'Máy này chưa có kho lưu key an toàn. Hãy bật Windows Credential Manager trước khi lưu key.'}));
    security.hidden=!security.hasChildNodes();
    const first=result.services.find(s=>!s.configured)?.name;
    services.replaceChildren(...result.services.map(s=>serviceCard(s,result,page,s.name===first)));
  }
  async function loadChannels(){
    const result=await ctx.call('get_channels');
    if(disposed)return;
    if(!result.ok){channels.replaceChildren(alert({variant:'error',message:result.error}));return;}
    const field=textarea({label:'Danh sách link kênh',value:result.text,rows:8,placeholder:'https://www.facebook.com/ten-page'}), errors=el('div');
    field.classList.add('settings-channel-editor');
    const save=button({label:'Lưu danh sách kênh',variant:'primary',onClick:()=>run(save,errors,async()=>{
      const saved=await ctx.call('save_channels',field.value);
      if(saved.ok && !disposed){ctx.toast(saved.message,{variant:'success'});await ctx.refreshApp();await loadChannels();}
      return saved;
    })});
    const body=el('div','stack',el('p','hint','Mỗi dòng là link trang chính của một page (fanpage), ví dụ https://www.facebook.com/ten-page. Không hỗ trợ nhóm (group). Dòng bắt đầu bằng # là ghi chú.'));
    if(result.problems?.length)body.append(alert({variant:'warning',message:'Các link sau sẽ bị bỏ qua khi quét:',list:result.problems}));
    body.append(field,el('p','hint',`Đang lưu ${result.count} kênh.`),el('div','row',save),errors);
    channels.replaceChildren(card({title:'Kênh cần quét',body}));
  }
  function renderFacebook(){
    if(disposed)return;
    const errors=el('div'), body=el('div','stack',statusPill({label:fbReady?'Đã đăng nhập':'Chưa đăng nhập',state:fbReady?'success':'warning'}),el('p','hint','Dùng tài khoản Facebook phụ để app quét được video. Cửa sổ trình duyệt sẽ mở để bạn tự đăng nhập; phiên được lưu cho lần quét sau.'),el('p','hint','Không chia sẻ thư mục profile/ và file data/fb_cookies.txt: chúng chứa phiên đăng nhập Facebook của bạn.'));
    const login=button({label:fbReady?'Đăng nhập lại':'Đăng nhập Facebook',variant:fbReady?'secondary':'primary',onClick:()=>run(login,errors,async()=>{
      const result=await ctx.call('start_login');
      if(result.ok && !disposed){loginBusy=true;loginState=null;renderFacebook();scheduleLogin();await ctx.refreshApp();}
      return result;
    })});
    body.append(el('div','row',login));
    if(loginBusy)body.append(alert({message:'Đang chờ đăng nhập trong cửa sổ Facebook… Hoàn tất các bước xác minh nếu có.'}));
    if(loginState?.message)body.append(alert({variant:'error',message:loginState.message}));
    const cookie=button({label:'Chọn file cookie…',onClick:()=>run(cookie,errors,async()=>{
      const result=await ctx.call('pick_cookie_file_and_import');
      if(result.ok && !result.cancelled && !disposed){ctx.toast(result.message,{variant:'success'});await ctx.refreshApp();fbReady=Boolean(app().guide?.fb_ready);renderFacebook();}
      return result;
    })});
    body.append(expander({title:'Không đăng nhập được? Nạp file cookie',body:el('div','stack',el('p','hint','Đăng nhập tài khoản Facebook phụ trên trình duyệt, dùng Cookie-Editor để xuất cookie của facebook.com ra file JSON hoặc TXT rồi chọn file ở đây. Không chia sẻ file cookie cho người khác.'),el('div','row',cookie))}),errors);
    facebook.replaceChildren(card({title:'Đăng nhập Facebook',body}));
  }
  function scheduleLogin(){clearTimeout(loginTimer);if(!disposed)loginTimer=setTimeout(pollLogin,1000);}
  async function pollLogin(){
    if(disposed || loginPolling)return;
    loginPolling=true;
    try{
      const result=await ctx.call('get_login_state');
      if(disposed)return;
      if(!result.ok){loginState={message:result.error};renderFacebook();if(loginBusy)scheduleLogin();return;}
      loginState=result;loginBusy=Boolean(result.logging_in);fbReady=Boolean(result.fb_ready);
      renderFacebook();
      if(result.notice)ctx.toast(result.notice,{variant:'success'});
      if(loginBusy)scheduleLogin();
      else await ctx.refreshApp();
      sync();
    }finally{loginPolling=false;}
  }
  async function loadTaxonomy(){
    const result=await ctx.call('get_taxonomy');
    if(disposed)return;
    if(!result.ok){taxonomy.replaceChildren(alert({variant:'error',message:result.error}));return;}
    const wasOpen=taxonomy.querySelector('details')?.open || false;
    const tables={},errors=el('div'),body=el('div','stack',el('p','','Jev đọc caption và lời thoại, rồi chọn đúng 1 nhãn trong mỗi nhóm.'),el('ul','settings-intro',result.intro.map(text=>el('li','',text))),el('p','hint','Sửa trực tiếp trong bảng. Mỗi nhóm cần ít nhất 2 nhãn. Tránh tạo quá nhiều nhãn để dễ nhận ra xu hướng.'));
    for(const group of result.groups){
      const table=editableTable({columns:[{key:'name',label:'Tên hiển thị'},{key:'description',label:'Mô tả cho Jev'}],rows:group.rows});
      tables[group.id]=table;
      body.append(el('section','stack settings-taxonomy-group',el('h3','',group.title),el('p','hint',group.note),table,el('p','hint',`Nhãn luôn được giữ (không chỉnh sửa): ${group.fixed.join(', ')}`)));
    }
    const save=button({label:'Lưu nhãn',variant:'primary',onClick:()=>run(save,errors,async()=>{
      const saved=await ctx.call('save_taxonomy',Object.fromEntries(Object.entries(tables).map(([id,table])=>[id,table.getRows()])));
      if(saved.ok && !disposed){ctx.toast(saved.message,{variant:'success'});await loadTaxonomy();}
      return saved;
    })});
    const confirmed=checkbox({label:'Tôi xác nhận khôi phục nhãn mặc định',onChange:value=>{restore.disabled=!value;}});
    const restore=button({label:'Khôi phục nhãn mặc định',onClick:()=>{
      if(!confirmed.value)return;
      return run(restore,errors,async()=>{
        const result=await ctx.call('reset_taxonomy');
        if(result.ok && !disposed){ctx.toast(result.message,{variant:'success'});await loadTaxonomy();}
        return result;
      });
    }});
    restore.disabled=true;
    body.append(el('div','row',save),errors,el('div','stack settings-taxonomy-reset',confirmed,el('div','row',restore)));
    taxonomy.replaceChildren(expander({title:'Nhãn phân loại (Jev)',body,open:wasOpen}));
  }
  async function loadAll(){await Promise.all([reloadServices(),loadChannels(),loadTaxonomy()]);if(!disposed){renderFacebook();sync();}}
  services.append(spinner({label:'Đang tải cấu hình…'}));
  const unsubscribe=ctx.store.subscribe(sync);
  sync();loadAll();pollLogin();
  return ()=>{disposed=true;clearTimeout(loginTimer);unsubscribe();};
}
