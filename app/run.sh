#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../scripts/.shared/common.sh"
select_python
exec "$RUN_PYTHON" "$PROJECT_ROOT/app/tools/build_data.py" "$@"
