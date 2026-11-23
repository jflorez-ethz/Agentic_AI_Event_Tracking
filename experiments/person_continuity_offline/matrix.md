# Person-continuity target marking × thinking matrix

Video perception defaults to Gemini 3.6 Flash and requests HIGH thinking. Existing explicit video model overrides still apply. Reasoning role settings, production validators, and orchestration are unchanged. No production video workflow was executed.

The matrix uses Gemini 3.6 Flash across all eight requests. Each packet retains the original textual coordinates and uses source frames 250, 300 and 325 as F1, F2 and F3. Endpoint marking uses a thin red ring, radius eight pixels, with an untouched center. The marked versions and source metadata are under `matrix-offline/marked/`. Original PNGs are unchanged. F2 is copied byte-for-byte. The two marked F1s are identical, and only the ring placement differs across marked F3s. The requests send no case or arm name or expected answer.

All cells use the same endpoint-specific instructions, structured schema and 4096 output-token ceiling. LOW versus HIGH is the only generation change. There is one physical HTTP attempt per cell, with SDK retries, redirects and continuations disabled by the existing client configuration. The earlier LOW run used a different ceiling and remains historical evidence.

| Arm | Images | Thinking | K7 outcome | Q4 outcome | Endpoint adherence / correspondence / references / independent reference |
|---|---|---|---|---|---|
| A | Original | LOW | Pending | Pending | Unmeasured |
| B | Original | HIGH | Pending | Pending | Unmeasured |
| C | Marked | LOW | Pending | Pending | Unmeasured |
| D | Marked | HIGH | Pending | Pending | Unmeasured |

Score endpoint adherence from the rationale and frames. Score temporal correspondence separately, including justified abstention. A structurally valid citation is insufficient to establish semantic correctness. Independent annotations are pending, so any semantic judgment remains provisional. One response per cell is a diagnostic result and cannot estimate performance reliably.

Each result retains the requested and returned model version when supplied, thinking level, marking flag, exact source-image references, raw and parsed response, validation result, finish reasons, latency, and provider-reported input, output and thinking tokens when provided.

From the repository root, after explicit authorization to send the matrix images:

```sh
run_dir=$(mktemp -d experiments/person_continuity_offline/matrix.XXXXXX)
.venv/bin/python experiments/person_continuity_offline/evaluate.py \
  --matrix --live --authorize-image-transfer --output "$run_dir/run"
```

Maximum: **eight HTTP requests**, three PNGs each. Omit both live flags for offline preparation.

Offline verification passed **113 tests and 32 subtests** in the production suite and **10 tests** in the isolated harness suite. No Gemini calls or transfers were made.
