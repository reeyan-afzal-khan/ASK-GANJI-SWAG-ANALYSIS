#!/usr/bin/env bash
# Run each episode in its own process. Save each SRT on episode completion.
# Usage: bash run_all_241.sh [first_episode] [last_episode]
set -u
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

FIRST="${1:-1}"
LAST="${2:-241}"
if ! [[ "$FIRST" =~ ^[0-9]+$ && "$LAST" =~ ^[0-9]+$ ]] || (( FIRST < 1 || LAST > 241 || FIRST > LAST )); then
  echo "Usage: bash run_all_241.sh [first (1-241)] [last (1-241)]" >&2
  exit 2
fi
mkdir -p logs/episodes urdu_transcript_srt_crisper

if [[ ! -f repair.py ]]; then
  echo "ERROR: repair.py not found in $(pwd)" >&2
  exit 2
fi
if [[ ! -f language_overrides.example.json ]]; then
  echo "ERROR: language_overrides.example.json is missing" >&2
  exit 2
fi

# Clear success, fallback, skipped, and failure statuses, independent of Python exit code.
status_from_review() {
  python3 - "$1" <<'PY'
import csv, pathlib, sys
p=pathlib.Path('audit/results/review.csv')
ep=f'{int(sys.argv[1]):03d}'
if not p.is_file():
    print('UNKNOWN'); raise SystemExit
try:
    with p.open(encoding='utf-8-sig', newline='') as f:
        states=[r.get('status','') for r in csv.DictReader(f) if r.get('episode')==ep]
except (OSError,csv.Error):
    print('UNKNOWN'); raise SystemExit
for s in ('EPISODE_ERROR', 'BASELINE_DRAFT', 'SECOND_PASS_PARTIAL',
          'SECOND_PASS_COMPLETE', 'FORMATTING_ONLY'):
    if s in states:
        print(s); break
else:
    print('UNKNOWN')
PY
}

for ((num=FIRST; num<=LAST; num++)); do
  printf -v EP '%03d' "$num"
  LOG="logs/episodes/episode_${EP}.log"
  OUT="urdu_transcript_srt_crisper/episode_${EP}.srt"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Episode ${EP}/241: processing ..."
  start=$SECONDS

  # This process ends after each episode; repair.py writes its SRT before it exits.
  python3 -u repair.py run \
      --only "$num" \
      --language auto \
      --chunk-seconds 30 \
      --language-overrides language_overrides.example.json \
      --deep-scan \
      --repair-code-switch \
      --offline \
      >"$LOG" 2>&1
  exit_code=$?
  elapsed=$((SECONDS-start))

  if [[ -s "$OUT" ]]; then
    if grep -q "verified prior full second pass; resume skip" "$LOG"; then
      echo "  SKIPPED (already verified) | $OUT | ${elapsed}s"
    else
      STATUS=$(status_from_review "$num")
      case "$STATUS" in
        SECOND_PASS_COMPLETE)
          echo "  SAVED (second pass complete) | $OUT | ${elapsed}s" ;;
        BASELINE_DRAFT)
          echo "  DRAFT ONLY (ASR incomplete; original text saved) | $OUT | ${elapsed}s" ;;
        SECOND_PASS_PARTIAL)
          echo "  PARTIAL (ASR incomplete; needs review) | $OUT | ${elapsed}s" ;;
        *)
          echo "  SRT PRESENT; CHECK AUDIT ($STATUS) | $OUT | ${elapsed}s" ;;
      esac
    fi
  else
    echo "  NO SRT SAVED | Episode $EP | ${elapsed}s"
  fi
  if (( exit_code != 0 )); then
    echo "  WARNING: Python exited with code $exit_code; inspect $LOG"
  fi
  echo "  Log: $LOG"
done

echo
echo "Processed range: ${FIRST}-${LAST}"
echo "SRTs currently present: $(find urdu_transcript_srt_crisper -maxdepth 1 -type f -name 'episode_*.srt' | wc -l) / 241"
echo "See audit/results/review.csv for quality and failed-chunk statuses."
