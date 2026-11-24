# Development progress

## 2026-11-20 — Deterministic frame pipeline

Implemented the frame side of the first development milestone in [contracts.py](../src/security_augmented/contracts.py) and [video.py](../src/security_augmented/video.py), following [the architecture](architecture.md) and [ADR-001](decisions/ADR-001.md). This covers the deterministic portion of E1. The frame/clip experiment and human and model assessments in the [implementation plan](implementation-plan.md) are still open.

- `ingest(path)` hashes the original file with SHA-256, probes the first video stream, and indexes decoded presentation timestamps in display order. The source origin is the first displayed PTS. The duration is the final frame's PTS plus its reported duration, relative to the origin and rounded up to integer microseconds. Missing PTS or final frame duration and decreasing PTS fail explicitly.
- `sample(video, interval, requested_times_us)` selects the first frame at or after each request within the half-open interval using exact rational comparisons. Equal PTS are resolved in display order. Repeated selections share a frame record. A request with no eligible frame maps to `None`. The inspection records the sampling policy, tool version, output format and status.
- Each frame record includes display index, original PTS, source-relative integer microseconds rounded down, and SHA-256 of the decoded RGB24 bytes. `Video.time_at_pts(pts)` returns the exact source-relative time as a fraction of a second.
- `validate_source(video)` checks source identity and file bytes. `validate_reference(video, inspection, frame_id)` checks the inspection and frame membership, reprobes the source metadata, and returns replayed RGB24 pixels after verifying PTS, stream time base, dimensions and pixel hash. Source location can change if the replacement path resolves to the same bytes.
- Records are frozen dataclasses with schema versions and deterministic IDs. Use `dataclasses.asdict` for JSON manifests. The current API is in-process. Each decode reads from the start of the video and buffers the selected RGB24 frames, which suits small inspection windows. Replay also reprobes the full frame index.

## Reproduction

Run from the workspace root with Python 3.11+ and `ffmpeg` and `ffprobe` on PATH. Verified with Python 3.12.6 and FFmpeg/ffprobe 6.1.1-3ubuntu5.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```sh
PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from security_augmented.contracts import Interval
from security_augmented.video import ingest, sample, validate_reference

video = ingest(Path("data/raw/LeftBag.mpg"))
inspection = sample(video, Interval(0, 10_000_000), [0, 1_000_000, 8_000_000])
for frame in inspection.frames:
    pixels = validate_reference(video, inspection, frame.id)
    print(frame.display_index, frame.pts, frame.source_time_us, len(pixels))
PY
```

Seven tests passed. They cover LeftBag replay at the beginning, middle, near the end and at an 8-second window request, deterministic manifests, equal PTS, half-open boundaries, repeated selections, invalid references, altered source metadata and missing, changed or invalid sources. A generated FFV1 fixture verifies replay with a nonzero initial PTS and unequal frame spacing.

## Dataset and next work

- `data/raw/LeftBag.mpg` SHA-256 `8f5d1dbf43d58da1bce57ca1b3f9491b8467773cfd66d2846f62f7d38d4a45e7`. Stream 0 is 384 × 288 with time base 1/90,000, initial PTS 0, 1,440 frames, five adjacent equal-PTS pairs and a decoded duration of 57,839,700 µs.
- `data/annotations/LeftBag.xml` SHA-256 `9599de02b41369065f1c718ec9c934bf1d58b65dc969b88e36c08ca54ab52bb7`. The XML contains 1,439 unique frame numbers from 0 through 1438. Verify alignment with displayed video frames before using it to score the pipeline.
- Continue E1 with clip extraction and clip-to-source replay mapping, then the observation schema and human/model comparison. SQLite, retrieval, agents and the frontend remain pending.

## 2026-11-20 — Video foundation follow-up

### LeftBag annotations

The XML has exactly 1,439 entries numbered 0 through 1438, with no missing or duplicate index inside that range. The video has 1,440 display indices numbered 0 through 1439. The final two decoded images are distinct. LeftBag has repeated PTS elsewhere, but repeated PTS alone do not identify an extra annotation or a repeated image.

The working mapping is **XML frame number → same zero-based display index → original PTS in the probed stream → exact source-relative time**. This puts decoded index 1439 outside XML coverage. The reason for the count difference and the identity of the unmatched frame under an independently confirmed mapping are unresolved. The XML has no per-frame PTS or external pairing metadata.

I inspected overlays for XML indices 0, 40, 80, 320, 540, 737, 900, 1110, 1364, and 1438 against decoded indices at offsets −1, 0 and +1 where available. I also inspected enlarged comparisons for selected moving objects, including frames 225, 449, 468 and 499. Same-index boxes track the visible subjects or objects at the checked points. Static and empty frames provide little offset evidence.

For a second check, I decoded grayscale frames in display order, subtracted the per-pixel temporal median of every tenth decoded frame, and thresholded the absolute difference above 30 grayscale levels. For each eligible XML object box (width and height at least 12 px, XML indices 5 through 1434), I compared offsets −4 through +4. The score was twice the foreground pixels inside the box divided by the box area plus the foreground pixels in its 15-pixel padded neighborhood. The mean scores at offsets −1, 0 and +1 were 0.50892, 0.51005 and 0.50704. Some subranges favored adjacent offsets, and a foreground-center weighting check slightly favored +1 overall. The overlays and scores support the same-index working mapping at the scene level, with insufficient evidence to establish a unique frame-exact mapping. Keep that uncertainty in any annotation-based scoring.

| XML index | Working display index | Source PTS | Source time (µs) |
|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 |
| 1 | 1 | 25,173 | 279,700 |
| 80 | 80 | 313,173 | 3,479,700 |
| 81 | 81 | 313,173 | 3,479,700 |
| 900 | 900 | 3,261,573 | 36,239,700 |
| 1438 | 1438 | 5,198,373 | 57,759,700 |
| — | 1439 | 5,201,973 | 57,799,700 |

[annotations.py](../src/security_augmented/annotations.py) parses objects, groups, boxes, and hypotheses, and rejects invalid, duplicate, or missing indices. `align_leftbag` applies the working mapping only to the checked asset hashes on stream 0, and keeps the display index even when PTS are shared.

### Clips and multimodal contract

- `extract_clip(video, interval)` returns a versioned `ClipInspection` and playable, video-only Matroska/FFV1 bytes. It selects each displayed frame with an onset in the requested half-open interval, retains repeated PTS in display order, and rebases the first selected frame to clip PTS zero. A request containing no frame onset raises `VideoError`.
- The manifest keeps the requested interval, source bounds from the first selected onset to the last selected frame's reported end, and the actual clip duration. The source bounds can extend past the requested end by the last frame's presentation duration. The per-frame mapping retains the source PTS, display index, and decoded clip PTS. Source timestamps remain exact. Matroska uses millisecond ticks, and verification checks each rounding error against half a tick and the final endpoint against one tick.
- Extraction and `validate_clip(video, inspection, bytes)` compare the decoded RGB24 pixels for every frame with the original footage and verify the media format, timestamp map, and artifact hash. FFmpeg uses single-threaded filtering and encoding, bitexact flags and timestamp passthrough. Current operations decode from the start and buffer the selected pixels, so use short windows.
- [observation.py](../src/security_augmented/observation.py) defines a replaceable `ObservationProvider` protocol. Inputs carry timestamped RGB24 images or a verified clip artifact. Results carry structured observations and inference metadata, with validation of allowed categories, inspection IDs, evidence membership and visibility/uncertainty fields. Clip-relative citations resolve through the recorded per-frame map. New frame manifests bind RGB24 dimensions. Older manifests can still replay, and can be resampled to populate dimensions for model input.
- No provider has been selected or called. The verified media contract is ready for local adapter work. An adapter needs to confirm the provider's supported input formats. If it transcodes the clip, retain and validate a separate mapping for the exact submitted artifact.

### Verification and next milestone

The complete suite passed **18 tests** with Python 3.12.6 and FFmpeg/ffprobe 6.1.1-3ubuntu5. This includes all seven earlier tests, repeated PTS, a 300 µs Matroska rounding case, source boundaries, nonzero start, a VFR clip with a 120 ms final frame, artifact and pixel tampering, annotation parsing, and multimodal evidence validation. Re-run with the command under Reproduction above.

Next, choose an authorized provider and run the E1 frame-versus-clip comparison on the same source windows. Record the exact submitted artifacts and mapping, raw results, model and prompt metadata, and independent human replay assessment. Use annotation offsets only with the uncertainty described above.

## 2026-11-20 — E1 Gemini adapter and offline pilot

- Added the [Gemini Developer API adapter](../src/security_augmented/gemini.py) behind `ObservationProvider` and the [paired pilot runner](../src/security_augmented/e1.py). Both arms produce the same observation records with explicit source video IDs and inference metadata. Frame labels resolve to actual frame IDs. Model-supplied clip bounds resolve through the verified WebM-to-source map. They are approximate citations.
- [E1 pilot protocol](e1-pilot.md) records the official model, media, pricing, authentication and quota references, the selected windows, XML relevance limits, offline reproduction commands and the human review rubric. The local pilot prepared all six requests. Windows A, B and C produced 8, 2 and 8 image parts and clips with 100, 20 and 100 encoded frames. No media was sent. Gemini's actual processed frames, observations, token usage, latency and cost remain unknown.
- Live inference is blocked by missing external-processing authorization and API credentials. The SDK is absent in this environment and a local installation attempt failed because package-index DNS was unavailable. Offline tests use an injected SDK client double and run real media encoding and replay checks. The separate, opt-in live suite uses a synthetic image.
- Keep explicit timestamped frames as the provisional MVP baseline for traceability and sampling control. After live access is authorized, run both arms, preserve their outputs and perform the independent footage review before making a model-quality or cost recommendation.
- Verification with Python 3.12.6 and FFmpeg 6.1.1-3ubuntu5 passed all 24 offline tests, including the 18 existing tests and six new integration tests. The separately discovered live smoke test was skipped. The standalone dry run also prepared all six LeftBag requests successfully.

## 2026-11-20 — Python packaging

Added setuptools packaging in `pyproject.toml` for Python 3.12+ with package discovery under `src/`. The project declares the Google GenAI SDK as a runtime dependency and pytest 9+ in the `dev` extra. The SDK range now includes the installed 3.x series and matches `requirements-e1.txt`. Default pytest discovery targets `tests/`. The opt-in live suite remains in `tests_live/`.

In a Python 3.12+ virtual environment, run `pip install -e '.[dev]'` and `python -m pytest -q` from the workspace root. FFmpeg and ffprobe are still required for the video tests.

Verified `pip install -e .` using local build wheels in the existing Python 3.12.11 virtual environment. With `PYTHONPATH` unset, the package imported from `src/` and pytest 9.2.0 reported **24 passed, 19 subtests passed**. No external API calls were made.

## 2026-11-21 — Gemini 3.5 Flash-Lite preflight

The user reported a successful text-only Gemini authentication test returning `OK` and consuming 7 tokens. The installed Google GenAI SDK is 3.6.1. Select the reported model through `GEMINI_MODEL` or the runner's `--model` option. The two-frame `--smoke` path uses the existing evidence contracts and requires a nonempty, validated observation before it counts as successful.

SDK mock transport confirmed the Developer API `v1beta` generateContent JSON serialization for inline PNG with separate timestamp text and inline WebM with `videoMetadata.fps = 2`. Both use the existing response JSON Schema, LOW thinking and a 4,096 output-token cap. The model documents image/video, structured output and LOW thinking support. [Model](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) · [Thinking](https://aistudio.google.com/docs/thinking)

CAVIAR lists the acted footage under CC BY-SA and asks for publication attribution to the EC Funded CAVIAR project/IST 2001 37540. Google's Swiss/paid data-use terms exclude prompts and responses from product improvement and allow limited logging and transient processing outside Switzerland. Verify the project/account conditions before sending. [CAVIAR](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) · [Gemini terms](https://aistudio.google.com/docs/terms)

Authorization requested for one smoke request at approximately 37.44 and 37.92 seconds, then at most 12 paired requests if it succeeds. Per repetition, the comparison would send 18 PNGs and 8.8 seconds of silent WebM across the three existing windows. The XML stays local. Standard paid pricing is USD 0.30 per million input tokens and USD 2.50 per million output/thinking tokens. The 13-request plan is estimated below USD 0.15 at the planned caps and expected input sizes. [Pricing](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite)

No project footage was sent during preflight. Live work awaits explicit authorization and a key available to this workspace process.

The offline suite passed **24 tests and 19 subtests**. The dry run prepared PNGs at 37,439,700 µs and 37,919,700 µs. A separate run through the installed SDK's mock HTTP transport validated the two PNG request parts and parsed a fixture observation. No provider inference or usage was measured during these checks.

Smoke-only transfer authorization received for the two selected LeftBag PNGs. No comparison or additional footage is authorized. The workspace process still has neither `GEMINI_API_KEY` nor `GOOGLE_API_KEY` configured, so no live request was attempted and no model output, token usage, or API error was observed.

## E1 comparison 001 — Local review

Reviewed all six saved requests and responses in `experiments/e1_comparison_001/`. The audit verified all 18 PNGs and 220 encoded clip frames against the original source pixels and PTS, reconstructed the SDK payloads locally, and replayed all ten cited frame references. Five responses passed structured validation. The A clip returned HTTP 503, leaving the positive pair incomplete. B clip's empty array is indeterminate for ambiguity scoring. Both C outputs agree with the negative control. No modality ranking is supported.

See [the E1 comparison 001 review](e1-comparison-001-review.md) for coverage, token metadata, source observations and acceptance criteria. The smallest follow-up after separate authorization would be a single unchanged retry of the archived Window A clip. No request was sent during this review.

Offline regression suite passed **24 tests and 19 subtests**. Application code and experiment artifacts were kept unchanged.

## E1 Window A clip retry — Offline preparation

Added `--retry-clip` to the existing E1 runner. It checks the archived WebM hash and size, replays the recorded inspection against the source, verifies every archived clip frame and timestamp, and dispatches the archived model, prompt, schema and generation settings through the existing Gemini adapter. The CLI requires a fresh output directory outside the original run. Live mode makes one request, with HTTP retries and SDK-side continuation disabled.

The offline dry run reproduced the original request manifest and WebM bytes exactly and left the original artifacts unchanged. No live call was made. Mocked responses exercised transport/API and output-validation failures, a resolving citation, an out-of-range citation, an incomplete candidate and an empty result. The retry records one attempt with the raw response, observations, resolved source frames, latency and available usage. Valid responses without placement are marked `missed_positive`. A placement claim is marked `placement_reported_review_required` until its cited content has been reviewed.

After explicit transfer authorization and with credentials available in the environment, run from the workspace root:

```sh
.venv/bin/python -m security_augmented.e1 \
  --retry-clip experiments/e1_comparison_001/window-a/clip \
  --output experiments/e1_comparison_001_a_clip_retry_001 \
  --live --authorize-footage-transfer
```

The complete offline suite passed **30 tests and 24 subtests**. An installed-SDK mock transport check also confirmed one HTTP request for a response carrying a continuation token, with no continuation setting added to the wire payload.

## Video-first offline vertical slice

The workflow starts from a video path and requires no question. `security_augmented.workflow` ingests and verifies source identity, replays archived PNG and WebM evidence, and revalidates the archived Gemini observations with the existing observation contract. Three bounded role policies select candidate findings, request complementary evidence, record verdicts and handoffs, and render a chronological report. An in-process `analyze_video` entry point accepts an explicitly supplied observation provider for new video and bounds initial frame windows and clip reinspection. The offline CLI uses archives and needs no credentials.

The [LeftBag demonstration](../experiments/e1_offline_investigation_001/report.md) produced one corroborated placement and left the shorter handling interval unresolved. The [structured result](../experiments/e1_offline_investigation_001/analysis.json) contains source PTS, evidence IDs, the decision trace, and four example queries. The placement evidence does not establish abandonment, unattended duration, or subsequent retrieval. Frame and clip observations came from the same model, and agreement is corroboration rather than independent validation. The archive covers selected windows, not the entire recording.

To reproduce the offline demo, use a new output directory:

```sh
.venv/bin/python -m security_augmented.workflow data/raw/LeftBag.mpg \
  --archive experiments/e1_comparison_001 \
  --archive experiments/e1_comparison_001_a_clip_retry_001 \
  --output /tmp/leftbag-investigation \
  --question "What happened between 00:30 and 00:45?"
```

Use `--interactive` for further questions after the report. An unmatched explicit time-range query can return up to three source frame references for inspection. No footage or API requests were sent. The next implementation milestone is persistent shared evidence and evaluation of replaceable role policies over additional footage. Hosted role reasoning and broad natural-language retrieval have not been evaluated.

Verification: **35 offline tests and 24 subtests passed**. The CLI demonstration independently produced two initial observations, one supported timeline event, one unresolved finding, and 19 trace entries.

## Gemini decision layer

The deterministic controller remains the offline baseline. The optional Gemini decision layer adds structured search and delegation, bounded frame or clip reinspection, shared inspection findings, constrained verdicts, and grounded report emphasis. Use `AgentModels.from_env()` for independent configuration, and `GeminiDecider.from_env(authorized=True)` only after approval for the relevant data transfer. For the authorized programmatic path, pass the resulting callable as `decide` to `analyze_archive`, or pass its `adapter` as the video provider and the callable as `decide` to `analyze_video`. The existing archive CLI remains deterministic and offline.

On identical archived LeftBag evidence, the scripted LLM policy retained the baseline's one corroborated placement and one unresolved finding. It chose one clip inspection versus the baseline's two, then reused the result while retaining uncertainty on the shorter handling window. Negative tests reject unauthorized execution, unavailable tools, fabricated citations, missing corroboration and repeated inspections. Competing evidence stays unresolved and failed tool calls stay visible. This comparison exercises controller behavior with mocked decisions. It does not measure Gemini's actual decision quality or show an improvement in perception.

No live Gemini calls were made and no experimental archives were changed.

Verification: **45 offline tests and 24 subtests passed**. A separate local HTTP mock exercised installed SDK 3.6.1 serialization for a structured role request and verified a single request to the configured model route. The source reinspection regression also confirms that repackaging identical frames under a new inspection ID cannot satisfy corroboration.

## Archive-only Gemini role evaluation preparation

Added `security_augmented.agent_eval` to compare both controllers against one verified seven-attempt snapshot. The default command is offline. The live option has a separate observation-text transfer gate, uses the same Gemini model for all three roles, and does not wire in an observation provider. Added per-role usage and latency records, structured tool arguments and results, and explicit failure and verification-iteration limits.

See the [controlled evaluation protocol](agent-evaluation-001.md) for the exact command, external data fields, six-call limit, and paired acceptance criteria. No live Gemini calls were made.

Offline verification passed **49 tests and 24 subtests**. The CLI dry run found one placement, one unresolved finding, and three resolving citations, with zero model requests. An installed SDK 3.6.1 HTTP mock confirmed a text-only payload and returned usage capture. Live execution is pending authorization for the observation text and an API key available to the process.

## Optional LangGraph recovery

Reviewed the saved first live role evaluation. Its premature supported verdict failed the corroboration rule, consumed the sole execution-failure allowance and stopped before any evidence lookup. StateGraph now supports a separate bounded route for missing corroboration. The verifier receives structured feedback, may request a validated inspection, and reconsiders the finding using returned evidence. The original controller and deterministic baseline remain selectable. No archived experiment was modified.

The offline scripted comparison used the same seven attempts. The deterministic baseline found one supported placement and one unresolved finding with two lookups. The custom controller with the scripted decisions stopped after two decisions, made no lookup and left two findings unresolved. StateGraph finished with one supported placement and one unresolved finding, using six scripted decisions, one lookup, three resolving citations and zero invalid citations. This demonstrates recovery from the saved failure mode. It does not measure Gemini reasoning, accuracy or live costs.

Install the optional `graph` extra with `pip install -e '.[graph]'` if LangGraph is unavailable. The package index was inaccessible in this workspace, so verification used the locally available LangGraph 1.2.14 and existing Google GenAI SDK. Run from the workspace root using a new output directory:

```sh
.venv/bin/python -m security_augmented.agent_eval data/raw/LeftBag.mpg \
  --archive experiments/e1_comparison_001 \
  --archive experiments/e1_comparison_001_a_clip_retry_001 \
  --output /tmp/leftbag-graph-recovery \
  --scripted-recovery
```

The command writes the three reports, execution traces and existing evaluation metrics to the selected directory. No live model calls, hosted tracing, or data transfers were performed.

Final offline verification with LangGraph 1.2.14 passed **56 tests and 27 subtests**. A regression test also verifies that invalid controller settings or an unavailable graph dependency fail before the new-video path calls its observation provider.

## Live StateGraph evaluation preparation

The existing live CLI selects StateGraph with `--controller langgraph`. It stays archive-only and uses `gemini-3.5-flash-lite` for all three roles. The evaluation records the selected controller and explicit graph transitions. Rejections now identify schema, tool, or verdict validation in the trace, separately from transport outcomes and recoverable missing corroboration.

The [StateGraph evaluation protocol](agent-evaluation-001.md#first-live-stategraph-run) records the command, scope of the text transfer, acceptance criteria, and the decision to retain the six-request cap. No live request or external data transfer was made.

Verification passed **57 offline tests and 29 subtests**. The live CLI branch was exercised through the installed SDK with a local HTTP mock, including direct retrieval in five requests and recovery in six. Both used text-only payloads and produced one supported placement, one unresolved finding and valid citations. No API key is currently available to the workspace process. Live execution still requires explicit authorization to transfer the documented text and a configured key.

## Evidence semantics and failure reporting

The archived third Gemini role call in `experiments/e1_agent_langgraph_001/evaluation.json` is a Verification `ServerError` with HTTP 503 after 4,012 ms. It occurred after the graph returned missing-corroboration feedback. The record contains no provider status, body, or retry hint, so the provider-side cause cannot be established. The archive was preserved. Future role failures retain allowlisted provider status and numeric Retry-After when present, without saving raw messages or headers. Retry behavior is unchanged.

Root causes addressed: verdicts previously treated category and temporal overlap as correspondence, archive tools used requested bounds as coverage and treated zero matches as complete, and a failed investigation could reach Reporting with an indistinguishable empty candidate list. The new [architecture contracts](architecture.md#correspondence-coverage-and-completion-contracts) define explicit pairwise grounding, actual source-relative coverage and completion status. The graph owns retrieved evidence in graph mode, the Python controller remains selectable, and the deterministic baseline remains unchanged. The new check preserves already supported findings if a later recovery fails.

No live Gemini calls or evidence transfers were performed. Pairwise semantic correspondence is still a model judgment constrained by real excerpts and cited frames; it requires human review in evaluation. The shared-frame criterion is conservative and can leave genuinely matching observations unresolved when their sampled frames are disjoint.

Full offline verification passed **69 tests and 29 subtests**. The scripted archive replay again produced one supported placement, one unresolved finding, and no invalid citations with StateGraph. It recorded both checks as completed. The original Python path still stopped on its terminal rejection policy and recorded zero completed verification checks.

## Controlled Gemini role retries

Both archived live StateGraph runs stopped on HTTP 503. The latest was an Investigation call returning `ServerError` / `UNAVAILABLE` after 1,054 ms. The earlier failure was Verification during recovery. Neither error establishes a fault in agent reasoning.

Inspected the installed Google GenAI SDK 3.6.1 synchronous `generate_content` path. It routes requests through its Tenacity policy, but the existing client explicitly sets `HttpRetryOptions(attempts=1)`, which includes the initial send. Thus it did not retry 503s. That SDK setting stays in place. The single retry layer now lives in the text-only role client and waits one second plus uniform jitter up to one second before a single resend on HTTP 408, 500, 502, 503, or 504. HTTP 400, HTTP 429, exceptions without an HTTP response, and structured-output or evidence validation failures do not trigger a resend. The SDK's 90-second request timeout remains in place. The media adapter's single-request behavior is unchanged.

The evaluation still permits six logical calls, including any Reporting call. Physical sends are capped at twelve per run and two per logical request. The trace stores per-attempt HTTP status, safe provider diagnostics, and retry delay separately from model usage and workflow actions. Reported token and cost totals only include provider-returned usage. Offline HTTP fixtures cover immediate success, 503 then success, terminal 503, HTTP 400, and a lowered physical cap. The LangGraph fixtures verify that retries do not duplicate tools, that terminal 503s stop further Gemini calls, and that a partial report preserves an already-verified placement. No live request or external transfer was made.

After explicit authorization, use a fresh output directory and run:

```sh
.venv/bin/python -m security_augmented.agent_eval data/raw/LeftBag.mpg \
  --archive experiments/e1_comparison_001 \
  --archive experiments/e1_comparison_001_a_clip_retry_001 \
  --output experiments/e1_agent_langgraph_003 \
  --controller langgraph --live --authorize-observation-text-transfer
```

This run reuses the archive and sends only role instructions and text context. It does not invoke media perception or send images or video.

Full offline verification with `.venv/bin/python -m pytest -q` passed **70 tests and 32 subtests**.

## Gemini model availability and synthetic compatibility

The third archived StateGraph run received HTTP 200 for Investigation and initial Verification, then entered recovery. The recovery decision returned HTTP 503 / UNAVAILABLE on both sends. The retry waited 1.69 seconds. The logical recovery request took 11,166 ms including that delay. Three logical calls produced four physical requests. No recovery decision was returned. The second archived run failed on its first request, so the observed failures do not establish that consecutive role requests are the trigger. Keep pacing unchanged for the first comparison. If failures later correlate with request spacing or quota evidence, compare fixed pacing with no pacing under identical model, synthetic payload, and retry settings. [Google API troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting)

The archive CLI now reads `GEMINI_INVESTIGATION_MODEL`, `GEMINI_VERIFICATION_MODEL`, and `GEMINI_REPORTING_MODEL` independently. Each still defaults to `gemini-3.5-flash-lite`. Video selection remains independent through `GEMINI_VIDEO_MODEL` (or the existing `GEMINI_MODEL` fallback). The archive CLI still bypasses video inference. The six logical calls and twelve physical attempts, single bounded retry policy, and deterministic failure reporting are unchanged. No provider or model fallback was added.

Google documents structured outputs for the incumbent `gemini-3.5-flash-lite` and alternatives `gemini-3.6-flash` and `gemini-3.8-flash`. The older `gemini-3.5-flash` alias is deprecated and routed to 3.6 Flash. [Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) · [3.6 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash) · [3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) · [3.5 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)

After separate authorization, use the configured API key and the development extra (`pip install -e '.[dev,graph]'`). Run the catalog first and probe each listed candidate explicitly. Save stdout in a fresh local directory if needed.

```sh
.venv/bin/python -m security_augmented.agent_probe --authorize-synthetic-probe --list-models
.venv/bin/python -m security_augmented.agent_probe --authorize-synthetic-probe --model gemini-3.5-flash-lite
.venv/bin/python -m security_augmented.agent_probe --authorize-synthetic-probe --model gemini-3.6-flash
.venv/bin/python -m security_augmented.agent_probe --authorize-synthetic-probe --model gemini-3.8-flash
```

The catalog is an authenticated, potentially paginated `models.list()` metadata request with no prompt. It lists entries advertising `generateContent`. Catalog visibility alone does not establish generation access. Each model probe sends at most two logical generation requests and four physical attempts. The payload contains the production role instructions and JSON schemas, identical generation settings, and synthetic toy-block observation text, placeholder IDs, intervals, and missing-corroboration feedback. It loads no archived observations or media and executes no tools. [Models API](https://ai.google.dev/api/models)

Compare catalog status, requested and returned model versions, HTTP status and attempt count, local JSON Schema validity, elapsed time including retries, and provider-reported token counts. Require a completed, schema-valid response from both roles before marking a model compatible. Keep API errors, invalid output, and schema failures separate. A single passing pair establishes compatibility for those requests and does not measure decision quality or availability rates. Current key-specific availability remains unconfirmed because no live API calls or data transfers were made during preparation.

Offline verification passed **75 tests and 32 subtests**. Local HTTP mocks exercised catalog pagination and filtering, the exact on-wire Investigation and Verification schemas, rejection of schema-invalid output, token capture, and the existing HTTP retry path. The CLI configuration test confirms independent role and video selection with the original request limits.

## Observation triage and investigation completion

The archived Gemini 3.6 Flash run `experiments/e1_agent_langgraph_004/evaluation.json` confirmed one placement with two source citations and one clip lookup. All four role calls succeeded. Investigation explicitly selected the placement and ignored the ambiguous initial observation. Its delegation schema had only candidate IDs and a global reason. The old completion calculation compared accepted verdicts with that queue, so its 1/1 result concealed the omitted evidence.

The model-guided controllers now record delegated, associated, deferred, excluded, and system-detected omitted dispositions. Associations reuse grounded event correspondence. Optional Verification resolutions must link the associated observation to accepted corroboration from a separate inspection with additional source frames. Unresolved associations, deferrals, and omissions retain source citations without creating verification tasks. The report separates initial-observation accounting, verification queue status, and full investigation completion. The deterministic baseline, video pipeline, and archives were preserved. [Completion contract](architecture.md#correspondence-coverage-and-completion-contracts)

The archived omission regression can be replayed offline with:

```sh
.venv/bin/python -m pytest -q tests/test_graph_workflow.py -k silently_omitted_handling
```

The fixture delegates only placement and uses the archived clip to corroborate it. Verification finishes 1/1, triage records 1/2, and the report retains the ambiguous observation as unresolved and the investigation as partial. The independent scripted-recovery comparison remains available through `security_augmented.agent_eval --scripted-recovery` with the two original E1 archives.

Exclusion relevance and whether later evidence truly clarifies ambiguity remain model judgments. The validator checks record shape, exact excerpts, shared frame anchors, independent inspection, and frame novelty. A valid relationship can remain unresolved if samples do not share a frame. Initial evidence outside the bounded shortlist must still be retrieved before it can be accounted for. Live Gemini compatibility of the updated schemas has not been tested. No data was sent externally.

The offline scripted-recovery CLI accounted for 2/2 initial observations and completed 2/2 checks on StateGraph. It produced one supported placement, one unresolved finding, three valid citations, one evidence lookup, and six scripted decisions. The original Python scripted path also accounted for 2/2 observations but completed 0/2 checks after its terminal rejection, so the investigation remained partial. The full offline suite passed **84 tests and 32 subtests**.

## New-video MVP integration

The integration audit found that the programmatic video-to-observation-to-agent path already existed. The missing pieces were a new-video CLI entry point, configurable initial sampling, and persistent coverage and inspection metadata. The CLI now connects the existing Gemini SDK adapter and StateGraph controller. It requires separate authorizations for media and derived observation text. It defaults the three reasoning roles to Gemini 3.6 Flash for this mode and preserves independent video model selection. The archive mode and deterministic baseline remain available.

The new offline fixture has independently checked pixel transitions at 2.0 and 6.0 seconds. Through the installed SDK with local HTTP mocks, the positive path used two frame requests, one targeted clip, and four role decisions. It returned a placement-proxy finding with source-replayable frame and clip citations, accounted for the initial observation, and retrieved the same evidence through a post-analysis question. Tests also cover a missed transition, an unresolved false observation, a rejected citation, and a budget-truncated scan. No live calls or data transfers were made. A real annotated-video evaluation remains pending. [Audit, exact live command, transfer contract, and scoring plan](new-video-evaluation.md)

Full offline verification with `.venv/bin/python -m pytest -q` passed **89 tests and 32 subtests**. FFprobe independently confirmed the documented fixture generation produces 40 frames across eight seconds.

## Visibility-transition verification

Audited both saved eight-second fixture runs against the original decoded video. In the completed run, the appearance lookup sampled only pre-transition frames, the requested clip contained the first white frame at its end and returned no observation, and the global inspection and reasoning limits prevented a second inspection for disappearance. The two accepted insufficient verdicts were justified for the physical action labels.

The model-guided path now distinguishes literal visibility changes within the existing category field. It can accept a model-assessed explicit before/after pair of cited source frames for those claims. The action corroboration rules, event-correspondence validator, deterministic baseline, and archives are preserved. [Evidence audit, acceptance contract and controlled comparison](visual-transition-verification.md)

The controlled comparison used two initial media observations, four scripted decisions and zero targeted inspections to support both literal brackets (1–2 s and 5–6 s), with 2/2 observations accounted for. The LeftBag scripted LangGraph replay retained one placement, one unresolved finding and three valid citations, using one tool call and six scripted decisions. The full offline suite passed **99 tests and 32 subtests**. No live calls or evidence transfers were made.

## Local retrieval for visual transitions

Replayed `/tmp/security-augmented-visual-test-20261121-173823/analysis.json` against local retrieval. The supported timeline already contained both visual transitions. “Visual changes” missed both the category matcher and the broad-query rule, leaving a label-token overlap filter that discarded both events. Seconds-based ranges also bypassed the clock parser and unintentionally searched the full timeline.

The matcher now recognizes broad visual-change terms and seconds ranges while retaining the existing category and overlap filters. Answers return the original supported events and citations and display the actual visibility brackets. On a missed physical-action query, a related visibility finding can be noted without returning a physical-action event. Time queries with no inspected evidence state the coverage gap. Where a bracket crosses a gap, the answer preserves timing uncertainty. The recorded artifacts were left unchanged.

| Recorded query | Before | After |
|---|---|---|
| What visual changes occurred in the video? | No results | Appearance at 1–2 s and disappearance at 5–6 s |
| What appeared in the video? | Appearance only, label text | Appearance only, bracket and original citation |
| When did the object disappear? | Disappearance only, label text | Disappearance only, 5–6 s bracket and original citation |
| What happened between 1 and 3 seconds? | Both transitions | Appearance only |
| Did someone physically place the object? | No result, generic uncertainty | No placement event. The answer explains the related appearance and causal limit |
| Did a person enter the scene? | No result, absence unproven | Same conservative result |
| What happened between 7.2 and 7.8 seconds? | Both transitions | No results. The answer identifies the uninspected interval |

Replayed all eight cited source frames for the two findings against the original video. Source and inspection IDs, frame membership, PTS, and pixel hashes matched. Verification's selected bracket frame indices were 5 and 10 for appearance, and 25 and 30 for disappearance. Retrieval remains lexical and cannot generalize to arbitrary paraphrases or infer causes. No live calls or data transfers were made.

Full offline verification passed **99 tests and 32 subtests**, including the existing LeftBag retrieval checks.

## Meet Walk Together budget comparison

The first live run at `experiments/meet_walk_pts_20261122_013252/` accounted for 4/4 observations, delegated two candidates, completed one check, and reported no supported events. All six logical reasoning calls succeeded. Its inspection plan used three 10-second windows and 1-second frame steps.

The video-first CLI now accepts `--max-candidates`, `--max-inspections`, `--max-agent-calls`, and `--max-verification-iterations`, with the existing defaults of 2, 2, 6, and 3. The effective settings are recorded under `analysis.budget`. The output also records separate physical role and media limits and their sum. With 4, 4, 14, and 4 and the original sampling plan, the caps are 28 physical role requests and 7 single-attempt media requests, or 35 total. The next run can compare the delegation and verification counts, supported and unresolved findings, actions, and provider usage in a fresh output directory. No live call was made for this change.

Full offline verification passed **100 tests and 32 subtests**. The SDK mock exercised default and expanded flags and checked the serialized configuration and request caps.

## Candidate-local inspection recovery

The saved expanded-budget run at `experiments/meet_walk_pts_budget14.VxoEyL/run/analysis.json` used four successful HTTP 200 role calls. Verification proposed support for the first candidate without corroboration and spent its one recovery. Its first tool request was frames over [8,000,000, 9,000,001) µs. It returned a person-entry observation with partial coverage, reusing both original source frames at PTS 102400 and 115200. The rejected second request has no raw arguments in the historical trace. The rejection reason and code path identify the same modality and interval key because only one of four inspection slots was used. No second tool executed. The old graph logged the duplicate as a run-wide failure, reaching `max_failures=1`. It reached both later candidates and Reporting, but the model-call guard blocked all three despite remaining logical and physical capacity.

The graph now records a structured candidate-local inspection rejection with exact request parameters, code, and tool constraints. With recovery allowance left, the verifier can propose a different inspection or finish with insufficient evidence. Missing corroboration and inspection rejection share the existing candidate-local allowance. Rejected inspection arguments or a rejected verdict do not spend the run-wide failure budget. The Python baseline, evidence validators, and global provider or tool-execution failure policy are preserved. An executed lookup with no archived matching evidence still returns no evidence. [StateGraph contract](architecture.md)

The offline replay used the three recorded initial observations and the recorded targeted result. Before the change it reproduced 0/3 completed checks, four scripted calls, and one inspection. After the change it produced 2/3 completed checks, seven scripted calls, and one inspection. The first candidate remained unfinished because it had spent its sole recovery. Later candidates each received a scripted insufficient verdict. No supported findings were added. A separate synthetic test with a second recovery available used a genuinely different inspection with new source frames and valid correspondence, completed 3/3 checks, and retained the strict support requirement. Additional cases verified that logical exhaustion and provider errors still prevent later calls, and every candidate receives a final status. No live Gemini calls or external transfers were made.

Full offline verification passed **104 tests and 32 subtests**, including the HTTP-mock global failure and physical request-cap checks.

## Meet Walk Together entry verification audit

Replayed the candidate-isolated run against its recorded observations and original source. A's repeated grid yielded no novel cited frame. C's off-grid frames were novel but shared no cited frame and the inspection slots were exhausted. B's correspondence passed, but the verdict included the visibility-only `transition` field. Restricted that field in the Gemini verdict schema to visibility candidates. The validators and tools are unchanged. The scripted schema-corrected counterfactual completed 2/3 checks versus 1/3 and produced one validator-accepted finding. Local review favors continuous movement across A and B and leaves the physical boundary claim unestablished. [Full evidence audit](meet-walk-entry-audit.md)

Full offline verification passed **105 tests and 32 subtests**.

## Narrowing person-entry claims

The person-entry audit exposed a representation limit: event categories were fixed to their seeds, so a verifier could withhold an entry claim but could not retain person visibility or movement on its own. The model-guided workflow now supports those two direct visual categories and explicit refinement using the existing ordered, source-cited frame-pair checks. Physical entry still requires grounded corroboration and now requires a physical boundary phrase shared by the accepted correspondence excerpts. Existing association rules remain in place.

On identical recorded Meet Walk Together inputs, the scripted replay produced A as first visibility (8–9 s), kept B insufficient, and retained C as movement within view (27–28 s). It completed 3/3 checks versus 1/3, with 11 role decisions, four inspections and no supported physical entry in either replay. The original claim and refinement are visible in the trace. Semantic quality of live decisions remains unevaluated. No data was transferred. [Audit and replay](meet-walk-entry-audit.md#claim-refinement-on-the-same-evidence)

Full offline verification passed **113 tests and 32 subtests**, including LeftBag and the synthetic visual-transition regressions.

## Visibility question handoff: live A/B and 500 ms forwarding fix

Ran one authorized live pair on the WalkSplit relational task (3.52–9.52 s): a specific visibility question versus the generic objective, with only Verification and Perception live. A blinded packet comparison against a user-confirmed, AI-assisted provisional reference was a tie. Both packets bracketed loss and recovery of separate distinguishability at 6.00–6.52 s and 7.00–7.52 s. Neither final verdict addressed distinguishability; both accepted an approach relation. Calls were equal (2 Verification + 1 Perception per arm), with 30,226 vs 30,725 total tokens. The independent reviewer forms remain blank.

The trace exposed a handoff defect. At the 500 ms step, Verification's logged `visual_question` was not passed to the Perception tool; it was forwarded only at 250 ms. `AgentRun.reinspect` now uses one validated question for both the trace and the tool call. A mock-transport regression replays both archived decisions and checks the serialized request byte-for-byte against the archived body hash, minus the question sentence. It fails when the 250 ms-only forwarding is restored. The live run therefore measured evidence selection only; the question's effect on Perception output is unmeasured. [Record](../experiments/relational_question_handoff/visibility-live.md)

## CAVIAR LeftBox and Rest_FallOnFloor: falls, triage priority, corroboration recovery and operator review

Two new CAVIAR clips were evaluated live with HIGH thinking, three 10 s windows at 500 ms, and only the first 30 s. `LeftBox.mpg` lacks usable PTS, so it is replayed from a lossless FFV1 copy, `LeftBox_pts.mkv`, whose decoded frames are pixel-identical. `Rest_FallOnFloor.mpg` ingests directly. CAVIAR XML frame numbers must be converted through decoded PTS, not frame/25. The fall clip's `drop down` label is a per-track context, not the fall time; the fall appears in `movement` (26.44 s PTS).

- **person_fell.** A new direct visual category: upright before, lying on the floor after. It is checked by the existing ordered before/after frame-pair contract. Sitting, crouching or partial occlusion is insufficient. A person-entry candidate cannot be refined into a fall. Tests use a synthetic upright-to-lying video end to end. In the live fall run, `person_fell` was supported at 26.04–27.52 s, consistent with the frames. [Fall run](../experiments/fall_live.spFaYl/run/report.md)
- **Investigation priority.** In the first LeftBox run, Investigation spent all four slots on `person_moved` and deferred the correctly described box placement as "secondary". Every non-routine event category must now be delegated or associated before any slot goes to `person_moved`, `person_appeared` or a relational task. All such observations are visible to Investigation. A violation gets one feedback round; a repeated one is enforced by the runtime, so no check is lost. An Investigation-only live replay, with text only and no media, delegated the box and the fall 3/3 each directly from the prompt (6 requests, about $0.16). [Replay](../experiments/investigation_priority_replay/live-20261124T002515/results.json)
- **Corroboration recovery.** In the next LeftBox run, the box was delegated first. The corroborating 500 ms inspection was then rejected before dispatch because every frame was already sampled, and that rejection consumed the only recovery. Pre-dispatch rejections now get their own feedback round. The `no_new_frames` feedback says to use 250 ms over at most five seconds or to shift the interval. Physical-action candidates also see `new_frames_at_500ms_in_citation`. Investigation sees 16 observations in the CLI (`--max-visible-observations`); archived replays keep 8. Role calls archive the returned decision. In the following live run, Verification inspected at 250 ms and the box was supported (15 requests, about $0.26). [Before](../experiments/leftbox_live.1iXjTj/run/report.md) · [After](../experiments/leftbox_live.HwKyEx/run/report.md)
- **Operator review queue.** Following the group plan's guardrails (PDF p. 8), unconfirmed security events become `needs_review` alerts, and the report opens with **Alertes à vérifier**. Each alert gives what, when, a short frame selection, why it is unconfirmed (a deterministic reason code) and an operator question. Strict `supported` and every evidence consumer are unchanged. A step-0 simulation over 17 archived runs found 11 candidate alerts:
  - 2 true box alerts;
  - 8 `person_enters_area` that cannot be confirmed without a configured zone;
  - 1 contradicted fixed object.

  With entries deferred until zones exist (plan detector C1), and only never-dismissed categories alerting when contradicted, the archives yield 2 alerts, both true. `analysis.review` records counts and alerts with an empty `operator_label`, and the CLI writes a blind `alerts.csv`. [Operator review](operator-review.md)

Open: blind labelling of alerts, direct visual verdicts with affirmative reasons (to be diagnosed from the archived decisions), configurable thinking level, monitored zones, and coverage after 30 s.

Full offline verification passed **153 production tests and 32 subtests** and **204 experiment tests**.
