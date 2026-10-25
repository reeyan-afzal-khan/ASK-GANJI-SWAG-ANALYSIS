#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
while (($#)); do
    case "$1" in
        --help|-h)
            echo 'Usage: bash scripts/04-transcribe/run.sh [--episodes 243,244] [--smoke-test EPISODE]'
            echo 'Also accepts FIRST_EPISODE, LAST_EPISODE, EPISODES, CRISPER_MODEL and CRISPER_PYTHON environment variables.'
            exit 0 ;;
        --episodes) export EPISODES="${2:?Missing episode list}"; shift 2 ;;
        --smoke-test) export CT2_SMOKE_TEST=1 FIRST_EPISODE="${2:?Missing episode number}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
lock_pipeline
if [[ -n "${CRISPER_PYTHON:-}" ]]; then export GANJI_PYTHON="$CRISPER_PYTHON"; fi
select_python ask-ganji-ct2
exec "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/04-transcribe/transcribe.py"
