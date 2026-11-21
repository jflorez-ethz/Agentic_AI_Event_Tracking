"""Step 4 / experiment 2: which model setting checks CCTV clips best per dollar and per second?

Runs every test clip (testset.csv) through every variant, N repeats, with prompt event_check_v2,
scores each answer against the label (agentlab/scoring.py) and writes:
    runs/compare/<timestamp>/calls.jsonl   one line per call (answer, tokens, cost, score)
    runs/compare/<timestamp>/summary.csv   one row per variant
    results/step4_<timestamp>.md           summary tables to share (results/ is tracked by git)

Always estimate first, then run small, then run all:
    python scripts/compare_models.py --dry-run                    # cost estimate, no API calls
    python scripts/compare_models.py --only T09,T12,T15 --repeats 1   # smoke test, a few cents
    python scripts/compare_models.py --repeats 3                  # full run (asks before spending > $1)
    python scripts/compare_models.py --rescore runs/compare/<timestamp>   # re-score saved answers, no API calls
Pick variants with --variants g38-low,h4-low (default: all in VARIANTS).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentlab.scoring import score  # noqa: E402
from agentlab.usage import PRICES, PRICES_2027, cost_usd  # noqa: E402

# name: (provider, model, options). Output-token guesses (from the step 3 hand runs) are only
# used for the --dry-run estimate.
VARIANTS = {
    "g38-high":  ("google", "gemini-3.8-flash", {"thinking": "HIGH"}),
    "g38-low":   ("google", "gemini-3.8-flash", {"thinking": "LOW"}),
    "g35lite":   ("google", "gemini-3.5-flash-lite", {}),
    "h4-high":   ("google", "gemini-4-hydrogen", {"thinking": "HIGH"}),
    "h4-low":    ("google", "gemini-4-hydrogen", {"thinking": "LOW"}),
    "sonnet-8f": ("anthropic", "claude-sonnet-5-5", {"frames": 8}),
}
EXTRA_VARIANTS = {  # not in the default set; name them with --variants to run
    "g38-high-mediahigh": ("google", "gemini-3.8-flash", {"thinking": "HIGH", "media_high": True}),
    # follow-up 21 Nov: does more detail per frame fix objects and far vehicles? is Haiku enough?
    "g38-low-mediahigh": ("google", "gemini-3.8-flash", {"thinking": "LOW", "media_high": True}),
    "h4-low-mediahigh":  ("google", "gemini-4-hydrogen", {"thinking": "LOW", "media_high": True}),
    "g35lite-mediahigh": ("google", "gemini-3.5-flash-lite", {"media_high": True}),
    "haiku-8f":          ("anthropic", "claude-haiku-5-5", {"frames": 8}),
    "haiku-16f":         ("anthropic", "claude-haiku-5-5", {"frames": 16}),
    "sonnet-16f":        ("anthropic", "claude-sonnet-5-5", {"frames": 16}),
}
FOLLOWUP = "g38-low-mediahigh,h4-low-mediahigh,g35lite-mediahigh,haiku-8f,haiku-16f,sonnet-16f"
# Mean output tokens per clip seen in the 21 Nov smoke test (3 clips); g38-high is very uneven
# (1,000 on short clips, 19,000 on the crowded bus clip).
GUESS_OUT_TOKENS = {"g38-high": 6000, "g38-low": 200, "g35lite": 160, "h4-high": 2000, "h4-low": 700,
                    "sonnet-8f": 450, "g38-high-mediahigh": 15000, "g38-low-mediahigh": 250,
                    "h4-low-mediahigh": 800, "g35lite-mediahigh": 180, "haiku-8f": 500, "haiku-16f": 550,
                    "sonnet-16f": 500}
TEXT_TOKENS = 1100            # system prompt + question, roughly
VIDEO_TOKENS_PER_S = 70       # Gemini default resolution (4x with media_high)
CLAUDE_TOKENS_PER_FRAME = 900  # 1024 px wide frame (full run: 8,245 input tokens for 8 frames + text)


def load_testset(limit: int | None, only: str | None = None) -> list[dict]:
    rows = list(csv.DictReader(open(ROOT / "testset.csv", newline="", encoding="utf-8")))
    if only:
        prefixes = [p.strip() for p in only.split(",") if p.strip()]
        rows = [r for r in rows if any(r["id"].startswith(p) for p in prefixes)]
    return rows[:limit] if limit else rows


def estimate(variants: list[str], items: list[dict], repeats: int) -> tuple[float, list[str]]:
    lines, total = [], 0.0
    all_v = {**VARIANTS, **EXTRA_VARIANTS}
    for v in variants:
        provider, model, opts = all_v[v]
        cost = 0.0
        for it in items:
            dur = float(it["duration_s"])
            if provider == "google":
                tin = TEXT_TOKENS + VIDEO_TOKENS_PER_S * dur * (4 if opts.get("media_high") else 1)
            else:
                tin = TEXT_TOKENS + CLAUDE_TOKENS_PER_FRAME * opts.get("frames", 8)
            cost += cost_usd(model, int(tin), GUESS_OUT_TOKENS.get(v, 1000)) or 0.0
        cost *= repeats
        total += cost
        lines.append(f"  {v:<20} {model:<24} ~${cost:6.2f}")
    return total, lines


def run_one(clients: dict, variant: str, item: dict, repeat: int, prompt: dict) -> dict:
    from agentlab.event_check import claude_check, gemini_check

    provider, model, opts = {**VARIANTS, **EXTRA_VARIANTS}[variant]
    clip, dur = ROOT / item["clip"], float(item["duration_s"])
    tag = f"step4:{variant}:{item['id']}:r{repeat}"
    base = {"variant": variant, "model": model, "item": item["id"], "repeat": repeat,
            "label": {k: item[k] for k in ("type", "real", "start_s", "end_s")}}
    for attempt in range(3):
        try:
            if provider == "google":
                res = gemini_check(clients["google"], model, clip, dur, thinking=opts.get("thinking"),
                                   media_high=opts.get("media_high", False), prompt=prompt, tag=tag)
            else:
                res = claude_check(clients["anthropic"], model, clip, dur, n_frames=opts.get("frames", 8),
                                   prompt=prompt, tag=tag)
            res["cost_2027"] = cost_usd(model, res["usage"]["input_tokens"], res["usage"]["output_tokens"],
                                        PRICES_2027)
            return {**base, **res, "score": score(item, res), "error": None}
        except Exception as err:  # noqa: BLE001 - keep going, record the error
            msg = f"{type(err).__name__}: {err}"
            retry = any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "500", "overloaded", "Overloaded"))
            if retry and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            return {**base, "error": msg[:500], "score": None}


def summarise(calls: list[dict], variants: list[str]) -> tuple[list[dict], str]:
    rows, md = [], []
    for v in variants:
        cs = [c for c in calls if c["variant"] == v]
        ok = [c for c in cs if not c["error"]]
        sc = [c["score"] for c in ok]
        real = [c["score"] for c in ok if c["label"]["real"] == "true" and c["label"]["type"] != "none"]
        look = [c["score"] for c in ok if c["label"]["real"] != "true" and c["label"]["type"] != "none"]
        none = [c["score"] for c in ok if c["label"]["type"] == "none"]
        errs = [s["start_err"] for s in real if s["start_err"] is not None]
        secs = [c["seconds"] for c in ok]
        pct = lambda xs, k: round(100 * sum(1 for s in xs if s[k]) / len(xs)) if xs else None  # noqa: E731
        rows.append({
            "variant": v, "model": {**VARIANTS, **EXTRA_VARIANTS}[v][1], "calls": len(cs), "errors": len(cs) - len(ok),
            "video_missing": sum(1 for c in ok if c.get("video_missing")),
            "correct_%": pct(sc, "correct"), "real_found_%": pct(real, "correct"), "real_top1_%": pct(real, "top1"),
            "right_type_wrong_time": sum(1 for s in real if s["type_only"]),
            "lookalike_no_alarm_%": pct(look, "correct"), "lookalike_named_%": pct(look, "recognised"),
            "none_no_alarm_%": pct(none, "correct"),
            "missed_person_down": sum(1 for s in sc if s["missed_critical"]),
            "start_err_s": round(statistics.mean(errs), 1) if errs else None,
            "secs_mean": round(statistics.mean(secs), 1) if secs else None,
            "secs_p90": round(sorted(secs)[int(0.9 * (len(secs) - 1))], 1) if secs else None,
            "in_tok_mean": round(statistics.mean(c["usage"]["input_tokens"] for c in ok)) if ok else None,
            "out_tok_mean": round(statistics.mean(c["usage"]["output_tokens"] for c in ok)) if ok else None,
            "usd_per_clip": round(statistics.mean(c["usage"]["cost_usd"] or 0 for c in ok), 4) if ok else None,
            "usd_per_clip_2027": round(statistics.mean(c["cost_2027"] or 0 for c in ok), 4) if ok else None,
            "usd_total": round(sum(c["usage"]["cost_usd"] or 0 for c in ok), 3),
        })
    cols = list(rows[0])
    md.append("| " + " | ".join(cols) + " |")
    md.append("|" + "---|" * len(cols))
    for r in rows:
        md.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |")

    # per clip: share of correct answers per variant across repeats
    items = sorted({c["item"] for c in calls})
    md += ["", "Per clip, correct answers out of repeats:", "",
           "| clip | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for it in items:
        cells = []
        for v in variants:
            cs = [c for c in calls if c["variant"] == v and c["item"] == it]
            good = sum(1 for c in cs if c["score"] and c["score"]["correct"])
            cells.append(f"{good}/{len(cs)}" + (" err" if any(c["error"] for c in cs) else ""))
        md.append(f"| {it} | " + " | ".join(cells) + " |")
    return rows, "\n".join(md)


def write_outputs(calls: list[dict], variants: list[str], out_dir: Path, title: str, report_name: str) -> list[dict]:
    rows, md = summarise(calls, variants)
    with open(out_dir / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    report = ROOT / "results" / report_name
    report.parent.mkdir(exist_ok=True)
    report.write_text(f"# {title}\n\n{md}\n")
    print("\n" + md)
    print(f"\nReport: {report.relative_to(ROOT)}")
    return rows


def rescore(run_dir: Path) -> int:
    """Score saved answers again with the current scoring rules and labels (no API calls)."""
    items = {r["id"]: r for r in load_testset(None)}
    calls = [json.loads(line) for line in open(run_dir / "calls.jsonl")]
    for c in calls:
        if not c.get("error") and c["item"] in items:
            c["score"] = score(items[c["item"]], c)
    variants = [v for v in {**VARIANTS, **EXTRA_VARIANTS} if any(c["variant"] == v for c in calls)]
    with open(run_dir / "calls.jsonl", "w") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
    write_outputs(calls, variants, run_dir, f"Step 4 model comparison, {run_dir.name} (re-scored)",
                  f"step4_{run_dir.name}.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rescore", metavar="RUN_DIR", help="re-score a saved run (runs/compare/<timestamp>) and stop")
    ap.add_argument("--variants", default="all", help="comma list, 'all' (default set) or 'followup'")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, help="only the first N test clips")
    ap.add_argument("--only", help="only these test clips, by id prefix, e.g. T09,T12,T15")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="print the cost estimate and stop")
    ap.add_argument("--yes", action="store_true", help="do not ask before spending more than $1")
    args = ap.parse_args()
    if args.rescore:
        return rescore((ROOT / args.rescore).resolve() if not Path(args.rescore).is_absolute() else Path(args.rescore))

    variants = (list(VARIANTS) if args.variants == "all" else
                FOLLOWUP.split(",") if args.variants == "followup" else args.variants.split(","))
    unknown = [v for v in variants if v not in {**VARIANTS, **EXTRA_VARIANTS}]
    if unknown:
        sys.exit(f"unknown variants: {unknown}; choose from {list(VARIANTS) + list(EXTRA_VARIANTS)}")
    missing = [v for v in variants if {**VARIANTS, **EXTRA_VARIANTS}[v][1] not in PRICES]
    if missing:
        sys.exit(f"no price for {missing} in agentlab/usage.py PRICES")
    items = load_testset(args.limit, args.only)
    if not items:
        sys.exit("no test clips selected; check --only / --limit against testset.csv")
    total, lines = estimate(variants, items, args.repeats)
    n_calls = len(variants) * len(items) * args.repeats
    print(f"{len(items)} clips x {len(variants)} variants x {args.repeats} repeats = {n_calls} calls")
    print("\n".join(lines))
    print(f"  estimated total ~${total:.2f} (output tokens are guesses; real cost is logged per call)")
    if args.dry_run:
        return 0
    if total > 1 and not args.yes:
        if input(f"Estimated cost ${total:.2f} is above $1. Continue? [y/N] ").strip().lower() != "y":
            return 1

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    clients = {}
    if any({**VARIANTS, **EXTRA_VARIANTS}[v][0] == "google" for v in variants):
        from google import genai
        clients["google"] = genai.Client(api_key=os.environ["GOOGLE_API_KEY"].strip())
        from agentlab.event_check import gemini_upload
        for it in items:  # upload each clip once before the parallel run
            gemini_upload(clients["google"], ROOT / it["clip"])
    if any({**VARIANTS, **EXTRA_VARIANTS}[v][0] == "anthropic" for v in variants):
        import anthropic
        clients["anthropic"] = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())

    from agentlab.event_check import load_prompt
    prompt = load_prompt("v2")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "runs" / "compare" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    calls = []
    jobs = [(v, it, r) for r in range(1, args.repeats + 1) for it in items for v in variants]
    with ThreadPoolExecutor(max_workers=args.workers) as pool, open(out_dir / "calls.jsonl", "w") as log:
        futures = [pool.submit(run_one, clients, v, it, r, prompt) for v, it, r in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            c = fut.result()
            calls.append(c)
            log.write(json.dumps(c) + "\n")
            log.flush()
            s = c["score"]
            status = "ERROR " + c["error"][:80] if c["error"] else ("ok   " if s["correct"] else "MISS ") + \
                f"{c['seconds']:5.1f}s ${c['usage']['cost_usd']}" + (" VIDEO MISSING" if c.get("video_missing") else "")
            print(f"[{i:>3}/{len(jobs)}] {c['variant']:<12} {c['item']:<40} r{c['repeat']} {status}")

    rows = write_outputs(calls, variants, out_dir,
                         f"Step 4 model comparison, {stamp}\n\nPrompt event_check_v2; {len(items)} clips; "
                         f"{args.repeats} repeats; variants {', '.join(variants)}.", f"step4_{stamp}.md")
    print(f"Total spent: ${sum(r['usd_total'] for r in rows):.3f}. Calls: {out_dir.relative_to(ROOT)}/calls.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
