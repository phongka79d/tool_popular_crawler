"""Capture the local, synthetic UI only; never enter real credentials.
Run: .venv/Scripts/python tools/make_guide_images.py
The existing static server must serve frontend/ on port 8765.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'img'
URL = 'http://127.0.0.1:8765/index.html?mock=1'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 1280, 'height': 860}, device_scale_factor=1.5, color_scheme='light')
        page = context.new_page()
        page.clock.install()
        page.add_init_script('localStorage.clear()')

        def load(fresh=False):
            page.goto(URL + ('&mockFresh=1' if fresh else ''), wait_until='networkidle')
            page.wait_for_timeout(700)

        def text(value):
            return page.get_by_text(value, exact=True).first

        def button(value):
            return page.get_by_role('button', name=value, exact=True)

        def card(title):
            return text(title).locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " card ")][1]')

        def shot(name, targets, region=None, viewport=False):
            # ISO timestamps avoid unit ambiguity; pause polling only for the capture.
            page.clock.pause_at(page.evaluate('new Date(Date.now()+100).toISOString()'))
            page.locator('#guide-annotations').evaluate_all('(nodes)=>nodes.forEach(n=>n.remove())')
            page.locator('.toast').evaluate_all('(nodes)=>nodes.forEach(n=>n.close())')
            if viewport:
                page.evaluate('window.scrollTo(0,0)')
            else:
                (region or targets[0]).evaluate('(e)=>e.scrollIntoView({block:\"center\",behavior:\"instant\"})')
            boxes = [target.bounding_box() for target in targets]
            if any(box is None for box in boxes):
                raise RuntimeError(f'Invisible annotation target: {name}')
            page.evaluate('''boxes => {
              const layer=document.createElement('div'); layer.id='guide-annotations';
              layer.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:2147483647';
              boxes.forEach((b,i)=>{const r=document.createElement('div');
                r.style.cssText=`position:absolute;left:${b.x+scrollX-4}px;top:${b.y+scrollY-4}px;width:${b.width+8}px;height:${b.height+8}px;border:3px solid #ff4b4b;border-radius:9px;box-sizing:border-box`;
                const n=document.createElement('span');n.textContent=i+1;
                n.style.cssText='position:absolute;left:-17px;top:-16px;min-width:25px;height:25px;padding:0 3px;border-radius:50%;background:#ff4b4b;color:white;font:bold 17px/25px Segoe UI;text-align:center;box-shadow:0 0 0 2px white';
                r.append(n);layer.append(r);});document.body.append(layer);
            }''', boxes)
            options = {}
            if not viewport:
                b = region.bounding_box() if region else {
                    'x': min(v['x'] for v in boxes), 'y': min(v['y'] for v in boxes),
                    'width': max(v['x']+v['width'] for v in boxes)-min(v['x'] for v in boxes),
                    'height': max(v['y']+v['height'] for v in boxes)-min(v['y'] for v in boxes)}
                dims = page.evaluate('({w:document.documentElement.scrollWidth,h:document.documentElement.scrollHeight,x:scrollX,y:scrollY})')
                x, y = max(0, b['x'] + dims['x'] - 22), max(0, b['y'] + dims['y'] - 22)
                options['clip'] = {'x': x, 'y': y, 'width': min(b['width']+44, dims['w']-x), 'height': min(b['height']+44, dims['h']-y)}
                options['full_page'] = True
            page.screenshot(path=str(OUT / (name+'.png')), **options)
            page.locator('#guide-annotations').evaluate('(e)=>e.remove()')
            page.clock.resume()
            print(name)

        load()
        shot('01-tong-quan', [page.locator('.app-header'), page.locator('[role=tablist]'), page.get_by_text('Việc tiếp theo:', exact=False).first], viewport=True)
        load(True)
        shot('02-lan-dau', [page.locator('.settings-welcome'), button('Bắt đầu thiết lập')], page.locator('.settings-welcome'))
        button('Bắt đầu thiết lập').click()
        jev = page.locator('.settings-service').filter(has=page.locator('summary').filter(has_text='Jev')).first
        if not jev.evaluate('(e)=>e.open'):
            jev.locator('summary').click()
        page.locator('.settings-service').nth(1).evaluate('(e)=>e.open=false')
        shot('03-dich-vu-mo', [jev.locator('summary'), jev.get_by_label('API key'), jev.get_by_role('button', name='Kết nối', exact=True)], jev)
        jev.locator('summary').click()
        shot('04-dich-vu-thu-gon', [page.locator('.settings-service').nth(i).locator('summary') for i in range(3)], page.locator('.settings-controls > section').first)
        jev.locator('summary').click()
        jev.get_by_label('API key').fill('DEMO-ONLY-NOT-A-REAL-KEY')
        shot('05-dan-key', [jev.get_by_label('API key'), jev.get_by_role('button', name='Kết nối', exact=True)], jev)
        jev.get_by_role('button', name='Kết nối', exact=True).click()
        jev.get_by_role('button', name='Kiểm tra và lưu', exact=True).wait_for()
        shot('06-model-de-xuat', [jev.locator('.settings-model-summary'), jev.get_by_text('Nâng cao · chọn model khác', exact=True), jev.get_by_role('button', name='Kiểm tra và lưu')], jev.get_by_text('Bước 2 · Kiểm tra và lưu', exact=True).locator('xpath=parent::*'))
        jev.get_by_role('button', name='Kiểm tra và lưu').click()
        page.wait_for_timeout(1500)
        deep = page.locator('.settings-service').nth(1)
        if not deep.evaluate('(e)=>e.open'):
            deep.locator('summary').click()
        deep.get_by_label('API key').fill('DEMO-ONLY-NOT-A-REAL-KEY')
        deep.get_by_role('button', name='Kết nối', exact=True).click()
        deep.get_by_text('Nâng cao · model và ngôn ngữ', exact=True).click()
        shot('07-deepgram-nang-cao', [deep.locator('.settings-model-summary'), deep.get_by_text('Tự nhận biết tiếng Việt / tiếng Anh', exact=True)], deep.get_by_text('Bước 2 · Kiểm tra và lưu', exact=True).locator('xpath=parent::*'))
        deep.get_by_role('button', name='Kiểm tra và lưu').click()
        page.wait_for_timeout(1500)
        llm = page.locator('.settings-service').nth(2)
        if not llm.evaluate('(e)=>e.open'):
            llm.locator('summary').click()
        shot('08-nha-cung-cap', [llm.get_by_label('Nhà cung cấp'), llm.get_by_label('API key')], llm)
        load(True)
        button('Bắt đầu thiết lập').click()
        shot('09-danh-sach-kenh', [page.get_by_label('Danh sách link kênh'), button('Lưu danh sách kênh')], card('Kênh cần quét'))
        text('Không đăng nhập được? Nạp file cookie').click()
        shot('10-facebook-cookie', [button('Đăng nhập Facebook'), text('Không đăng nhập được? Nạp file cookie'), button('Chọn file cookie…')], card('Đăng nhập Facebook'))
        text('Nhãn phân loại (Jev)').click()
        taxonomy = text('Nhãn phân loại (Jev)').locator('xpath=parent::*')
        shot('11-nhan-phan-loai', [text('Nhãn phân loại (Jev)'), taxonomy.locator('.settings-taxonomy-group').first])
        load()
        page.get_by_role('tab', name='Chạy quét', exact=True).click()
        button('Bắt đầu quét').wait_for()
        page.wait_for_timeout(900)
        shot('12-tuy-chon-quet', [text('Nội dung đăng trong').locator('xpath=parent::*'), text('Loại quét').locator('xpath=parent::*'), page.locator('.scan-kind-grid'), page.locator('.scan-length').first], card('Nội dung nào được quét?'))
        page.get_by_label('Lượt xem so với follower (×)', exact=True).fill('5')
        page.get_by_label('Lượt xem so với follower (×)', exact=True).blur()
        page.wait_for_timeout(650)
        shot('13-nguong-loc', [page.get_by_label('Lượt xem tối thiểu', exact=True), page.get_by_label('Lượt xem so với follower (×)', exact=True), page.locator('.scan-summary')], card('Ngưỡng lọc'))
        shot('14-bat-dau', [page.locator('.scan-key').first.locator('xpath=parent::*'), page.locator('.scan-terms'), button('Bắt đầu quét')])
        page.get_by_label('Tôi đã đọc và tự chịu trách nhiệm', exact=True).check()
        page.wait_for_timeout(650)
        button('Bắt đầu quét').click()
        page.wait_for_timeout(4000)
        shot('15-dang-quet', [page.get_by_text('Tiến độ tổng (ước tính)', exact=False).first, card('Tiến độ từng kênh'), button('Dừng quét')])
        text('Cần bạn chọn để tiếp tục').wait_for(timeout=30000)
        shot('16-cau-hoi', [text('Cần bạn chọn để tiếp tục'), button('Tiếp tục quét'), button('Bỏ qua kênh này')], card('Cần bạn chọn để tiếp tục'))
        button('Tiếp tục quét').click()
        page.wait_for_timeout(5000)
        shot('17-su-dung-ai', [text('Sử dụng dịch vụ'), page.locator('.scan-usage-grid')], text('Sử dụng dịch vụ').locator('xpath=parent::*'))
        shot('18-dien-bien', [card('Diễn biến gần nhất'), page.locator('summary').filter(has_text='Toàn bộ diễn biến lần quét')])
        button('Quét lần mới').wait_for(timeout=45000)
        shot('19-hoan-tat', [button('Mở file Excel'), button('Lưu bản sao…'), button('Xem trong Kết quả')], viewport=True)
        button('Xem trong Kết quả').click()
        text('Tổng quan kết quả').wait_for()
        page.wait_for_timeout(800)
        shot('20-ket-qua', [page.get_by_label('Xem thống kê file'), text('Tổng quan kết quả')], viewport=True)
        shot('21-bieu-do', [text('Biểu đồ kết quả')], text('Biểu đồ kết quả').locator('xpath=parent::*'))
        shot('22-file-excel', [page.locator('.results-file').first], page.locator('.results-files'))
        button('Nhật ký').click()
        page.get_by_role('dialog').wait_for()
        shot('23-nhat-ky', [page.get_by_role('dialog')], page.get_by_role('dialog'))
        browser.close()


if __name__ == '__main__':
    main()
