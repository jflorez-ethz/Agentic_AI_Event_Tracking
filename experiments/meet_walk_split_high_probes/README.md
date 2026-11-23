# One-request stage probes

From the repository root, run the positional subcommands `media`, `investigation`, and `continuation` without live flags to write local input plans. Each requires a fresh `--output` directory.

Media reproduces [10,20) s at the archived 500 ms sample schedule. It checks 20 frame references, PTS and RGB hashes, then rebuilds PNGs with the production adapter. `input.json` records exact reconstructed prompt parts, frame maps, PNG hashes and Gemini 3.6 Flash / HIGH / 8192 settings from the production adapter. The old artifact lacks original PNG bytes and the serialized prompt; the probe reconstructs them from the saved inspection and the live workflow prompt. `result.json` records HTTP status when available, candidate count, finish reasons, completion and validation status, usage and latency. MAX_TOKENS is recorded without changing settings or retrying.

Investigation reconstructs the 11 observations from `experiments/meet_walk_split_high.Cpby7p/run/analysis.json` and passes the original Budget to the production Investigation method. Production exposes eight observations in the initial decision and signals additional evidence. A search selection is recorded, but the probe cannot send a second decision request. Its separate pre-send cap prevents any additional model calls. `input.json` records evidence IDs, exact context and bounded schema. The request uses Gemini 3.6 Flash / HIGH / 20480 with a four-candidate delegation limit. `decision.json` holds parsed output when available. `result.json` retains raw text, role diagnostics, HTTP attempts, delegation result and validation trace. No perception, Verification, Reporting or LangGraph run is invoked by this probe.

Continuation loads the 11 observations and the recorded 14.52–24.96 s search result from [the automatic run](../meet_walk_split_high.uGljGL/run/analysis.json). It reconstructs the second decision context using the production serializer and validator. The archived wire body is unavailable. The probe starts with the first decision and search already charged to their budgets. Its input plan records the archived interval and returned IDs. Its output records the raw candidate text, parsed decision when available, transport and completion diagnostics, usage, latency, validated delegation and observation dispositions.

The historical second request returned HTTP 200 and one `MAX_TOKENS` candidate with 7,860 thinking and 315 candidate tokens. The reconstructed role context grows from 10,009 to 13,769 UTF-8 bytes. Its 11 observation descriptions are distinct. The search result repeats three identifiers in 268 bytes and includes no duplicate observation bodies. Frame IDs recur across observations that cite the same frames. With search complete, the schema exposes only the bounded delegate action. Triage of 11 observations plausibly increased the reasoning load, but the trace establishes the ceiling as the cause of termination and does not explain the provider's internal token allocation. Use the continuation probe before another full run. Look for one `STOP` candidate, accepted delegation within the four-candidate limit, and dispositions accounting for all 11 observations.

The [first live continuation](live.O6q6N8/continuation/result.json) finished with STOP at HIGH / 16384. Its disposition `id` contained an unknown string, while its nested `correspondence.id` referred to the real appearance observation. The former schema accepted any string at both positions. The current schema enumerates visible canonical IDs for delegation and every disposition observation reference. Runtime checks still enforce uniqueness, candidate membership and correspondence grounding. For the 11-observation continuation the compact schema grows from 1,144 to 5,534 UTF-8 bytes. This is a local size measurement. Provider acceptance, completion and usage with the larger schema still require a separately authorized continuation probe.

The SDK is configured for one attempt with redirects and continuation disabled. An independent pre-send cap enforces at most one physical request per probe. Offline HTTP-mock tests cover the request path, including STOP, MAX_TOKENS, valid bounded delegation, an HTTP 503 without retry, and authorization.

After separate explicit authorization for the corresponding footage or derived observation text:

```sh
probe_dir=$(mktemp -d experiments/meet_walk_split_high_probes/live.XXXXXX)
.venv/bin/python experiments/meet_walk_split_high_probes/probe.py media --live \
  --authorize-footage-transfer --output "$probe_dir/media"
.venv/bin/python experiments/meet_walk_split_high_probes/probe.py investigation --live \
  --authorize-observation-text-transfer --output "$probe_dir/investigation"
.venv/bin/python experiments/meet_walk_split_high_probes/probe.py continuation --live \
  --authorize-observation-text-transfer --output "$probe_dir/continuation"
```

A full rerun is justified only once the middle request returns one STOP candidate and valid observations (or a valid empty result) and the Investigation probe returns a normally completed decision that passes validation for the evidence visible in that request. A valid empty media result warrants checking whether the evaluation needs usable middle-window observations before rerunning. If either probe fails, use its diagnostic before authorizing additional calls. Success verifies stage execution and contracts, not semantic accuracy or future reliability.
