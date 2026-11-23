# Meet Walk Split video-first evaluation

The existing live entry point is `python -m security_augmented.workflow`. It ingests and samples video, invokes Gemini for observations, and runs the three roles through LangGraph. Investigation triages observations and delegates candidates. Verification can request bounded frame or clip inspections and validate proposed verdicts against source-linked observations. Reporting selects a supported lead or emphasis and the deterministic renderer produces the report. No question is required to start analysis.

The adapter defaults to `gemini-3.6-flash`; the workflow resolves `GEMINI_VIDEO_MODEL`, then legacy `GEMINI_MODEL`, then the default. Video requests set `thinking_config.thinking_level=HIGH` directly. Video Perception, Verification, and Reporting use HIGH thinking with an 8192-token output ceiling. Investigation uses HIGH thinking with a 20480-token ceiling. The command pins all requested model IDs. Check the returned video model and requested thinking setting in the saved inference records after the run.

## One authorized run

Use only after explicit authorization for both sampled footage and derived observation text, with the Gemini API key configured. The 500 ms sampling, three 10-second windows, and agent limits match the previous 500 ms run. The source lasts 24.96 seconds, so the schedule reaches the final window. Coverage remains discrete unless a targeted clip supplies a span.

```sh
run_dir=$(mktemp -d experiments/meet_walk_split_high.XXXXXX)
GEMINI_VIDEO_MODEL=gemini-3.6-flash \
GEMINI_INVESTIGATION_MODEL=gemini-3.6-flash \
GEMINI_VERIFICATION_MODEL=gemini-3.6-flash \
GEMINI_REPORTING_MODEL=gemini-3.6-flash \
/usr/bin/time -f '%e' -o "$run_dir/wall-seconds.txt" \
.venv/bin/python -m security_augmented.workflow data/raw/Meet_WalkSplit_pts.mp4 \
  --live --authorize-footage-transfer --authorize-observation-text-transfer \
  --max-initial-windows 3 --window-seconds 10 --frame-step-ms 500 \
  --max-candidates 4 --max-inspections 4 --max-agent-calls 14 --max-verification-iterations 4 \
  --output "$run_dir/run"
```

Maximum: 14 logical reasoning calls, 28 physical reasoning attempts, and seven single-attempt media requests, for 35 physical requests total. The media cap includes up to three initial and four targeted requests. Gemini receives timestamped PNG frames or targeted silent WebM with metadata, instructions and schemas, and derived evidence context for role calls. Follow-up questions are optional and stay local. With no question, the workflow still writes the report and analysis and leaves `answers` empty.

## Offline no-question regression

```sh
.venv/bin/python -m pytest -q tests/test_new_video.py -k archived_scan
```

The test replays the 11 observations from [the archived scan](../experiments/meet_walk_split_high.Cpby7p/run/analysis.json) through the real CLI, FFmpeg sampling, and LangGraph. A local mock transport supplies the archived observations and scripted decisions. The test checks the search continuation from eight to 11 visible observations, all 11 dispositions, the four-candidate schema limit, and the targeted source frames. It covers a valid empty targeted response, an incomplete response, and an HTTP 503. The scripted movement verdict checks the existing evidence contract. Semantic correctness and autonomous model decisions still require evaluation against the footage.

## Output and scoring checklist

| Capability | Existing output | Check |
|---|---|---|
| Video-to-text | `analysis.json → analysis.observations`, `analysis.evidence[]`, and `analysis.coverage` | Check actual sampled timestamps and failed requests, especially [20,24.96). Replay a cited frame against its source index, PTS and pixel hash. Compare each observation's semantic claim with the frames and separate visibility, movement and causal interpretations. |
| Event reconstruction | `analysis.timeline`, `analysis.unresolved`, `analysis.completion`, `analysis.trace` | Check chronological brackets and observation associations. Did Verification actually inspect the relevant aftermath? If the evidence cannot distinguish joint movement, divergence or loss of trackability, record that limit. An association, shared frame, or nearby interval is insufficient to establish identity continuity on its own. |
| Evidence retrieval | `analysis.json → answers[]` | Score whether returned events and citations address the aftermath, not merely earlier movement. The local query parser matches lexical categories, explicit times and supported timeline items. It does not resolve the word “after” against a prior event or infer subsequent relationships. The explicit time question tests retrieval within a later interval; on no match it may attach local frame references without generating a new interpretation. |
| Reporting | `report.md`, `analysis.trace`, `analysis.completion` | Compare each report statement and citation with the accepted verdict and source images. Check that coverage gaps and unresolved findings remain visible, and that triage completion is not confused with verified continuity. |

Record total wall seconds from the sibling `wall-seconds.txt`. Use top-level `role_calls[]` for models, statuses, latency, attempts and reported token usage, and `analysis.evidence[].inference` for media metadata and usage when available. Count targeted attempts by `phase=targeted`, distinguish failed and successful results, and read `inspect`, `tool_result`, `correspondence`, `evidence_insufficient`, `inspection_rejected`, `verdict_rejected` and `model_failure` trace entries. Compare meaningful handoffs and new cited evidence, not just call counts. Sum provider-reported metrics only where present; provider latencies differ from elapsed wall time.

## Historical comparison

- [500 ms, Gemini 3.5 Flash-Lite / LOW](../experiments/meet_walk_split_500ms.bqVoWC/run/analysis.json): six reasoning calls, one targeted request [0,2) s, 3/3 completed checks, and two supported movement findings. The later finding ended at 14.52 s.
- [1,000 ms, Gemini 3.5 Flash-Lite / LOW](../experiments/meet_walk_split_eval.LDnYfL/run/analysis.json): nine reasoning calls, one targeted request [0,3) s, 4/4 completed checks, and three supported movement findings, the last ending at 14 s.

Neither historical run recorded a targeted inspection of the aftermath or saved answers to these questions. Compare the new run descriptively. The perception model and thinking setting both change, and stochastic execution can affect choices, evidence and completion. The live outcome remains unmeasured until an authorized run produces artifacts.

## Failure audit of the first HIGH run

The preserved run is [meet_walk_split_high.Lgrgbb](../experiments/meet_walk_split_high.Lgrgbb/run/analysis.json). Wall time was 74.16 s.

- **Middle media window [10,20) s:** Local decoding produced 20 frame references and Gemini returned a model revision, token usage and 25,607 ms elapsed time. The evidence record has `failure_stage=validation` and the exact error “Gemini did not return one normally completed candidate.” The adapter stopped at the completion guard, before observation JSON/schema validation or citation processing. The other two windows completed. The failed inspection retained its decoded frames but supplies no successful observation coverage. Video media attempts use the single-attempt SDK path. The saved record does not retain the middle window's physical HTTP trace, candidate count, finish reasons, or raw response. It cannot establish whether the candidate count was unexpected or a finish reason was non-STOP. Provider-reported 369 output and 3,709 thinking tokens sum to 4,078 near the configured 4,096 cap. That is suggestive but does not establish truncation or causation by HIGH thinking.
- **Investigation:** The single request returned HTTP 200 in 2,529 ms, with 4,641 prompt and 365 candidate tokens. `received` means the role wrapper passed the single STOP candidate guard and parsed JSON. The trace records `delegate` and then “Unknown, duplicate or excessive evidence IDs.” Rejection occurred in the ID guard before writing any dispositions or delegation. The raw decision is missing, so the exact failure within that guard cannot be recovered. The rationale about accounting for five observations does not establish that the ID list had five entries. LangGraph routed from Investigation to an empty queue, then Reporting. The validation rejection consumed the one global failure allowance, so no Verification or Reporting model calls ran. The deterministic report retained the unresolved evidence. The logical reasoning budget was not exhausted.
- **Correction:** The Investigation schema now communicates the same maximum delegate count that the runtime already enforces. Runtime errors distinguish excess count, unknown IDs, and duplicates. Failed media evidence stores bounded completion diagnostics, and role call records include candidate count and finish reasons where available. These changes preserve strict validation and do not retry an incomplete response or change HIGH video/LOW reasoning settings.

A full paid rerun is premature as the next diagnostic. If separately authorized later, isolate the original middle window with its exact input and existing settings, and confirm that the provider accepts the bounded delegation schema in a small role probe. Use the resulting finish reason and validation record to decide whether a further change is justified. No change to model settings follows from this trace alone.

For the current CLI, saved-run questions, typed relational anchors, and two-video delivery evaluation, use the [MVP delivery guide](../README.md). The historical runs and failure audit above retain their original settings.
