# Anonymous tracking pilot (offline)

Question: would anonymous tracks ("Person C", "Bag 1"), produced locally before Gemini as the plan's detector C1, make the missed bag pickup in `LeftBag_PickedUp` detectable? Can an off-the-shelf tracker deliver them?

## C.1: perfect tracker (CAVIAR XML tracks)

A deterministic rule with no model call looks for object tracks that start or end inside the view, away from the image edge, while touching a person. On `lbpugt.xml`:

- Bag 1 appears inside the view at 20.36 s, touching Person C.
- Bag 1 vanishes inside the view at 40.88 s, touching Person C.
- Bag 1 stays stationary meanwhile, with 4 px drift over 20.5 s.

Both placement and pickup become candidates without depending on Gemini noticing them. On LeftBox the bag track ends at the last frame of the video. That means the bag is still present when the video ends, not removed, and the rule must say so. Fall, Walk2 and TwoEnterShop1front contain no annotated objects and produce no candidate.

## C.2: RF-DETR Nano (COCO weights) + ByteTrack, CPU

`pilot.py` scores each XML track against the predicted tracks at IoU ≥ 0.3. Results are in `leftbag_pickedup-stride{5,1}.json`.

| Ground-truth track | 5 fps | 25 fps |
|---|---|---|
| Person C (leaves and picks up the bag) | 91.5% found, 2 numbers, switch at 40.04 s | 92.6%, 3 numbers, switches at 41.84 s and 45.76 s |
| Bag 1 | 0% found | 2.7% found, 3 numbers |
| Person B (half outside the view) | 0% | 0% |
| Person A | 84%, 1 number | 94.3%, 1 number |
| Predicted tracks for 4 real objects | 23 | 38 |
| CPU detect and track time per video minute | 48 s | 232 s |

The off-the-shelf detector does not see the small, dark bag in this 384×288 overhead footage. The person's number changes at the pickup itself, where the boxes merge while the person bends. Background fixtures also produce false person tracks. The tracks that C.1 needed are therefore not available from this configuration.

Licences: RF-DETR is Apache-2.0. ByteTrack in supervision uses motion and overlap only, with no appearance embedding, and numbers are valid within one video. Install the CPU extra with `pip install -e '.[tracking]' --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple`.
