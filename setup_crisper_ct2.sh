#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
    echo "Run this inside Ubuntu/WSL2. The CT2 fork requires Linux x86_64." >&2
    exit 1
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
VENV="$HOME/.venvs/ask-ganji-ct2"
if [[ ! -x "$VENV/bin/python" ]]; then
    # Ubuntu may ship Python 3.14, newer than the fork's published wheels.
    BOOTSTRAP="$HOME/.venvs/ct2-bootstrap"
    python3 -m venv "$BOOTSTRAP"
    "$BOOTSTRAP/bin/python" -m pip install uv
    "$BOOTSTRAP/bin/uv" python install 3.12
    "$BOOTSTRAP/bin/uv" venv --python 3.12 "$VENV" --seed
fi
"$VENV/bin/python" -m pip install --upgrade pip
# CUDA PyTorch supports GPU torch workloads as well as model conversion.
"$VENV/bin/python" -m pip install 'torch==2.11.0' --index-url https://download.pytorch.org/whl/cu128
"$VENV/bin/python" -m pip install -r requirements-ct2.txt
"$VENV/bin/python" -m pip check
