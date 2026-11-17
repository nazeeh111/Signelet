"""Draw the recorded two-note example. Python standard library only.

Run from any directory: python docs/assets/build-annotation-transfer.py
This writes editable SVG and standalone HTML. Capture the SVG with a browser for PNG.
"""
import json
from pathlib import Path
from xml.sax.saxutils import escape

HERE=Path(__file__).resolve().parent
d=json.loads((HERE.parent/'examples/repeated-transfer.json').read_text())
assert d['original']=='The very blue boat.' and d['edited']=='The very very blue boat.'
assert d['before_choice']['boat']['target']==[19,23]
assert d['before_choice']['very']['first_character_candidates']==[4,9]
assert [(x['note'],x['start'],x['end'],x['text']) for x in d['reopened_native']]==[('very',9,13,'very'),('boat',19,23,'boat')]
parts=['''<svg xmlns="http://www.w3.org/2000/svg" width="840" height="960" viewBox="0 0 840 960" role="img" aria-labelledby="transfer-title transfer-desc">
<title id="transfer-title">Signelet: one edit, two annotation outcomes</title>
<desc id="transfer-desc">Inserting a second very carries boat from offsets 14–18 to 19–23, while very remains under review until a reviewer assumes character 4 maps to 9.</desc>
<style>text{font-family:Arial,Helvetica,sans-serif;fill:#20282e}.mono{font-family:'Courier New',Courier,monospace}.muted{fill:#4d5a64}.blue{fill:#245c8b}.amber{fill:#80520b}</style>
<rect width="840" height="960" fill="#fffdf8"/>
<path d="M48 48H60V92H48M88 48H76V92H88" fill="none" stroke="#245c8b" stroke-width="4"/>
<path d="M60 80L76 60" stroke="#245c8b" stroke-width="4"/>
''']
def text(x,y,value,size=28,cls='',weight='400'):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" class="{cls}">{escape(value)}</text>')
def rect(x,y,w,h,fill):parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
text(108,80,'Signelet',40,weight='700')
text(48,148,'One edit. Two decisions.',44,weight='700')
text(48,192,'Annotations across text revisions',28,'muted')
parts.append('<path d="M48 220H792" stroke="#cdd3d5"/>')
text(48,268,'Original',28,'muted')
# Courier New at 36px has a 21.6035px advance in the validated Chrome capture.
advance=21.603515625;x=48
rect(x+14*advance,287,4*advance,44,'#dcebf4')
text(x,322,d['original'],36,'mono')
text(48,388,'Edited',28,'muted')
rect(x+4*advance,407,4*advance,44,'#f8e6bf');rect(x+9*advance,407,4*advance,44,'#f8e6bf')
rect(x+19*advance,407,4*advance,44,'#dcebf4')
text(x,442,d['edited'],36,'mono')
text(48,490,'Same words; different certainty.',28,'muted')
parts.append('<path d="M48 522H792" stroke="#cdd3d5"/>')
rect(48,558,6,112,'#245c8b')
text(76,586,'boat  ·  carried',34,'blue','700')
text(76,630,'[14,18) → [19,23)',32,'mono')
text(76,668,'Exact span and note data retained.',28,'muted')
rect(48,710,6,156,'#80520b')
text(76,738,'very  ·  held for review',34,'amber','700')
text(76,782,'First character: 4 → 4 or 9',32,'mono')
text(76,824,'No destination chosen automatically.',28,'muted')
text(76,866,'Pin 4 → 9, recompute: [9,13)',28,'mono')
parts.append('<path d="M48 900H792" stroke="#cdd3d5"/>')
text(48,940,'Recorded example · Unicode offsets · conditional pins',26,'muted')
parts.append('</svg>');svg='\n'.join(parts)+'\n'
(HERE/'annotation-transfer.svg').write_text(svg)
(HERE/'annotation-transfer.html').write_text('<!doctype html>\n<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Signelet annotation transfer</title><style>body{margin:0;background:#fffdf8}main{max-width:840px;margin:auto}svg{display:block;width:100%;height:auto}</style><main>'+svg+'</main></html>\n')
print('Wrote annotation-transfer.svg and annotation-transfer.html')
