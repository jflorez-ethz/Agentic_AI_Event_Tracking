"""Architecture audit, step 1: what the agents actually did in the 16 frozen KPI runs (offline, archived traces only).

    .venv/bin/python experiments/architecture_audit/traces.py
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = [(s, ROOT / l) for s, f in (("dev", "runs.txt"), ("heldout", "runs_heldout.txt"))
        for l in (ROOT / "experiments/kpi" / f).read_text().split()]
PRIORITY = {"person_fell", "person_on_floor", "object_placed", "object_removed", "person_enters_area",
            "object_appeared", "object_disappeared"}
out = {}


def main():
    actions = Counter()
    per_role_calls, per_role_tokens = Counter(), defaultdict(lambda: [0, 0, 0])
    verdicts = Counter()          # (category class, verdict)
    candidate_paths = Counter()   # sequence of verification actions per candidate
    inspections_per_candidate = Counter()
    rejection_codes = Counter()
    recoveries = Counter()
    investigation = Counter()
    budget = Counter()
    reporting = Counter()
    disposition = Counter()
    priority_handling = Counter()
    rows = []
    for split, run in RUNS:
        d = json.loads((run / "run/analysis.json").read_text())
        a = d["analysis"]
        b = a["budget"]
        budget[(b["max_candidates"], b["max_inspections"], b["max_agent_calls"], b["max_retrievals"])] += 1
        for c in d["role_calls"]:
            per_role_calls[c["role"]] += 1
            u = dict(c["usage"] or {})
            t = per_role_tokens[c["role"]]
            t[0] += u.get("prompt_token_count", 0); t[1] += u.get("candidates_token_count", 0); t[2] += u.get("thoughts_token_count", 0)
        obs = {f["observation"]["id"]: f["observation"] for e in a["evidence"] for f in e["findings"]}
        initial = {f["observation"]["id"]: f["observation"] for e in a["evidence"] if e["phase"] == "initial" for f in e["findings"]}
        current, path = None, []
        for t in a["trace"]:
            actions[(t["actor"], t["action"])] += 1
            if t["actor"] == "investigation" and t["action"] in ("search", "recovery", "priority_enforced", "context_trimmed", "rejected"):
                investigation[t["action"]] += 1
            if t["actor"] == "verification":
                if t["action"] == "decision":
                    kind = t["reason"].split(":")[0]
                    path.append(kind)
                if t["action"] in ("inspection_rejected",):
                    rejection_codes[(t.get("details") or {}).get("code") or t["reason"][:40]] += 1
                if t["action"] in ("evidence_insufficient", "verdict_rejected", "relation_insufficient"):
                    rejection_codes[t["action"] + ":" + ((t.get("details") or {}).get("code") or t["reason"][:50])] += 1
                if t["action"] == "recovery":
                    recoveries[(t.get("details") or {}).get("code")] += 1
                if t["action"] == "verdict":
                    det = t.get("details") or {}
                    cid = det.get("candidate_id") or (t["observation_ids"][0] if t["observation_ids"] else None)
                    cat = obs.get(cid, {}).get("category", "?")
                    verdicts[("priority" if cat in PRIORITY else "routine", det.get("status") or t["reason"][:20], det.get("completed"))] += 1
                    candidate_paths[" > ".join(path)] += 1
                    inspections_per_candidate[path.count("inspect")] += 1
                    rows.append({"split": split, "video": run.name, "category": cat, "verdict": det.get("status"),
                                 "completed": det.get("completed"), "path": list(path)})
                    path = []
            if t["actor"] == "reporting":
                reporting[t["action"]] += 1
        comp = a["completion"]
        for rec in comp["observation_dispositions"]:
            cat = initial.get(rec["id"], {}).get("category", "?")
            pos = initial.get(rec["id"], {}).get("possible_category")
            cls = "priority" if cat in PRIORITY or pos in PRIORITY else "routine"
            disposition[(cls, rec["status"])] += 1
        out[run.name] = comp
    print("Budgets used (max_candidates, max_inspections, max_agent_calls, max_retrievals):", dict(budget))
    print("\nRole calls:", dict(per_role_calls))
    for r, (i, o, th) in per_role_tokens.items():
        print(f"  {r:13s} input {i:8,d} output {o:7,d} thinking {th:8,d}  thinking/output ratio {th / max(o, 1):.1f}")
    print("\nInvestigation events:", dict(investigation))
    print("\nObservation dispositions (16 runs):")
    for k, v in sorted(disposition.items()):
        print(f"  {k[0]:8s} {k[1]:10s} {v}")
    print("\nVerification verdicts (class, status, completed):")
    for k, v in sorted(verdicts.items(), key=str):
        print(f"  {k}: {v}")
    print("\nVerification decision paths per candidate (top):")
    for p, n in candidate_paths.most_common(12):
        print(f"  {n:3d}  {p}")
    print("Inspections per candidate:", dict(sorted(inspections_per_candidate.items())))
    print("\nValidation rejections:", dict(rejection_codes.most_common()))
    print("Recoveries:", dict(recoveries))
    print("\nReporting actions:", dict(reporting))
    print("\nCompletion status per run:", Counter((c["investigation"], c["verification"]) for c in out.values()))
    open_priority = 0
    (ROOT / "experiments/architecture_audit/traces.json").write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
