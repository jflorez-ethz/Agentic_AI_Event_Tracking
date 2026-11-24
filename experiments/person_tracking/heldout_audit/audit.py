"""Re-score the frozen held-out caches. Run with the project virtual environment."""
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import linear_sum_assignment

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pilot as p
from meet2_audit.legacy_reader import ground_truth as legacy_reader

manifest = json.loads((p.HERE/'results_heldout_nano_576x768.json').read_text())
params = manifest['frozen']
clips = [('Walk1','wk1gt.xml'), ('LeftBag_BehindChair','lbbcgt.xml'), ('Meet_WalkTogether2','mwt2gt.xml')]


def spatial(gt, tracks, frames):
    matched = set()
    for n in frames:
        ids = [g for g,b in gt.items() if n in b]
        boxes = [b[n] for b in tracks.values() if n in b]
        if not boxes or not ids:
            continue
        iou = np.array([[p.iou(gt[g][n], b) for b in boxes] for g in ids])
        weights = (iou >= 0.5) * (min(iou.shape)+1+iou)
        for i,j in zip(*linear_sum_assignment(-weights)):
            if weights[i,j]:
                matched.add((ids[i],n))
    return matched


def stages(rows, times):
    bt = p.track(rows, **{k:params[k] for k in ('activation','lost_s','matching')})
    stitched = p.stitch(bt,times,**{k:params[k] for k in ('tau_s','base_px')})
    return bt, stitched, p.drop_static(stitched)


def identity(gt, tracks, frames):
    m = p.evaluate(gt,tracks,frames)[0]
    tp = int(m['idtp'])
    return dict(idtp=tp,idfp=m['predicted_detections']-tp,idfn=m['truth_detections']-tp,
                idf1=m['idf1'],switches=m['id_switches'])


def area(box):
    return (box[2]-box[0])*(box[3]-box[1])


def exhibit(name,video,xml,gt,old,n,g,pts):
    pixel = subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-vf',f'select=eq(n\\,{n})',
                                     '-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
    im = Image.frombytes('RGB',(384,288),pixel)
    sheet = Image.new('RGB',(768,315))
    for i,(title,ref) in enumerate([('Historical',old),('Direct box',gt)]):
        panel = im.copy()
        draw = ImageDraw.Draw(panel)
        draw.rectangle(ref[g][n],outline='yellow',width=2)
        sheet.paste(panel,(384*i,27))
        ImageDraw.Draw(sheet).text((384*i+3,4),f'{title} | XML {g} | frame {n} | {pts:.4f} s')
    sheet.save(HERE/f'{name}.png')
    obj=ET.parse(xml).find(f'.//frame[@number="{n}"]/objectlist/object[@id="{g}"]/box')
    return dict(frame=n,pts=pts,xml_id=g,box=obj.attrib,legacy=old[g][n],corrected=gt[g][n])


def audit(name,xmlname):
    video, xml = p.RAW/(name+'.mpg'), p.ANNOTATIONS/xmlname
    for path in (video,xml):
        assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['inputs'][path.name]['sha256']
    old,ob = legacy_reader(xml)
    gt,bag = p.ground_truth(xml)
    assert {g:set(b) for g,b in old.items()}=={g:set(b) for g,b in gt.items()} and set(ob)==set(bag)
    times=p.pts_times(str(video))
    frames=list(range(0,len(times),5))
    source=HERE if name!='Meet_WalkTogether2' else p.HERE/'meet2_audit'
    cache=json.loads((source/'detections_stride5_nano_576x768.json').read_text())[name]
    historical=next(r for r in manifest['rows'] if r['video']==name)
    assert len(times)==historical['frame_count'] and set(map(int,cache))==set(frames)
    bt,st,final=stages(cache,times)
    labels=p.label(final)
    summary={labels[t]:dict(first_s=round(times[min(b)],2),last_s=round(times[max(b)],2),detections=len(b)) for t,b in final.items()}
    assert summary==historical['tracks'] and p.evaluate(old,final,frames)[0]==historical['metrics']
    def oracle(ref):
        inputs={str(n):[[*b[n],0.95] for b in ref.values() if n in b] for n in frames}
        return identity(ref,stages(inputs,times)[-1],frames)
    old_oracle=oracle(old)
    changed=[(n,g) for g,b in gt.items() for n in b if b[n]!=old[g][n]]
    sampled=[(n,g) for n,g in changed if n%5==0]
    raw={}
    for n,rows in cache.items():
        for i,b in enumerate(rows):
            raw.setdefault(i,{})[int(n)]=b[:4]
    counts={}
    prev=set()
    for title,tracks in [('raw',raw),('byte',bt),('stitch',st),('final',final)]:
        matches=spatial(gt,tracks,frames)
        counts[title]=dict(matches=len(matches),boxes=sum(map(len,tracks.values())),lost=len(prev-matches),
                           gained=len(matches-prev),idtp=None if title=='raw' else identity(gt,tracks,frames)['idtp'])
        prev=matches
    audited=dict(reference=sum(map(len,gt.values())),changed=len(changed),sampled_changed=len(sampled),
                 scored=historical['metrics']['truth_detections'],object_boxes=len(bag),
                 changed_objects=sum(ob[n]!=b for n,b in bag.items()), frame_count=len(times),stages=counts,
                 nano_old=identity(old,final,frames),nano=identity(gt,final,frames),
                 oracle_old=old_oracle,oracle=oracle(gt) if sampled else old_oracle)
    tp=counts['raw']['matches']
    audited['detection']=dict(tp=tp,fp=counts['raw']['boxes']-tp,fn=audited['scored']-tp,
                              precision=tp/counts['raw']['boxes'],recall=tp/audited['scored'])
    if name!='Meet_WalkTogether2':
        # Earliest changed scored box with a visible displacement, or largest scored box for a legible agreement check.
        candidates=sampled or [(n,g) for g,b in gt.items() for n in b if n%5==0]
        n,g=min(candidates) if sampled else max(candidates, key=lambda pair: area(gt[pair[1]][pair[0]]))
        audited['exhibit']=exhibit(name,video,xml,gt,old,n,g,times[n])
    return audited


if __name__=='__main__':
    results={name:audit(name,x) for name,x in clips}
    totals={}
    for variant in ('nano_old','nano','oracle_old','oracle'):
        v={k:sum(r[variant][k] for r in results.values()) for k in ('idtp','idfp','idfn')}
        v['idf1']=2*v['idtp']/(2*v['idtp']+v['idfp']+v['idfn'])
        totals[variant]=v
    det={k:sum(r['detection'][k] for r in results.values()) for k in ('tp','fp','fn')}
    totals['detection']=dict(**det,precision=det['tp']/(det['tp']+det['fp']),recall=det['tp']/(det['tp']+det['fn']))
    (HERE/'counts.json').write_text(json.dumps(dict(clips=results,pooled=totals),indent=2)+'\n')
