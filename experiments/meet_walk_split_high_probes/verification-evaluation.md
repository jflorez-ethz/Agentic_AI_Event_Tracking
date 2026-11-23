# Verification handoff evaluation

The production CLI starts a new investigation and has no resume flag or persisted LangGraph checkpoint. Its archive path looks up archived observations but does not resume this accepted handoff with live source reinspection. The evaluation runner replays the recorded search and accepted delegation as local decisions through the existing graph and validators. It checks the reconstructed continuation context against the saved input and checks the validated dispositions before allowing an external role request. The first two logical Investigation slots are consumed locally, as in the recorded run. The initial scan and Investigation Gemini calls are skipped. The runner calls the same single-inspection function used by the production workflow only when Verification requests an inspection.

From the repository root, after explicit authorization for both targeted footage and observation text:

```bash
probe_dir=$(mktemp -d experiments/meet_walk_split_high_probes/verification.XXXXXX)
.venv/bin/python experiments/meet_walk_split_high_probes/verification.py \
  --authorize-observation-text-transfer --authorize-footage-transfer \
  --output "$probe_dir/run"
```

The run uses the archived 500 ms sample step and existing 14 logical calls, four inspections, and four Verification decisions per candidate. With two logical Investigation decisions replayed locally, the remaining ceiling is 12 logical Verification and Reporting calls, 24 physical role attempts and four single-attempt targeted media requests. The existing global failure policy can end the run sooner. The runner sends derived evidence context for Verification and Reporting, and timestamped frames or clips and inspection instructions only if Verification requests them. No calls are made by importing the runner.

`result.json` stores completion, graph transitions, verdicts, canonical citations, structured decisions, targeted inference records, latency, usage, and physical attempts. `report.md` renders the validated supported and unresolved events. Count `supported`, `unsupported`, and `insufficient` separately. An `unsupported` verdict does not on its own establish that the opposite happened. Distinguish completed checks from supported claims, and separate tool or model failures from a completed insufficient verdict.

## Source-review criteria

The following are provisional checks from selected locally decoded frames (display indices 0, 88, 125, 175, 238, 250, 363, 500, 550 and 613). Review the exact verdict frames and intervening footage before scoring a live result.

| Candidate prefix | Recorded bracket | What would support the claim |
|---|---|---|
| `3bfb1c56` | 0–9.52 s | Track the visible figure from the sunlit aisle onto the atrium floor using position and direction across frames. Glare and the left-side structure obscure portions of the aisle. |
| `da6fdebc` | 3.52–9.52 s | Follow the figure moving diagonally and identify the other walker before and after the close approach. The figures are close together around 7 s. Proximity supports a literal description of convergence where visible. A claim that one joins the other requires separate evidence for both paths and continuity. |
| `ac83682` | 10–14.52 s | Two people are distinguishable near the left side at 10 s and their positions evolve near the seating area. Identify which path matches the upper-left movement. The same frame set also supports the possibility of a separate observation about the other walker. |
| `433e1420` | 20–24.52 s | Track an identifiable moving figure in the covered walkway across frames and verify direction. Glare and structural occlusion limit what can be resolved from the sampled views. Leave clothing details and any link to earlier people uncertain unless visible. |

Score provenance separately by replaying the cited display index, PTS and RGB hash. Score semantic support claim by claim, including whether people remain distinguishable during occlusion and whether endpoints are linked by visible motion. A citation or a repeated Gemini interpretation cannot independently establish continuity. Compare report claims to validated verdicts and check that deferred and unresolved observations remain explicit.

## Offline regression

```bash
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_verification.py
```

The mock exercises four candidates, a newly extracted targeted frame sequence, a subsequent Verification decision, and Reporting. It deliberately leaves all four candidates unresolved. It verifies the evidence path and bounded execution without estimating real model accuracy.
