"""Run with the project venv after caching frozen Nano x2 detections for Meet_WalkTogether2 here."""
import json
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pilot as p

name = 'Meet_WalkTogether2'
xml = p.ANNOTATIONS / 'mwt2gt.xml'
video = p.RAW / (name + '.mpg')
times = p.pts_times(str(video))
frames = list(range(0, len(times), 5))
from legacy_reader import ground_truth as historical_ground_truth
legacy, _ = historical_ground_truth(xml)
truth = {}
for frame in ET.parse(xml).getroot().findall('frame'):
    n = int(frame.get('number'))
    for obj in frame.findall('objectlist/object'):
        g = obj.get('id')
        if g not in legacy or n not in legacy[g]:
            continue
        x, y, w, h = (int(obj.find('box').get(k)) for k in ('xc', 'yc', 'w', 'h'))
        truth.setdefault(g, {})[n] = (x-w/2, y-h/2, x+w/2, y+h/2)
rows = json.loads((HERE/'detections_stride5_nano_576x768.json').read_text())[name]
settings = json.loads((HERE.parent/'results_heldout_nano_576x768.json').read_text())['frozen']
def stages(rows):
    bt = p.track(rows, **{k:settings[k] for k in ('activation','lost_s','matching')})
    stitched = p.stitch(bt,times,**{k:settings[k] for k in ('tau_s','base_px')})
    return bt,stitched,p.drop_static(stitched)
bt,st,final = stages(rows)
raw = {}
for n, boxes in rows.items():
    for i,b in enumerate(boxes):
        raw.setdefault(i,{})[int(n)] = b[:4]
def matches(gt, tracks, n):
    return {g:i for (g,_),i in p.frame_matches(gt,tracks,[n]).items()}
def oracle(gt):
    return stages({str(n):[[*b[n],0.95] for b in gt.values() if n in b] for n in frames})[-1]
for gt in [legacy,truth]:
    for title,tracks in [('Nano',final),('XML',oracle(gt))]:
        m=p.evaluate(gt,tracks,frames)[0]
        print(title,{k:m[k] for k in ('idtp','truth_detections','predicted_detections','idf1','id_switches')})
print('first changed',min((n,g) for g,b in truth.items() for n in b if n in frames and b[n]!=legacy[g][n]))
changed=sum(b[n]!=legacy[g][n] for g,b in truth.items() for n in b if n in frames)
print('changed boxes',changed)
ns=[0, *range(190,216,5)]
pixels=subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-vf','select='+'+'.join(f'eq(n\\,{n})' for n in ns),'-fps_mode','passthrough','-pix_fmt','rgb24','-f','rawvideo','-'])
for idx,n in enumerate(ns):
    im=Image.frombytes('RGB',(384,288),pixels[idx*331776:(idx+1)*331776])
    sheet=Image.new('RGB',(768,3*314))
    for j,(label,tracks) in enumerate([('Original XML <box>',truth),('Pilot XML reader',legacy),('Raw Nano / confidence',raw),('ByteTrack',bt),('After stitching',st),('After static removal',final)]):
        panel=im.copy(); draw=ImageDraw.Draw(panel)
        for key,boxes in tracks.items():
            if n not in boxes: continue
            box=boxes[n]; color='yellow' if j==2 else 'lime'
            draw.rectangle(box,outline=color)
            tag=f'{rows[str(n)][key][-1]:.2f}' if j==2 else str(key)
            draw.text((box[0],max(0,box[1]-11)),tag,fill=color,stroke_width=1,stroke_fill='black')
        x,y=(j%2)*384,(j//2)*314
        sheet.paste(panel,(x,y+26)); ImageDraw.Draw(sheet).text((x+3,y+5),f'{label} | frame {n} | PTS {times[n]:.4f} s',fill='white')
    sheet.save(HERE/f'frame_{n}.png')
    print(n,[(len(matches(truth,t,n)),len(matches(legacy,t,n))) for t in (raw,bt,st,final)])
    if n in (0,190,195):
        for g,b in truth.items():
            if n in b:
                print(g,[(round(max((p.iou(ref[g][n],s[n]) for s in tracks.values() if n in s),default=0),3)) for tracks in (raw,final) for ref in (truth,legacy)])
print('Whole clip, corrected XML: stage, frame matches, output boxes, IDTP (tracked stages only)')
for title, tracks in [('raw',raw),('ByteTrack',bt),('stitched',st),('final',final)]:
    print(title,sum(len(matches(truth,tracks,n)) for n in frames),sum(map(len,tracks.values())),None if title=='raw' else p.evaluate(truth,tracks,frames)[0]['idtp'])
print('XML ID 2: frame, best-overlap raw confidence')
for n in ns[1:]:
    print(n,max(rows[str(n)],key=lambda b:p.iou(truth['2'][n],b[:4]))[-1])
