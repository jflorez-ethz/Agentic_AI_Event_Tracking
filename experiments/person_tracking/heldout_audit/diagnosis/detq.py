"""Detection quality vs XML (corrected reader), per scored frame (stride 5). Flags fixed before reading results:
small: sqrt(area) < 22 px; edge: box within 8 px of image border; posture: CAVIAR movement tag (walking/running vs active vs inactive);
side_by_side: another XML person with IoU > 0 or centre distance < 0.75 * mean width; furniture: >=30% of the XML box covered by a
static detection (a box repeated at IoU >= 0.6 on >= 30% of the clip's frames, and not matching an XML person at IoU >= 0.3 on most of them)."""
from common import *
import xml.etree.ElementTree as ET
from scipy.optimize import linear_sum_assignment as lsa
def movement(x):
    m = {}
    for f in ET.parse(x).getroot().findall('frame'):
        n = int(f.attrib['number'])
        for o in f.findall('objectlist/object'):
            m[(o.attrib['id'], n)] = (o.findtext('.//movement') or '').strip()
    return m
def match(G, D, thr):
    if not len(G) or not len(D): return {}
    M = iou_mat(G, D); w = (M >= thr) * (2 + M)
    return {i: (j, M[i, j]) for i, j in zip(*lsa(-w)) if w[i, j]}
def static_boxes(det, gt):
    frames = sorted(map(int, det)); allb = [(n, b) for n in frames for b in det[str(n)] if b[4] >= 0.2]
    out = []
    for n, b in allb:
        hits = sum(1 for m in frames if det[str(m)] and iou_mat([b[:4]], [d[:4] for d in det[str(m)]]).max() >= 0.6)
        if hits >= 0.3 * len(frames):
            G = [gt[g][m] for g in gt for m in [n] if m in gt[g]]
            if not G or iou_mat([b[:4]], G).max() < 0.3: out.append(b[:4])
    return out
R = {}
for name, xml in CLIPS:
    video, x, gt, det = load(name, xml); mv = movement(x)
    stat = static_boxes(det, gt)
    rows = []; fps = []
    for n in sorted(map(int, det)):
        ids = [g for g in gt if n in gt[g]]; G = np.array([gt[g][n] for g in ids]).reshape(-1, 4)
        D01 = [b for b in det[str(n)]]; D04 = [b for b in D01 if b[4] >= 0.4]
        res = {}
        for c, D in (('c01', D01), ('c04', D04)):
            Dx = np.array([b[:4] for b in D]).reshape(-1, 4)
            for t in (0.3, 0.5):
                m = match(G, Dx, t); res[(c, t)] = m
                if t == 0.5:
                    used = {j for j, _ in m.values()}
                    for j, b in enumerate(D):
                        if j in used: continue
                        if any(iou_mat([b[:4]], [s])[0, 0] >= 0.6 for s in stat): k = 'static (meuble/plante/objet)'
                        elif len(G) and iou_mat([b[:4]], G).max() >= 0.1: k = 'sur une personne (mal localisé/doublon)'
                        else: k = 'autre'
                        fps.append((c, k))
        for i, g in enumerate(ids):
            b = G[i]; w, h = b[2] - b[0], b[3] - b[1]
            others = [G[k] for k in range(len(ids)) if k != i]
            side = any(iou_mat([b], [o])[0, 0] > 0 or np.hypot(*np.subtract(p.center(b), p.center(o))) < 0.75 * (w + o[2] - o[0]) / 2 for o in others)
            cover = max([max(0, min(b[2], s[2]) - max(b[0], s[0])) * max(0, min(b[3], s[3]) - max(b[1], s[1])) / max(w * h, 1) for s in stat] or [0])
            best = iou_mat([b], [d[:4] for d in D01]).max() if D01 else 0.0
            mvt = mv.get((g, n), '')
            rows.append(dict(id=g, n=n, small=np.sqrt(w * h) < 22, edge=min(b[0], b[1], W - b[2], H - b[3]) < 8,
                             posture='marche' if mvt in ('walking', 'running') else ('active (sur place)' if mvt == 'active' else ('inactive' if mvt == 'inactive' else 'autre')),
                             side=side, furniture=cover >= 0.3, best=best,
                             **{f'{c}_{t}': i in res[(c, t)] for c in ('c01', 'c04') for t in (0.3, 0.5)}))
    R[name] = (rows, fps, stat)
def pr(rows, fps_n, c, t):
    tp = sum(r[f'{c}_{t}'] for r in rows); return tp
print('=== Precision / rappel (appariement 1-1 par trame) ===')
for c, cn in (('c01', 'conf>=0.1 (cache brut)'), ('c04', 'conf>=0.4 (seuil d’activation ByteTrack)')):
    for t in (0.3, 0.5):
        line = []
        TP = NP = NG = 0
        for name, xml in CLIPS:
            rows = R[name][0]; video, x, gt, det = load(name, xml)
            npred = sum(1 for n in det for b in det[n] if b[4] >= (0.1 if c == 'c01' else 0.4))
            tp = sum(r[f'{c}_{t}'] for r in rows); TP += tp; NP += npred; NG += len(rows)
            line.append(f'{name[:12]} P={tp/npred:.3f} R={tp/len(rows):.3f}')
        print(f'{cn} IoU {t}: ' + ' | '.join(line) + f' || POOL P={TP/NP:.3f} R={TP/NG:.3f} (TP {TP}, préd {NP}, vérité {NG})')
allrows = [r for n in R for r in R[n][0]]
print('\n=== Personnes XML manquées : nature (conf>=0.1) ===')
for name in list(R) + ['POOL']:
    rows = allrows if name == 'POOL' else R[name][0]
    c = dict(ok=sum(r['c01_0.5'] for r in rows), loc=sum((not r['c01_0.5']) and r['c01_0.3'] for r in rows),
             weak=sum((not r['c01_0.3']) and r['best'] >= 0.1 for r in rows), none=sum(r['best'] < 0.1 for r in rows))
    print(name, len(rows), c)
print('\n=== Rappel par situation (drapeaux non exclusifs) : n, R@0.5 c0.1, R@0.3 c0.1, R@0.5 c0.4 ===')
def show(lbl, sel):
    s = [r for r in allrows if sel(r)]
    if s: print(f'{lbl:40s} n={len(s):4d}  {np.mean([r["c01_0.5"] for r in s]):.2f}  {np.mean([r["c01_0.3"] for r in s]):.2f}  {np.mean([r["c04_0.5"] for r in s]):.2f}')
show('toutes', lambda r: True)
for k, l in (('small', 'petite (sqrt aire<22px)'), ('edge', 'bord image (<8px)'), ('side', 'côte à côte'), ('furniture', 'sur meuble statique')):
    show(l, lambda r, k=k: r[k]); show('  non ' + l, lambda r, k=k: not r[k])
for pz in ('marche', 'active (sur place)', 'inactive', 'autre'): show('posture: ' + pz, lambda r, pz=pz: r['posture'] == pz)
show('aucun drapeau (grande, dégagée, marche)', lambda r: not (r['small'] or r['edge'] or r['side'] or r['furniture']) and r['posture'] == 'marche')
print('\n=== Par ID XML : n, R@0.5 c0.1, drapeaux dominants ===')
for name in R:
    for g in sorted({r['id'] for r in R[name][0]}, key=int):
        s = [r for r in R[name][0] if r['id'] == g]
        print(f'{name[:12]} X{g}: n={len(s)} R={np.mean([r["c01_0.5"] for r in s]):.2f} small={np.mean([r["small"] for r in s]):.2f} edge={np.mean([r["edge"] for r in s]):.2f} side={np.mean([r["side"] for r in s]):.2f} meuble={np.mean([r["furniture"] for r in s]):.2f} inactive/active={np.mean([r["posture"]!="marche" for r in s]):.2f}')
print('\n=== Faux positifs IoU 0.5 : type ===')
from collections import Counter
for c in ('c01', 'c04'):
    C = Counter(k for n in R for cc, k in R[n][1] if cc == c); tot = sum(C.values())
    print(c, tot, {k: f'{v} ({v/tot:.0%})' for k, v in C.items()})
for name in R: print(name, 'boîtes statiques (non-personnes):', len(R[name][2]))
import pickle; pickle.dump({k: (v[0], v[2]) for k, v in R.items()}, open('detq.pkl', 'wb'))
