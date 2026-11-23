# Meet Walk Split supported-findings audit

Source: `data/raw/Meet_WalkSplit_pts.mp4`. Decision and inspection records: [archived Verification result](verification.Uk6X57/run/result.json). The archived renderer is preserved in [report.md](verification.Uk6X57/run/report.md).

FFprobe reports 384 × 288, 25 fps, stream time base 1/12800. Local source SHA-256, display index, source PTS, source-relative time and RGB24 SHA-256 matched for all 53 final citation references (40 distinct frames) and all 614 recorded targeted clip source-frame references (667 references over 467 distinct source frames). See the [frame manifest](supported-findings-frame-manifest.json). The four WebM inspection records provide exact requested and actual half-open source spans, source-to-clip mappings, artifact hashes, and a requested 2 fps. The run directory retains no submitted WebM payload or provider frame-sampling record. The inspection frame inventory establishes local clip coverage, while the exact subset evaluated by Gemini cannot be recovered.

## Claim-to-evidence ledger

Frame numbers below are zero-based source display indices. The display timestamps in the report show the final cited sample, while clip end times are exclusive.

| Bracket / candidate | Recorded claim and targeted result | Source review and verdict |
|---|---|---|
| 0–9.52 s / `3bfb1c56…` | Dark shirt and lighter trousers, from sunlit aisle into central atrium toward upper left. Verification selected transition 0→238 and cited the initial 20-frame sequence. Targeted [0,9.52) returned two movement descriptions: an orange-top figure from the left and a dark-clothed figure from the lower edge. The latter explicitly leaves continuity across an earlier frame-edge gap unproven. Neither clip observation is in final citations. | Frames 75–125 (3–5 s) show movement along the bright aisle and onto the adjoining floor, with a separately visible lower-edge figure. Frames 138–238 show movement toward the upper-left part of the atrium. **Supported at the visual movement level.** Initial glare and multiple figures limit clothing precision and an unbroken identity assignment from frame 0. |
| 3.52–9.52 s / `da6fdebc…` | Dark-clothed figure walks diagonally toward upper left, with the Investigation description adding that the figure joins another walker. Verification selected 88→238 and cited 13 initial frames. Targeted [3.52,9.52) returned two appearance and two movement descriptions. The proposed verdict selected clip observation `74a538a6…` for lower-right to upper-left movement; the final event retained the original frame witness. | Frames 88 and 125 show the lower-right figure moving diagonally. Frames 150–188 (6–7.52 s) show closing distance, partial overlap and subsequent nearby walking. **Supported for diagonal movement and approach; social joining, coordinated intent and persistent pairing remain uncertain.** Adjacent source frames around the 9.52–10 s gap are audit context rather than final citations. |
| 10–14.52 s / `ac83682…` | Walk toward the upper-left corridor. Verification selected 250→363 and described clip corroboration. Targeted [10,14.52) returned two appearance and two movement observations. `2170e043…` describes an upper-left path and is marked same-event with shared frame 250. `34671dfa…` describes a separate movement toward seating. The final event cites ten initial frames only. | Frames 250, 300 and 325 show two dark figures and distinguish paths toward the upper-left wall and the seats. Frame 363 is darker and harder to read near the boundary. **Supported from the final frame sequence alone** for movement toward the upper-left part of the scene. Neither the common frame nor the clip observation establishes identity with people in earlier events. The rationale cites a clip contribution that the rendered Event citations omit; the same model supplied both interpretations. |
| 20–24.52 s / `433e1420…` | Purple top and dark pants moving left to right along glass-roofed walkway. Verification selected 500→613 and cited ten initial frames. Targeted [20,24.52) completed with zero observations. | Frames 500, 550 and 613 (20, 22 and 24.52 s; PTS 256000, 281600, 313856) show a purple-toned shape in roughly the same position relative to the crossbars. Native-frame review and nearest-neighbor enlargement of every fifth frame show small local changes amid glare and occlusion. Adjacent frames 605–623 do not clarify a traversal. **Insufficient to independently confirm a person traversing the walkway or a reliable left-to-right path.** Local motion or posture changes remain possible. The empty clip result establishes neither presence nor absence. |

For the 10–14.52 s association the exact shared frame is `frame-f6da36a00991e63bcc20c523bfd3d338bba4a131f9a3ff5afe220be385e5b7ad` (index 250, PTS 128000). The final endpoint is index 363, PTS 185856. For the close approach, indices 150, 175 and 188 are 6.00, 7.00 and 7.52 s. The manifest records full identifiers and digests.

## Provenance and reporting

Production's direct-transition validator keeps the seed and selected before/after witness. All four decisions selected the seed as witness, so the resulting frame-only final citations are consistent with that rule. The extra clip observation for 10–14.52 s remains traceable in the archived verdict and inspection. The missing report link is a distinction between the evidence required for the final verdict and additional evidence the model discussed. The current renderer attributes the rationale to the model, but the archived report predates that rendering and shows the generic movement label only. A valid citation and two distinct pixel hashes establish provenance and frame change. They cannot establish which object moved or the meaning of a trajectory.

No production change is warranted from this single provisional audit. Keep the 20–24.52 s finding flagged for review. For 10–14.52 s, describe the clip as additional evidence discussed in the rationale and point to its archived inspection if it is mentioned. If the distinction must appear in the product, add an explicit trace link for the rationale rather than expanding the validated citation set.

## Reproduction and review protocol

From the repository root:

```sh
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,time_base,r_frame_rate -of json data/raw/Meet_WalkSplit_pts.mp4
ffmpeg -v error -i data/raw/Meet_WalkSplit_pts.mp4 -vf "select='between(n,500,613)*not(mod(n-500,5))',crop=152:76:0:157,scale=304:152:flags=neighbor,tile=5x5" -frames:v 1 /tmp/meet-walk-tail.png
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_verification.py -k preserves_archived
```

The manifest can be rechecked using `video.ingest` and `video._decode` over its sorted distinct display indices. Compare `video.frame_pts[index]`, `video.time_at_pts(pts) * 1000000`, and `hashlib.sha256(rgb).hexdigest()` to each reference, using the nested `source` record for clip frames.

Independent blinded review was unavailable. The visual judgments above are provisional and agreement is unmeasured. A reviewer should first mark movement, direction, person continuity and occlusion from the cited frames only and record exact supporting indices. Then reveal adjacent frames and record any changed judgments separately before showing model labels and rationale.
