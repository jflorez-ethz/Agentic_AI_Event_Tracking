from common import *
from collections import Counter, defaultdict
P = FROZEN
def stages(rows, times):
    bt = p.track(rows, activation=P['activation'], lost_s=P['lost_s'], matching=P['matching'])
    st = p.stitch(bt, times, tau_s=P['tau_s'], base_px=P['base_px'])
    return bt, st, p.drop_static(st)
OUT = {}
for name, xml in CLIPS:
    video, x, gt, det = load(name, xml); times = p.pts_times(str(video)); frames = sorted(map(int, det))
    bt, st, fin = stages(det, times)
    print(f'\n##### {name}')
    # raw matched -> lost by ByteTrack: why?
    raw = {}
    for n in frames:
        for i, b in enumerate(det[str(n)]): raw.setdefault((n, i), {})[n] = b[:4]
    rawm = p.frame_matches(gt, {k: v for k, v in raw.items()}, frames)
    btm = p.frame_matches(gt, bt, frames); finm = p.frame_matches(gt, fin, frames)
    why = Counter()
    for (g, n), k in rawm.items():
        if (g, n) in btm: continue
        conf = det[str(n)][k[1]][4]
        why['conf<0.4 (jamais activée seule)' if conf < 0.4 else 'conf>=0.4 mais perdue par ByteTrack'] += 1
    print('raw matched', len(rawm), '-> ByteTrack', len(btm), '-> final', len(finm), '| pertes ByteTrack:', dict(why))
    m, _ = p.evaluate(gt, fin, frames)
    print('final metrics', {k: m[k] for k in ('idf1', 'idtp', 'truth_detections', 'predicted_detections', 'id_switches', 'predicted_tracks')})
    # identity-perfect bound on final boxes: credit every spatial match
    ub = 2 * len(finm) / (m['truth_detections'] + m['predicted_detections'])
    print(f'borne "identité parfaite" sur les boîtes finales: IDF1 <= {ub:.3f} (vs {m["idf1"]}) -> perte due à l’association seule = {ub-m["idf1"]:.3f}')
    # per GT id: final tracks that cover it, fragments
    for g in sorted(gt, key=int):
        seq = [(n, finm[(g, n)]) for n in frames if (g, n) in finm]
        tr = Counter(t for _, t in seq)
        frag = 1 + sum(1 for a, b in zip(seq, seq[1:]) if a[1] != b[1]) if seq else 0
        nsc = sum(1 for n in frames if n in gt[g])
        print(f'  X{g}: {nsc} vérités, {len(seq)} appariées en sortie, pistes {dict(tr)}, segments {frag}')
    # final tracks: purity and false tracks
    for t, b in fin.items():
        hits = Counter(g for (g, n), tt in finm.items() if tt == t)
        print(f'  T{t}: {len(b)} boîtes, {times[min(b)]:.1f}-{times[max(b)]:.1f}s, appariements {dict(hits)}, non appariées {len(b)-sum(hits.values())}')
    OUT[name] = dict(bt=bt, st=st, fin=fin, finm=finm, times=times)
import pickle; pickle.dump(OUT, open('assoc.pkl', 'wb'))
