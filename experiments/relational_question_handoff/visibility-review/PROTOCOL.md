# Visibility evidence selection

Give each independent reviewer only the lossless views.png, instructions.txt and one blank CSV in reviewer/. Keep the manifest, SDK captures, planning context, other judgments and prior reports private from reviewers. Lock the two originals before revealing model selections. From this directory compare completed copies using:

```bash
../../../.venv/bin/python ../visibility_reference.py manifest.json /path/to/locked-1.csv /path/to/locked-2.csv
```

The reference covers sampled instants across the full 3.52–9.52 s interval. Thirteen are original in-scope cited frames; twelve are interleaved local source views. The two extraction windows are reference preparation only. A live task would have one optional fine inspection, five seconds and 20 unique frames maximum. No particular inspection window, rate, marks or reviewer labels appear in either Verification input. The incoming evidence includes original model descriptions (including relational wording) and canonical citations. Verification reads text; the perception tool receives images if invoked.

## Future blinded assessment

No independent labels, autonomous selections, or behavioral scores have been collected. The mock response used to finish serialization carries no behavioral meaning.

1. Preserve the first autonomous Verification decision, its exact interval and rate, actual tool execution, returned observations, cited frames, physical requests, image count and latency. Distinguish an inspection rejected before dispatch from an executed inspection. An abstention is permitted. Keep both arms under the same existing runtime limits.
2. Assemble anonymous X/Y packets with the same visibility question. Include the original in-scope cited pixels available as evidence via references and any genuinely inspected additional in-scope pixels. Deduplicate by canonical ID. Distinguish original cited frames from added frames in the evidence ledger. Keep contextual citations outside the assigned interval separate. Disclose that the human assessor sees pixels directly, while Verification receives observations and references. Hide prompts, verdicts, arm identities and locked labels. Record the assessor’s answer and citations in assessment.csv before unblinding.
3. For each opposite-state bracket from the locked forms, check whether the assessor cites the two corresponding distinguishability states in the right order. Record recovered, missed or unassessable. Compare the width of the assessor’s cited time bracket with the reference bracket. A wider bracket can recover the change with poorer localization. Do not claim an exact transition time or number of intervening changes. Where both reviewers cannot agree on a state, keep it unscored. If a new source frame falls off the locked grid, do not transfer the nearest frame’s label. Leave its state unscored unless separately reviewed blind.
4. Record unsupported identity claims separately. Abstention is appropriate where selected pixels do not resolve the question; also record any change missed relative to the full reference. Equal supported answers, localization and evidence cost tie. If both give equally supported answers, prefer fewer additional frames/requests. Report accuracy–cost tradeoffs as such when neither dominates. If the reference contains no agreed change, score the supported sampled states and leave transition recovery inapplicable.
5. The same independent reception-bound check (10–15 s) was displaced in both arms. Hold it fixed. This design cannot evaluate Investigation’s willingness to delegate the task or the net value of displacing that check.

Rebuild into a fresh directory from the repository root with `.venv/bin/python experiments/relational_question_handoff/visibility_packet.py /tmp/visibility-review-new`. Preparation uses only mock SDK transport. The assignment fixture replicates the previous controlled allocation; it is not an archived live relational assignment.

## Authorized live comparison

From the repository root, with your Gemini credential configured privately and the human forms locked separately:

```bash
.venv/bin/python experiments/relational_question_handoff/visibility_live.py --output "experiments/visibility-live-$(date -u +%Y%m%dT%H%M%SZ)" --authorize-paid-calls --authorize-footage-transfer --authorize-observation-text-transfer
```

The frozen inputs are generic.json and specific.json only. The runner checks their digests and their one-field difference, then rejects any mismatched first wire request before transmission. Each arm gets fresh state, a separately randomized blind label and the original decision/inspection allowances. Verification sends the original derived observation text and citations to Gemini and may autonomously request images within the assigned source interval. Each arm has at most four Verification calls and three physical targeted perception calls, since another Verification iteration must remain after an inspection. Both roles use Gemini 3.6 Flash HIGH / 8192. There are no retries. The pair is capped at 14 physical requests and 114,688 maximum combined generation tokens. Image input tokens, latency and actual charge depend on the chosen intervals and provider billing.

Keep private-key.json, generic/result.json and specific/result.json from assessors. These contain execution order, blind mapping, model decisions, actual tool outcomes, provider diagnostics, source-frame metadata and usage. Monetary charge is null because generateContent does not supply a billed amount. For a successful experiment give the assessor only assessor/X and assessor/Y plus the same visibility question and the blank assessment form. PNG filenames give source-relative microseconds; frames.json supplies canonical IDs. Each packet includes the original in-scope cited pixels and unique additions from successful inspections, even if no proposal resulted. Out-of-scope contextual citations remain in the saved model request. An HTTP failure, a runtime rejection, an exhausted budget and a voluntary insufficient verdict have separate trace records; inspect those before attributing abstention to the model. Any arm marked execution_failure is not a semantic result.
