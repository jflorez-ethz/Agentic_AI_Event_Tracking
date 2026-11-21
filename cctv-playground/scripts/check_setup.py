"""Step 1 check: Python, ffmpeg, .env keys, model access, and one tiny call per provider.

Run from the fake-cctv folder with the venv active:
    python scripts/check_setup.py           # local checks only, no API calls
    python scripts/check_setup.py --call    # also list models and send one tiny prompt each

--call costs well under $0.001 in total (two prompts of about 20 tokens). Each call is
logged to runs/usage.jsonl. Keys are never printed, only their length and last 4 characters.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
CLAUDE_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
PING = "Reply with the single word OK."

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'ok' if ok else 'FAIL':>4}] {name}" + (f": {detail}" if detail else ""))
    return ok


def mask(value: str) -> str:
    return f"{len(value)} chars, ends ...{value[-4:]}" if value else "empty"


def local_checks() -> None:
    v = sys.version_info
    check("Python >= 3.10", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro} at {sys.executable}")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            first = subprocess.run([tool, "-version"], capture_output=True, text=True).stdout.splitlines()[:1]
            check(f"{tool} on PATH", True, first[0] if first else path)
        else:
            check(f"{tool} on PATH", False, "install with: brew install ffmpeg")

    in_venv = sys.prefix != sys.base_prefix
    check("running inside a virtual environment", in_venv,
          sys.prefix if in_venv else "run: source .venv/bin/activate")

    missing = []
    for module, pip_name in (("google.genai", "google-genai"), ("anthropic", "anthropic"), ("dotenv", "python-dotenv")):
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    if not check("packages installed", not missing,
                 f"missing {', '.join(missing)}: python -m pip install -r requirements-agent.txt"
                 if missing else "google-genai, anthropic, python-dotenv"):
        return False

    gitignore = ROOT / ".gitignore"
    ignored = gitignore.exists() and ".env" in gitignore.read_text().split()
    check(".env listed in .gitignore", ignored)

    # Keys already exported in the shell (old coursework, ~/.zshrc) would shadow .env with plain
    # load_dotenv(); our scripts load with override=True so .env wins. Report them so you know.
    shell = [k for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(k)]
    if shell:
        print(f"[note] already set in your shell, .env will override for these scripts: {', '.join(shell)}")

    env_file = ROOT / ".env"
    if not check(".env file present", env_file.exists(), str(env_file)):
        return False
    from dotenv import load_dotenv
    load_dotenv(env_file, override=True)
    for key in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        check(f"{key} loaded", bool(os.environ.get(key, "").strip()), mask(os.environ.get(key, "").strip()))
    if os.environ.get("GEMINI_API_KEY") and os.environ.get("GOOGLE_API_KEY"):
        print("[note] GEMINI_API_KEY is also set; the SDKs use GOOGLE_API_KEY. Remove GEMINI_API_KEY to avoid confusion.")
    return True


def gemini_checks() -> None:
    from google import genai
    from agentlab.usage import log_call

    try:
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"].strip())
        names = {m.name.removeprefix("models/") for m in client.models.list()}
    except Exception as err:  # noqa: BLE001 - we want the message whatever it is
        check("Gemini: list models", False, f"{type(err).__name__}: {err}")
        return
    for model in GEMINI_MODELS:
        check(f"Gemini: {model} available", model in names)

    model = GEMINI_MODELS[0]
    t0 = time.perf_counter()
    try:
        resp = client.models.generate_content(model=model, contents=PING)
    except Exception as err:  # noqa: BLE001
        check(f"Gemini: tiny call to {model}", False, f"{type(err).__name__}: {err}")
        return
    secs = time.perf_counter() - t0
    u = resp.usage_metadata
    thoughts = getattr(u, "thoughts_token_count", 0) or 0
    out = (getattr(u, "candidates_token_count", 0) or 0) + thoughts
    row = log_call(provider="google", model=model, input_tokens=u.prompt_token_count or 0,
                   output_tokens=out, thinking_tokens=thoughts, seconds=secs, tag="check_setup")
    check(f"Gemini: tiny call to {model}", True,
          f"reply={(resp.text or '').strip()[:20]!r} in={row['input_tokens']} out={row['output_tokens']} "
          f"(thinking {thoughts}) {secs:.1f}s ${row['cost_usd']}")


def claude_checks() -> None:
    import anthropic
    from agentlab.usage import log_call

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    try:
        ids = {m.id for m in client.models.list(limit=100)}
    except Exception as err:  # noqa: BLE001
        check("Claude: list models", False, f"{type(err).__name__}: {err}")
        return
    for model in CLAUDE_MODELS:
        check(f"Claude: {model} available", model in ids)

    model = CLAUDE_MODELS[0]
    t0 = time.perf_counter()
    try:
        resp = client.messages.create(model=model, max_tokens=200,
                                      messages=[{"role": "user", "content": PING}])
    except Exception as err:  # noqa: BLE001
        check(f"Claude: tiny call to {model}", False, f"{type(err).__name__}: {err}")
        return
    secs = time.perf_counter() - t0
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    row = log_call(provider="anthropic", model=model, input_tokens=resp.usage.input_tokens,
                   output_tokens=resp.usage.output_tokens, seconds=secs, tag="check_setup")
    check(f"Claude: tiny call to {model}", True,
          f"reply={text[:20]!r} in={row['input_tokens']} out={row['output_tokens']} {secs:.1f}s ${row['cost_usd']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--call", action="store_true", help="list models and send one tiny prompt per provider")
    args = parser.parse_args()

    ready = local_checks()
    if args.call and not ready:
        print("[skip] API calls skipped until the local checks above pass.")
    if args.call and ready:
        if os.environ.get("GOOGLE_API_KEY", "").strip():
            gemini_checks()
        if os.environ.get("ANTHROPIC_API_KEY", "").strip():
            claude_checks()
        from agentlab.usage import USAGE_LOG, total_spend
        print(f"[info] logged spend so far: ${total_spend():.6f} (in {USAGE_LOG.relative_to(ROOT)})")

    failed = [name for name, ok, _ in results if not ok]
    print("\nAll checks passed." if not failed else f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
