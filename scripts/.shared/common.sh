#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$PROJECT_ROOT"
select_python() {
    local environment="${1:-}"
    if [[ -n "${GANJI_PYTHON:-}" ]]; then
        RUN_PYTHON="$GANJI_PYTHON"
    elif [[ -n "$environment" && -x "$HOME/.venvs/$environment/bin/python" ]]; then
        RUN_PYTHON="$HOME/.venvs/$environment/bin/python"
    elif [[ -n "$environment" ]]; then
        echo "Missing ~/.venvs/$environment. Run bash scripts/01-setup/run.sh or set GANJI_PYTHON." >&2
        exit 1
    elif command -v python3 >/dev/null 2>&1; then RUN_PYTHON=python3
    else RUN_PYTHON=python
    fi
}
lock_pipeline() {
    command -v flock >/dev/null || { echo 'flock is required; run inside Ubuntu/WSL2.' >&2; exit 1; }
    exec 9>"$PROJECT_ROOT/.ct2-batch.lock"
    flock -n 9 || { echo 'Another workflow is running in this repository.' >&2; exit 1; }
}
