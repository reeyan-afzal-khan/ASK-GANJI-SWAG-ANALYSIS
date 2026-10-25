#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash scripts/08-test/run.sh (standard-library tests; no GPU or network)'; exit 0
fi
select_python
"$RUN_PYTHON" -m unittest discover -s "$PROJECT_ROOT/scripts/08-test" -p "test_*.py" -v
exec "$RUN_PYTHON" -m unittest discover -s "$PROJECT_ROOT/app/tools" -p "test_*.py" -v
