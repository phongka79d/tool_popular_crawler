"""Render the illustrated Vietnamese guide without installing dependencies.
Run: .venv/Scripts/python tools/make_guide_pdf.py
"""
import html
import importlib.util
from pathlib import Path
import re
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def inline(text):
    tokens = []

    def keep(value):
        tokens.append(value)
        return f'\x00{len(tokens)-1}\x00'

    text = re.sub(r'`([^`]+)`', lambda m: keep('<code>'+html.escape(m[1])+'</code>'), text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: keep('<a href="'+html.escape(m[2], quote=True)+'">'+inline(m[1])+'</a>'), text)
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'\x00(\d+)\x00', lambda m: tokens[int(m[1])], text)


def minimal_markdown(source):
    """Support exactly the headings, lists, paragraphs, tables and figures in this guide."""
    lines = source.splitlines()
    output = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        heading = re.match(r'^(#{1,6}) (.+)$', line)
        image = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        if heading:
            level = len(heading[1])
            output.append(f'<h{level}>{inline(heading[2])}</h{level}>')
        elif image:
            caption = ''
            if i+2 < len(lines) and lines[i+2].startswith('①'):
                caption = '<figcaption>'+inline(lines[i+2])+'</figcaption>'
                i += 2
            output.append('<figure><img alt="'+html.escape(image[1], quote=True)+'" src="'+html.escape(image[2], quote=True)+'">'+caption+'</figure>')
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in row):
                    rows.append(row)
                i += 1
            output.append('<table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>' for row in rows[1:])+'</tbody></table>')
            continue
        elif re.match(r'^(?:- |\d+\. )', line):
            ordered = bool(re.match(r'^\d+\. ', line))
            tag = 'ol' if ordered else 'ul'
            items = []
            pattern = r'^\d+\. ' if ordered else r'^- '
            while i < len(lines) and re.match(pattern, lines[i].strip()):
                items.append('<li>'+inline(re.sub(pattern, '', lines[i].strip()))+'</li>')
                i += 1
            output.append(f'<{tag}>'+''.join(items)+f'</{tag}>')
            continue
        else:
            paragraph = [line]
            while i+1 < len(lines) and lines[i+1].strip() and not re.match(r'^(?:#|!\[|\||- |\d+\. )', lines[i+1]):
                i += 1
                paragraph.append(lines[i].strip())
            output.append('<p>'+inline(' '.join(paragraph))+'</p>')
        i += 1
    return '\n'.join(output)


def main():
    source = (DOCS / 'HUONG-DAN.md').read_text(encoding='utf-8')
    if importlib.util.find_spec('markdown'):
        import markdown
        body = markdown.markdown(source, extensions=['tables'])
    else:
        body = minimal_markdown(source)
    entries = []
    counter = 0

    def heading(match):
        nonlocal counter
        counter += 1
        level, title = match[1], match[2]
        anchor = f'section-{counter}'
        entries.append(f'<li class="level-{level}"><a href="#{anchor}">{title}</a></li>')
        return f'<h{level} id="{anchor}">{title}</h{level}>'

    body = re.sub(r'<h([23])>(.*?)</h\1>', heading, body)
    toc = '<nav class="toc"><h1>Mục lục</h1><p>Video Công Thức · Hướng dẫn sử dụng có ảnh</p><ul>'+''.join(entries)+'</ul></nav>'
    document = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Video Công Thức — Hướng dẫn</title><style>
      @page {size:A4;margin:16mm 16mm 19mm}
      * {box-sizing:border-box} body {font:10.5pt/1.53 "Segoe UI",Arial,sans-serif;color:#202733;margin:0}
      h1 {font-size:24pt;line-height:1.2;color:#162737;margin:0 0 8mm}
      h2 {break-before:page;font-size:19pt;line-height:1.25;color:#162737;margin:0 0 6mm;border-bottom:2px solid #ff4b4b;padding-bottom:3mm}
      h3 {font-size:13pt;margin:6mm 0 2mm;break-after:avoid}
      p {margin:2mm 0 3mm} li {margin:1.5mm 0} ul,ol {padding-left:6mm}
      a {color:#12618b;overflow-wrap:anywhere;text-decoration:none}
      code {font:9.4pt Consolas,monospace;background:#f0f2f5;padding:0 1mm;overflow-wrap:anywhere}
      table {border-collapse:collapse;width:100%;font-size:9.1pt;margin:4mm 0;table-layout:fixed}
      th,td {border:1px solid #ccd2da;padding:2mm;vertical-align:top;overflow-wrap:anywhere}
      th {background:#f0f2f6;text-align:left} tr {break-inside:avoid} thead {display:table-header-group}
      figure {margin:4mm 0 5mm;break-inside:avoid} img {display:block;max-width:100%;max-height:216mm;object-fit:contain;margin:auto;border:1px solid #e0e3e8}
      figcaption {font-size:9pt;color:#4b5563;margin-top:2mm}
      .toc {break-after:page} .toc ul {list-style:none;padding:0}.toc li {margin:1mm 0}.toc .level-2 {font-weight:700;margin-top:3mm}.toc .level-3 {padding-left:5mm;font-size:9.7pt}
    </style>'''+toc+body+'</html>'
    # Keep the intermediate HTML next to the Markdown so file:// image URLs resolve.
    temporary = tempfile.NamedTemporaryFile(mode='w', suffix='.html', prefix='.guide-', dir=DOCS, encoding='utf-8', delete=False)
    path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(document)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(path.as_uri(), wait_until='networkidle')
            page.evaluate('document.fonts.ready')
            missing = page.locator('img').evaluate_all('(images)=>images.filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src)')
            if missing:
                raise RuntimeError('Missing images: '+', '.join(missing))
            page.pdf(path=str(DOCS / 'HUONG-DAN.pdf'), format='A4', print_background=True, display_header_footer=True, header_template='<span></span>', footer_template='<div style="font:9px Segoe UI;width:100%;text-align:center;color:#657080">Video Công Thức · <span class="pageNumber"></span> / <span class="totalPages"></span></div>', prefer_css_page_size=True)
            browser.close()
    finally:
        path.unlink(missing_ok=True)
    pdf = DOCS / 'HUONG-DAN.pdf'
    data = pdf.read_bytes()
    pages = len(re.findall(rb'/Type\s*/Page\b', data))
    print(f'{pdf.name}: {pages} pages, {len(data):,} bytes')


if __name__ == '__main__':
    main()
