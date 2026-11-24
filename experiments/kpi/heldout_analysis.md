# Analysis of the never-seen table (2026-11-24, after the runs)

[KPI_heldout.md](KPI_heldout.md) is the frozen result and is unchanged. This page only explains it, from the run files and the images. Nothing was re-scored.

## The 5 alerts counted as false

| Video | Category, status | Time | What Gemini wrote | On the images | Verdict |
|---|---|---|---|---|---|
| Browse1 | person down, "possible" | 7.52–8.52 s | "upright … then lower and partially hidden near the image boundary … cannot be confirmed whether the person fell or stepped beyond the image edge" | The person in blue walks out through the bottom edge ([frames](heldout_evidence/after_run/Browse1_possible_fall_7.5s.png)) | **Real error**, flagged as uncertain |
| Browse2 | object placed, "possible" | 30.0–31.0 s | "standing next to a black case on the floor … uncertain whether the person placed the case or if it was already located there" | The "case" is the fixed black object against the right wall, already there at frame 0 and unchanged afterwards ([frames](heldout_evidence/after_run/Browse2_possible_placement_30s.png)) | **Real error**, flagged as uncertain |
| Fight_OneManDown | person down, "possible" | 20.04–22.04 s | "sitting or crouching on the floor in F1 before getting up … not shown upright before" | The same victim, on the floor since 14 s, getting up ([frames](heldout_evidence/after_run/Fight_possible_fall_20s.png)) | **Real scene, same fall seen again** in the next 10 s window |
| Rest_SlumpOnFloor | person down, **confirmed** | 2.52–3.04 s | "grey top and dark trousers … standing upright in F6 and lying on the floor in F7"; Verification: supported from those 2 frames | The grey person just walks around the stool and the armchair, then leaves; seen from above, a walking body looks stretched out ([frames](heldout_evidence/after_run/Slump_confirmed_fall_2.5s.png), [zoom](heldout_evidence/after_run/Slump_confirmed_fall_2.5s_zoom.png)) | **Real error, and confirmed**: the most serious one |
| Rest_WiggleOnFloor | person down, "possible" | 40.0–49.52 s | "transitions to lying on the floor, but is not observed standing upright prior" | The same person, still on the floor from 28.8 s to beyond 49 s; the XML also has them "inactive" on the floor ([frames](heldout_evidence/after_run/Wiggle_possible_fall_40s.png)) | **Real scene, same fall seen again** |

None is an event missing from the XML: there was no new fall, placement or removal. The bottom-left person in Slump (0–3 s) only carries a briefcase through.

The 5 alerts split into two kinds:

- **3 real errors.** Two are "possible" alerts, and Gemini wrote its own doubt (a person leaving through the image edge; an object that was already there). One is **confirmed**: Slump at 2.5 s. Verification accepted "standing in F6, lying in F7" from only two images 0.5 s apart. It is the same mistake as in the dev table (LeftBag 1.5–3.5 s, a person bending), but this time it passed Verification.
- **2 repeats of a real fall** (Fight, Wiggle). Each 10 s window is analysed without memory of the previous one. A person who is still on the floor in the next window becomes a new "possible fall", because they are "not seen upright before". The scene is real, but the operator gets a second alert for the same incident. The strict ±2 s rule therefore counts them as false.

On the images, 5 of the 8 alerts concern a real person on the floor, but only 3 of the 8 are new events. The frozen figure 3/8 stays the reference.

## LeftBag_BehindChair: was the bag visible to Gemini?

**No.** Gemini received 384×288 frames, 2 per second.

- 12–14 s: a dark shape on the back of the person walking in. Gemini wrote "a person carrying a backpack walks … toward the desk and seating area on the left" (10–19.5 s).
- 15.5–19 s: the person goes behind the armchairs. The placement is hidden by the upper armchair. In the frames sent after 20 s, nothing is distinguishable behind the chair ([frames sent 12–22.5 s](heldout_evidence/after_run/LeftBag_BehindChair_sent_frames_12-22.5s.png)).
- 31.5–36 s: the person in a white shirt behind the armchairs covers only a few pixels. Gemini does not mention them at all ([frames sent 30–36.5 s](heldout_evidence/after_run/LeftBag_BehindChair_sent_frames_30-36.5s.png)).

The two misses are a visibility limit of this camera and this resolution, not a reasoning error: the object never appears on its own in the frames sent. The only usable clue would be the backpack seen on arrival and no longer seen on departure. That would require memory across windows, which the current version does not have. These two events rest on a manual label with low confidence.

## What this changes in the reading of the table

- Critical events: 3/5 found. The 2 misses are a hidden object; all 3 falls were found.
- The real weaknesses seen on never-seen videos are:
  1. **A confirmed false fall from two images.** This matters most, because it is not flagged as uncertain.
  2. **Repeated alerts for the same incident**, because windows have no memory.
  3. **"Possible" alerts at the image edge or on fixed objects**, which are correctly flagged as uncertain.
- These are observations from 7 short videos. They do not change the frozen table and are not a new tuning.
