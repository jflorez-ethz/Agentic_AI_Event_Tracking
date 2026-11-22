"""The alert inbox: two append-only JSON-lines files shared by the runner and the screen.

alerts.jsonl     one line per triaged candidate (escalated, dismissed or linked)
decisions.jsonl  one line per guard decision (approve or dismiss)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class AlertStore:
    def __init__(self, runtime_dir: str | Path):
        self.dir = Path(runtime_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.dir / "alerts.jsonl"
        self.decisions_path = self.dir / "decisions.jsonl"

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass  # a line still being written
        return rows

    @staticmethod
    def _append(path: Path, row: dict) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def add(self, candidate: dict, verdict: dict, trace: list[dict], created_site_time: datetime) -> dict:
        alert = {
            "id": f"A-{len(self._read(self.alerts_path)) + 1:03d}",
            "created": created_site_time.isoformat(timespec="seconds"),
            "candidate": candidate,
            **verdict,
            "trace": trace,
        }
        self._append(self.alerts_path, alert)
        return alert

    def decide(self, alert_id: str, decision: str, site_time: datetime, note: str = "") -> None:
        self._append(self.decisions_path, {"alert_id": alert_id, "decision": decision,
                                           "site_time": site_time.isoformat(timespec="seconds"), "note": note})

    def all(self) -> list[dict]:
        decisions = {d["alert_id"]: d for d in self._read(self.decisions_path)}
        out = []
        for alert in self._read(self.alerts_path):
            d = decisions.get(alert["id"])
            if alert["verdict"] == "escalate":
                alert["status"] = d["decision"] if d else "pending"
            else:
                alert["status"] = "closed by agent"
            out.append(alert)
        return out

    def open_alerts(self) -> list[dict]:
        return [a for a in self.all() if a["verdict"] == "escalate" and a["status"] in ("pending", "approved")]

    def handled_candidates(self) -> set[str]:
        return {a["candidate"]["candidate_id"] for a in self._read(self.alerts_path)}

    def clear(self) -> None:
        for p in (self.alerts_path, self.decisions_path):
            p.unlink(missing_ok=True)
