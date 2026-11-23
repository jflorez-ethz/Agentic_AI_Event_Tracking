# Gemini person-continuity probe

The isolated runner reuses the Google GenAI SDK client, environment authentication, single-attempt transport policy and timeout from the existing Gemini integration. The common model is Gemini 3.6 Flash. Each request sends only three original PNGs, neutral frame IDs F1–F3, and the target coordinates from the first and final images. The mapping from these IDs to original frame index, PTS and decoded RGB24 hash is stored locally. Condition labels, filenames, reviewer keys and full video are absent from the payload. The middle image alone changes between K7 and M2; the final target coordinates alone change between K7 and Q4. The offline test compares the actual input parts.

Each packet gets one SDK call, with one maximum HTTP attempt, redirects disabled and no continuation or configured tools. Maximum total is three physical requests. All use the same instructions, schema, 1024 output token cap and LOW thinking level. The runner records raw response text, parsed decision, usage, latency, finish reasons, and validation status. Definite outcomes must cite both endpoints. Valid references alone do not establish a correct correspondence.

## Commands

Run from the repository root:

```sh
plan_dir=$(mktemp -d /tmp/sa-person-plan.XXXXXX)
.venv/bin/python experiments/person_continuity_offline/evaluate.py --output "$plan_dir/plan"
.venv/bin/python -m pytest -q experiments/person_continuity_offline/test_evaluate.py
```

After explicit authorization to send the nine packet images, with the Gemini key configured:

```sh
run_dir=$(mktemp -d experiments/person_continuity_offline/eval.XXXXXX)
.venv/bin/python experiments/person_continuity_offline/evaluate.py \
  --live --authorize-image-transfer --output "$run_dir/run"
```

## Results and scoring

| Packet | Provisional control construction | Independent reference | Model decision | References / usage / latency |
|---|---|---|---|---|
| K7 | Visible continuity | Pending | Unmeasured | Unmeasured |
| M2 | Weakened bridge; abstention not presupposed | Pending | Unmeasured | Unmeasured |
| Q4 | Different target | Pending | Unmeasured | Unmeasured |

Use [the packet form](form-packet.md) before revealing [the continuous-source form](form-source.md). Score what reviewers could establish from each packet independently of what the continuous source reveals. Record correct grounded matches, false matches, justified abstentions, unsupported definite answers (including guesses that happen to agree with the source), and invalid citations. Mark semantic assessment provisional without independent annotations. Three packets on one scene support a diagnostic comparison, with no estimate of general person-continuity performance.

Eight focused offline tests passed. The offline plan verified all images against original decoded pixels and source PTS. No Gemini calls or external transfers were made.
