"""Stage 1 entry gate on Walk2 and LeftBag (PROTOCOL.md)."""
import json
from score import HERE, p, detection, rates, pool, cpu

CLIPS = {"Walk2": "wk2gt.xml", "LeftBag": "LeftBag.xml"}
x2 = json.loads((HERE / "det_x2.json").read_text())
x3 = json.loads((HERE / "det_x3.json").read_text())
cached = json.loads((HERE.parent / "detections_stride5_nano_576x768.json").read_text())
out = {"clips": {}}
for name, xml in CLIPS.items():
    gt, _ = p.ground_truth(p.ANNOTATIONS / xml)
    same = x2[name] == cached[name]
    out["clips"][name] = {"x2": rates(c2 := detection(gt, x2[name])), "x3": rates(c3 := detection(gt, x3[name])),
                          "x2_rerun_identical_to_cache": same, "_c2": c2, "_c3": c3}
r2 = rates(pool([v["_c2"] for v in out["clips"].values()])); r3 = rates(pool([v["_c3"] for v in out["clips"].values()]))
delta = r3["recall_small"] - r2["recall_small"]
out["pooled"] = {"x2": r2, "x3": r3, "delta_recall_small": delta}
out["gate"] = {"delta_recall_small>=0.15": delta >= 0.15, "precision04_x3>=0.60": r3["precision04"] >= 0.60}
out["gate"]["pass"] = all(out["gate"].values())
out["cpu_s_per_video_min"] = {"x2": cpu(x2, CLIPS), "x3": cpu(x3, CLIPS), "x2_cached_run": cpu(cached, CLIPS)}
for v in out["clips"].values():
    v.pop("_c2"); v.pop("_c3")
(HERE / "gate.json").write_text(json.dumps(out, indent=2, default=lambda o: o.item()) + "\n")
print(json.dumps(out, indent=2, default=lambda o: o.item()))
