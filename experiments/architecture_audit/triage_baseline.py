"""Architecture audit, step 2: does Investigation's model triage differ from a fixed rule on watch-list observations?

Rule (no model): delegate every confident watch-list observation (category in PRIORITY_LABELS) by time, up to
max_candidates; fill the remaining slots with routine observations by time. Suspicions (insufficient_evidence)
are not delegated (Verification can never support them, see agents.AgentRun.verdict).
    .venv/bin/python experiments/architecture_audit/triage_baseline.py
"""
import json
from pathlib import Path

from security_augmented.workflow import PRIORITY_LABELS

ROOT = Path(__file__).resolve().parents[2]
same = differ = 0
for listing in ("runs.txt", "runs_heldout.txt"):
    for line in (ROOT / "experiments/kpi" / listing).read_text().split():
        a = json.loads((ROOT / line / "run/analysis.json").read_text())["analysis"]
        k = a["budget"]["max_candidates"]
        initial = [f["observation"] for e in a["evidence"] if e["phase"] == "initial" for f in e["findings"]]
        start = {f["observation"]["id"]: f["citation"]["interval"]["start_us"] for e in a["evidence"] for f in e["findings"]}
        model = {d["id"] for d in a["completion"]["observation_dispositions"] if d["status"] == "delegated"}
        prio = sorted((o["id"] for o in initial if o["category"] in PRIORITY_LABELS or o["category"] == "person_fell"), key=start.get)
        rule_prio = set(prio[:k])
        model_prio = {i for i in model if i in prio}
        ok = rule_prio == model_prio
        same += ok; differ += not ok
        print(f"{Path(line).name:26s} watch-list obs {len(prio)}  rule delegates {len(rule_prio)}  model delegates {len(model_prio)}  "
              f"{'same' if ok else 'DIFFERENT'}  (model also delegated {len(model) - len(model_prio)} routine)")
print(f"Watch-list delegation identical to the fixed rule in {same}/{same + differ} runs")
