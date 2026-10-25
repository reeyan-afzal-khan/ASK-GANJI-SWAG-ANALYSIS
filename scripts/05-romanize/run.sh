#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then select_python
else lock_pipeline; select_python ask-ganji-roman
fi
exec "$RUN_PYTHON" -u "$PROJECT_ROOT/scripts/05-romanize/romanize.py" "$@"
