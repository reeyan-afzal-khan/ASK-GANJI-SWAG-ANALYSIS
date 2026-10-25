#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash scripts/02-download-model/run.sh'
    echo 'Downloads pinned Roman Urdu model files to .cache/roman-model (about 1.94 GB).'; exit 0
fi
lock_pipeline
select_python ask-ganji-roman
exec "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/02-download-model/download_model.py"
