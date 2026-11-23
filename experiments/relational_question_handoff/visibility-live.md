# Visibility question: live A/B (2026-11-23)

Run directory: [`experiments/visibility-live-20261123T190614Z/`](../visibility-live-20261123T190614Z/). Runner: [`visibility_live.py`](visibility_live.py). Review protocol: [`visibility-review/PROTOCOL.md`](visibility-review/PROTOCOL.md).

The same WalkSplit relational task (3.52–9.52 s, two overlapping observations) was handed to live Verification twice: once with the specific visibility question ("specific") and once with the existing generic objective ("generic"). The 10–15 s reception-bound check was displaced in both arms. Only Verification and the Perception tool were live; Investigation and Reporting were fixed.

## Blinded evidence comparison: tie

Before unblinding, the two evidence packets (X = specific, Y = generic, see `private-key.json`) were compared against a provisional reference ([`exploratory-review/`](../visibility-live-20261123T190614Z/exploratory-review/)). That reference is a user-confirmed, AI-assisted assessment. The two independent reviewer forms (`visibility-review/reviewer/`) remain blank, so no independent reference is locked and this result is exploratory.

- Each packet had 18 frames, sharing 17, including all 13 original cited frames. X alone added 4.04 s; Y alone added 9.04 s. Neither unique frame was near the disputed visibility change.
- Loss of separate distinguishability: both packets bracket it at 6.00–6.52 s (both miss the 6.28 s reference view).
- Recovery: both bracket it at 7.00–7.52 s (both miss 7.28 s, where the provisional review already distinguishes two people).
- Both added the same off-grid 7.04 s overlap view, which has no reference label.

Merged outlines do not establish that one person disappeared or that the same pair later separated.

## Recorded arm results

| | Specific | Generic |
|---|---:|---:|
| Requested inspection | 3.52–8.52 s | 4.52–9.52 s |
| Executed sampling | 500 ms, 10 images | 500 ms, 10 images |
| Physical requests | 2 Verification + 1 Perception | 2 Verification + 1 Perception |
| Input / thinking / output tokens | 22,595 / 7,102 / 529 | 22,649 / 7,447 / 629 |
| Total tokens | 30,226 | 30,725 |
| Elapsed | 40.892 s | 42.898 s |
| Accepted relation (first–last cited view) | approach, 3.52–7.04 s | approach, 4.52–7.04 s |

All six requests returned HTTP 200 / STOP; both arms finished without abstention or execution failure. No monetary charge was reported.

Neither final verdict answered when the silhouettes were separately distinguishable; both accepted the narrower approach (decreasing image-plane spacing). The generic arm's wording ("meet", "alongside") went beyond what was validated.

## Handoff defect found and fixed

Verification's own inspection questions were:

- specific: "Which portions of this interval, if any, show two separately distinguishable silhouettes?"
- generic: "Do the two people meet and walk alongside each other toward the upper-left lobby area?"

Both were logged in the trace, but at the 500 ms step the Perception tool received only `relational=True, sampling_step_ms=500`; the question reached Perception only at 250 ms. **This run therefore tested the question's effect on Verification's evidence selection, not its effect as an instruction to Perception.**

Fix (in place since 20:35): `AgentRun.reinspect` builds one `inspection_question` and uses it for both the trace and the `self.inspect(...)` call (`src/security_augmented/agents.py`, around line 1077–1090), so a relational task forwards its question at 500 or 250 ms. The 250 ms limits are unchanged.

Regression: `test_archived_default_rate_inspection_forwards_its_question` in [`test_visibility_live.py`](test_visibility_live.py) replays each arm's archived first decision through the runner using mock HTTP. It asserts that the serialized Perception body carries the arm's own question exactly once as an unverified lead, and that removing only that sentence reproduces the archived request's SHA-256. It also asserts unchanged frames and request counts. A reverted copy that forwards only at 250 ms fails both parametrizations.

## What this supports

For this single pair, the specific question communicated the intended uncertainty to Verification but showed no gain in evidence quality, transition localization or answer correctness, at equal call count and 499 fewer tokens. One pair against a provisional reference cannot establish a repeatable effect. Whether a forwarded question improves Perception's answer is unmeasured; testing it needs a separately authorized live run scored against locked independent reviews.

Still open: a non-relational adaptive inspection at 500 ms accepts an optional `visual_question` but does not forward it (the forwarding condition requires a relational task or 250 ms).
