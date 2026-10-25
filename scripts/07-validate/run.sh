#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
select_python
exec "$RUN_PYTHON" "$PROJECT_ROOT/scripts/.shared/manage_subtitles.py" validate "$@"
