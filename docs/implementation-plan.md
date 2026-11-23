# Implementation plan and first technical experiment

Status: the E1 pilot and offline vertical slice have run. The remaining milestones are proposed. Dates below are relative to project start and assume a six-week course window, to be confirmed with the supervisor. [Architecture](architecture.md) defines the contracts; [evaluation protocol](evaluation-protocol.md) defines measurement.

## Prerequisites and decision gates

- Obtain an authorized short prerecorded CCTV recording with known viewing conditions and permission for any hosted-model transfer; choose a stream and keep the original read-only.
- Obtain model credentials and confirm video/image input, schema support, access, data handling terms and an acceptable budget. Record model ID, provider, SDK and settings.
- Agree on two or three visible event categories and initial acceptance thresholds with the supervisor before the held-out evaluation. Resources, dataset size and project calendar are not yet established.
- Capture Python/OS, FFmpeg and ffprobe versions and available storage. Local VLM feasibility is unknown; no GPU is assumed.

## Experiment E1: source timestamp to observation and replay

**Goal:** test whether one source recording can produce structured observations tied to actual replayable source content, and compare frame-sequence and clip inputs where supported. This is a feasibility experiment, not a reliability or accuracy claim.

**Inputs:** one approved short recording; one manually annotated interval with a visible event and one ambiguous/occluded or empty interval if present; a multimodal model and credentials; FFmpeg/ffprobe; a pinned Python environment. If the recording lacks an ambiguous interval, mark that check blocked rather than fabricate a result. Use the same source interval for both input modalities.

**Procedure:**

1. Hash the original recording, probe the selected stream and record duration, PTS time base, first displayed PTS, frame timestamps and tool versions. Reject unusable PTS instead of using nominal FPS as proof of time.
2. Select a short interval. Decode a small sequence of frames at requested times, retaining each actual decoded PTS and its source-relative time. Extract a short clip from the same interval, retaining actual decoded start/end and the explicit mapping from clip-relative timestamps to the original stream. Record extraction commands/settings and hashes of artifacts.
3. Confirm the chosen model supports each input method. Submit timestamp-labeled frames; separately submit the clip when supported, using the same event taxonomy, question and output fields. Record model/version, prompt, schema, parameters, exact input references and raw response. Avoid sending footage to a hosted model until authorized.
4. Request JSON observations containing category, literal visible description, supporting frame IDs or clip-relative interval, and uncertainty/visibility limitations. Validate schema, allowed categories, nonempty supporting references and the source-time mapping. Reject malformed, fabricated, or out-of-range references; log errors without silently repairing them.
5. Replay each referenced source frame or interval from the original recording. Compare displayed source timestamps and content with the actual submitted visual inputs; retain a replay manifest. For frame references, match actual PTS and image content; for clip references verify the recorded clip-to-source mapping and boundary frames. Report any imprecision, not only the requested seek time.
6. Independently compare descriptions with the original footage using the rubric in the evaluation protocol. Record missed, incorrect and uncertain statements separately for each modality. Repeat the same inputs and configuration and save outputs to inspect variability. Compare outcomes and measured elapsed time/usage; neither method is presumed superior.

**Proposed artifacts:** source manifest (hash and stream metadata), timestamped frame/clip manifest, configuration and prompt, raw responses, validated observations, replay manifest, human review sheet, and a short results log. Keep raw footage and credentials out of version control; choose an approved storage location.

**Acceptance checks:**

| Check | Pass condition or explicit limit |
|---|---|
| Timestamp correctness | For beginning, middle, end and a window boundary in the selected source, decoded frame PTS maps to replayed content. Use exact PTS/time-base comparison; allow at most one source-frame duration for displayed/rounded seek behavior, with actual PTS recorded. Test nonzero start and variable frame rate only if suitable fixtures exist; otherwise record as unverified. |
| Structured output | Valid parse and schema, permitted category, uncertainty field and valid evidence reference; invalid responses fail closed and are retained. |
| Reference integrity | Every cited frame belongs to the recorded inspection or every cited clip interval lies within actual inspected bounds; source hash and interval resolve and replay. A valid reference does not prove its description. |
| Observable description | Independent reviewer can locate and judge each literal observation in the cited content; tally supported, contradicted and indeterminate. Agree any numeric quality target before execution. |
| Ambiguity | A genuinely obscured/ambiguous case yields uncertainty or an inconclusive result, not unsupported certainty; if unavailable, mark untested. |
| Reproducibility | Another run can identify source hash, versions, exact timestamps, prompt, settings, inputs and outputs; compare reruns, without assuming hosted-model determinism. |

If clip input is unavailable, mark the comparison blocked and complete the frames arm only; do not infer relative quality. If timestamps cannot round-trip, repair the extraction/mapping before judging model quality.

## Incremental milestones

| Milestone | Components, dependencies and technical risk | Acceptance criteria |
|---|---|---|
| 1 — Protocol and experiment, weeks 1–2 | E1, prerequisites above; risk: data/API availability and timestamps. | Source-to-model-to-replay path works on an approved recording; positive and ambiguous cases evaluated where available; unsupported checks are recorded. |
| 2 — Shared contracts and storage, week 2 | Versioned video, inspection, observation, claim and verdict records; SQLite; depends on E1 mapping. Risk: lost provenance. | Schema and bounds tests pass; source hash, PTS and evidence chains resolve; contradictory and failed records are retained. |
| 3 — First complete slice, week 3 | Timestamped video-to-text, conservative timeline, time-range/lexical retrieval, candidate alert verification and cited report; initially minimal roles. Risk: integration. | A supplied video automatically yields a timeline and replayable evidence-linked report, then accepts representative questions; ambiguous case ends inconclusive. All four capabilities work end to end. |
| 4 — Multi-agent handoffs, week 4 | Investigator, verifier, reporter and bounded Python controller; depends on contracts and working slice. Risk: redundant calls and correlated errors. | Trace shows agent decisions, tool use, evidence handoffs, verifier reinspection or explicit reason not to, and bounded termination. |
| 5 — Retrieval and evaluation, week 5 | Independently annotated data, FTS baseline, optional embedding comparison, baseline and oracle runs. Risk: annotations and inadequate search recall. | Evaluation produces per-case metrics and failure attribution, including retrieval misses and insufficient-evidence cases. |
| 6 — Held-out review, week 6 | Freeze configuration, run evaluation, document results and limitations. Risk: quality below agreed targets. | Reproducible manifests, actual baseline comparison, costs/usage and a supervisor-reviewable demo of all required capabilities. |

Stop or revise the approach if source timestamps cannot be replayed, if model access or permitted data is unavailable, or if the end-to-end slice cannot complete within the agreed budget. A lexical retrieval failure on predeclared paraphrase criteria triggers the embedding comparison; no result is assumed. Multi-agent requirements remain mandatory even if evaluation shows no improvement over the baseline.

## Video-first vertical slice

1. Ingest a supplied video and bind archived observations to verified source inspections. Use frame observations for initial perception and reserve archived clips for verification. Record the actual coverage and any failed requests.
2. Run the investigation, verification and reporting roles under bounded Python control. Record candidate selection, inspection decisions and handoffs. Build the timeline from resolved evidence and keep unresolved items visible.
3. Query the shared result by time and event language after analysis. Test with the E1 archive, including placement versus abandonment, and run the full offline suite.

## Gemini decisions in the video-first controller

1. Add independently configured Gemini role models behind an authorized, injectable decision interface. Use structured action responses and retain the deterministic workflow as the default.
2. Allow Investigation to search and delegate observation IDs. Allow Verification to request bounded frame or clip inspections, incorporate results into shared evidence, and return a constrained verdict. Validate all IDs, windows, actions, and budgets before execution.
3. Allow Reporting to select a supported lead and choose coverage or uncertainty emphasis. Render all events and citations from verified records, falling back to the deterministic report when the decision fails validation.
4. Exercise both controllers with the same archived LeftBag inputs and scripted decisions. Measure appropriate outcomes and tool choices separately from call counts.

## Controlled role-decision evaluation

1. Load one verified E1 archive snapshot and run both the deterministic baseline and the optional Gemini decisions against it. Keep the entry point archive-only with an explicit text-transfer gate.
2. Bound model calls, tool dispatches, verification turns and failures. Persist validated decisions and tool arguments, plus usage and latency from the SDK. Keep raw reasoning and credentials out of artifacts.
3. Score the paired placement, uncertainty and citation outcomes separately from request count. Verify the CLI and transport offline before any authorized run.

## Optional StateGraph recovery

1. Preserve the saved rejection as a regression case. Distinguish verified evidence insufficiency from invalid citations and tool or API failures using a typed validation error.
2. Add an optional StateGraph that reuses AgentRun for decisions, tools, budgets and rendering. Route a recoverable verdict through feedback to the verifier; keep all other failures on the ordinary termination path.
3. Compare the custom and graph controllers against the same archive and scripted policy, then run the complete offline suite. Keep tracing local and the original controllers available.

## Evidence semantics and completion

1. Separate event correspondence from citation validity. Require a pairwise assessment, grounded in quoted descriptions and a shared source frame, before an agent can corroborate a claim.
2. Return actual sampled or decoded coverage and distinguish missing, partial, covered and failed archive lookup results. Leave original citations intact and exclude findings that straddle the requested scope from that tool result.
3. Record accepted delegation and verdicts separately from interrupted checks. Render completion from validated records, and keep graph evidence state separate from run-owned counters and traces.
4. Reproduce archive and synthetic cases offline, inspect the saved provider failure, and preserve historical artifacts and the deterministic baseline.
