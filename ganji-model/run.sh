#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../scripts/.shared/common.sh"
select_python ask-ganji-roman
exec "$RUN_PYTHON" -u "$PROJECT_ROOT/ganji-model/cli.py" "$@"
