# E1 LeftBag frame-versus-clip pilot

## Provider configuration

Gemini Developer API candidate `gemini-3.8-flash` is documented for image and video input and structured output. Google lists up to 1,048,576 input tokens and 65,536 output tokens. E1 uses the Google GenAI Python SDK with `generate_content`, `v1beta`, JSON Schema, low thinking and an output cap of 4,096 tokens. Project-level access remains unverified. [Model](https://aistudio.google.com/docs/models/gemini-3.8-flash) · [Structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output) · [SDK](https://googleapis.github.io/python-genai/)

The image guide lists PNG, JPEG, WebP, HEIC and HEIF. The video guide lists MP4, MPEG, QuickTime, AVI, FLV, MPG, WebM, WMV and 3GPP. This pilot uses inline PNG and silent lossless VP9 WebM. The Generate Content inline example specifies a 20 MB total request limit, even though the guide’s general comparison table lists a higher inline limit. E1 conservatively budgets 19 MB for base64 media plus request text and schema. There is no Files API upload. [Image formats](https://aistudio.google.com/docs/image-understanding?generate-content=true#supported-formats) · [Video formats and inline limits](https://aistudio.google.com/docs/video-understanding?generate-content=true)

Static video processing defaults to 1 FPS. The SDK exposes custom video FPS in `video_metadata`. E1 requests 2 FPS. The actual provider-selected frame identities and count remain unknown unless the provider reports them. The encoded clip frame count and token usage cannot establish either. [Video sampling](https://aistudio.google.com/docs/video-understanding?generate-content=true#custom-frame-rate)

Google AI Studio creates authorization keys by default and the API rejects unrestricted standard keys. Set a Gemini API key through `GEMINI_API_KEY` or `GOOGLE_API_KEY`. Rate limits apply per project and can include requests per minute, input tokens per minute and requests per day. Check active limits in AI Studio. Google lists standard paid pricing through December 31, 2026 of USD $0.75 per million input tokens and $3.75 per million output tokens including thinking, with $1.50 and $7.50 respectively listed from January 1, 2027. The pricing page indicates free-tier data may be used to improve Google products and paid-tier data is listed differently. Any E1 cost value is an estimate at published standard paid rates, without cache discounts. [Authentication](https://aistudio.google.com/docs/api-key) · [Quotas](https://aistudio.google.com/docs/rate-limits) · [Pricing and data handling](https://aistudio.google.com/docs/pricing#gemini-3.8-flash)

## Cases and offline preparation results

Both modes use the same half-open requested source windows, taxonomy, substantive prompt and model configuration. The frame arm requests a frame every 500 ms starting at the first clip frame’s source time and then uses the deterministic first-at-or-after rule. It labels each PNG with its actual source time. The clip arm contains all selected source frames and asks Gemini to sample at 2 FPS. Actual first and last image times are recorded separately from clip bounds. The only prompt differences concern citation format and modality-specific limits.

| Case | Requested source interval (s) | Local visual reference | PNG parts | Encoded clip frames |
|---|---:|---|---:|---:|
| A | [36.0, 40.0) | A person approaches the right side with a dark bag, bends, and moves away while a dark bag remains by the seat. | 8 | 100 |
| B | [37.4, 38.2) | The person bends over the dark object. Their body overlaps it and this window lacks a clear before-and-after view establishing release. | 2 | 20 |
| C | [44.0, 48.0) | The dark object stays beside the seat with no visible placement or removal in the checked window. | 8 | 100 |

A and B overlap intentionally and are different views of the same episode. Treat them as correlated cases from a single recording. The same-index XML mapping is visually supported at scene level; it has unresolved frame-level offset uncertainty. After selecting the windows from the footage, I checked that XML object 4 appears at index 945 near the visible dark object and remains boxed near the seat during the negative window. The XML can corroborate object presence and location at the scene level. It provides no frame-exact release label and gives no independent verdict for the short ambiguous window. XML and case judgments are excluded from every model prompt.

The offline run prepared all six requests. Each WebM was decoded and checked against the lossless source clip for every PTS, final duration and pixel hash. The runner saves exact submitted bytes, payload hashes, per-part labels, request settings and source mappings. In a live run it also saves raw responses, validated observations, attempt errors, latency, returned usage, cost estimates where available, and a replay manifest of resolved source frames.

## Reproduction

From the workspace root, with the Python and FFmpeg prerequisites in [progress.md](progress.md), including FFmpeg with `libvpx-vp9`. Use a new local output directory for each run.

```sh
PYTHONPATH=src python3 -m security_augmented.e1 --output /tmp/leftbag-e1-offline
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

After explicit authorization to transfer the LeftBag footage and configuration of the auth key and project, run the following. Two repetitions issue up to 12 requests across the three windows and two modes. The separate opt-in live smoke suite sends a synthetic image only.

```sh
python3 -m pip install -r requirements-e1.txt
E1_RUN_LIVE_SMOKE=1 PYTHONPATH=src python3 -m unittest discover -s tests_live -v
PYTHONPATH=src python3 -m security_augmented.e1 --live --authorize-footage-transfer \
  --repeat 2 --output /tmp/leftbag-e1-live
```

## Human review after live inference

Have a reviewer establish reference events and visibility from the original video before looking at model responses. For each window, mode and repetition, inspect the exact submitted artifact and replay the recorded references from the source. For clips, a resolved interval identifies possible source frames in the supplied clip without establishing what Gemini actually sampled.

Record each statement as supported, contradicted, or indeterminate, with a short reason. Count expected events omitted and unsupported events invented. Count attempted and valid requests, total and resolving references, and observations with adequate visibility and uncertainty descriptions in case B. Record the resolved frame times or clip-to-source range and compare timing against independently recorded event bounds, including their uncertainty. Separate schema/reference failures from visual errors and absence of evidence from a demonstrated negative. Compare returned token counts, elapsed latency and estimates per request and arm, using denominators and reporting unavailable values explicitly.

| Window / mode / attempt | Supported / contradicted / indeterminate | Missed / unsupported | Resolved / cited | Localization and ambiguity notes | Latency / tokens / cost |
|---|---|---|---|---|---|
| | | | | | |

No model inference, latency, usage, cost, or accuracy result has been observed. Recommend explicit timestamped frames as the provisional MVP baseline because their exact visual inputs and source citations can be reproduced and sampling density is under local control. Use the paired comparison to decide whether clips add value on short actions or ambiguity at acceptable cost. The pilot is exploratory and supports no statistical accuracy claim.
