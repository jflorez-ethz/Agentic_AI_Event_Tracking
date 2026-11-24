# Security, Augmented

Supply a local video to run an automatic investigation. The CLI scans it at a nominal 2 FPS, dispatches work through three LangGraph roles, and writes a cited timeline and report. Questions are optional and run locally. The included WalkSplit replay works offline.

## Open the delivered demonstration

From the repository root with Python 3.12, FFmpeg and ffprobe on PATH. The existing environment uses `.venv/bin/python`. For a fresh environment, install the project with `python -m pip install -e '.[dev,graph]'`. Encoded Gemini clips require FFmpeg with libvpx-vp9. Install Pillow for the optional evaluation sheets with `python -m pip install Pillow`.

```bash
.venv/bin/python -m security_augmented.workflow data/raw/Meet_WalkSplit_pts.mp4 \
  --saved-analysis experiments/mvp_evaluation/delivery_replay/analysis.json \
  --question 'What happened between 10 and 15 seconds?' \
  --question 'Did the two people separate afterward?'
```

The first answer returns the 10–14.52 s movement and its source citations. The second records insufficient evidence for person continuity. Use `--interactive` to ask more questions. Saved mode reads a trusted local workflow artifact and checks the supplied video identity. The output is JSON on stdout. [Replay report](experiments/mvp_evaluation/delivery_replay/report.md)

## Guard report

Each CLI run also writes `report.html` next to `report.md`. It is a plain-language page for a security guard:

- the review queue, with a question for the operator;
- confirmed security events, with before, during and after thumbnails embedded in the page;
- normal activity, one line each;
- limits.

It contains no technical identifiers and links to `report.md`. To regenerate it for saved runs without any model call (the source video must still be at its recorded path for the thumbnails):

```bash
.venv/bin/python -m security_augmented.guard_report experiments/<run>/run [experiments/<run2>/run ...]
```

## Run a new investigation

A live run requires a Gemini API key privately configured as `GEMINI_API_KEY` or `GOOGLE_API_KEY`, authorization for the footage and observation text, and a fresh output directory. This command uses the budgets of the archived WalkSplit evaluation. Run it only after approval.

```bash
run_dir=$(mktemp -d experiments/mvp_live.XXXXXX)
GOOGLE_GENAI_HTTP_CLIENT=httpx \
GEMINI_VIDEO_MODEL=gemini-3.6-flash \
GEMINI_INVESTIGATION_MODEL=gemini-3.6-flash \
GEMINI_VERIFICATION_MODEL=gemini-3.6-flash \
GEMINI_REPORTING_MODEL=gemini-3.6-flash \
.venv/bin/python -m security_augmented.workflow data/raw/Meet_WalkSplit_pts.mp4 \
  --live --authorize-footage-transfer --authorize-observation-text-transfer \
  --max-initial-windows 3 --window-seconds 10 --frame-step-ms 500 \
  --max-candidates 4 --max-inspections 4 --max-agent-calls 14 \
  --max-verification-iterations 4 --output "$run_dir/run"
```

For this 24.96 s source the initial three requests carry 20, 20 and 10 discrete PNGs with timestamps. Verification can request up to four additional inspections of at most 10 s each, using sampled images or a silent encoded clip. Each inline media request is subject to the adapter's 19,000,000-byte size check. Gemini receives those visual inputs and the roles' derived text, including observation descriptions, IDs, citations, task context, instructions and schemas. The cap is **35 physical requests**: seven single-attempt media sends and up to 28 role attempts across 14 reasoning decisions. A role may retry once on a qualifying transport error. Actual use depends on the decisions and response lengths. All four components use HIGH thinking, with 20,480 maximum output tokens for Investigation and 8,192 for the others.

Keep `--frame-step-ms 500` for the initial 2 FPS scan. Verification chooses the step on each targeted **frame** inspection. Omitting `sampling_step_ms` selects 500 ms. It can ask for 250 ms once per movement or independent relational task, with a concrete visual question, a window of at most five seconds and up to 20 distinct source frames. The tool rejects windows that add no new source frames. Shared frames remain in an accepted sequence for context. The existing inspection, payload, iteration and physical request caps still apply. A finer sample changes the number of images in one request. The same evidence validators decide whether the returned observations support a finding.

Inspect the sampling choice, actual decode and result locally after a run:

```bash
jq '.analysis.trace[] | select(.action == "inspect" or .action == "inspection_rejected" or .action == "tool_result")' "$run_dir/run/analysis.json"
jq '.analysis.evidence[] | select(.phase == "targeted" and .modality == "frames") | {status, interval, frames: .inspection.frames}' "$run_dir/run/analysis.json"
```

`report.md` is the human-readable report. `analysis.json` holds observations, evidence from initial and targeted inspections, coverage, timeline, unresolved events, completion metadata, tool transitions and request diagnostics. Use the saved-analysis command above with the new output path. A completed CLI process can produce a partial investigation. For a longer video, check the reported initial-scan endpoint against its duration. The bounded initial scan covers at most the first 30 seconds under this command.

## How evidence moves through the system

1. FFmpeg decodes source frames. Video Perception examines sampled images or a targeted interval and returns observations tied to those inputs.
2. Investigation receives a bounded set of observations. It can search additional stored evidence and allocate candidate slots to individual checks or open-ended relational tasks over compatible observations. Search and relational task creation are optional.
3. Verification can request a source inspection and reconsider its decision. A supported direct movement needs an ordered before/after pair. A spatial relation must independently pass its frame, time, geometry and uncertainty checks. The autonomous perception tool does not establish identity across occlusion.
4. Reporting selects a lead or emphasis. The deterministic renderer preserves citations, attributes model rationales and describes unresolved evidence. Local retrieval uses typed relations and source-time intervals. A supported relation can be retrieved even when its individual movement check failed.

`--movement-only` selects the existing baseline for live comparisons. The separate temporal-coverage A/B experiment has offline request captures. No live A/B result was available for deciding whether to change Investigation's planning context.

## Reproduce the evaluation offline

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q experiments
delivery_dir=$(mktemp -d)
.venv/bin/python experiments/mvp_evaluation/replay_delivery.py --output "$delivery_dir/replay"
.venv/bin/python experiments/mvp_evaluation/delivery_review.py --output "$delivery_dir/review"
```

The replay decodes the actual WalkSplit video, checks the archived source frames, passes archived normalized perception results through the production validation path, and supplies each recorded Gemini decision only when its role and regenerated context match. The two-video assessment checks the pixels behind the final citations and provides review sheets. The first live end-to-end run reached a partial investigation. Independent human adjudication and a live evaluation of the adaptive inspection choice remain outstanding. [Live-run audit and source frames](experiments/mvp_live.UAJd48/audit.md). [Evaluation results and limitations](docs/mvp-delivery.md) · [Two-video visual assessment](experiments/mvp_evaluation/delivery_review/README.md)
