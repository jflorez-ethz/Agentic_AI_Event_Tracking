# Matched 2 FPS and 4 FPS perception probe

Both arms inspect [5.000000, 20.000000) seconds of Meet_WalkSplit_pts.mp4. They use the existing perception prompt snapshot, production event categories, response schema, and Gemini adapter. Configuration is Gemini 3.6 Flash, HIGH, 8192 output tokens. The production CLI rejects a 250 ms step at its InspectionPlan guard, so this isolated probe supplies the timestamp grid directly to the existing sample function. No production validation or architecture changes were made.

The sampler chooses the first presentation frame at or after each source-relative grid point, within the half-open window. Repeated selected frames share one record; these arms have no repeats or misses. PNGs are sent as individual inline image parts with actual source timestamps. No video clip, video_metadata FPS, or Files API upload is used. Encoded clips in the other production mode can be sampled independently by Gemini. Image parts establish what will be submitted; provider processing of each part is not observable here. [Google image guide](https://aistudio.google.com/docs/image-understanding#technical-details-image) and [video guide](https://aistudio.google.com/docs/video-understanding).

| Arm | Sent image parts | First and last possible source references | Raw PNG bytes | Actual SDK JSON bytes |
|---|---:|---|---:|---:|
| 500 ms | 30 | index 125 / PTS 64000 / 5.00 s → index 488 / PTS 249856 / 19.52 s | 7,084,435 | 9,451,288 |
| 250 ms | 60 | index 125 / PTS 64000 / 5.00 s → index 494 / PTS 252928 / 19.76 s | 14,145,660 | 18,869,564 |

Presentation time base is 1/12800. Realized sparse gaps are 480 or 520 ms. Dense gaps are 240 or 280 ms. Every sparse selection matches its even-position dense selection in source index, PTS, actual timestamp, RGB24 hash, and submitted PNG bytes. The differing last selected times are a consequence of the grids inside the same requested boundary. The local [500 ms manifest](sampling_pair_plan/step-500/input.json) and [250 ms manifest](sampling_pair_plan/step-250/input.json) record the full grids, image hashes, request configuration and serialized body fingerprints.

The installed SDK serialized both requests through a local mock transport. Both are below the project's 19,000,000-byte ceiling, with 130,436 bytes of headroom for 4 FPS. The dense body is about 99.7% larger. Google's general image guide lists a much higher image count cap than 60, and its general inline limit is model/file dependent. The project cap is the operative local check. Exact provider acceptance and account limits have not been tested with this payload. [Google file input methods](https://aistudio.google.com/docs/file-input-methods#method-comparison).

The historical 20-frame [perception run](live.ttMLDy/media/result.json) reported 21,818 prompt tokens at this model and configuration. If that scale holds, 30 and 60 images would be roughly 33k and 65k prompt tokens. This is a rough extrapolation from another window. Actual tokens, latency, and billed cost are unknown. Image count and payload bytes cannot determine thinking usage, finish reason, or semantic accuracy. The archived runs also differ in windows and sometimes settings, so they cannot be the 2 FPS counterpart.

## Offline and authorized commands

Run from the repository root. Reproduce both arms into a fresh directory as needed:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/sampling_pair.py prepare \
  --output /tmp/meet-walk-sampling-pair
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_sampling_pair.py \
  experiments/meet_walk_split_high_probes/test_probe.py
```

Only after explicit authorization for both arms:

```sh
probe=experiments/meet_walk_split_high_probes/sampling_pair.py
plan=experiments/meet_walk_split_high_probes/sampling_pair_plan
out=$(mktemp -d experiments/meet_walk_split_high_probes/sampling-live.XXXXXX)

.venv/bin/python "$probe" run --prepared "$plan" --frame-step-ms 500 \
  --authorize-footage-transfer --output "$out/step-500"
.venv/bin/python "$probe" run --prepared "$plan" --frame-step-ms 250 \
  --authorize-footage-transfer --output "$out/step-250"
```

Each command permits one physical request, two total. Retries, redirects, and continuation are disabled. The probe verifies the frozen SDK request bytes before permitting the send. Each output includes the input manifest and result with raw decision text, resolved observations when valid, HTTP status and attempts, completion reasons, usage and latency. HTTP 200 with MAX_TOKENS remains a failed arm. No downstream agent runs. The only footage sent is the arm's timestamped PNG sequence. No provisional audit descriptions are included in the prompt.

## Blank comparison template

First record successful completion, provider model version, input/thinking/output tokens, latency and attempts per arm. If an arm fails, retain its result and mark the semantic comparison incomplete. A rerun requires separate authorization.

| Criterion | 500 ms outcome, observation IDs and source frames | 250 ms outcome, observation IDs and source frames | Independent review or uncertainty |
|---|---|---|---|
| Two distinguishable individuals | | | |
| Movement and direction toward the upper part of the scene | | | |
| Decrease in apparent separation near 6–8 s | | | |
| Correspondence through overlap or occlusion | | | |
| Visible divergence or insufficient evidence of separation | | | |
| Unsupported relations, omissions, visibility limits and timestamp errors | | | |

Use the [provisional source review](approach-anchor-audit.md) and the [later source-frame audit](supported-findings-audit.md) outside the model prompt. Judge movement, projected convergence, correspondence and separation separately. Two people moving along similar paths or an individual becoming difficult to see do not settle identity or intent. The current schema has movement categories and free-text descriptions, without a validated person continuity field. Score whether the raw descriptions and cited frames warrant the relationship and whether the output acknowledges uncertainty. A single pair is exploratory even if both arms succeed.
