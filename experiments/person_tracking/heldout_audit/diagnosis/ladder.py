from common import *
from scipy.optimize import linear_sum_assignment as lsa
P = FROZEN
def run(rows, times, gt, frames):
    bt = p.track(rows, activation=P['activation'], lost_s=P['lost_s'], matching=P['matching'])
    fin = p.drop_static(p.stitch(bt, times, tau_s=P['tau_s'], base_px=P['base_px']))
    m, _ = p.evaluate(gt, fin, frames); return m
tot = {}
for name, xml in CLIPS:
    video, x, gt, det = load(name, xml); times = p.pts_times(str(video)); frames = sorted(map(int, det))
    old, _ = legacy(x)
    jump = lambda R: np.median([np.hypot(*np.subtract(p.center(R[g][n]), p.center(R[g][n-1]))) for g in R for n in R[g] if n-1 in R[g]])
    print(f'{name}: saut médian du centre entre trames consécutives: corrigé {jump(gt):.1f}px, ancien lecteur {jump(old):.1f}px')
    L = {k: {} for k in ('L0 oracle XML', 'L0+FP: XML + faux positifs Nano', 'L1 XML là où Nano détecte (conf 0.95)',
                         'L1b idem avec la conf Nano', 'L2 boîtes Nano vraies (sans FP)', 'L3 Nano complet')}
    for n in frames:
        ids = [g for g in gt if n in gt[g]]; D = det[str(n)]
        G = np.array([gt[g][n] for g in ids]).reshape(-1, 4); Dx = np.array([d[:4] for d in D]).reshape(-1, 4)
        tp = {}
        if len(G) and len(Dx):
            M = iou_mat(G, Dx); w = (M >= 0.5) * (2 + M)
            tp = {i: j for i, j in zip(*lsa(-w)) if w[i, j]}
        fpj = [j for j in range(len(D)) if j not in tp.values()]
        s = str(n)
        L['L0 oracle XML'][s] = [[*G[i], 0.95] for i in range(len(G))]
        L['L0+FP: XML + faux positifs Nano'][s] = L['L0 oracle XML'][s] + [D[j] for j in fpj]
        L['L1 XML là où Nano détecte (conf 0.95)'][s] = [[*G[i], 0.95] for i in tp]
        L['L1b idem avec la conf Nano'][s] = [[*G[i], D[j][4]] for i, j in tp.items()]
        L['L2 boîtes Nano vraies (sans FP)'][s] = [D[j] for j in tp.values()]
        L['L3 Nano complet'][s] = D
    for k, rows in L.items():
        m = run(rows, times, gt, frames)
        t = tot.setdefault(k, [0, 0, 0]); t[0] += m['idtp']; t[1] += m['truth_detections']; t[2] += m['predicted_detections']
        print(f'   {k:42s} IDF1 {m["idf1"]:.3f}  switches {m["id_switches"]}')
print('\nPOOL')
for k, (a, b, c) in tot.items(): print(f'   {k:42s} IDF1 {2*a/(b+c):.3f}')
