# Offline KPI (work plan task B7)

The KPIs describe **one** system version: src tree `7e86f3b` (commit `bd6046f`), pinned in [rules.json](rules.json). They are measured only on runs made by [run_all_kpi.sh](run_all_kpi.sh) at that version. The older archived runs remain as history and are never read.

All rules were committed before any computation: [rules.json](rules.json) and the [hand check](hand_check.md).

## Steps

1. **Live runs (paid, you launch them).** The script checks the frozen version, a clean `src/` and the video hashes. It then runs the nine CAVIAR videos at the current settings (whole video, HIGH, 4 candidates / 4 inspections / 14 calls / 4 iterations), with at most three at a time. It writes one directory per video under `experiments/kpi_runs/<time>-<commit>/` and the list to `experiments/kpi/runs.txt`.

   ```bash
   GEMINI_API_KEY=... experiments/kpi/run_all_kpi.sh
   ```

2. **KPI table (offline, free).**

   ```bash
   .venv/bin/python experiments/kpi/kpi.py   # writes KPI.md and kpi.json
   .venv/bin/python -m pytest -q experiments/kpi/test_kpi.py
   ```

## What is measured

The reference is the CAVIAR XML. It contains 8 critical events: 4 objects placed, 3 removed and 1 fall. Walk2, TwoEnterShop1front, Meet_WalkSplit and Meet_WalkTogether1 are controls with no critical event.

| KPI | Definition (details in rules.json) |
|---|---|
| Alerts reaching a person, and share that are real | Supported security events plus `needs_review` alerts, matched one-to-one to XML events within ±2 s. Sensitivity at ±1 and ±5 s. The raw-alert reduction uses an approximation until detector C1 exists. |
| Missed critical events (target 0) | Each miss has a cause: `not_covered`, `never_seen`, or `dismissed` (seen and then dropped by the agent). |
| Time to alert (target ≤ 30 s) | As run, and live (simulated). Both are lower bounds built from the recorded `elapsed_ms`. The real wall time per run is reported next to them. |
| Report and evidence | Report produced; cited images; images within ±2 s of the event; validity of every citation. |
| Cost per camera per month | Tokens × `gemini-3.6-flash` price, at the launch rate and the standard rate. Perception is scaled to 43,200 minutes. Agents are reported per run. |

## Not measurable yet

- Human reference times (B5): footage search and hand-written reports. So there is no time-to-evidence (B6 is also missing) and no report time saved.
- Approved reports and correction rate (B8): `operator_label` is still empty.
- Real time to alert in operation, true raw alerts and two-step cost: these need detector C1.
- Fire: CAVIAR has none.
- Generalisation: every clip was used during development, and there are only 8 critical events.
