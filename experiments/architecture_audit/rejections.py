"""Architecture audit, step 3: the inspections Verification asked for and the tool refused (no_new_frames).
Would a 250 ms grid over the same interval have added source frames? Offline: video decode metadata only.
    .venv/bin/python experiments/architecture_audit/rejections.py
"""
import json
from pathlib import Path

from security_augmented.agents import InspectionRejected, additional_frame_indices
from security_augmented.contracts import Interval
from security_augmented.video import ingest

ROOT = Path(__file__).resolve().parents[2]
total = new250 = 0
for listing in ("runs.txt", "runs_heldout.txt"):
    for line in (ROOT / "experiments/kpi" / listing).read_text().split():
        a = json.loads((ROOT / line / "run/analysis.json").read_text())["analysis"]
        video = ingest(Path(a["video"]["source_path"]))
        known = {f["display_index"] for e in a["evidence"] if e.get("inspection") and e["status"] == "success"
                 for f in e["inspection"]["frames"]}
        for t in a["trace"]:
            d = t.get("details") or {}
            if t["action"] == "inspection_rejected" and d.get("code") == "no_new_frames":
                r = d["requested"]
                interval = Interval(r["start_us"], r["end_us"])
                total += 1
                try:
                    n = len(additional_frame_indices(video, interval, 250, known))
                    new250 += 1
                except InspectionRejected:
                    n = 0
                print(f"{Path(line).name:22s} {interval.start_us / 1e6:6.2f}-{interval.end_us / 1e6:6.2f}s  new frames at 250 ms: {n}")
print(f"{new250}/{total} refused requests would have added frames at 250 ms (lower bound: 'known' includes frames sampled later in the run)")
