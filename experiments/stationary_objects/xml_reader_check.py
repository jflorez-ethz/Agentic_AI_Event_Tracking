"""Re-run stationary trial 1 'XML (perfect)' person filter with boxes read from the direct <box> element."""
import sys, json, xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot as S
from videos import RAW, ANNOTATIONS, VIDEOS
def persons_correct(xml):
    out = {}
    for f in ET.parse(xml).getroot().findall('frame'):
        n = int(f.attrib['number'])
        for o in f.findall('objectlist/object'):
            if 'object' in (o.findtext('.//role') or ''): continue
            b = {k: int(o.find('box').attrib[k]) for k in ('xc', 'yc', 'w', 'h')}
            out.setdefault(n, []).append((b['xc']-b['w']/2, b['yc']-b['h']/2, b['xc']+b['w']/2, b['yc']+b['h']/2))
    return out
hist = json.load(open(S.HERE / 'results.json'))
fz = hist['frozen']
for name, video, xml in VIDEOS:
    if name not in ('TwoEnterShop1front', 'Meet_WalkSplit'): continue
    times = S.pts_times(str(RAW / video)); events, old = S.truth(ANNOTATIONS / xml, times); new = persons_correct(ANNOTATIONS / xml)
    assert set(old) == set(new)
    for stride in (1, 5):
        c, _ = S.detect(str(RAW / video), times, stride=stride, static_s=fz['static_s'], min_area=fz['min_area'], person_boxes=lambda n: new.get(n, []))
        found, false = S.match(c, events)
        h = next(v for v in hist['runs'][f'persons=xml,fps={25 if stride == 1 else 5}']['videos'] if v['video'] == name)
        print(name, 'fps', 25 if stride == 1 else 5, 'fausses alertes corrigé', len(false), 'historique', len(h['false_alarms']),
              [(round(x['t'], 1), [round(v) for v in x['xy']]) for x in false], flush=True)
