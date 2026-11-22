"""Keeping each agent run: the alert store, evidence copies and the audit log. No API calls.

    python -m pytest tests/test_audit.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from pydantic_ai import models

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluate  # noqa: E402
from agentlab import audit  # noqa: E402
from d3d5_helpers import ScriptedRun, kept_run, no_env  # noqa: E402,F401

models.ALLOW_MODEL_REQUESTS = False

OLD_RUN = ("This run folder has no alerts.jsonl; it was made before the review step. "
           "Run evaluate.py --triage agent again.")


def test_append_and_read_round_trip(tmp_path):
    first = audit.append(tmp_path, {"type": "verdict", "n": 1})
    audit.append(tmp_path, {"type": "decision", "n": 2})
    rows = audit.read(tmp_path)
    assert [r["n"] for r in rows] == [1, 2]
    assert all(r["ts"] for r in rows)
    assert rows[0] == first


def test_append_never_changes_earlier_lines(tmp_path):
    path = tmp_path / audit.AUDIT_FILE
    earlier = '{"ts": "x",  "type":"verdict"}\n'  # spacing that a rewrite would normalise
    path.write_text(earlier)
    audit.append(tmp_path, {"type": "decision"})
    assert path.read_text().startswith(earlier)
    assert len(path.read_text().splitlines()) == 2


def test_read_without_a_log_is_empty(tmp_path):
    assert audit.read(tmp_path) == []


def test_keep_evidence_copies_and_skips_missing(tmp_path):
    clip = tmp_path / "work" / "clip.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"video")
    run = tmp_path / "run"
    kept = audit.keep_evidence(run, "CAM-A-1", [str(clip), str(tmp_path / "gone.mp4")])
    assert kept == ["evidence/CAM-A-1/clip.mp4"]
    assert (run / kept[0]).read_bytes() == b"video"


def test_agent_run_keeps_store_evidence_and_audit(site_dir, tmp_path):
    run = kept_run(site_dir, tmp_path / "run")
    alerts = [json.loads(line) for line in (run / "alerts.jsonl").read_text().splitlines()]
    assert len(alerts) == 2
    for a in alerts:
        assert len(a["evidence"]) == 1
        for path in a["evidence"]:
            assert path.startswith(f"evidence/{a['candidate']['candidate_id']}/")
            assert (run / path).is_file()
    entries = audit.read(run)
    assert [e["type"] for e in entries] == ["verdict", "verdict"]
    assert [e["alert_id"] for e in entries] == [a["id"] for a in alerts]
    for e, a in zip(entries, alerts):
        assert e["site"] == "Test site" and e["candidate_id"] == a["candidate"]["candidate_id"]
        assert (e["camera"], e["zone"], e["kind"]) == (a["candidate"]["camera_id"], a["candidate"]["zone"],
                                                       "after_hours_person")
        assert (e["verdict"], e["priority"], e["reason"]) == (a["verdict"], a["priority"], a["reason"])
        assert (e["evidence"], e["linked_to"]) == (a["evidence"], a["linked_to"])
        assert e["first_seen"] == a["candidate"]["first_seen"] and e["created"] == a["created"]
        assert e["model"] == "claude-haiku-5-5" and e["run_file"] == f"{e['candidate_id']}.json"
        assert (run / e["run_file"]).is_file()
        assert (e["requests"], e["tool_calls"], e["tool_errors"], e["overrides"]) == (5, 4, 0, [])
        assert e["cost_usd"] > 0 and e["video"] == "none"


def test_verdict_entry_without_stats():
    alert = {"id": "A-001", "created": "2026-01-10T02:00:07", "verdict": "escalate", "priority": "high",
             "reason": "r", "evidence": [], "linked_to": None,
             "candidate": {"candidate_id": "C-1", "camera_id": "C", "zone": "Z", "kind": "fire",
                           "first_seen": "2026-01-10T02:00:05"}}
    entry = audit.verdict_entry(alert, "Site", None)
    assert entry["type"] == "verdict" and "cost_usd" not in entry and "model" not in entry


def test_stub_run_writes_no_run_folder(site_dir, tmp_path, tmp_path_factory, monkeypatch):
    work = tmp_path_factory.mktemp("stub-work")
    monkeypatch.setattr(evaluate.tempfile, "mkdtemp", lambda **kw: str(work))
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    evaluate.run(str(site_dir / "site" / "index.json"), 2)
    evaluate.run(str(site_dir / "site" / "index.json"), 2, keep_run=True)  # the stub has no run_dir
    assert list(tmp_path.iterdir()) == []
    assert not (work / audit.AUDIT_FILE).exists() and not (work / "evidence").exists()


def test_used_run_folder_is_refused_before_any_triage(site_dir, tmp_path):
    run = kept_run(site_dir, tmp_path / "run")
    before = (run / audit.AUDIT_FILE).read_bytes()
    again = ScriptedRun(run)
    with pytest.raises(SystemExit, match="already holds a run"):
        evaluate.run(str(site_dir / "site" / "index.json"), 2, triage_fn=again, keep_run=True)
    assert again.calls == 0
    assert (run / audit.AUDIT_FILE).read_bytes() == before


@pytest.mark.parametrize("repeats, folders", [(1, ["single"]), (2, ["r1", "r2"])])
def test_main_keeps_every_agent_run(site_dir, tmp_path, monkeypatch, capsys, repeats, folders):
    def fake_make_agent(model, run_dir=None):
        return ScriptedRun(tmp_path / (run_dir.name.rsplit("-", 1)[1] if run_dir else "single"))

    monkeypatch.setattr(evaluate, "make_agent", fake_make_agent)
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--triage", "agent", "--delay", "2", "--repeats", str(repeats),
                                      "--index", str(site_dir / "site" / "index.json")])
    evaluate.main()
    for name in folders:
        assert len((tmp_path / name / "alerts.jsonl").read_text().splitlines()) == 2
        assert len(audit.read(tmp_path / name)) == 2


def _folder(root: Path, name: str, mtime: int | None) -> Path:
    d = root / "runs" / "triage" / name
    d.mkdir(parents=True)
    if mtime is not None:
        (d / "alerts.jsonl").write_text("")
        os.utime(d / "alerts.jsonl", (mtime, mtime))
    return d


def test_resolve_latest_skips_folders_without_alerts(tmp_path):
    older = _folder(tmp_path, "20261121-100000", 1_000)
    newer = _folder(tmp_path, "20261121-110000", None)
    (tmp_path / "runs" / "triage" / "run2x3.json").write_text("{}")
    assert audit.resolve_run_dir("latest", tmp_path) == older
    with pytest.raises(SystemExit) as err:
        audit.resolve_run_dir(str(newer), tmp_path)
    assert str(err.value) == OLD_RUN


def test_resolve_latest_is_the_run_made_last_not_the_one_reviewed_last(tmp_path):
    second = _folder(tmp_path, "20261121-100000-r2", 2_000)
    tenth = _folder(tmp_path, "20261121-100000-r10", 3_000)
    (second / audit.AUDIT_FILE).write_text("")  # a review touches the folder, not alerts.jsonl
    os.utime(second, (9_000, 9_000))
    assert audit.resolve_run_dir("latest", tmp_path) == tenth


def test_resolve_creates_nothing(tmp_path):
    with pytest.raises(SystemExit, match="No run folder"):
        audit.resolve_run_dir("latest", tmp_path)
    with pytest.raises(SystemExit, match="No run folder"):
        audit.resolve_run_dir(str(tmp_path / "typo"), tmp_path)
    assert list(tmp_path.iterdir()) == []
