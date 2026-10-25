#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
read_only=false
for arg in "$@"; do
    case "$arg" in --check|--help|-h) read_only=true ;; esac
done
if [[ "$read_only" == false ]]; then lock_pipeline; fi
select_python
exec "$RUN_PYTHON" "$PROJECT_ROOT/scripts/.shared/manage_subtitles.py" format "$@"
