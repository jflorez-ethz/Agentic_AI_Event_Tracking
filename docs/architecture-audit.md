# Architecture audit: Investigation, Verification, Reporting

Date: 2026-11-26. Offline only: no production code changed, no paid call, no footage sent.

**Evidence base.**
- Source code at `38afe35`.
- The archived traces of the 16 frozen KPI runs: 9 development and 7 never-seen, all on src tree `7e86f3b`.
- The KPI tables and their ground truth (CAVIAR XML, plus the frozen held-out truth).
- The fall-check experiments.

**Scripts.** All are offline and reproducible, in [experiments/architecture_audit/](../experiments/architecture_audit/):
- `traces.py`: what each agent did;
- `triage_baseline.py`: Investigation compared with a fixed rule;
- `rejections.py`: the inspections the tool refused.

**Important scope note.** The 16 runs predate the code-side floor check. In them, `person_fell` still went through Investigation and Verification. Since `4bf1462` and `38afe35`, people on the floor bypass the agents entirely (`workflow.py:723`, `floor_check.py`). Findings about falls describe the version that was measured, not the current one.

Evidence classes used below:
- **[V]** verified from code or traces;
- **[E]** supported by an offline experiment;
- **[H]** plausible hypothesis, not verified;
- **[P]** design preference.

---

## 1. Bottom line

1. **The system is a deterministic workflow with three constrained LLM decision points. That is mostly the right design for this task.** The architecture is good in three places, and this should be kept:
   - the code validates everything the models return (IDs, quotes, shared frames, intervals, budgets);
   - every level-1 item goes to the guard regardless of verdicts;
   - the recent move of people on the floor to code-measured facts.
2. **The main weakness is where Verification's effort goes, not how much autonomy the agents have.**
   - 77 % of Verification decisions and 68 % of its inspections went to "person walking" or "person appeared". These are watch-list level 3: never an alert.
   - Every suspicion (`insufficient_evidence` with a possible watch-list category) is structurally impossible to support (`agents.py:1395`). Investigation excluded or deferred all 11 of them, so they reach the guard unchecked.
   - The effort is spent where uncertainty is lowest, and withheld where it is highest.
3. **Investigation's autonomy is nominal for watch-list items.** In 16 of 16 runs, its delegation of watch-list observations is identical to a fixed rule. Its search tool was never used.
4. **Reporting has no effect on what the guard sees.** `report.html` ignores it. In 9 of 16 `report.md` files, its one choice (the "lead finding") is a walking person, including 4 runs with watch-list alerts pending (3 of them level 1).
5. **Verification's "supported" is the same model agreeing with itself.** Perception and Verification are both `gemini-3.6-flash`. Corroboration is a second Perception call. The literature and our own Slump case say this is weak evidence.
6. **The agents cannot fix the largest error source.** All 3 missed reference events were never reported by Perception at all, so no agent change can recover them. Expected gains from architecture changes are therefore in **cost, labelling accuracy and handling of suspicions**, not in recall.

More ReAct-style loops or more reflection are **not** recommended:
- 34 of 64 candidates were decided without any inspection;
- extra loops were spent mostly repairing tool-call errors.

---

## 2. Reconstructed architecture (as implemented)

```mermaid
flowchart TD
    V[Source video<br/>ingest, SHA-256, PTS] --> P0[Perception initial scan<br/>Gemini, frames every 500 ms, windows]
    P0 --> SPLIT{code: is_candidate<br/>person_on_floor?}
    SPLIT -- yes --> FC[floor_check.py, code<br/>neutral posture probe + follow-ups<br/>facts, doubt signals]
    FC --> FA[System's assessment<br/>text-only call, code-checked]
    SPLIT -- no --> INV
    subgraph LangGraph StateGraph [graph_workflow.py]
      INV[Investigation agent, 1 call<br/>delegate up to max_candidates IDs<br/>+ dispositions; search = reveal stored obs] --> SC[start_candidate]
      SC -->|next candidate| DEC[Verification agent: decide<br/>inspect or verdict]
      DEC -->|inspect| INS[reinspect tool, code<br/>scope, budget, new-frame checks<br/>-> Perception targeted call]
      INS -->|rejected: feedback, 1 recovery| DEC
      INS -->|tool result| DEC
      DEC -->|verdict| VAL[validate, code<br/>correspondence quotes, shared frame,<br/>corroboration, transition frames]
      VAL -->|CorroborationRequired: 1 recovery| DEC
      VAL --> FIN[finish: Event]
      FIN --> SC
      SC -->|no candidates left| REP[Reporting agent, 1 call<br/>choose lead_id + emphasis]
    end
    REP --> RQ[review.py, code<br/>watch-list levels, never-dismissed,<br/>unclear suspicions -> guard]
    FA --> RQ
    RQ --> OUT[report.md, report.html (guard_report.py, code),<br/>alerts.csv, analysis.json]
```

**Who decides what.**

| Decision | Made by | Evidence |
|---|---|---|
| Which observations are watch-list candidates, the order and the budget | code (priority rule `agents.py:851-889`, `_enforce_priority`) | rule-identical in 16/16 runs ([V], [E]) |
| Which routine observations fill the remaining slots | Investigation model | level 3, never alerted |
| Inspect or conclude, and the interval and modality | Verification model | 30 of 64 candidates inspected at least once |
| Whether a verdict is accepted | code (`verdict`, `assess_correspondence`, `CorroborationRequired`) | 3 verdicts rejected, 21 inspections refused |
| What reaches the guard and its status | code (`review.py:130`, `_unclear_alerts`, `floor_check`) | level 1 never dismissed |
| Report headline and sections | code (`guard_report.py`); Reporting only adds one line to `report.md` | [V] |

---

## 3. Intended vs observed behaviour (16 KPI runs)

All runs used the same budget: 4 candidates, 4 inspections, 14 agent calls and 1 search per video. All roles used `gemini-3.6-flash` with thinking HIGH.

| Intended (prompts, docs) | Observed | Class |
|---|---|---|
| Investigation "searches if additional evidence is available" | 0 searches in 16 runs (budget 1); always 1 call | [V] |
| Watch-list observations come first | true, but entirely through code: identical to the fixed rule in 16/16 | [V][E] |
| Investigation defers what cannot be checked | 11/11 suspicions excluded or deferred. 1 real `object_removed` (LeftBag 54 s) deferred "due to candidate budget limit" | [V] |
| Verification resolves meaningful visual uncertainty | 64 candidates: 53 routine (47 `person_moved`), 11 watch-list. 82/107 decisions and 32/47 inspections spent on routine | [V] |
| Verification gathers new evidence before supporting a physical action | yes for objects (code-enforced). 34/64 candidates concluded with no inspection, 32 of them routine | [V] |
| Recovery handles genuine evidence gaps | 23 inspections refused (21 `no_new_frames`). 18 recovery rounds (17 % of Verification calls). After a refusal, 12/23 candidates went straight to a verdict | [V] |
| The tool offers new frames when possible | at least 8 of the 21 refused requests would have added frames at 250 ms over the same interval | [E] |
| Reporting picks the lead | lead = `person_moved` in 9/16 runs. `report.html` never reads it | [V] |
| Thinking where needed | thinking/output token ratio: Investigation 17×, Verification 7.9×, Reporting 8.0× | [V] |

**Outcomes on watch-list candidates** (KPI truth, ±2 s):

| Verification verdict | Count | Against the truth |
|---|---|---|
| Supported | 8 | 5 match a reference event. 2 are LeftBag 1.5 s and 4.0 s: the bag is set down at the feet and picked up again (physically real, but not a reference event under the KPI rule; a truth-definition dispute). 1 is the Slump false fall, a genuine error after 3 inspections. |
| Unsupported | 1 | the real Slump fall (kept for the guard: never dismissed) |
| No verdict (insufficient) | 1 | the LeftBag 1.5 s `person_fell` claim: three inspection attempts, refused or without new frames, then the check ended (a person stooping, not a fall) |

**Misses.**
- 3 of the 13 reference events were missed: LeftBag_AtChair placement, and LeftBag_BehindChair placement and removal.
- In all 3, Perception never reported the event (raw alerts = 0 at those times). No agent saw them.

---

## 4. Agent-by-agent assessment

### Investigation

**Real autonomy.**
- It chooses which **routine** observations fill spare slots.
- It writes the disposition reasons.
- It can associate duplicate observations (6 associations, all routine).

**Predetermined.** Watch-list delegation (code priority rule and budget) and the visible set (`investigate`, `agents.py:896`).

**Tools.**
- `search` only reveals observations already produced by Perception and hidden from its context. It does not acquire evidence. It was unused in all 16 runs.
- Investigation cannot request footage.

**Abstention.** It abstains rationally on suspicions, because Verification cannot support them (`agents.py:1395`).

**Verdict.** In practice it is a router with a free choice only on level-3 items. It cost 16 calls: 127k input and 69k thinking tokens, about 9 % of the run cost. The multi-agent requirement keeps it; its responsibility should become one that changes outcomes (§6, R4).

### Verification

**Real autonomy.**
- It decides whether to inspect.
- It chooses the interval, the modality and (at 250 ms) a visual question.
- It returns the verdict and the correspondence claims.

This is a genuine, if bounded, ReAct-style loop: decide → act (Perception) → observe → decide (`graph_workflow.py:230-233`).

**Constraints, all well designed.**
- Scope, budget and repeat checks before any call.
- Quote-grounded correspondence with a shared frame (`evidence.py`).
- Corroboration from new source frames for physical actions.
- Before and after frames for transitions.

**Limits.**
- It sees **no pixels**. It judges Perception's text, and its "evidence" for "supported" is another description from the **same model**. The prompt itself says this is "not independent confirmation" (`agents.py:142`), yet the rule accepts it.
- It cannot turn a suspicion into a checked event: `insufficient_evidence` is not in `EVENT_LABELS`, so `CorroborationRequired` is raised for every supported verdict on it (`agents.py:1395`).
- The inspection tool rejects instead of adapting. The "new frames available" hint is given only for action categories (`agents.py:1081-1093`), so 18 of the 23 refusals hit routine or fall candidates.

**Verdict.** The validation layer is the strongest part of the system. The loop runs on the wrong items and ends in a verdict label, whose value for the guard is small: level 1 is never dismissed, and the guard sees the images anyway.

### Reporting

**Real autonomy.** It chooses `lead_id` (among supported events only) and `emphasis` (evidence / uncertainty).

**Effect.** One "Lead finding" line and one count line in `report.md` (`agents.py:1540-1606`). It has no effect on `report.html`, alerts or KPI. The deterministic `guard_report.py` headline replaced its role in practice.

**Verdict.** A nominal agent: 16 calls, about 37k tokens. Its choice was misleading in 4 runs, where it named a walking person while watch-list alerts were pending (3 of them level 1).

---

## 5. Ranked weaknesses

| # | Weakness | Evidence | Class |
|---|---|---|---|
| W1 | **Verification effort is inverted.** Most of it goes to level-3 routine claims; suspicions, where uncertainty lies, cannot be verified at all. | 82/107 decisions and 32/47 inspections on routine; 11/11 suspicions excluded or deferred; `agents.py:1395` makes them unsupportable; they reach the guard as "unclear" with no extra evidence | [V] |
| W2 | **"Supported" is same-model self-agreement.** | Perception and Verification are both `gemini-3.6-flash`. Slump false fall supported after 3 inspections. Huang et al. (ICLR 2024): LLMs "struggle to self-correct their responses without external feedback". Kamoi et al. (TACL 2024): self-correction "works well in tasks that can use reliable external feedback". The floor check replaced this with code-measured facts (v2 residual 343/840 false "verified"; v4 220/840 unmarked) | [V] for the design; [E] small n (1 clear false out of 8) |
| W3 | **Fixed budget ignores watch-list load.** | LeftBag: 5 watch-list observations, 4 slots; the real removal at 54 s went to the guard as "not checked" | [V] |
| W4 | **The tool interface creates avoidable loops.** | 21 `no_new_frames` refusals; 18 recovery calls (17 % of Verification calls); at least 8 of 21 had new frames at 250 ms; 12/23 refusals ended in a verdict without new evidence | [V], [E] |
| W5 | **Investigation's model decisions do not change watch-list outcomes.** | 16/16 identical to the fixed rule; search unused | [V], [E] |
| W6 | **Reporting has no effect on the guard and a misleading effect in `report.md`.** | `guard_report.py` never reads it; lead = walking person in 9/16 | [V] |
| W7 | **Thinking HIGH on constrained-choice roles may be unnecessary cost.** | ratios 17× / 8× / 8×; no evidence on accuracy either way | [H] |
| W8 | **Recall is limited upstream of the agents.** | 3/3 misses never reported by Perception | [V]. This bounds what any agent change can gain. |

---

## 6. Patterns and minimal changes, per component

The Anthropic guide recommends "the simplest solution possible, and only increasing complexity when needed", and adding complexity "only when it demonstrably improves outcomes" (Building effective agents, 2024). It distinguishes workflows ("predefined code paths") from agents ("LLMs dynamically direct their own processes"). The evidence above favours **routing and a code evaluator, with a narrow agentic loop only where evidence must be acquired**.

| Component | Pattern | Problem it solves | Why the current one is insufficient | Trade-off |
|---|---|---|---|---|
| Candidate selection | **Routing (deterministic)** by watch-list level, then suspicion, then routine | W1, W3, W5 | the model already reproduces the rule; routine items take budget from level 1/2 | less flexibility for unforeseen categories (mitigated: unknown categories stay routable to the agent) |
| Verification loop | **Hypothesis-driven, bounded ReAct** with a code evaluator (an evaluator-optimizer in which the evaluator is code, not the same LLM) | W1, W2 | same-model agreement is not external feedback; suspicions are dead ends | more inspection calls on suspicions (offset by dropping routine checks) |
| Verification output | **Measured facts + doubt signals** instead of a verdict (as for people on the floor) | W2 | "facts verified" overstates a same-model agreement | the guard reads signals instead of a label (already accepted for the floor) |
| Inspection tool | **Deterministic tool repair**: offset the grid or offer 250 ms automatically | W4 | rejections cost model calls and end checks early | none measurable |
| Investigation | **Plan-and-Execute (planner role)**: for each delegated item, state the competing hypotheses and the visual cue that separates them | W5, and feeds W1 | its current free choices are only level 3 | one structured field more per candidate; quality to be tested |
| Reporting | **Prompt chaining, constrained**: the deterministic headline by severity; Reporting writes the code-checked "System's assessment" sentences (moved from `floor_check.assess`) | W6 | the lead choice is redundant with `guard_report.py` | same number of calls; the assessment becomes one Reporting call per run instead of one per incident |
| Self-reflection loops (Reflexion, Self-Refine) | **Not recommended** | — | without an external signal they add cost; Huang et al. report degradation | — |
| Supervisor agent | **Not recommended** | — | the orchestration is already explicit code; no observed coordination failure | — |

### Minimal changes, ranked

- **R1 (W1, W3, W5). Route by level and uncertainty.**
  - Level 1/2 confident claims and suspicions get the slots first.
  - Routine items get Verification only when slots remain, at 1 iteration.
  - Allow a suspicion to be resolved: the supported outcome becomes "the suspected category is seen", with the same corroboration rules. This means adapting `agents.py:1395` for `insufficient_evidence` with `possible_category`.
- **R2 (W2). Objects: measured facts and doubt signals instead of "facts verified".** This is already planned in `PROJECT_STATE.md`. Example facts: object visible before / after, person next to it, time left alone. Example signals: disagreement between looks, small object, occlusion, single source.
- **R3 (W4). Repair inspections in the tool.** When a 500 ms request adds no frame, use 250 ms over the same interval (or the offset grid) within the same budget, and say so in the tool result. Give the "new frames available" hint for every category.
- **R4 (W5). Investigation writes, per candidate, `hypotheses` (2–3) and `distinguishing_cue`.** Verification receives them and uses the cue as its `visual_question`.
- **R5 (W6). Deterministic lead; Reporting writes the assessment sentences** under the existing code checks.
- **R6 (W7). Test thinking LOW** for Investigation and Reporting.

**What should not change.**
- The validation layer.
- The never-dismissed rule.
- Code-side floor facts.
- Archived replay.
- Separate media and role budgets.

---

## 7. Validation protocols

**Shared design.**
- **Baseline:** the frozen system (src `7e86f3b` for agents, current floor check).
- **Inputs:** replay the **archived initial scans** of the 16 runs, so Perception's first look is identical in every arm. Only the agent layer and its targeted inspections run again. This removes the largest confounder (Perception's variation on the first look).
- **Truth:** the KPI truth (XML) and the frozen held-out truth, plus **new never-seen clips with truth frozen before running** for anything decided after reading these results.
- **Noise floor:** each arm runs **3 times**. A difference smaller than the run-to-run spread does not count.
- **Budgets:** same models, same media and role budgets per video. Tokens and cost are reported from the provider's usage fields.
- **Criteria are written into a rules file before any run**, as for the KPI.

### P1: routing by level and uncertainty (R1)

**Problem evidence.** 77 % of decisions on level 3; 11/11 suspicions unverified.

**Why it helps.** The same budget moves to items that reach the guard.

**Metrics, per watch-list reference event and per suspicion.**
- reached the guard (recall);
- correct label;
- suspicions resolved with new frames;
- false "seen" labels;
- Verification calls and tokens.

**Success, written before the run.**
- Recall is not lower: no reference event lost in any of the 3 repeats.
- At least 50 % of suspicions get at least one new-frame inspection (today 0 %).
- False "seen" labels are not higher than the baseline's false "supported" labels.
- Verification tokens per video are not higher.

**Confounders.**
- Truth-definition disputes (LeftBag set-down / pick-up): score them separately.
- Suspicion counts are small: report n.

**Smallest version.** The 16 archived scans × 2 arms × 3 repeats = 96 agent-layer runs, without new initial scans.

### P2: facts and signals for objects (R2)

**Problem evidence.** Same-model "supported"; 1 clear false out of 8 (small n).

**Truth.** Object labels per frame (present / absent / carried) on the 7 object clips, written before computing, by a second annotator if possible.

**Offline first**, as for the floor:
- simulate the object probe from the labels;
- write the criterion: every known false placement marked, at most one true placement marked;
- inject noise.

**Live.** Never-seen object clips; share of false placements marked "Look closely" vs the baseline's false "supported".

**Confounder.** The object vocabulary itself (carried vs placed).

### P3: tool repair (R3)

**Offline (already partly done).** At least 8 of 21 refusals had new frames available.

**Live check, with the P1 runs (no extra arm).**
- refusals per video;
- recovery calls;
- share of candidates concluded without new evidence after a refusal (today 12/23).

**Success.**
- Refusals drop by at least 70 %.
- No increase in media calls beyond the budget.

### P4: hypotheses and cue from Investigation (R4)

**Hypothesis [H].** A stated distinguishing cue makes Verification's inspections more discriminating.

**Arms.** P1 routing with and without the hypotheses field, 3 repeats each.

**Metrics.**
- share of inspections whose result changes the label or the signals;
- inspections per resolved item;
- tokens.

**Success.** At least 20 % fewer inspections per resolved item, with no loss of recall.

**Confounder.** A longer Verification context. Control for it by giving the baseline arm a neutral filler of equal length.

### P5: deterministic lead and assessment by Reporting (R5)

**Offline.** Recompute the lead by severity on the 16 runs. Today the lead is a walking person in 9/16; the expected number with level-1 items present is 0.

**Live.**
- assessment sentences accepted by the code check (today, the per-incident floor calls);
- tokens per video.

**Success.**
- Acceptance is not lower.
- Calls per video are not higher.

### P6: thinking level (R6)

**Arms.** Investigation and Reporting at HIGH vs LOW on the archived scans, 3 repeats.

**Metrics.**
- identical delegation sets (watch-list items are rule-fixed, so expect identical);
- schema failures;
- tokens.

**Success.** No change in delegation or failures; at least 50 % fewer thinking tokens.

---

## 8. Answers to the three questions, per recommendation

| | Evidence the problem exists | Why the change addresses it | Independent result that would show improvement |
|---|---|---|---|
| R1 | traces: 77 % of decisions on level 3; `agents.py:1395`; 11/11 suspicions excluded | budget and the evidence loop move to the items the guard must judge | P1: suspicions inspected ≥ 50 %, recall unchanged, against XML / frozen truth |
| R2 | same model on both sides; Slump false "supported"; the floor-check precedent | the code measures facts; the model cannot certify itself | P2: false placements marked vs false "supported", on never-seen clips with frozen labels |
| R3 | 21 refusals, 18 recoveries, ≥ 8 had new frames | the tool returns evidence instead of an error | P3: refusals −70 %, measured by provider calls |
| R4 | Investigation's watch-list choices are rule-identical | gives it a decision that can change Verification's evidence | P4: inspections per resolved item, against a length-matched control |
| R5 | `report.html` ignores Reporting; lead = walking person in 9/16 | makes the one Reporting call produce guard-visible text under code checks | P5: lead correctness by rule; assessment acceptance |
| R6 | thinking/output ratios 8–17× | constrained choices may not need long reasoning | P6: identical decisions at lower tokens |

---

## 9. Limits of this audit

- **Sample size.** 16 runs of CAVIAR: 11 watch-list candidates and 13 reference events. Every verdict-quality number is small-n.
- **Version.** The traces come from the version before the floor check. Fall-related findings describe what was measured, not current behaviour.
- **Ground truth.** The KPI truth rule counts the LeftBag set-down / pick-up as no event; another reasonable rule would count it.
- **What this audit can and cannot show.** It shows where effort goes and what is structurally possible. It cannot show, offline, that the proposed changes improve the guard's decisions. That is what P1–P6 are for.
- **Sources.**
  - The pattern sources were checked on their primary pages: Anthropic "Building effective agents" (2024); Huang et al., ICLR 2024; Kamoi et al., TACL 2024; Yao et al., ReAct (evaluated on HotpotQA, Fever, ALFWorld, WebShop); Shinn et al., Reflexion.
  - Reflexion allows "internally simulated" feedback, so the claim that it needs an external signal is a simplification.
  - The LangGraph documentation pages could not be fetched (they redirect).

---

## 10. Comparison with the agent layer (`cctv-playground`)

**Sources.**
- Branch `cctv-playground` at commit `87c376d`, cloned read-only: `README.md`, `agentlab/`, `results/`.
- The group target in `docs/alignment_note_v2.tex` (v2, 25 Nov).

Their file references are relative to `cctv-playground/`. Nothing was run; no model was called.

**Their pipeline, as implemented.**
1. A **stand-in detector** fires a few seconds after every labelled event, look-alikes included (`cctv_playground/detector.py:1-9`).
2. A **triage agent** reads the alert. It is Claude Haiku 5.5 with tools: clip, frame, badge log, roster, procedures, `ask_video`, `second_look` (`agentlab/triage_agent.py:124-204`).
3. `ask_video` runs a **video check cascade**. Haiku looks at 16 frames. A code rule re-asks Sonnet for objects or when the answer is empty (`agentlab/video_check.py:24-32, 71-81`).
4. **Code rules** apply after the verdict: person down and fire are always escalated, and any failure escalates (`triage_agent.py:275-302`).
5. A **person approves** (`agentlab/review.py`). The **report** is written with code-made facts, Haiku prose and a checker (`agentlab/report_writer.py:3-8, 234-260`). Everything goes to an **append-only audit log** (`agentlab/audit.py:11, 26-31`).

**Their evidence.**
- 18 labelled clips × 3 runs, comparing video-check models (`results/step4_*.md`).
- A replay of the 486 logged answers comparing vote, single model and cascade, with no new calls.
- A 17-alert MEVA site × 3 runs plus a 4th run (`results/triage_real_site_3runs.json`).

In the 3-run file, the agent used a median of 3 model requests and 4 tool calls per alert (ranges 3–5 and 3–7). There was 1 tool error in 51 alert runs, and identical verdicts across runs.

**How comparable it is to ours.**
- **Footage:** MEVA and CAUCAFall (daytime, larger people) vs CAVIAR (384×288, people about 27 px).
- **Trigger:** their trigger knows the labels, so trigger misses cannot occur. The CAVIAR misses happened in Perception (W8).
- **Rules set after seeing the clips:** their cascade rule was set after seeing the same 18 clips (README §2), and so was our `no_floor_seen` signal.
- **Metric:** theirs is the alert verdict (escalate / dismiss / link). Ours is event-level, cited facts (±2 s).
- **Our side:** our 16 runs predate the floor check.

Their results are **experimentally supported on their site**. For transfer to other footage they are a **hypothesis**, as ours are.

### Weakness by weakness

| | Their design | Evidence on their side | Label |
|---|---|---|---|
| **W1** effort on routine; suspicions unverifiable | **Solves it, by construction.** The trigger only raises watch-list types (`event_check.py:22`, `EVENT_TYPES`), so walking never reaches the agent. Every alert gets at least one video check that must answer real or look-alike (51/51 alerts had a video answer). | 17-alert site: every alert checked | verified (code); experimentally supported (their site) |
| **W2** same-model self-agreement | **Partly.** The cascade uses a second, stronger model (Sonnet), but on the **same frames** (`video_check.py:71-81`). Only `second_look` gets new frames (±15 s); how often it was used is not in their results file. The triage brain, like our Verification, sees no pixels: it reads `ask_video`'s text. | Vote 81 % vs Haiku alone 89 % vs cascade 94 % (replay, README §2): models share blind spots. The rule was chosen on the same clips. | experimentally supported (theirs); hypothesis on new footage |
| **W3** one budget per video | **Solves it.** Each alert has its own budget: 12 requests and 2 second looks (`triage_agent.py:42, 308`). | — | verified |
| **W4** tool refusals cost loops | **Does not apply**: their clip tool cuts any window ≤ 60 s. Errors come back with guidance (`triage_agent.py:68-70`). | 1 tool error in 51 alerts | verified |
| **W5** Investigation's choices change nothing | **Partly.** Their agent has site records, which change verdicts. But the fixed rules **also** used the records (look-alikes dismissed: rules 2/7, agent 4/7). The agent's measured gain over the rules is **2 bags** whose owners kept them, dismissed after looking at the video. It mostly follows the scripted "usual route" (`triage_agent.py:55-65`; median 4 tool calls). | 12/17 → 14/17 correct, 3 runs plus a 4th | experimentally supported (their site) |
| **W6** Reporting has no effect | **Solves it.** Reports are written after approval, facts are made in code, a checker flags times, cameras and gender words, and the report is guard-facing. | 2 real drafts, no flags; not timed against writing by hand | verified (code); small n |
| **W7** thinking HIGH | **Supports our hypothesis for vision checks:** "Thinking High adds no accuracy over Low" (Gemini settings, README §1). Not tested for agent roles. | `results/step4_*.md` | experimentally supported (vision, their clips) |
| **W8** recall limited upstream | **Same problem, hidden.** The stand-in detector cannot miss, so trigger recall is unmeasured (alignment note §3.0). | none yet | verified (code) |

**Difference that needs a group decision.**
- Their agent may **dismiss an unattended-object alert**: `unattended_object` is not in `NEVER_DISMISS` (`cctv_playground/triage_stub.py:17`). Its gain over the rules comes exactly from such dismissals.
- Our watch-list puts "object left" at level 1, never dismissed (`review.py:19-23`), and the alignment note's rule R3 says level 1 is "always shown".

The two cannot both hold. **Preference:** show it, ranked low, with the agent's view, rather than dismiss it.

### Recommendation by recommendation

| | Their design | Label |
|---|---|---|
| **R1** route by level and uncertainty | **Already done at the trigger**, by event type. We still need R1 wherever our general eye emits routine observations. | verified |
| **R2** facts and doubt signals instead of a verdict | **Not done.** The video check returns a verdict (`real` true/false) and one reason (`event_check_v2.md`, Fields). This is the same "label as fact" pattern that alignment-note rule R1 asks us to show as the system's view. | verified |
| **R3** tool repair | Not needed with their tools. | verified |
| **R4** hypotheses and distinguishing cue | **Done in a fixed form.** Each event type lists its look-alikes in the prompt (`event_check_v2.md`, types 1–5), and the agent's question is passed as a focus line (`event_check.py:163-164`). There is no test with vs without the focus line. | verified (code); hypothesis (benefit) |
| **R5** Reporting writes guard-facing text under code checks | **Done:** the `report_writer.py` pattern is what R5 proposes. | verified |
| **R6** lower thinking | Supported for vision; untested for the brain. | experimentally supported (partly) |

### Mapping our three agents onto the merged target

Target: trigger → general eye → triage agent with site knowledge → rules in code → guard approval → report + audit log.

| Target stage | Keep from ours | Adopt from theirs | Drop |
|---|---|---|---|
| 0. Trigger (code) | the motion and box analysis of `experiments/image_input_study/STEP1.md` §d (it covered 13/13 events, but cannot measure savings on CAVIAR) | the alert-driven, per-alert flow and the replay clock | the full-video initial scan as the default path (keep it for evaluation and the search index) |
| 1. General eye | frame citations (126/126 valid), the neutral floor probe, the facts-and-signals principle | the cheap → strong cascade **with the rule in code**; the look-alike vocabulary per event type | — |
| 3. Triage agent = **our Investigation** | the code validation of every model output (IDs, quotes, shared frames) | site tools (roster, badge log, procedures, neighbouring cameras), the per-alert budget, the "send / dismiss with reason / link" output | Investigation's `search` (unused) and the 4-slot triage over a whole video |
| Second look on new frames = **our Verification**, called by triage | the new-frames requirement, quote-grounded correspondence, the 250 ms fine look | `second_look` as a tool with a per-alert cap | routine verification; the "supported" label as a fact (it becomes the system's view) |
| 4. Rules in code | watch-list levels, never-dismissed, the floor doubt signals | failure → escalate; link validation (`apply_rules`) | — |
| 5. Guard, report, audit = **our Reporting** | `report.html` layout (facts, signals, images); the assessment wording checks | `review.py` approve / dismiss / reopen; append-only `audit.jsonl`; `report_writer.py` (code facts + model prose + checker) | the `lead_id` / `emphasis` choice |

**Smallest set of changes, in order.**

Each change is proposed only. None is implemented; each needs your approval and the experiment named in §7.

1. **Run per alert, not per video**, so every alert gets its own Investigation → Verification budget. This addresses W1 and W3 together. **Hypothesis**; test with P1 on the archived scans, cost below.
2. **Give Investigation read-only site tools** (roster, badge log, procedures, from their kit), and add the "dismiss with reason" output, subject to the level rules. **Experimentally supported on their site only**; needs a CAVIAR-like site profile to test.
3. **Turn Reporting into the post-approval report writer** (their `report_writer.py` pattern, our checker words), and **adopt their audit log and review step.** This addresses W6. **Verified** that it works on their side; low risk.
4. **Verification:** make suspicions resolvable, and repair the tool (R1 suspicions part, and R3).
5. **The general-eye cascade** (cheap → strong model by code rule). On CAVIAR this needs a model comparison like their step 4. **Hypothesis** for our footage (objects are the hard case on both).

**Cost of the smallest experiments.** These are estimates from the archived usage at Gemini 3.6 Flash launch rates. The agent layer alone costs about $0.15 per video run: Verification, Investigation, Reporting and targeted Perception, for 16 runs, from `tokens.py`.
- **P1 / change 1:** 16 videos × 2 arms × 3 repeats ≈ 96 runs ≈ **$15**, with no new initial scans.
- **Change 2 (site tools):** needs a small CAVIAR site profile and alerts. The model cost is below $5, but most of the cost is hand-writing the records.
- **Change 3:** offline, plus about 10 report drafts ≈ **under $1** (their measured $0.0014 per draft with Haiku; similar order with Gemini Flash).
- **Change 5:** a cascade comparison on the 16 clips × 3 runs. With Gemini only, about **$5–10**. A Claude arm would need an extra provider and your approval.

**Bottom line.**
- **Both layers are workflows with bounded agent decisions.** Theirs puts its one real decision where it pays: site context plus a video check per alert. Ours spends ours on routine items inside a whole-video scan.
- **Merge around their alert-driven skeleton, and keep our evidence discipline:** citations, new frames, facts and signals, code validation.
- **Preference:** hold the group decision on dismissing level-1 object alerts before adopting their dismiss output.
