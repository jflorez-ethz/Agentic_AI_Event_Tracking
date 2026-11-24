"""Stage 2 on unseen clips (PROTOCOL.md). Run only if gate.json says pass."""
import json, xml.etree.ElementTree as ET
import numpy as np
from score import HERE, p, detection, rates, pool, tracking, cpu

assert json.loads((HERE / "gate.json").read_text())["gate"]["pass"], "gate failed: stop"
CLIPS = ["Walk3", "Meet_Split_3rdGuy", "Browse_WhileWaiting1"]
x2 = json.loads((HERE / "det_x2.json").read_text()); x3 = json.loads((HERE / "det_x3.json").read_text())


def mean_iou(gt, det, k, dx, dy):
    s = []
    for n in map(int, (n for n in det if not n.startswith("_"))):
        D = [d[:4] for d in det[str(n)] if d[4] >= 0.5]
        for g in gt:
            if n + k in gt[g]:
                b = gt[g][n + k]; b = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
                s.append(max([p.iou(b, d) for d in D] or [0]))
    return float(np.mean(s))


out = {"alignment": {}, "clips": {}}
for name in CLIPS:
    gt, _ = p.ground_truth(p.ANNOTATIONS / f"{name}.xml")
    times = p.pts_times(str(p.RAW / f"{name}.mpg"))
    xf = [int(f.attrib["number"]) for f in ET.parse(p.ANNOTATIONS / f"{name}.xml").getroot().findall("frame")]
    k = max(range(-6, 7), key=lambda k: mean_iou(gt, x2[name], k, 0, 0))
    best = max(((mean_iou(gt, x2[name], k, dx, dy), dx, dy) for dx in range(-4, 5) for dy in range(-4, 5)))
    al = dict(decoded=len(times), xml_frames=len(xf), frame_shift=k, dx=best[1], dy=best[2],
              mean_iou_at_0=round(mean_iou(gt, x2[name], 0, 0, 0), 3), mean_iou_best=round(best[0], 3))
    al["ok"] = len(times) == len(xf) + 1 and k == 0 and abs(best[1]) <= 2 and abs(best[2]) <= 2
    out["alignment"][name] = al
    print(name, al, flush=True)
    out["clips"][name] = {}
    for tag, det in (("x2", x2), ("x3", x3)):
        c = detection(gt, det[name])
        out["clips"][name][tag] = {"_c": c, **rates(c), "tracking": tracking(gt, det[name], times)}
assert all(a["ok"] for a in out["alignment"].values()), "alignment check failed: stop before scoring"
out["pooled"] = {}
for tag, det in (("x2", x2), ("x3", x3)):
    rows = [out["clips"][n][tag] for n in CLIPS]
    tp = sum(r["tracking"]["idtp"] for r in rows); tot = sum(r["tracking"]["truth_detections"] + r["tracking"]["predicted_detections"] for r in rows)
    out["pooled"][tag] = {"idf1": round(2 * tp / tot, 3), **rates(pool([r["_c"] for r in rows])), "cpu_s_per_video_min": cpu(det, CLIPS)}
for n in CLIPS:
    for tag in ("x2", "x3"):
        out["clips"][n][tag].pop("_c")
x = out["pooled"]["x3"]
out["criterion"] = {"idf1>=0.70": x["idf1"] >= 0.70, "recall_small>=0.50": x["recall_small"] >= 0.50}
out["criterion"]["pass"] = all(out["criterion"].values())
(HERE / "test.json").write_text(json.dumps(out, indent=2, default=lambda o: o.item()) + "\n")
print(json.dumps({k: out[k] for k in ("pooled", "criterion")}, indent=2, default=lambda o: o.item()))
for n in CLIPS:
    print(n, {t: (out["clips"][n][t]["tracking"]["idf1"], round(out["clips"][n][t]["recall_small"], 3)) for t in ("x2", "x3")})
