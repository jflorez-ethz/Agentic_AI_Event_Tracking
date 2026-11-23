# Blinded annotation packets

Open only the evaluation video, its `frames.csv`, this guide and your copy of the blank form. The packets contain no model descriptions, reports, verdicts or XML labels. Score the footage on its own. A coordinator should keep model outputs out of reviewers' working directories until the references are frozen.

| Packet | Duration | Blank form |
|---|---:|---|
| [Meet Walk Split](walk_split/README.md) | 24.96 s | [annotation.json](walk_split/annotation.json) |
| [Meet Walk Together](walk_together/README.md) | 28.32 s | [annotation.json](walk_together/annotation.json) |
| [LeftBag excerpt](left_bag/README.md) | 25.00 s | [annotation.json](left_bag/annotation.json) |

## Review procedure

1. Give two reviewers separate copies of the same form. Each enters a stable code in `reviewers`. Keep `case` and `source_sha256` intact. Watch the entire evaluation video once, including intervals where nothing is discernible.
2. On a second pass, identify literal visible events, then refine their boundaries and find supporting frames. Annotate the weakest claim the images justify. If people overlap or leave view and correspondence cannot be established, record that limit. A later visible person, similar clothing, or movement in the same direction cannot establish continuity.
3. Complete the predefined questions after the event pass. Keep question IDs and text fixed. Cite the frames used for the reference answer or the frames showing the limitation. Reviewers work independently until their first passes are saved.
4. Adjudicate disagreements against the video. Keep both original forms and record the rationale for disputed boundaries, visibility and correspondence. Keep any genuinely ambiguous observation as ambiguous. Keep `review_complete` false while any part of the reference review is unfinished.

### Event form

Copy this blank object into `events` for each event. Replace `null` and empty strings with your annotations. Add or remove frame objects as needed.

```json
{
  "id": "",
  "description": "",
  "category": "",
  "interval": {"start_us": null, "end_us": null},
  "status": "",
  "participants": [],
  "supporting_frames": [
    {"display_index": null, "pts": null, "source_time_us": null}
  ],
  "uncertainty": ""
}
```

Use unique local IDs such as E01. Use integer microseconds on the evaluation source clock. The start is inclusive and the end is exclusive. When the last supporting frame is also the chosen end of the visible bracket, set the exclusive end just after it and within the clip duration. Record alternative boundary estimates in `uncertainty`. Copy frame fields directly from the packet CSV. `participants` may contain local descriptions of distinguishable people or objects and may be empty. Describe gaps or unclassifiable activity in optional top-level `review_notes` instead of creating a new event category.

| Category | Required visual evidence |
|---|---|
| `person_moved` | A distinguishable figure changes position within view. |
| `person_appeared` | A person becomes visible across a before/after bracket. Being visible on the first frame alone cannot establish appearance. |
| `person_enters_area` | A person crosses a physically identifiable boundary. Describe the boundary. Visibility at the edge of the image supports a visibility claim only. |
| `object_appeared`, `object_disappeared` | A visible change across frames, with cause left open if unseen. |
| `object_placed`, `object_removed` | The physical placement or pickup is visible. An object's presence or disappearance alone cannot establish physical handling. |

Use `supported` when the visible evidence establishes the event. Use `ambiguous` when a plausible event of an existing category remains visually uncertain. Include frames showing what limits the judgment. An empty `events` list is acceptable after a complete review that finds no annotatable events. It is also the default for an unfinished form, which must retain `review_complete: false`.

### Question reference form

Each form contains three question prompts with blank response fields. Complete `expectation` as follows:

- `answer` when footage supports a grounded answer. List one or more supported event IDs in `expected_event_ids` and write the literal answer in `reason`.
- `abstain` when the question asks for a conclusion the footage cannot establish. Keep `expected_event_ids` empty and state the evidence limitation in `reason`.
- `unscorable` when a defensible reference judgment cannot be made. Keep `expected_event_ids` empty and explain why in `reason`.

Add `supporting_frames` using the event frame format. The scorer checks question IDs, outcomes and expected event links. Reviewers check the textual rationale and question frame references during adjudication.

### Reproduce a review frame

From the repository root, substitute the evaluation video path from the packet and the zero-based display index from the CSV:

```bash
video=data/raw/Meet_WalkSplit_pts.mp4
frame=0
ffmpeg -v error -i "$video" -map 0:v:0 -vf "select=eq(n\,$frame)" \
  -frames:v 1 /tmp/sa-review-frame.png
ffprobe -v error -select_streams v:0 -show_entries stream=time_base:frame=pts \
  -of json "$video"
```

The CSV uses presentation order and time relative to the first source frame. Use LeftBag excerpt columns for validation. The original columns let reviewers find the same frame on the original recording's clock.

## Freeze and validate

The set is ready to freeze when both independent passes and adjudication cover all three videos, event and question IDs are stable, question judgments are complete, and residual disagreements are documented. The adjudicated file lists reviewer codes and sets `review_complete: true`. Passing the scorer's checks confirms file and source consistency. The coordinator still checks visual support, complete review and blinding.

Run after adjudication from the repository root. These commands check the original scorer prerequisites **without opening saved model output**, including for LeftBag:

```bash
for case in walk_split walk_together left_bag; do
  .venv/bin/python experiments/mvp_evaluation/score.py --validate-only \
    --case "$case" --annotations "annotations/$case.gold.json" || break
done
```

Keep each printed source and annotation SHA-256 with the frozen files. If a reference changes later, retain the old version and record why. Do not edit a frozen reference after seeing model outputs without flagging the change.

## Compare after freeze

Keep the following outputs outside the blinded packet directories:

```bash
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split \
  --annotations annotations/walk_split.gold.json > walk_split-review-packet.json
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split \
  --annotations annotations/walk_split.gold.json --review walk_split-reviewed.json \
  > walk_split-scores.json
```

Repeat for `walk_together`. LeftBag validation is available now. Scoring that case additionally requires `--artifact /path/to/saved/analysis.json` for this exact hashed excerpt. See the [scoring protocol and review file](../README.md).
