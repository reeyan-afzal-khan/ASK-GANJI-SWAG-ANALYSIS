#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
target="${1:-all}"
if [[ "$target" == --help || "$target" == -h ]]; then
    echo 'Usage: bash scripts/01-setup/run.sh [all|transcription|roman]'
    echo 'Creates separate Linux environments under ~/.venvs and installs pinned dependencies.'
    exit 0
fi
case "$target" in all|transcription|roman) ;; *) echo "Unknown target: $target" >&2; exit 2 ;; esac
[[ "$(uname -s)" == Linux ]] || { echo 'Run setup in Ubuntu/WSL2.' >&2; exit 1; }
lock_pipeline
create_environment() {
    local name="$1" requirements="$2"
    local venv="$HOME/.venvs/$name" bootstrap="$HOME/.venvs/ct2-bootstrap"
    if [[ ! -x "$venv/bin/python" ]]; then
        python3 -m venv "$bootstrap"
        "$bootstrap/bin/python" -m pip install uv
        "$bootstrap/bin/uv" python install 3.12
        "$bootstrap/bin/uv" venv --python 3.12 "$venv" --seed
    fi
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install 'torch==2.11.0' --index-url https://download.pytorch.org/whl/cu128
    "$venv/bin/python" -m pip install -r "$PROJECT_ROOT/scripts/01-setup/requirements-$requirements"
    "$venv/bin/python" -m pip check
}
if [[ "$target" == all || "$target" == transcription ]]; then create_environment ask-ganji-ct2 transcription.txt; fi
if [[ "$target" == all || "$target" == roman ]]; then create_environment ask-ganji-roman romanization.txt; fi
