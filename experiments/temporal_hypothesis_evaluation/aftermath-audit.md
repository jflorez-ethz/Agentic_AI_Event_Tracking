# Audit of the live pair and aftermath endpoint

The archived run is `paired.jqmQZe/run`. All twenty unique submitted frames were decoded locally and matched against source PTS, times and RGB24 hashes. A's ten frames are the exact prefix of B's. All recorded perception citations resolve to their own submitted frames.

| Arm | Requested / actual sample range | Recorded perception and discriminating evidence | Justified aftermath conclusion | Observed cost |
|---|---|---|---|---|
| A | [14.52,19.52) / 14.52–19.04 s | Ten common frames. Gemini Vision returned insufficient evidence, citing resolution and glare. Both trajectories cannot be reliably followed. | Indeterminate. Ordinary supported verdict reconfirmed 10–14.52 s and is off-topic for aftermath. | Three reasoning calls, one media call, ten images, 25,009 tokens. |
| B | [14.52,24.52) / 14.52–24.04 s | Same ten frames plus ten at 19.52–24.04 s. Gemini Vision reported one person moving and cited all twenty. The added views of the left walkway do not visibly link both earlier people to later trajectories. The response gives no narrower bracket establishing that the extra frames caused detection. | Indeterminate. Ordinary supported verdict is also off-topic. The single-person observation establishes neither joint continuation nor divergence nor observed visibility loss for the original pair. | Three reasoning calls, one media call, twenty images, 37,342 tokens. |

The added frames extend the observable interval. Local review does not identify a discriminating cue that resolves the two tracks. This is provisional; no independent reviewer was available. The media calls differ in duration and frames. The extra 12,333 reported tokens (+49.3%) are not a bill and cannot be attributed solely to the instruction. No improvement in reconstruction is demonstrated.

## Harness correction

The experiment-only verification request now asks for joint continuation, divergence, observed visibility loss, or indeterminate. A definite result must provide two distinct continuity descriptions with cited source anchors and strictly post-anchor references belonging to follow-up observations. This checks reference structure; the truth of the continuity account still needs visual review. Invalid and off-topic responses are recorded separately with an indeterminate outcome. The experimental assessment is written to `aftermath.json`; the production graph consumes a local insufficient placeholder and does not turn the experiment's outcome into a production finding. No added call, retry, or inspection. Production validators, budgets and architecture were not changed.

Reproduce offline from the repository root:

```sh
.venv/bin/python experiments/temporal_hypothesis_evaluation/audit_aftermath.py --contact-sheet /tmp/sa-aftermath-extra.png
.venv/bin/python -m pytest -q experiments/temporal_hypothesis_evaluation/test_paired.py
```

The audit scores the archived verdicts as off-topic. Tests use scripted data to check valid references, one-person insufficiency, out-of-time frames and replay conditions. The revised outcome has not been evaluated with live agent decisions.
