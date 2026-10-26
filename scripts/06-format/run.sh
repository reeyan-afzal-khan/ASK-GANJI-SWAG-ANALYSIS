#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash scripts/06-format/run.sh [--episodes 243,244] [--check] [--skip-align] [--force-align] [--fill] [--loops]'
    echo 'Times every word of the original Crisper SRTs against the audio on the GPU (cached in .cache/alignment/),'
    echo 'then rewrites the Roman SRTs as evenly paced single-line cues. --check reports without writing or the GPU.'
    echo '--fill also transcribes the stretches the audio check found speech in, and --loops transcribes the stretch'
    echo 'of every decoding loop again; romanise them with bash scripts/05-romanize/run.sh --alignment, then run'
    echo 'this again with --skip-align to pace them in.'
    exit 0
fi
episodes=(); force=(); check=false; align=true; fill=false; loops=false
while (($#)); do
    case "$1" in
        --episodes) episodes=(--episodes "${2:?Missing episode list}"); shift 2 ;;
        --check) check=true; align=false; shift ;;
        --skip-align) align=false; shift ;;
        --force-align) force=(--force); shift ;;
        --fill) fill=true; shift ;;
        --loops) loops=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
if [[ "$check" == true ]]; then
    select_python
    exec "$RUN_PYTHON" "$PROJECT_ROOT/scripts/.shared/manage_subtitles.py" format --check "${episodes[@]}"
fi
lock_pipeline
if [[ "$align" == true || "$fill" == true || "$loops" == true ]]; then
    (
        if [[ -n "${CRISPER_PYTHON:-}" ]]; then export GANJI_PYTHON="$CRISPER_PYTHON"; fi
        select_python ask-ganji-ct2
        if [[ "$align" == true ]]; then
            "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/06-format/align.py" "${episodes[@]}" "${force[@]}"
        fi
        if [[ "$fill" == true ]]; then
            "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/06-format/align.py" --fill "${episodes[@]}" "${force[@]}"
        fi
        if [[ "$loops" == true ]]; then
            "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/06-format/align.py" --loops "${episodes[@]}" "${force[@]}"
        fi
    )
fi
select_python
exec "$RUN_PYTHON" "$PROJECT_ROOT/scripts/.shared/manage_subtitles.py" format "${episodes[@]}"
