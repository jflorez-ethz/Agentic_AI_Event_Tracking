# Isolated WalkSplit selection and Perception probes

These probes reuse existing runtime interfaces. Neither starts LangGraph, runs Investigation or Reporting, or executes a Verification-selected inspection. The commands use Gemini 3.6 Flash, HIGH, 8192 maximum output tokens. Each authorized run has a hard ceiling of **one physical request** through the SDK request hook, with no redirects. The prep and frozen-request checks use a local mock transport with a dummy key.

## What was preserved

The Verification probe takes the complete saved `context` for `observation-ac83682fb5f7d3d5ee5c7eeacb15a97e8a0854d2a629f67175c20d78061d5390` directly from `verification-relational-selection-live/result.json`. This includes the corridor-bound movement, deferred reception-bound inspection lead, ten frame references per observation, six remaining model calls, three inspection slots, and four remaining iterations. The saved dispatch state is reconstructed locally, and the returned decision goes through the original decision guard. Any inspection is checked with the original dispatch guards and stops at a local stub. The saved budget describes the decision point seen by the model. The transport cap is the actual authorized budget for the probe.

The original wire body was unavailable. The saved context and recorded model, thinking and output settings are matched against the actual SDK serialization. The system instruction and schema are reconstructed with the unchanged production builder and SDK 3.6.1. They also match the prior enhanced-mode mock capture for this candidate. That earlier capture replayed a different live run's decisions and had eight remaining model calls. The prepared selection probe uses **six** from the target live run. No new words, goals or hints are added to the decision input. The entire serialized request is hashed at preparation and checked before any authorized send.

The fixed-window Perception probe calls the same `_observe_video` targeted path as a relational frames request. It uses the half-open interval **[10,000,000, 13,000,001) µs** with 500 ms requests so 13.00 s is included. Its input carries source images, timestamps, and the existing generic visual instruction and response schema. It receives no archived observation text, reference relationship, expected marks, or person links.

| Frame label | Source index | Source time | PTS |
|---|---:|---:|---:|
| F1 | 250 | 10.00 s | 128000 |
| F2 | 263 | 10.52 s | 134656 |
| F3 | 275 | 11.00 s | 140800 |
| F4 | 288 | 11.52 s | 147456 |
| F5 | 300 | 12.00 s | 153600 |
| F6 | 313 | 12.52 s | 160256 |
| F7 | 325 | 13.00 s | 166400 |

| Probe | Prepared input | Physical cap |
|---|---|---:|
| Verification | 3,380 UTF-8 context bytes and 9,897 serialized body bytes. The archived call reported 2,716 input, 352 output, and 1,503 thinking tokens. | 1 |
| Perception | 7 PNGs totaling 1,610,644 bytes before encoding. Serialized body 2,152,713 bytes. Provider token usage depends on the later response and was not measured offline. | 1 |

The prepared Perception manifest retains source-relative times, canonical frame IDs, PTS, RGB24 hashes and PNG hashes alongside the schema and redacted body. The archived video SHA-256 is verified on each preparation and run.

## Commands

Offline preparation uses a new directory:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/isolated_relational.py prepare \
  --output /tmp/sa-late-relation-plan
```

Run the following **only after explicit authorization** to send the archived observation text:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/isolated_relational.py run verification \
  --prepared /tmp/sa-late-relation-plan \
  --authorize-observation-text-transfer \
  --output experiments/meet_walk_split_high_probes/isolated-selection-live
```

Run the following separately **only after explicit authorization** to send the seven source images:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/isolated_relational.py run perception \
  --prepared /tmp/sa-late-relation-plan \
  --authorize-footage-transfer \
  --output experiments/meet_walk_split_high_probes/isolated-perception-live
```

Use new output directories. Each contains the frozen `input.json` and `result.json`. Check the result status, raw response, transport attempts, and completion and usage metadata. The Verification result includes the archived-runtime dispatch check, selected interval, evidence gap and question when supplied. The Perception result includes normalized citations and the unchanged validator's verdict or rejection. A null proposal is recorded as abstention. An omitted proposal field and an invalid proposal are recorded separately. An exit code of zero indicates artifacts were written.

## Interpret the two outcomes separately

1. A useful relational selection passes the original dispatch guards and asks a concrete question its chosen views could answer. Check timing and evidence independently. An eligible action may still call for weak evidence.
2. If it selects a useful inspection and the fixed probe returns a supported relation, compare the intervals and actual frames. The two results test both capabilities on matched evidence only if the views match. The selection probe never executes its inspection automatically.
3. If it selects a useful inspection and the fixed probe abstains or fails, review frame sufficiency, finish reason and validator diagnostics before attributing the result to Perception.
4. If it does not select a useful inspection but the fixed probe produces a visually defensible relation, selection was the first observed gap on that trial. If both fail, the two probes do not isolate a primary cause.
5. Blind reviewers to the expected outcome and show only the submitted frames before comparing with the model proposal. Judge whether the window addresses the visual question, whether marks track comparable visible points, and whether apparent spacing supports the claim. Human findings stay outside the inputs. Both the fixed-window and selection trials leave identity continuity unresolved unless independently established.

One trial cannot establish a stable selection rate or calibrate mark accuracy. The fixed probe has a reviewer-chosen interval and cannot measure autonomous selection.

```sh
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_isolated_relational.py
```
