"""The audit log and the run folders (task D3).

A kept agent run is one folder under runs/triage/:

  alerts.jsonl, decisions.jsonl   the kit's AlertStore
  <candidate id>.json             the triage agent's run files
  evidence/<candidate id>/        copies of the clips and frames the agent produced
  audit.jsonl                     one line per verdict, decision, approved action and report
  reports/                        incident reports

audit.jsonl is append-only: this module opens it for append or read, never for write.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

AUDIT_FILE = "audit.jsonl"
STAT_KEYS = ("cost_usd", "requests", "tool_calls", "tool_errors", "overrides", "video")
OLD_RUN_MESSAGE = ("This run folder has no alerts.jsonl; it was made before the review step. "
                   "Run evaluate.py --triage agent again.")


def append(run_dir: Path, entry: dict) -> dict:
    """Add one line with the wall-clock time (local, with its UTC offset) and return it."""
    row = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **entry}
    with open(Path(run_dir) / AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def read(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / AUDIT_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def keep_evidence(run_dir: Path, candidate_id: str, paths: list[str]) -> list[str]:
    """Copy the files that exist to evidence/<candidate id>/; returns paths relative to the run folder."""
    kept = []
    for source in map(Path, paths):
        if not source.is_file():
            continue
        rel = Path("evidence") / candidate_id / source.name
        (Path(run_dir) / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, Path(run_dir) / rel)
        kept.append(rel.as_posix())
    return kept


def verdict_entry(alert: dict, site_name: str, stats: dict | None, model: str | None = None) -> dict:
    cand = alert["candidate"]
    entry = {
        "type": "verdict", "alert_id": alert["id"], "candidate_id": cand["candidate_id"], "site": site_name,
        "camera": cand["camera_id"], "zone": cand["zone"], "kind": cand["kind"],
        "first_seen": cand["first_seen"], "created": alert["created"],
        **{k: alert[k] for k in ("verdict", "priority", "reason", "evidence", "linked_to")},
        "run_file": f"{cand['candidate_id']}.json",
    }
    if model:
        entry["model"] = model
    if stats:
        entry.update({k: stats.get(k) for k in STAT_KEYS})
    return entry


def resolve_run_dir(arg: str, root: Path) -> Path:
    """A kept run folder. "latest" is the one whose alerts.jsonl was written last (a review adds
    to the folder but never to that file). Creates nothing, unlike AlertStore."""
    if arg == "latest":
        stores = list((Path(root) / "runs" / "triage").glob("*/alerts.jsonl"))
        if not stores:
            raise SystemExit("No run folder with alerts.jsonl under runs/triage. "
                             "Run evaluate.py --triage agent first.")
        return max(stores, key=lambda p: (p.stat().st_mtime_ns, p.parent.name)).parent
    run_dir = Path(arg)
    if not run_dir.is_dir():
        raise SystemExit(f"No run folder at {run_dir}.")
    if not (run_dir / "alerts.jsonl").is_file():
        raise SystemExit(OLD_RUN_MESSAGE)
    return run_dir
