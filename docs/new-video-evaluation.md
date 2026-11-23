# New-video end-to-end evaluation

## Integration audit

| Component | Existing connection | Change for this run |
|---|---|---|
| Source ingestion | `analyze_video` calls FFprobe and FFmpeg and keeps source identity, timestamps, and frame provenance. | Expose it through the workflow CLI. |
| Automatic inspection | `analyze_video` scheduled fixed 10-second windows and sampled at 1-second intervals. | Make window length, sample spacing, and window count configurable within controlled limits. |
| Gemini video understanding | The observation provider already handled frame sequences and clips. | Connect the existing Gemini adapter in the new-video CLI. |
| Evidence storage and provenance | The workflow kept observations and citations in run-local records. | Retain inspection metadata, media inference metadata, and attempted, examined, and uninspected coverage in the JSON output. |
| Investigation | The existing role receives initial observations and produces dispositions and a verification queue. | Use the current role interfaces. An uncovered or failed initial scan is visible in completion. |
| Verification and tools | Archive mode reads stored observations. New-video mode already performs targeted frame or clip inference. | Keep the existing validation, correspondence, and tool budgets. |
| LangGraph | `analyze_video` already accepts the optional StateGraph controller. | Select it for this live CLI mode. Preserve the archive CLI and deterministic baseline. |
| Reporting | Python renders findings and citations after the Reporting Agent selects emphasis and a supported lead. | Include scan status and a caveat about shared-model corroboration. |
| Natural-language retrieval | The `Analysis.ask` interface already retrieves supported events and supports local frame inspection. | Reuse `--question` and `--interactive` after automatic analysis. |

## Input and ground truth

Use this eight-second fixture for the first controlled integration run. It is new to this evaluation and has no archive. It contains 40 frames at 5 fps. At source time 2.0 seconds a white block appears. At 6.0 seconds it disappears. At 1.8 and 6.0 seconds the test pixel is black, and at 2.0 and 5.8 seconds it is white. There is no person and no visible actor placing or removing the block. The test harness uses the two transitions as known positive cues to exercise the pipeline. The fixture can validate integration and timestamp localization, while a later independently annotated real clip is required to evaluate real-world event semantics.

```sh
demo_dir=$(mktemp -d /tmp/security-augmented-new-video.XXXXXX)
ffmpeg -v error -f lavfi -i color=c=black:s=96x64:r=5:d=8 \
  -vf "drawbox=x=30:y=30:w=25:h=20:color=white:t=fill:enable='gte(t,2)*lt(t,6)'" \
  -c:v ffv1 "$demo_dir/block.mkv"
```

## Authorized execution

Install the graph extra and configure `GEMINI_API_KEY` or `GOOGLE_API_KEY` through the environment. The flags below must be supplied only after authorization for both the media and derived-text transfers. Run this command in the same shell as the fixture generation. Investigation starts from the file alone. The optional question runs after analysis and can also be omitted.

```sh
GEMINI_INVESTIGATION_MODEL=gemini-3.6-flash \
GEMINI_VERIFICATION_MODEL=gemini-3.6-flash \
GEMINI_REPORTING_MODEL=gemini-3.6-flash \
GEMINI_VIDEO_MODEL=gemini-3.5-flash-lite \
.venv/bin/python -m security_augmented.workflow "$demo_dir/block.mkv" \
  --live --authorize-footage-transfer --authorize-observation-text-transfer \
  --max-initial-windows 2 --window-seconds 4 --frame-step-ms 1000 \
  --output "$demo_dir/run" --question "What happened between 00:01 and 00:03?"
```

The CLI writes `report.md` and `analysis.json`. The JSON contains model selection, per-role transport attempts, usage and elapsed time when available, inspection records, observations, timeline, unresolved findings, citations, trace, completion, coverage, and optional question results.

### External data and bounds

- Initial media requests contain inline PNG bytes, frame labels and source-relative timestamps, perception instructions and output schema. For this fixture the two planned windows are [0, 4) and [4, 8) seconds. Each supplies four PNGs. More generally the plan scans a contiguous prefix until the initial-window budget or end of source.
- Verification can request a targeted frame input or an inline silent WebM clip from the source. Clip requests include clip-relative citation instructions and requested FPS. Locally validated clip frame maps resolve those citations to exact source frames. A successful WebM request records the submitted span. Gemini's actual internal sample times remain unknown.
- Role requests contain role instructions, schemas, derived observation text, evidence IDs and timestamps, coverage and tool results, and selected verification or reporting context. The media and role requests use the existing SDK authentication. Post-analysis questions, local source-frame lookups, and report generation stay local.
- Allow two initial media requests and up to two targeted media requests in this command, for **four physical media requests** at most. Media calls are single-attempt. Reasoning has **six logical calls and twelve physical HTTP requests** at most, with the existing bounded retry policy and a reserved Reporting slot. Total maximum is **16 physical requests**. The offline positive path used three media requests and four role requests. A live run can use fewer or more within the limits. The evaluation also caps candidates at two, retrievals at one, verification iterations at three per candidate, missing-corroboration recovery at one per candidate, and terminal role failures at one. Media outputs have a 4,096-token cap per request and role outputs a 1,024-token cap.
- The general CLI permits up to three initial windows of at most ten seconds and a frame step of at least 500 ms. An initial or targeted frames request contains at most 20 unique frames. Targeted clip requests are bounded at ten seconds. Payload limits can cause large inputs to be rejected locally. This raises the general media request maximum to five when all three initial windows are enabled.

## Score the evaluation

| Check | Acceptance or measurement |
|---|---|
| Event detection and errors | Compare each observation and each final finding with the labeled source. Count supported matches, missed positive cues, and false claims separately. On the fixture, judge appearance and disappearance separately from unsupported human actions, and retain uncertainty when the taxonomy cannot express the cue literally. |
| Temporal accuracy | Compare cited source times with the labeled transition and report whether the cited frames bracket or show it. Record timing errors and the available sampling resolution. |
| Citations | Every reference resolves to the original video, inspection, frame index, PTS and pixels. Reject a provenance mismatch regardless of semantic plausibility. |
| Coverage | Record scheduled windows, failed attempts, exact successful sample times, submitted clip spans, and gaps. Each frame sample uses a one-microsecond point marker for bookkeeping. A successful scan of the planned windows does not imply continuous coverage. An uninspected interval does not establish absence. |
| Investigation | Inspect each initial observation's disposition. Check that missed triage and failed or truncated initial scans remain incomplete, and that uncorroborated findings keep their uncertainty. |
| Verification | Check whether the selected action can answer the open question. Review the status and shared-frame grounding of each association. Agreement between inspections run by the same model is corroboration within this workflow, with no independent semantic confirmation. |
| Report and query | Check that the report contains only supported findings and explicitly unresolved items. Ask a relevant time or activity question after analysis and compare its returned citations with the report. A no-match response should preserve uncertainty. |
| Reliability | Record media and role failures separately from misses. Compare role attempts, latency, and returned usage, marking unavailable values as missing. |

The initial scan is a bounded temporal sample. Short events can fall between samples, and the role context and candidate budgets can leave observations pending. Clips may be subsampled by the provider. Provider availability and the revised role schemas still need live verification on the new input. The fixture and local mocks verify plumbing, provenance and failure handling. They do not estimate real-world accuracy.
