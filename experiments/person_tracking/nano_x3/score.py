"""Scoring shared by the gate and the test (definitions fixed in PROTOCOL.md)."""
import json, sys
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment as lsa

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pilot as p  # noqa: E402

FROZEN = json.loads((HERE.parent / "results_heldout_nano_576x768.json").read_text())["frozen"]


def small(b):
    return np.sqrt((b[2] - b[0]) * (b[3] - b[1])) < 22


def matches(G, D, thr=0.5):
    if not G or not D:
        return {}
    M = np.array([[p.iou(g, d) for d in D] for g in G])
    w = (M >= thr) * (2 + M)
    return {i: j for i, j in zip(*lsa(-w)) if w[i, j]}


def detection(gt, det):
    """Counts for recall (conf >= 0.1, all and small) and precision (conf >= 0.4)."""
    c = dict(gt=0, gt_small=0, tp=0, tp_small=0, pred04=0, tp04=0)
    for n in sorted(map(int, (k for k in det if not k.startswith("_")))):
        ids = [g for g in gt if n in gt[g]]
        G = [gt[g][n] for g in ids]
        D01 = [d[:4] for d in det[str(n)] if d[4] >= 0.1]
        D04 = [d[:4] for d in det[str(n)] if d[4] >= 0.4]
        m = matches(G, D01)
        c["gt"] += len(G); c["gt_small"] += sum(map(small, G))
        c["tp"] += len(m); c["tp_small"] += sum(small(G[i]) for i in m)
        c["pred04"] += len(D04); c["tp04"] += len(matches(G, D04))
    return c


def rates(c):
    return dict(recall=c["tp"] / c["gt"], recall_small=c["tp_small"] / max(c["gt_small"], 1),
                precision04=c["tp04"] / max(c["pred04"], 1), n_small=c["gt_small"], n=c["gt"])


def pool(cs):
    return {k: sum(c[k] for c in cs) for k in cs[0]}


def tracking(gt, det, times):
    frames = sorted(int(k) for k in det if not k.startswith("_"))
    bt = p.track(det, activation=FROZEN["activation"], lost_s=FROZEN["lost_s"], matching=FROZEN["matching"])
    fin = p.drop_static(p.stitch(bt, times, tau_s=FROZEN["tau_s"], base_px=FROZEN["base_px"]))
    m, _ = p.evaluate(gt, fin, frames)
    return {k: m[k] for k in ("idf1", "idtp", "truth_detections", "predicted_detections", "id_switches", "predicted_tracks")}


def cpu(det, names):
    s = sum(det["_cpu"][n]["seconds"] for n in names); v = sum(det["_cpu"][n]["video_s"] for n in names)
    return round(s / v * 60, 1)
