# Visibility-transition verification

## Source and trace audit

The completed run was `/tmp/security-augmented-new-video.DnyCqC/run_tier1_20261121_170515/analysis.json`. The sibling `run/analysis.json` was a distinct, incomplete trial. Both matched the current `block.mkv` SHA-256 `03a437317b267c620f2a2105c518126df271c30dc301cc8e0b978acd708642b8`. Decoding the original verified the PTS and RGB24 hashes for all 16 recorded inspection frame references in the completed trial and all 10 in the incomplete trial. The video has 40 frames, PTS time base 1/1000 and first PTS zero.

| Source frame index | PTS | Source time | White pixels in decoded image |
|---:|---:|---:|---:|
| 5 | 1000 | 1.0 s | 0 |
| 9 | 1800 | 1.8 s | 0 |
| 10 | 2000 | 2.0 s | 500 |
| 20 | 4000 | 4.0 s | 500 |
| 25 | 5000 | 5.0 s | 500 |
| 29 | 5800 | 5.8 s | 500 |
| 30 | 6000 | 6.0 s | 0 |
| 35 | 7000 | 7.0 s | 0 |

The fixture independently establishes two visible transitions. Its pixels establish no physical handling or actor. The analysis artifact preserves normalized media outputs, source citations, role decisions, coverage and tool results, plus role transport metadata. Exact raw provider responses and the frames actually sampled by Gemini from the clip are unavailable in that artifact.

| Candidate | Initial evidence and handoff | Verification path | Point where support failed |
|---|---|---|---|
| A, `object_placed` | Description said an object appeared between F2 and F3. Its source citations were PTS 1000 and 2000. Investigation delegated it. | A frame request for [0.5, 2.5) s sampled at 0.5 and 1.5 s, selecting source frames at 0.6 and 1.6 s. Both were black, and the tool returned an insufficient-evidence observation with partial coverage. A second request asked for a clip [1.000000, 2.000001) s. The actual clip contained source frames from 1.0 through 2.0 s, at 200 ms spacing, with decoded extent [1.0, 2.2) s. The first white frame was the final encoded frame. The tool returned `covered_without_findings` for the requested span. | Neither result supplied a corresponding placement claim. The black samples were before the transition. Requested clip FPS was 2, and the empty response does not establish whether the provider saw the final encoded frame. Verification returned `insufficient` with no correspondence assessment. |
| B, `object_removed` | Description said the object visible in F1 and F2 was removed by F3 and F4. It cited PTS 4000, 5000, 6000 and 7000. Investigation delegated it. | Both global inspection slots had been spent on A. Only one usable reasoning call remained before the reserved Reporting slot, also too few for inspection and reconsideration. Verification cited only the original observation in an `insufficient` verdict. | There was no second inspection or event-correspondence assessment. This is a demonstrated budget limitation. The initial evidence brackets disappearance and leaves physical removal unsupported. |

The completed trial used four media requests, six logical role calls and eight physical role attempts. Two role calls recovered from HTTP 504 on retry. Both insufficient verdicts were accepted checks. The Reporting Agent attempted an unsupported lead, which validation rejected. Python rendered two unresolved items. The sibling run retrieved the same 1 s and 2 s frames for A, proposed support, and recorded a valid correspondence assessment. The check still failed because the new inspection introduced no new source frame. Its recovery then ended on two HTTP 504s. That run never completed verification of either candidate.

## Contract and correction

The action contract requires a separate inspection, grounded same-event correspondence with verifiable excerpts and a shared frame, plus a new source frame in the corroborating citation. Scope and opposing-observation checks still apply. This contract justifies withholding the two causal action findings. The demonstrated defect is representational. In the old vocabulary, an appearance or disappearance had to be filed under an action category or lose its identity as `insufficient_evidence`. Supporting it as an action would have overstated the visual evidence.

The model-guided path now uses two additional values in the existing category field, `object_appeared` and `object_disappeared`. Perception and Verification distinguish changes in visibility from physical actions. Verification can support a literal change using an explicit ordered before/after pair from a cited frame observation. Another observation must pass the unchanged event-correspondence validator. Python resolves the pair on the source clock and rejects uncited, reversed, same-time or pixel-identical pairs. Identical pixels rule out a visible endpoint change. Different pixels cannot establish which object changed or why. Gemini retains responsibility for that semantic judgment. A direct pair cannot support an action category. Missing adequate evidence remains insufficient, and malformed references remain validation failures. The deterministic baseline and the causal corroboration path retain their original acceptance rules.

## Offline comparison

Use `.venv/bin/python -m pytest -q tests/test_visual_transitions.py` for the focused cases. The tests regenerate the same fixture, use real decoded frames and supply controlled model decisions. The old action-contract assertions passed before production changes, while both literal-positive cases failed for lack of corroboration.

| Case | Previous behavior | Targeted behavior |
|---|---|---|
| Appearance | Action unsupported from the initial observation or a reinspection of the same frames. | Literal visibility finding bracketed by 1.0 and 2.0 s. |
| Disappearance | Action unsupported from one inspection. | Literal visibility finding bracketed by 5.0 and 6.0 s within the original 4–7 s citation. |
| Unsupported causal inference | Initial appearance alone could not support placement. | A before/after pair cannot be used to support a causal category. |
| Missing or invalid temporal evidence | Evidence remained insufficient or the citation failed validation. | Single or reversed frames remain insufficient. An uncited frame is rejected. |
| Unchanged interval | No supported finding in the control. | Even a mocked positive decision is insufficient for pixel-identical endpoints. |
| LeftBag | Scripted StateGraph recovered placement and retained ambiguity. | The causal validator and archive replay remain in place. |

The paired fixture replay uses two initial frame requests, four scripted role decisions, zero targeted requests, and 2/2 accounted observations. It preserves the original source-linked citations and records the specific verification frame pair. The narrower brackets describe sampling uncertainty and do not claim that the transition happened at the first or last timestamp exactly. Existing partial-scan, failed-tool, unavailable-coverage, invalid-citation and budget tests continue to exercise separate failure paths.

A future authorized validation can reuse the [new-video protocol](new-video-evaluation.md) on the same fixture and models with a fresh output directory. Compare its literal descriptions, bracket frames, attempted tool spans and unresolved results against this audit. Keep the same budgets. The updated schemas and live semantic choices remain unverified. Any interpretation of real footage beyond visible state changes still needs human review or independent semantic annotation.
