"""Proposed actions and the procedures they mirror. No API calls.

    python -m pytest tests/test_actions.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic_ai import models

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import make_real_site  # noqa: E402
from d3d5_helpers import no_env  # noqa: E402,F401

models.ALLOW_MODEL_REQUESTS = False

RULE_7 = ("7. Unattended object: alert the control room, priority medium. "
          "A guard checks it in person; it is not moved before it is checked.")
GUARD = "The guard on duty checks Yard and decides on dispatch. The system never contacts the police."


@pytest.mark.parametrize("kind, text", [
    ("person_down", "Send the nearest guard to Yard now. The guard decides whether to call emergency services."),
    ("fire", "Send the nearest guard to Yard now. The guard decides whether to call emergency services."),
    ("after_hours_person", GUARD),
    ("after_hours_vehicle", GUARD),
    ("unattended_object", "A guard checks the object in Yard in person. It is not moved before it is checked."),
    ("blocked_exit", "The supervisor has the exit in Yard cleared before the next shift."),
    ("something_new", "The guard on duty reviews the clip."),
])
def test_proposed_action_per_kind(kind, text):
    from agentlab.actions import proposed_action
    assert proposed_action(kind, "Yard") == text


def test_kit_procedures_have_rule_7():
    assert RULE_7 in (ROOT / "context" / "procedures.md").read_text().splitlines()


def test_real_procedures_have_rule_7():
    assert RULE_7 in make_real_site.procedures_text().splitlines()
    assert RULE_7 in (ROOT / "context" / "real" / "procedures.md").read_text().splitlines()
