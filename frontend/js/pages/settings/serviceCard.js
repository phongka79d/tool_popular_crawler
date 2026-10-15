import {el} from '../../components/dom.js';
import {button, textInput, select, toggle, alert, expander} from '../../components/index.js';

export function serviceCard(service, data, page, open) {
  const {ctx} = page;
  const name = service.name;
  const body = el('div', 'stack');
  const root = expander({title: service.configured ? `✓ ${service.label} · model ${service.model}` : `○ ${service.label} · chưa cấu hình`, body, open});
  root.classList.add('settings-service');
  body.append(el('p', '', service.role), el('p', 'hint', service.key_help));
  if (service.needs_model) body.append(alert({variant:'warning', message:'Đã có key nhưng còn thiếu model. Làm tiếp hai bước dưới đây.'}));
  body.append(el('h3', '', 'Bước 1 · Kết nối'));
  let models = [], modelField, languageField, autoField;
  let baseUrl = service.llm?.base_url || data.llm_providers[0]?.url || '';
  const stepTwo = el('div', 'stack'), errors = el('div');
  const invalidate = () => { models = []; stepTwo.replaceChildren(); errors.replaceChildren(); connect.classList.remove('secondary'); connect.classList.add('primary'); };
  if (name === 'llm') {
    const endpoint = textInput({label:'Địa chỉ endpoint', value:baseUrl, placeholder:'https://.../v1', hint:'Đường dẫn API tương thích OpenAI, thường kết thúc bằng /v1.', onChange:value=>{baseUrl=value.trim();invalidate();}});
    const endpointArea = el('div');
    const providers = select({label:'Nhà cung cấp', options:[...data.llm_providers.map(p=>p.label), data.custom_label], value:service.llm?.provider_label || data.llm_providers[0]?.label, onChange:drawEndpoint});
    function drawEndpoint() {
      const preset = data.llm_providers.find(p=>p.label===providers.value);
      if (preset) {baseUrl=preset.url;endpointArea.replaceChildren(el('p','hint',`Endpoint: ${baseUrl}`));}
      else {baseUrl=endpoint.value.trim();endpointArea.replaceChildren(endpoint);}
    }
    providers.input.addEventListener('change', invalidate);
    drawEndpoint();
    body.append(providers, endpointArea);
  }
  if (service.saved_mask) body.append(el('p', 'hint', `Đang lưu key: ${service.saved_mask}. Để trống ô dưới để kết nối bằng key này.`));
  const key = textInput({label:'API key', type:'password', placeholder:service.saved_mask ? 'Để trống để dùng key đã lưu' : 'Dán API key vào đây', onChange:invalidate});
  const connect = button({label:'Kết nối',variant:'primary',onClick:loadModels});
  body.append(key, el('div','row',connect), errors, el('p','hint','Bấm Kết nối để tải danh sách model. Chưa có gì được lưu cho đến bước 2.'), stepTwo);

  async function loadModels() {
    await page.run(connect, errors, async()=>{
      const result = await ctx.call('connect_service', name, key.value.trim(), name==='llm'?baseUrl:'');
      models = [];
      stepTwo.replaceChildren();
      if (!result.ok) return result;
      models = result.models || [];
      if (!models.length) return {ok:false,error:'Dịch vụ không trả về model nào. Kiểm tra lại key và endpoint.'};
      drawModels(result);
      connect.classList.remove('primary');connect.classList.add('secondary');
      return result;
    });
  }
  function drawModels(result) {
    const detail = el('p','hint'), languageArea = el('div','stack');
    modelField = select({label:name==='jev'?'Model Jev':name==='deepgram'?'Model Deepgram':'Model LLM', options:models, value:result.default_id || models[0].id, searchable:name==='llm', onChange:drawDetail});
    if (name==='deepgram') autoField = toggle({label:'Tự nhận biết tiếng Việt / tiếng Anh', checked:service.deepgram?.auto_language ?? true, hint:'Chọn tiếng Việt hoặc tiếng Anh cho từng video; khi độ tin cậy thấp, chép lại bằng tiếng Việt.', onChange:value=>{if(languageField)languageField.input.disabled=value;}});
    function drawDetail() {
      const chosen = models.find(m=>m.id===modelField.value);
      detail.textContent = chosen?.detail || (chosen?.architecture ? `Kiến trúc: ${chosen.architecture}` : '');
      if (name!=='deepgram') return;
      const languages = chosen?.languages || [];
      const previous = languageField?.value || result.default_language || service.deepgram?.language;
      const preferred = languages.some(l=>l.code===previous)?previous:languages.some(l=>l.code==='vi')?'vi':languages[0]?.code;
      languageField = select({label:'Ngôn ngữ thoại (khi tắt tự nhận biết)', options:languages.map(l=>({id:l.code,label:`${l.label} (${l.code})`})), value:preferred, disabled:autoField.value});
      languageArea.replaceChildren(autoField, languageField);
      if(!languages.length) languageArea.append(alert({variant:'error',message:'Model này không có ngôn ngữ nào. Hãy chọn model khác.'}));
    }
    const reload = button({label:'Tải lại danh sách',variant:'ghost',size:'small',onClick:loadModels});
    const save = button({label:'Kiểm tra và lưu',variant:'primary',onClick:async()=>{
      await page.run(save, errors, async()=>{
        const selection = {model:modelField.value};
        if(name==='deepgram') Object.assign(selection,{language:languageField.value,auto_language:autoField.value});
        if(name==='llm') selection.base_url=baseUrl;
        const saved=await ctx.call('save_service',name,key.value.trim(),selection);
        if(saved.ok && page.alive()) {key.value='';root.open=false;ctx.toast(saved.message,{variant:'success'});await ctx.refreshApp();await page.reloadServices();}
        return saved;
      });
    }});
    stepTwo.replaceChildren(el('h3','','Bước 2 · Chọn model'),el('div','row',el('p','hint',`Đã kết nối · ${models.length} model khả dụng.`),reload));
    if(name==='llm') stepTwo.append(el('p','hint','Một số nhà cung cấp liệt kê model mà không kiểm tra key. Key chỉ được xác nhận khi bấm Kiểm tra và lưu. Gõ tên model để lọc danh sách.'));
    stepTwo.append(modelField,detail,languageArea,el('div','row',save));
    drawDetail();
  }
  return root;
}
