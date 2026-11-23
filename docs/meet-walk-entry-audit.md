# Meet Walk Together entry audit

The [recorded run](../experiments/meet_walk_recovery.50raLm/run/analysis.json) used 11 logical reasoning calls and all four inspections. Investigation delegated all three initial observations. Source SHA-256 matched the run, and all 38 recorded inspection-frame references matched the original frame indices, PTS, source time and decoded RGB24 hashes. The source clock is 1/12,800 second per PTS tick.

| Candidate | Initial citation | Targeted media and returned observations | Verification outcome |
|---|---|---|---|
| A | 8.00, 9.00 s. Person enters from top right. | [8,10) supplied 8,9 s and returned an entry observation citing those exact same frames. [7,9) supplied 7,8 s and returned no observation. The end bound excluded the 9 s frame. | The first returned observation passed correspondence, including a shared 9 s frame, but contributed no new frame to the citation. Recovery produced no additional cited evidence. The check was left unfinished. |
| B | 10.00, 11.00 s. Blue-shirted person enters lobby from top right. | [9,12) supplied 9,10,11 s. The returned observation describes someone walking into the frame and cites 9,10 s. The 9 s frame was new to this candidate's citation, though already present elsewhere in the investigation. | The recorded same-event assessment passed the quote and shared-frame checks with the 10 s frame. The verdict was rejected for including `transition` on an action category. The check was unfinished. |
| C | 27.00, 28.00 s. Two people enter from the upper-left corridor. | [26.5,28.32) supplied 26.52,27.52 s, both new. The observation describes people walking through the corridor and cites both. | No source frame was shared with the initial citation, so the pair could not meet the grounded same-event condition despite temporal overlap. All four inspection slots had been used. A subsequent insufficient verdict completed the check. |

The normalized artifacts preserve the validator reason and B's passed assessment, but not the full raw verdict object or exact transition values. The offline reconstruction uses the recorded excerpts and shared frame, with representative before/after field values sufficient to reach the same validator branch. A and C's unsupported decision payloads are likewise reconstructed from the resulting trace rather than represented as byte-for-byte recordings.

## Visual interpretation and tools

Local review of frames around 7–12 seconds shows a figure beginning to appear at the upper-right image edge around 9 seconds and continuing on a compatible path into view at 10–12 seconds. The spacing, route and appearance favor one continuous passage across A and B. These samples do not independently establish identity or a second crossing. Frames at 26.52 through 28 seconds show people moving in and near the upper-left corridor. The workflow never defined a monitored-area boundary. Walking into the frame, movement inside the corridor, and crossing into a specified area are different visual claims. The initial and targeted descriptions do not consistently distinguish them.

The live LangGraph inspection path invokes the workflow's provider for every accepted request, including when source frames were submitted earlier. The path runs through `AgentRun.reinspect`, the live `observe` closure, source decoding, and fresh Gemini perception. Archive-only mode looks up recorded entries. An inspection can add new sampled frames, but the verdict sees the frames actually cited by its returned observation. A separate inspection ID alone cannot establish corroboration.

All four requests selected frames at the existing one-second step, starting from each request's lower bound; the sampler uses the first actual frame at or after each tick. That can repeat the seed grid, as for A, or shift completely off it, as for C. The controller needs a common cited frame and an additional cited frame for grounded corroboration. Local extraction at the already configurable 500 ms step demonstrated both were available in principle: [8,10) yielded 8, 8.52, 9 and 9.52 s; [26,28.32) yielded 26, 26.52, 27, 27.52 and 28 s. Those samples demonstrate tool capability. They offer no guarantee of model citations, correspondence, or a defined-area crossing. The agent may also choose clips, whose internal Gemini sample times remain unobserved. No sampling, budget or verification-policy change was made.

## Narrow correction and replay

The verification response schema previously allowed the visibility-only `transition` field for every candidate. It now advertises that field only for visibility categories. The runtime validator is unchanged and still rejects it for physical action claims. No observation category, tool or evidence rule changed.

| Scripted replay using the same source evidence | Reasoning decisions | Inspections | Completed checks | Validator-accepted findings |
|---|---:|---:|---:|---:|
| Reconstructed original verdict | 11 | 4 | 1/3 | 0 |
| B's same decision with the invalid field omitted | 11 | 4 | 2/3 | 1 |

The second result is a structural counterfactual. It shows that B's recorded correspondence, novel frame relative to its seed and separate inspection are sufficient for the existing validator if the invalid field is absent. It does not independently prove a separate physical entry. The semantic ambiguity around which boundary was crossed, and whether A and B are duplicate descriptions of one passage, remains open. No API calls or external transfers were made.

## Consecutive-frame review and same-window sampling control

FFprobe independently reported 708 presentation frames at 25 fps with time base 1/12,800. I matched its PTS list to the project ingest and reviewed consecutive decoded frames 175–300 (7–12 s) and 650–707 (26–28.28 s) in order. The local reviewer packet at `/tmp/sa-entry-review/` contains the full-resolution frames in X and Y, numbered contact sheets, a PTS and RGB24-SHA-256 manifest, and a separate `reviewer-rubric.md` without model labels or findings. This is a source-first rereview, with prior familiarity from the earlier audit. No independent reviewer was available. The visual readings below are provisional.

In X, the image edge provides a visibility boundary. The figure appears near the upper-right edge around 9 s and continues down and left across the later frames. Continuity of trajectory favors one passage across the A and B windows. A separate entry at 10–11 s was not established. In Y, people emerge from the corridor-side area near the upper left and move into clearer view. The opening and floor geometry provide landmarks, but the run specifies no physical line or zone. The footage review does not establish which fixed boundary each person crosses or a crossing bracket for a defined monitored area.

Rows below list **presentation index / PTS / seconds**. Submitted frames are the recorded extraction inputs. The artifact does not preserve exact encoded PNG request bodies or raw provider responses. Novelty is relative to each candidate's original citation. Tool outputs and verdict traces are recorded unless explicitly noted.

### A

| Stage | Frames and decision |
|---|---|
| Initial observation, delegated | 200 / 102400 / 8.00 and 225 / 115200 / 9.00. |
| Frames [8,10) | Supplied and cited the same pair. Two anchors, zero novel cited frames. Shared-frame assessment passed at frame 225. |
| Frames [7,9) | Supplied 175 / 89600 / 7.00 and 200 / 102400 / 8.00. Frame 175 was novel to the seed, but the lookup returned no observation. The request excluded 9 s. |
| Verdict and conclusion | Proposed support failed the novel-citation check. The recovery ended unfinished. Visibility is plausible. Corroboration would require a relevant new cited view with a shared anchor, and a physical crossing claim would need a defensible boundary and frames showing the crossing. |

### B

| Stage | Frames and decision |
|---|---|
| Initial observation, delegated | 250 / 128000 / 10.00 and 275 / 140800 / 11.00. |
| Frames [9,12) | Supplied 225 / 115200 / 9.00, 250 / 128000 / 10.00 and 275 / 140800 / 11.00. Returned citation used frame 225 (novel to B, already in A) and 250 (shared). It omitted 275. |
| Correspondence and verdict | The original excerpts and frame 250 passed correspondence. With the reconstructed visibility-only field, the verdict fails the action-category field guard before action corroboration. Omitting only the field lets the matching category, separate inspection, shared-frame assessment and novel cited frame pass. The counterfactual accepts B structurally. |
| Visual conclusion | The consecutive frames favor continued movement of the figure already becoming visible in A. Establishing a separate entry would require an observable second passage or a specified physical boundary with evidence of a crossing. |

### C

| Stage | Frames and decision |
|---|---|
| Initial observation, delegated | 675 / 345600 / 27.00 and 700 / 358400 / 28.00. |
| Frames [26.5,28.32) | Supplied and cited 663 / 339456 / 26.52 and 688 / 352256 / 27.52. Both were novel. Neither was a shared anchor. |
| Verdict and conclusion | The support attempt lacked grounded correspondence. The inspection budget was exhausted, and the accepted insufficient verdict completed the check. A shared anchor and relevant novel frames could support reassessment. Movement through the corridor remains distinct from crossing a specified boundary. |

The controlled extraction varied only the step from 1,000 to 500 ms within the same request bounds, one slot per alternative. A retained 200 and 225 and added 213 (8.52 s, before the 9 s view) and 238 (9.52 s, after it). C retained 663 and 688 as views around and between the seed frames, and added seed anchors 675 and 700 to the supplied grid. The original C return already cited 663 and 688, but no provider response exists for either alternate input. These results establish sampling feasibility. They cannot establish what a model would cite or whether a physical crossing occurred.

Both verdict replays again used four inspections and 11 scripted decisions. The reconstructed verdict reproduced 1/3 checks with zero validator-accepted findings. Omitting only the field produced 2/3 with one validator-accepted finding. The related schema, evidence and visual-transition suites passed 24 offline tests. No further implementation defect was isolated, so no production code or archived results changed.

## Citation-only sufficiency review

The staged, model-blinded review packets are at `/tmp/sa-citation-packets/`: `01-cited.zip`, `02-supplied.zip`, `03-consecutive.zip`, and `reviewer-form.md`. Each ZIP contains native-resolution lossless RGB frames and a CSV with index, PTS, source time and decoded RGB24 hash. Duplicate frame IDs were collapsed within each view; the earlier tables preserve their inspection membership. FFprobe timestamps and recorded decoded hashes were rechecked. No independent reviewer was available. The following is a provisional comparison, with prior knowledge of the case. Inter-reviewer agreement remains unmeasured.

| Candidate | Cited frames alone | All recorded supplied frames | Consecutive source frames | First defensible finding |
|---|---|---|---|---|
| A | 200 and 225 (8–9 s). A figure becomes visible at the upper-right image edge. | Ten unique frames (0–9 s). Earlier negative views add context; the 9 s frame remains the last supplied view. | Frames 175–300 (7–12 s) show the figure continuing into view. The upper image edge establishes a visibility boundary. | Citation supports first visibility bracketed by 200–225. No defined physical crossing. |
| B | 225, 250 and 275 (9–11 s). The figure is already visible at 9 s and moves farther into view. A unique physical line and origin/destination pair are not established. | Eleven unique frames (9–19 s). Later movement is clearer; the additional views do not establish another entry in the claimed 10–11 s interval. | The shared AB sequence favors continuity of the same passage from A across B. It does not identify the person or locate a separate crossing. | Citation supports movement within view. Continuity across A and B is clearest in the consecutive sequence. |
| C | 663, 675, 688 and 700 (26.52, 27, 27.52 and 28 s). Figures move near the upper-left corridor opening. | Eleven unique frames. Earlier corridor context adds visibility information; the targeted inspection supplied no uncited frames of its own. | Frames 650–707 (26–28.28 s) clarify movement out of the darker corridor-side area. Wall and floor edges are landmarks, but the monitored boundary and side-to-side crossing bracket remain indeterminate. | Citation supports corridor-side movement. No defined physical crossing. |

Replaying B with its reconstructed `transition` field passed evidence-ID and overlap checks and validated the recorded excerpts and shared frame 250. It failed the category guard before action corroboration was evaluated. Omitting only the field allowed the separate inspection, matching category, shared frame and novel frame 225 to pass. The full verdict JSON was unavailable. The before/after field values and complete decision shape are reconstructed; the rejection and correspondence log are recorded. Both replays used four inspections and 11 scripted decisions. Completed checks moved from 1/3 to 2/3, and accepted findings from zero to one. This difference measures controller behavior. It does not establish a crossing.

The focused schema, evidence and visibility suites passed 24 tests. No additional implementation change was made. No Gemini calls or external transfers were made.

## Claim refinement on the same evidence

The previous event contract fixed the timeline category to the delegated observation. `person_enters_area` rendered as entry into an observed area and followed the stricter action route. The model had no person-specific first-visibility or movement label and could not narrow an entry seed at verdict time. The code also lacked an explicit boundary requirement on entry verdicts, so a matching category, shared cited frame, and novel cited frame could structurally pass for B without defining the area.

The model-guided path now supports `person_appeared` and `person_moved` as direct visual findings. A verifier can explicitly refine a person-entry seed to one of those labels using the existing ordered before/after frame contract. A non-seed witness still needs grounded same-event correspondence. The timeline uses the selected pair's source bracket, preserves the original source citation, and records the change of claim type in the verdict trace. Python does not automatically refine a failed entry verdict.

A model-guided physical-entry verdict still requires the separate-inspection, shared-frame, and novel-frame checks. It must also quote an identifiable physical boundary in the validated assessments of both views. Orientation phrases such as “top right” and camera-frame edges cannot serve as the physical boundary. There is a conservative landmark vocabulary for structural validation; unnamed or differently described boundaries can remain unresolved. The model still judges whether a crossing occurs. A grounded phrase and validator acceptance are insufficient to independently validate that judgment.

| Identical recorded inspections and initial evidence | Before | Scripted refinement |
|---|---|---|
| A, original citation at 8–9 s | Unfinished | Supported first visibility, source bracket 8–9 s |
| B, original citation at 10–11 s | Rejected, unfinished | Completed insufficient. A separate passage remains unestablished |
| C, original citation at 27–28 s | Completed insufficient | Supported movement within view, source bracket 27–28 s |
| Accounting and budgets | Triage 3/3, checks 1/3, 11 decisions, four inspections | Triage 3/3, checks 3/3, 11 decisions, four inspections |
| Physical entries supported | 0 | 0 |

The replay used fixed decisions on the same recorded evidence. It demonstrates expressivity, bracket grounding and routing behavior, not live model quality. A and B's original citations share no frame, so the existing association path cannot merge them directly. The script preserves B as unresolved. Synthetic tests retain a grounded association without a duplicate supported event and preserve separate scripted passages as distinct. No tracking, sampler, budget, or routing policy was introduced. The deterministic baseline's behavior remains intact. No reviewer-independent semantic accuracy was measured and no live Gemini calls were made.

## Live evaluation after claim refinement

In `experiments/meet_walk_evaluation.i2mvYw/run/analysis.json`, all 13 unique reported source frames matched decoded pixels and recorded PTS. This run produced new observations, so its counts are not a paired causal comparison with earlier runs. The review is provisional.

- 9 s first visibility: the seed cites only 9 s. Investigation delegated it and Verification correctly requested [8,10) s, obtaining an observation spanning 8–9 s. The verdict failed with “Transition frames are outside the cited observation.” The 8 s frame was available via the targeted observation. The raw verdict is absent, so the exact mismatched field is unknown.
- 10–13 s movement: cited endpoints and intervening frames show the blue-shirted figure moving farther into the scene. The movement label and bracket are supported by this review.
- 17–19 s movement: figures move toward the upper-left side. The narrower bracket supports movement. The earlier meeting and an actual exit are distinct claims; the selected endpoint pair does not establish them. The report conservatively renders movement.
- 27–28 s first visibility: people are discernible near the corridor already at 27 s and clearer farther into view at 28 s. This pair supports motion and improved visibility; it does not clearly establish first visibility for both. The associated movement observation shares the same frames and was not verified separately. It is an unresolved association, not another completed check.

Three of four delegated checks completed, with five of five observations accounted for. No physical entry was reported. The evidence review agrees with two movement labels, flags the first-visibility label at 27–28 s as too strong, and distinguishes that semantic error from the rejected source-reference decision at 9 s. No live calls, transfers or code changes were made during review.
