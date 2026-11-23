# Adaptive temporal sampling on Meet_WalkSplit

## Source replay

The existing FFmpeg sampler selected the first frame at or after each requested timestamp, inside the half-open inspection interval. Both arms start on the same grid. The later interval ends at 14,520,001 µs to include the frame at 14.52 s. The script re-decodes RGB24, checks each PTS against the source, and compares every complete frame reference and the video SHA-256 against the corresponding archived sampling arm. The manifest records exact requests, sample outcomes, display indices, integer PTS, timestamps, canonical IDs and hashes.

| Requested interval in seconds | Shared display indices (2 FPS) | Additional display indices at 4 FPS with actual seconds | Actual first–last frame |
|---|---|---|---|
| [6, 8) | 150, 163, 175, 188 | 157 (6.28), 169 (6.76), 182 (7.28), 194 (7.76) | 6–7.52 s → 6–7.76 s |
| [10, 14.520001) | 250, 263, 275, 288, 300, 313, 325, 338, 350, 363 | 257 (10.28), 269 (10.76), 282 (11.28), 294 (11.76), 307 (12.28), 319 (12.76), 332 (13.28), 344 (13.76), 357 (14.28) | 10–14.52 s at both rates |

These are discrete views with gaps. The 6–8 s replay is aligned to the archived 2 FPS grid. A production inspection starting off-grid may have a different frame subset.

## Visual assessment and validator results

- **Apparent convergence and proximity.** Shared frames 150 and 163 show the projected distance decreasing. Frame 163 supports a local nearby judgment. The dense views narrow the onset of silhouette overlap to after frame 163 and by frame 169. By frame 182 the heads are distinguishable again although the bodies still overlap in projection. Sparse frames 175 and 188 already showed the overlap and later clearer silhouettes.
- **Local divergence.** Shared frames 250 and 325 show an increase in projected spacing. The intervening views show two paths near the seating/corridor boundary. Dense frames 319 and 332 better sample that progression but supply no change to the local divergence verdict. The view gets harder to assess near the boundary toward 14.52 s.
- **Same-pair separation.** Neither rate establishes both individuals through the overlap and across the gap between the targeted intervals. The full-span separation attempt also fails the projected-spacing criterion with the supplied marking uncertainty. No identity links were assigned. Apparent convergence and later divergence leave social joining unsupported.

The prototype accepted local approach, nearby and visible divergence under both arms' review inputs. The marks are approximate head locations with a four-pixel uncertainty radius, and proximity and distinct paths are visual judgments. These are single-reviewer observations rather than independently adjudicated labels. Both arms deliberately use the same decisive endpoints to test whether their shared evidence already suffices. The manifest distinguishes these review inputs from canonical frame metadata. Existing controlled tests separately exercise sufficient two-person continuity links, missing links, overlap, and unsupported joining.

## Tool audit and adaptive policy

The Verification decision schema accepts modality and start/end times for inspection. Both the Python and LangGraph paths use the same `AgentRun.reinspect` guard. It requires candidate overlap, limits the span to 10 s, rejects duplicate modality/interval pairs and charges the global inspection budget. The observation callback receives only interval and modality. Frame inspections inherit the initial plan's frame step, whose minimum is 500 ms. A clip uses a separate media path and provides no per-request explicit 250 ms RGB24 grid. There is currently no targeted finer-sampling override.

A possible opt-in policy would require an unresolved visual uncertainty (overlap, direction change, convergence/divergence, or a specific occlusion transition), the smallest relevant interval, the requested step, and a question about what the extra pixels could discriminate. Example: “6.5–7.5 s at 250 ms: at which views can both silhouettes be distinguished immediately before and after overlap?” Stop when existing evidence suffices. An absent request, exhausted budget, or inconclusive return leaves the claim unresolved. Timing a visible transition is a better reason than hoping extra samples recover identity hidden by the view.

**Conditional pilot.** The evidence justifies testing a narrow timing inspection, with no case yet for production rollout or identity resolution. If independent review needs tighter timing and confirms the added views change a decision, extend the existing frame inspection decision and callback with a targeted-only 250 ms option, retaining 500 ms for the default and initial scan. Use a five-second maximum and at most 20 unique frames per fine request as pilot limits. Reuse sampler IDs, hashes and actual coverage. Reject oversized payloads using the existing Gemini adapter's 19,000,000-byte inline guard before send. Intake should reject repeated requests and shifted intervals yielding no new evidence by comparing actual sampled frame IDs. Allow one fine retry per unresolved candidate, within the existing global logical inspection budget and physical media request budget. Keep single-request media behavior and trace both the proposed window/step and returned citations through the existing Verification handoff. The offline admission tests exercise the proposed request fields, span, candidate overlap, repeats and available budgets. Payload checking, equivalent-frame deduplication and one fine retry per candidate are conditional integration requirements.

Targeting both windows would submit 27 images across two requests (8 and 19) versus 60 images in the earlier single broad dense request. The comparable 2 FPS windows contain 14 images. The 13 new images measure incremental evidence, while the full submitted image count measures payload. Actual request overhead, token use and latency were not measured in this offline study. Production rollout should require independently reviewed examples where the tighter bracket changes a verdict, and a check that extra samples do not increase false same-pair links.

## Reproduce

From the repository root:

```sh
.venv/bin/python experiments/relational_motion/adaptive_sampling.py \
  experiments/relational_motion/adaptive-frame-manifest.json
.venv/bin/python -m pytest -q experiments/relational_motion
```
