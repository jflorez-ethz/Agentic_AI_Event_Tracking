# E1 comparison 001 review

Five of six requests completed with valid structured responses. The only positive clip case returned HTTP 503, leaving no matched positive comparison. The successful pairs describe one ambiguous window and one negative window from the same recording. They do not establish relative perception quality.

## Local verification

- Reprobed the original LeftBag recording and matched the saved source hash, video ID, stream and frame timestamp index. Verified the size and SHA-256 of all 18 archived PNGs and three WebMs. Every PNG decoded to the exact RGB24 pixels of the timestamped source frame. Every WebM decoded to the exact source pixels in display order, including all 220 frames across the three clips. Each clip was 384 × 288 VP9 with a single video stream, no audio, zero-based PTS on a 1 ms clock, and the recorded frame PTS and final duration.
- Reconstructed all six payloads from the archives with Google GenAI SDK 3.6.1 and a local mock HTTP transport. The SDK serialized the expected `v1beta` `generateContent` route for `gemini-3.5-flash-lite`, alternating source-time text and inline `image/png` parts for frames and an inline `video/webm` part with `videoMetadata.fps: 2.0` for clips. The decoded base64 bytes matched the archived files. The wire config contained the archived JSON Schema, JSON response MIME type, LOW thinking and a 4,096-token output cap. This was a local reconstruction. The historical archive contains no HTTP wire capture or provider-selected frame list.
- All five successful provider candidates ended with `STOP`. Reparsed the raw JSON with the archived taxonomy and evidence and reproduced the saved observations and replay records. The ten cited frame references resolved to the exact submitted source frames. No successful clip cited an interval, so live clip citation behavior remains untested. The 503 had no model candidate, raw response or usage in the archive. It is an API/server failure with an undetermined cause. Its reconstructed body was 7.44 MB, while the successful Window C clip body was 7.38 MB. This makes a simple size-limit explanation less persuasive without ruling out media-specific server issues.

## Coverage and observed usage

Times are source-relative seconds. Clip bounds are half-open and include the final frame duration. The frame arm uses first-at-or-after sampling on a 500 ms request grid, with realized gaps of 480 or 520 ms. Both arms begin at the same source frame per window. Clips encode the tail after the last PNG, but the provider’s selected frame times, count and effective coverage are unknown.

| Window | PNGs and first–last sample | Clip frames and extracted bounds | Clip duration |
|---|---|---|---:|
| A | 8, 36.0397–39.5597 | 100, [36.0397, 40.0397) | 4.0 s |
| B | 2, 37.4397–37.9597 | 20, [37.4397, 38.2397) | 0.8 s |
| C | 8, 44.0397–47.5597 | 100, [44.0397, 48.0397) | 4.0 s |

| Request | Result | Prompt tokens by reported modality | Candidate / total tokens | Latency |
|---|---|---|---:|---:|
| A frames | Placement | 8,512 image + 266 text | 165 / 8,943 | 2,857 ms |
| A clip | HTTP 503 | Unavailable | — | 2,489 ms |
| B frames | Insufficient evidence | 2,128 image + 170 text | 155 / 2,453 | 3,115 ms |
| B clip | Empty array | 126 video + 165 text | 9 / 300 | 3,734 ms |
| C frames | Empty array | 8,512 image + 266 text | 9 / 8,787 | 3,911 ms |
| C clip | Empty array | 504 video + 166 text | 5 / 675 | 3,113 ms |

The five successful responses reported 20,815 prompt and 343 candidate tokens, totaling 21,158. VIDEO token metadata establishes that the provider accounted for video input. It does not reveal sampled frame counts, frame times, or visual detail. These are per-call observations. Billing for the failed request is unknown.

## Perception and comparison validity

- **A, positive placement.** Original display frames 895–983 show the person approaching the right-hand seat with a dark bag, bending near it, then walking away while it remains. The placement description is supported at the event level. The model’s proposed release bracket F3–F5 spans 37.0397–38.0397 s, but hand contact and exact release remain uncertain from these views. Citing all eight images supplies context with limited localization. The XML first marks object 4 at index 945 near the seat under the provisional same-index alignment. That corroborates appearance, with no exact release label. The failed clip leaves this pair unavailable for perception scoring.
- **B, ambiguity.** Source frames 930 and 943 show a person bent over near the dark object. Other frames in the short clip around 945–949 still show overlap and do not clearly establish the action’s outcome. The frame response therefore gives a defensible explicit abstention. The clip’s empty array is valid JSON with no asserted event, but whether it reflects appropriate abstention, a missed visible cue, or inference behavior remains unresolved. An empty array alone does not satisfy the ambiguity criterion. The longer A window contains decisive context that B omits.
- **C, negative.** Review of source frames in the window shows a stationary bag beside the seat with no visible placement or removal. Relevant XML entries, including 1095 and 1194, retain object 4 at the same location. Both empty outputs agree with this negative case. They provide no evidence that the model actively assessed the entire window.

The shared taxonomy and prompt support comparison of explicit placement, removal and uncertainty outputs. They leave a negative finding, abstention and missed event indistinguishable when the output is empty. The pilot contains no independent positive removal case. It also confounds modality with provider sampling and visual processing, and A and B overlap. Compare these arms as configured pipelines, without attributing differences to the media format alone.

## Corrections and smallest follow-up

No clip encoding, timestamp mapping, MIME or FPS defect was found. Logging and evaluation have gaps. The adapter preserves only the sanitized HTTP status for the 503, so its cause cannot be diagnosed from the archive. On future authorized calls, retain safe provider error codes and request identifiers when available. Require normal completion before scoring output, and keep transport, schema, citation and perception outcomes separate. For a later ambiguity comparison, use the same prompt in both arms and require an explicit per-window assessment distinguishing a visible event, no visible target event and insufficient evidence. Keep abstentions distinct from negatives in scoring. None of these changes is needed to repeat the missing positive clip as archived.

**First follow-up, one additional request after authorization.** Replay only the saved Window A WebM with the same hash, model, prompt, schema and 2 FPS setting. Leave the other five requests unchanged. Record the attempt separately and stop after one response, including another 503.

- Operational acceptance requires a completed candidate with valid JSON, recorded usage when returned, and a resolving source interval for any placement claim. A repeated API error leaves the positive pair missing. A parse or citation error is recorded in its own category.
- Perception acceptance requires a supported placement description with a citation covering the visible transition or sufficient before-and-after evidence. It should avoid asserting an exact release time or claiming identity or intent. A valid empty result on A is a missed positive for that configured arm on this attempt, with provider sampling still unobserved.
- A successful A retry completes the positive pair for this pilot. It cannot resolve the meaning of B’s historical empty response. Test B separately only if the ambiguity question remains a priority, using one request per arm with the same explicit assessment prompt. Acceptance is an evidence-linked uncertainty assessment grounded in the bending and occlusion, without a definitive placement or removal claim.

No external API calls were made during this review.
