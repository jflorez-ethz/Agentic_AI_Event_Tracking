# Step 5 build notes: where the code differs from the plan

21 Nov 2026. Changes made while building Tasks 1–5 of `2026-11-21-step5-triage-agent-plan.md`.
Each one follows the spec's intent where the plan conflicted with the code or the Pydantic AI v2
docs (pydantic.dev/docs/ai, checked against the installed pydantic-ai-slim 2.71.0).

## Environment
- pydantic-ai v2 needs Python 3.11+ (the plan said ≥3.10). The venv is Python 3.14.6.

## Task 1
- `test_claude_check_without_focus_has_no_focus_line` passed before the change (it checks for
  an absence), so Step 2 showed 2 failures, not 3.
