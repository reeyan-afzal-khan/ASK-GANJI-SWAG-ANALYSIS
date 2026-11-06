#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
select_python
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    exec "$RUN_PYTHON" "$PROJECT_ROOT/scripts/03-download-audio/download.py" --help
fi
select_downloader
lock_pipeline
exec "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/03-download-audio/download.py" "$@"
