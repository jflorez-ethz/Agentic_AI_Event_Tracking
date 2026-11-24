from common import *
import json
out = {}
CONF = 0.5
for name, xml in CLIPS:
    video, x, gt, det = load(name, xml)
    old,_ = legacy(x)
    res = {}
    for label, ref in (('corrected', gt), ('legacy', old)):
        frames = sorted(map(int, det))
        def score(k, dx, dy):
            s, c = [], 0
            for n in frames:
                D = [b[:4] for b in det[str(n)] if b[4] >= CONF]
                G = [ref[g][n+k] for g in ref if n+k in ref[g]]
                if not G: continue
                G = np.array(G) + [dx, dy, dx, dy]
                best = iou_mat(G, D).max(1) if D else np.zeros(len(G))
                s += list(best)
            return float(np.mean(s)), float(np.mean(np.array(s) >= 0.5))
        base = score(0,0,0)
        best_k = max(range(-10,11), key=lambda k: score(k,0,0)[0])
        grid = [(score(best_k,dx,dy)[0], dx, dy) for dx in range(-12,13,2) for dy in range(-12,13,2)]
        m, dx0, dy0 = max(grid)
        grid = [(score(best_k,dx,dy)[0], dx, dy) for dx in range(dx0-2,dx0+3) for dy in range(dy0-2,dy0+3)]
        m, dx, dy = max(grid)
        bestall = score(best_k, dx, dy)
        kcurve = {k: round(score(k,0,0)[0],3) for k in (-4,-2,-1,0,1,2,4)}
        res[label] = dict(base_meanIoU=round(base[0],3), base_frac05=round(base[1],3), best_frame_shift=best_k,
                          best_dx=dx, best_dy=dy, best_meanIoU=round(bestall[0],3), best_frac05=round(bestall[1],3), k_curve=kcurve)
        print(name, label, res[label], flush=True)
    # residuals of matched pairs at shift 0 (corrected)
    r = []
    for n in map(int, det):
        D = [b[:4] for b in det[str(n)] if b[4] >= CONF]
        for g in gt:
            if n in gt[g] and D:
                M = iou_mat([gt[g][n]], D)[0]; j = M.argmax()
                if M[j] >= 0.3:
                    a, b = gt[g][n], D[j]
                    r.append([(b[0]+b[2]-a[0]-a[2])/2, (b[1]+b[3]-a[1]-a[3])/2, (b[2]-b[0])-(a[2]-a[0]), (b[3]-b[1])-(a[3]-a[1])])
    r = np.array(r)
    res['residual_median_dx_dy_dw_dh'] = np.round(np.median(r,0),1).tolist(); res['residual_n']=len(r)
    print(name, 'median residual (det-xml) dx,dy,dw,dh =', res['residual_median_dx_dy_dw_dh'], 'n', len(r))
    out[name] = res
json.dump(out, open('offset.json','w'), indent=1)
