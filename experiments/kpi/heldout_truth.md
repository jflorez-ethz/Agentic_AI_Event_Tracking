# Held-out truth: videos never given to the agent system

The truth was frozen before any run, on 2026-11-24. The machine-readable version is [heldout_truth.json](heldout_truth.json), with hashes. The KPI rules ([rules.json](rules.json)) and the system version (src tree `7e86f3b`) are unchanged. Times are presentation timestamps (PTS) of the analysed file.

| Video (analysed file) | Expected critical event | PTS | Source and label | Checked on images |
|---|---|---:|---|---|
| Rest_SlumpOnFloor.mpg | person down (`person_fell`) | 26.08 s (frame 646) | XML object 5, context "drop down", first frame with situation "inactive" | sinks down 25.4–27.2 s, sitting on the floor at 27.8 s ([frames](heldout_evidence/Rest_SlumpOnFloor_21.8-28.4s.png)) |
| Rest_WiggleOnFloor_pts.mkv | person down | 27.76 s (frame 689) | XML object 2, "drop down", situation moving → inactive | down at 28.2 s, lying at 28.8 s ([frames](heldout_evidence/Rest_WiggleOnFloor_24.6-31.2s.png)) |
| Fight_OneManDown.mpg | person down | 13.72 s (frame 338) | `Fight_OneManDown_1.xml` object 5, "drop down", moving → inactive | on the floor at 13.4 s ([frames](heldout_evidence/Fight_OneManDown_12.2-16.6s.png)) |
| LeftBag_BehindChair.mpg | object placed | 20.96 s (frame 518), possible range 15.44–20.96 s | **manual label**, low confidence | see below |
| LeftBag_BehindChair.mpg | object removed | 34.04 s (frame 845), possible range 31.64–34.04 s | **manual label**, low confidence | see below |
| Rest_InChair.mpg | none (control) | — | XML: no drop down, no object | reviewed at 1 frame/s |
| Browse1.mpg | none (control) | — | same | same |
| Browse2_pts.mkv | none (control) | — | same | same |

The pooled total is 5 critical events: 3 people down, 1 object placed and 1 object removed.

## Choices to know

- **Rest_SlumpOnFloor.** The frozen automatic rule (moving → inactive) does not fire, because the person goes moving → browsing → inactive. The event is taken directly from the XML label.
- **Fight_OneManDown.** The three CAVIAR files disagree: `_1` gives 13.72 s, `_3` 14.76 s and `_2` 14.88 s (the rule does not fire on `_2`). `_1` is kept because it matches the images. The fight itself (about 9–13 s) is not a measured category.
- **Rest_WiggleOnFloor.** The XML stops at frame 1188, which is 47.76 s, while the video lasts 52.04 s. An alert lying entirely after 47.76 s is reported as "not scorable", never as false.
- **LeftBag_BehindChair (manual label).** The XML has no bag track. The bag is almost entirely hidden behind the upper orange armchair, next to the desk. A person in dark clothes goes behind that armchair from about 15.4 s and leaves upwards; the place stays changed from about 20.96 s ([frames](heldout_evidence/LeftBag_BehindChair_placement_17.6-21.4s.png)). A person in a white shirt reaches behind it from about 31.6 s, and the place is empty again from 34.04 s ([frames](heldout_evidence/LeftBag_BehindChair_removal_31.2-35.0s.png)). The small black block between the armchairs is a stool, present from 10 s, before anyone arrives ([frames](heldout_evidence/LeftBag_BehindChair_stool_present_from_10s.png)). The two times follow the convention of the frozen rule: the first frame with the object alone, and the first frame without it. An independent second label would make this event stronger.
- **"Never seen."** The agent system has never seen these videos, and no `src/` change is based on them. LeftBag_BehindChair was used earlier in the offline tracking audit (RF-DETR detections and a few frames looked at).
