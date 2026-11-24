#!/usr/bin/env bash
# Live re-run of the frozen system version (rules.json system_version) on the nine CAVIAR KPI videos.
# PAID: sends footage and observation text to Gemini. Run it yourself, from any directory:
#     GEMINI_API_KEY=... experiments/kpi/run_all_kpi.sh
# Writes experiments/kpi_runs/<time>-<commit>/<Video>/{run/,meta.json,stdout.log,stderr.log}
# and the list of run directories to experiments/kpi/runs.txt (read by kpi.py).
set -euo pipefail
cd "$(dirname "$0")/../.."

die() { echo "ERREUR : $*" >&2; exit 1; }
rule() { .venv/bin/python -c "import json,sys; print(json.load(open('experiments/kpi/rules.json'))['system_version'][sys.argv[1]])" "$1"; }

# 1. Same system version as rules.json, nothing uncommitted in the code.
[ "$(git rev-parse HEAD:src)" = "$(rule src_tree)" ] || die "src/ differs from the frozen version in rules.json"
[ "$(git rev-parse HEAD:pyproject.toml)" = "$(rule pyproject_blob)" ] || die "pyproject.toml differs from the frozen version"
git diff --quiet HEAD -- src pyproject.toml || die "uncommitted changes in src/ or pyproject.toml"
[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ] || die "GEMINI_API_KEY or GOOGLE_API_KEY is missing"

# 2. Sources: the _pts files where the CLI rejects the original MPEG (see rules.json video_choice).
VIDEOS=(LeftBag.mpg LeftBox_pts.mkv LeftBag_PickedUp.mpg LeftBag_AtChair.mpg Rest_FallOnFloor.mpg
        Walk2.mpg TwoEnterShop1front_pts.mkv Meet_WalkSplit_pts.mp4 Meet_WalkTogether1_pts.mp4)
for v in "${VIDEOS[@]}"; do
  want=$(.venv/bin/python -c "import json,sys; print(json.load(open('experiments/kpi/rules.json'))['videos'][sys.argv[1]]['video_sha256'])" "$v")
  [ "$(sha256sum "data/raw/$v" | cut -d' ' -f1)" = "$want" ] || die "data/raw/$v: SHA-256 differs from rules.json"
done

SET_DIR="experiments/kpi_runs/$(date +%Y%m%dT%H%M%S)-$(git rev-parse --short HEAD)"
mkdir -p "$SET_DIR"
.venv/bin/python -m pip freeze > "$SET_DIR/pip-freeze.txt" 2>/dev/null || true
cat > "$SET_DIR/manifest.json" <<EOF
{"commit": "$(git rev-parse HEAD)", "src_tree": "$(git rev-parse HEAD:src)",
 "pyproject_blob": "$(git rev-parse HEAD:pyproject.toml)", "started": "$(date -Is)", "videos": $(printf '"%s",' "${VIDEOS[@]}" | sed 's/,$//; s/^/[/; s/$/]/')}
EOF
: > experiments/kpi/runs.txt
for v in "${VIDEOS[@]}"; do n=${v%%.*}; echo "$SET_DIR/${n%_pts}" >> experiments/kpi/runs.txt; done
export SET_DIR SRC_TREE="$(git rev-parse HEAD:src)" COMMIT="$(git rev-parse HEAD)"

run_one() {
  local video=$1 name=${1%%.*}; name=${name%_pts}
  local dir="$SET_DIR/$name"; mkdir "$dir"
  local start end rc=0
  start=$(date +%s.%N)
  echo "[$(date +%T)] start $name"
  GOOGLE_GENAI_HTTP_CLIENT=httpx \
  GEMINI_VIDEO_MODEL=gemini-3.6-flash GEMINI_INVESTIGATION_MODEL=gemini-3.6-flash \
  GEMINI_VERIFICATION_MODEL=gemini-3.6-flash GEMINI_REPORTING_MODEL=gemini-3.6-flash \
  .venv/bin/python -m security_augmented.workflow "data/raw/$video" \
    --live --authorize-footage-transfer --authorize-observation-text-transfer \
    --max-initial-windows auto --window-seconds 10 --frame-step-ms 500 \
    --max-candidates 4 --max-inspections 4 --max-agent-calls 14 \
    --max-verification-iterations 4 --max-visible-observations 16 \
    --output "$dir/run" > "$dir/stdout.log" 2> "$dir/stderr.log" || rc=$?
  end=$(date +%s.%N)
  printf '{"video": "%s", "exit_code": %d, "start_epoch": %s, "end_epoch": %s, "commit": "%s", "src_tree": "%s"}\n' \
    "$video" "$rc" "$start" "$end" "$COMMIT" "$SRC_TREE" > "$dir/meta.json"
  echo "[$(date +%T)] end   $name (code $rc)"
}
export -f run_one

# 3. At most three videos at once. A failed video does not stop the others.
printf '%s\n' "${VIDEOS[@]}" | xargs -P 3 -I{} bash -c 'run_one "$1"' _ {} || true

echo "Done. Runs: $SET_DIR. List: experiments/kpi/runs.txt"
echo "KPI table: .venv/bin/python experiments/kpi/kpi.py"
