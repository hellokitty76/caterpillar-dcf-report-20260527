#!/usr/bin/env python3
"""Render a proposal markdown file into a styled, print-ready HTML for Chromium->PDF."""
import sys, re, markdown

src, out_html, lang = sys.argv[1], sys.argv[2], sys.argv[3]  # lang: 'en' or 'zh'

with open(src, encoding="utf-8") as f:
    text = f.read()

# Split off the top title block (first H1 + H2 + the bold meta lines) to build a cover page.
lines = text.split("\n")

# Pull the leading blockquote "note to reader" out so we can style it distinctly; markdown handles it fine though.
body_md = text

html_body = markdown.markdown(
    body_md,
    extensions=["tables", "sane_lists", "attr_list", "nl2br"],
)

# Wrap the very first <h1> ... up to the first <hr /> as a cover section.
# Chromium print: we rely on CSS page breaks.
cover_split = html_body.split("<hr />", 1)
cover = cover_split[0]
rest = cover_split[1] if len(cover_split) > 1 else ""

font_sans = "'Noto Sans CJK SC', 'Noto Sans', 'Helvetica Neue', Arial, sans-serif" if lang == "zh" else "'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
font_serif = "'Noto Serif CJK SC', Georgia, serif" if lang == "zh" else "Georgia, 'Times New Roman', serif"

doc_label = "机密投资提案" if lang == "zh" else "CONFIDENTIAL INVESTMENT PROPOSAL"

html = f"""<!DOCTYPE html>
<html lang="{'zh-CN' if lang=='zh' else 'en'}">
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: A4;
    margin: 20mm 18mm 18mm 18mm;
    @bottom-center {{ content: counter(page); }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: {font_sans};
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1a1f2e;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  /* ---- Cover ---- */
  .cover {{
    height: 247mm;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 0 6mm;
    page-break-after: always;
    position: relative;
  }}
  .cover::before {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 8mm;
    background: linear-gradient(90deg,#0b3d2e 0%, #1f7a5c 55%, #d4a017 100%);
  }}
  .cover-kicker {{
    font-size: 9pt; letter-spacing: 3px; text-transform: uppercase;
    color: #1f7a5c; font-weight: 700; margin-bottom: 10mm;
  }}
  .cover h1 {{
    font-family: {font_serif};
    font-size: 30pt; line-height: 1.15; margin: 0 0 4mm 0; color: #0b3d2e;
    border: none; padding: 0;
  }}
  .cover h2 {{
    font-size: 13pt; font-weight: 500; color: #3a4256; margin: 0 0 14mm 0;
    border: none; padding: 0;
  }}
  .cover-meta {{ font-size: 10.5pt; line-height: 1.9; color: #2a3142; }}
  .cover-meta strong {{ color: #0b3d2e; }}
  .cover-foot {{
    position: absolute; bottom: 6mm; left: 6mm; right: 6mm;
    display: flex; justify-content: space-between;
    font-size: 8pt; letter-spacing: 1px; text-transform: uppercase; color: #8a93a6;
    border-top: 1px solid #d9dee8; padding-top: 3mm;
  }}
  /* ---- Body ---- */
  .content {{ }}
  h1 {{ font-family:{font_serif}; font-size: 17pt; color:#0b3d2e; margin: 12mm 0 3mm; padding-bottom: 2mm; border-bottom: 2px solid #1f7a5c; page-break-after: avoid; }}
  h2 {{ font-size: 12.5pt; color:#0b3d2e; margin: 7mm 0 2mm; page-break-after: avoid; }}
  h3 {{ font-size: 11pt; color:#1f7a5c; margin: 5mm 0 1.5mm; page-break-after: avoid; }}
  p {{ margin: 0 0 2.6mm; }}
  strong {{ color: #0b2e23; }}
  a {{ color: #1f7a5c; text-decoration: none; }}
  ul, ol {{ margin: 0 0 3mm; padding-left: 6mm; }}
  li {{ margin-bottom: 1.2mm; }}
  blockquote {{
    background: #f3f7f4; border-left: 3px solid #1f7a5c;
    margin: 3mm 0; padding: 3mm 5mm; font-size: 9.7pt; color: #35424e;
    page-break-inside: avoid;
  }}
  table {{
    width: 100%; border-collapse: collapse; margin: 3mm 0 5mm;
    font-size: 9pt; page-break-inside: avoid;
  }}
  th {{ background: #0b3d2e; color: #fff; text-align: left; padding: 2mm 2.5mm; font-weight: 600; }}
  td {{ padding: 2mm 2.5mm; border-bottom: 1px solid #dbe2ea; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f5f8f6; }}
  hr {{ border: none; border-top: 1px solid #e0e5ec; margin: 6mm 0; }}
  h1 + p, h2 + p {{ margin-top: 1mm; }}
</style>
</head>
<body>
  <section class="cover">
    <div class="cover-kicker">{doc_label}</div>
    {cover}
    <div class="cover-foot"><span>SIVEP · Horizon Capital &amp; Advisory · Kama &amp; Associés</span><span>{'严格保密' if lang=='zh' else 'Strictly Confidential'}</span></div>
  </section>
  <section class="content">
    {rest}
  </section>
</body>
</html>"""

with open(out_html, "w", encoding="utf-8") as f:
    f.write(html)
print(f"wrote {out_html}")
