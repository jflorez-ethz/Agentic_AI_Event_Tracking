"""Build and run the isolated LOW/HIGH continuity benchmark."""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

from security_augmented.video import _decode, _run, ingest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "person_continuity_offline"))
from evaluate import CONFIG, MATRIX_PROMPT, MODEL, GeminiAdapter, evaluate


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def inputs(root, *, build=False):
    candidates = json.loads((ROOT / "candidates.json").read_text())
    videos = {}
    for code, case in sorted(candidates.items()):
        source = case["source"]
        if source not in videos:
            v = ingest(Path(source))
            ids = tuple(sorted({i for c in candidates.values() if c["source"] == source for i in c["frame_indices"]}))
            videos[source] = (v, dict(zip(ids, _decode(v, ids), strict=True)))
        video, pixels = videos[source]
        directory = root / code
        if build:
            directory.mkdir(parents=True, exist_ok=True)
        folder = directory / "input.json"
        targets = [case["start_xy"], case["end_xy"]]
        if any(not (0 <= x < video.width and 0 <= y < video.height) for x, y in targets):
            raise ValueError("Target outside native frame")
        if len(case["frame_indices"]) != 3 or sorted(set(case["frame_indices"])) != case["frame_indices"]:
            raise ValueError("A packet requires three ordered distinct source frames")
        size = f"{video.width}x{video.height}"
        refs = {}
        parts = [{"text": f"First target in F1 at (x,y)={targets[0]}; final target in F3 at (x,y)={targets[1]}."}]
        for n, idx in enumerate(case["frame_indices"], 1):
            label = f"F{n}"
            image = directory / f"{label}.png"
            rgb = pixels[idx]
            if build:
                image.write_bytes(_run("ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                                       "-video_size", size, "-i", "pipe:0", "-frames:v", "1", "-threads", "1",
                                       "-c:v", "png", "-f", "image2pipe", "pipe:1", input_bytes=rgb).stdout)
            decoded = _run("ffmpeg", "-v", "error", "-i", str(image), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "pipe:1").stdout
            if decoded != rgb:
                raise ValueError(f"Packet {code}/{label} does not match decoded source pixels")
            pts = video.frame_pts[idx]
            refs[label] = {"index": idx, "pts": pts, "source_time_us": int(video.time_at_pts(pts) * 1_000_000),
                           "rgb24_sha256": hashlib.sha256(rgb).hexdigest(), "source": source,
                           "source_sha256": video.sha256, "time_base": str(video.time_base)}
            parts.extend(({"text": label}, {"inline_data": {"mime_type": "image/png", "data": image.read_bytes()}}))
        public = {"dimensions": [video.width, video.height], "first_xy": targets[0], "last_xy": targets[1],
                  "frame_labels": list(refs)}
        if build:
            dump(folder, public)
        if json.loads(folder.read_text()) != public:
            raise ValueError("Reviewer inputs differ from selected targets")
        yield code, parts, refs


def schedule(codes, seed):
    codes = sorted(codes)
    random.Random(seed).shuffle(codes)
    return [(code, level) for n, code in enumerate(codes)
            for level in (("LOW", "HIGH") if n % 2 == 0 else ("HIGH", "LOW"))]


def config(level):
    return {**CONFIG, "system_instruction": MATRIX_PROMPT, "max_output_tokens": 4096,
            "thinking_config": {"thinking_level": level}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=221126)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-image-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.authorize_image_transfer:
        parser.error("Explicit image-transfer authorization is required")
    if args.live and args.build:
        parser.error("Build and verify the offline benchmark first")
    if not args.build and args.output is None:
        parser.error("--output is required unless building")
    rows = {code: (parts, refs) for code, parts, refs in inputs(ROOT / "packets", build=args.build)}
    manifest = {code: refs for code, (_, refs) in rows.items()}
    if args.build:
        dump(ROOT / "manifest.json", manifest)
    elif json.loads((ROOT / "manifest.json").read_text()) != manifest:
        raise ValueError("Recorded benchmark manifest differs from verified input")
    order = schedule(rows, args.seed)
    if args.output:
        args.output.mkdir(mode=0o700)
        dump(args.output / "plan.json", {"seed": args.seed, "order": order, "model": MODEL,
                                         "configurations": {k: config(k) for k in ("LOW", "HIGH")},
                                         "max_http_requests": len(order), "manifest": manifest})
    if args.live:
        adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, client_args={"follow_redirects": False})
        with adapter.client:
            for code, level in order:
                contents, refs = rows[code]
                dump(args.output / f"{code}-{level}.json", evaluate(adapter.client, contents, refs, config(level)))
    print(f"Verified {len(rows)} packets. Maximum {len(order)} HTTP requests for a live run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
