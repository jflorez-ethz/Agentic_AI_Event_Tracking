# Investigation 400 diagnosis and isolated retry protocol

The first independent relational-task run received HTTP 400 `INVALID_ARGUMENT` at Investigation, request 1, after 1.275 seconds. Neither a candidate nor token usage was recorded. The runner did not retry. Verification and targeted Perception did not start. The available saved run and local diagnostic artifacts contain no original error message, field violation, error-info entry, or provider response body. The production diagnostic helper retained the status and exception class and raised a generic application error. The earlier mock response was fabricated for trace reproduction and is not provider evidence.

## Reconstructed request and comparison

The SDK reconstruction uses `gemini-3.6-flash`, HIGH thinking, 16,384 output tokens, `application/json`, and `responseJsonSchema`. Investigation gets the first eight of eleven archived observations and may search or delegate. The same model, thinking level and output ceiling were accepted for the archived continuation under `live.CIW3cs/continuation`, which had eleven observations and a delegate-only schema. An earlier first decision accepted a search with HIGH thinking and an 8,192-token ceiling. Neither accepted request is an otherwise identical upstream control.

Toggling the task mode locally adds an optional `relational_tasks` property to the existing delegate branch. Required fields remain `action`, `reason`, `ids` and `dispositions`. Each task row has required `observation_ids` only, with a minimum of two IDs and an enum scoped to currently visible observations. The task list has the existing candidate limit of four, while the runtime still enforces the combined movement/task limit. The JSON Schema dialect check and the actual SDK serialization pass locally. The mock covers valid movement-only and opt-in task outputs and rejects unknown IDs in schema validation.

The added fields use documented constructs. Google documents that large or deeply nested schemas can still be rejected by the provider's grammar compiler. The reconstructed schema is 5,416 compact JSON bytes, versus 5,493 for the accepted continuation schema. Wire size alone cannot establish grammar complexity. There is no field-level evidence linking the HTTP 400 to the new branch, a schema limit, or any other setting. No request fields, prompt, validators, or workflow architecture were changed.

- [Gemini structured-output limitations](https://ai.google.dev/gemini-api/docs/structured-output#limitations)
- [Gemini GenerateContent reference](https://ai.google.dev/api/generate-content)

## One explicitly authorized diagnostic request

The script reconstructs the same initial Investigation context with the existing builder and invokes only that role. The transport hook caps physical sends at one and disables redirects. It never executes a returned action, starts LangGraph, or reads/transmits video frames. Use a new output directory and run only after separate authorization to send the archived observation text:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/investigation_diagnostic.py \
  --authorize-observation-text-transfer \
  --output experiments/meet_walk_split_high_probes/investigation-400-diagnostic-live
```

Inspect `result.json` for the local request number, HTTP and provider code/status, sanitized message, allowlisted field violations and error-info reason/domain, model configuration, SDK version, and body length and digest. The probe does not store request contents, raw provider bodies, credentials, header values, or the returned decision text. If a request succeeds it records completion and the action name, then stops. If the response lacks detailed diagnostics, the reason remains unknown. This command was not executed.

Offline tests:

```sh
.venv/bin/python -m pytest -q \
  experiments/meet_walk_split_high_probes/test_investigation_diagnostic.py \
  experiments/meet_walk_split_high_probes/test_relational_tasks.py \
  tests/test_agents.py tests/test_graph_workflow.py
```

## Confirmed provider rejection and narrow schema update

The subsequent, separately authorized diagnostic at `investigation-400-diagnostic-live/result.json` recovered the provider's explanation. Gemini rejected the request because its structured-output constraint had too many serving states. The error gave examples of possible contributors, including nested array limits and long enums. It did not identify the specific branch or keyword at fault.

The pre-change mock transport reconstructed the exact failed wire body. It was 17,685 bytes with SHA-256 `044b177f11e6eebc7d53650c47ef3b42392dc3cbe5ad9fae415d4ee34df4ca4a`, matching the saved diagnostic. Turning task delegation off with the same context and action menu supplies a structural control. The previously accepted continuation is a separate comparison because it had a different context and a delegate-only action menu.

| Schema | Compact bytes | Max depth | `anyOf` sites / alternatives | Optional properties | Enum sites / entries | Array bounds |
|---|---:|---:|---:|---:|---:|---|
| Failed request | 5,416 | 7 | 2 / 4 | 1 | 11 / 54 | Movement max 4, task max 4, task IDs min 2 |
| Same context with tasks disabled | 4,551 | 7 | 2 / 4 | 0 | 10 / 46 | Movement max 4 |
| Previously accepted continuation | 5,493 | 7 | 2 / 3 | 0 | 9 / 60 | Movement max 4 |
| Revised request | 5,390 | 7 | 2 / 4 | 1 | 11 / 54 | Movement max 4 |

Depth counts the root as one and follows property, item, and alternative subschemas. Enum entries include repeated references. None of the compared schemas uses `oneOf` or numeric `minimum`/`maximum` bounds.

The revised opt-in task branch leaves the two nested array-size constraints to the runtime. The provider schema omits `relational_tasks.maxItems` and `relational_tasks.items.properties.observation_ids.minItems`. Nested task rows and their visible-ID enum are retained. The complete revised request is 17,655 bytes with SHA-256 `0c5ae729d116ffab5d1ae4a9e14f78cfa19742fc47884ee5f0ee0a7bee86c0d5`. The mock comparison confirmed byte-structural equivalence after removing those two fields. The context, instructions, generation configuration outside the schema, and ordinary mode are unchanged.

Runtime still checks the combined movement/task candidate limit, two or more distinct visible IDs, task uniqueness, canonical source references, citation alignment, and temporal overlap. The same runtime validation helpers now run in the isolated diagnostic after a completed role response. A provider error, malformed response, and rejected runtime decision remain distinguishable. The diagnostic applies no search, delegation or verification work.

The measured schema differences do not estimate grammar state counts. Removing nested bounds is a targeted reduction based on the provider's error guidance, not a confirmed attribution of the earlier rejection or proof of acceptance. A successful isolated check would establish acceptance for the revised request on that trial. It would not identify which bound caused the original 400.

Use the same authorization command above with a new output directory, such as `experiments/meet_walk_split_high_probes/investigation-schema-bounds-check-live`. Check `role_call`, `provider_errors` and `decision_validation` in the result. The probe still stops after at most one physical request.
