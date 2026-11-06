#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
target="${1:-all}"
if [[ "$target" == --help || "$target" == -h ]]; then
    echo 'Usage: bash scripts/01-setup/run.sh [all|transcription|roman|download]'
    echo 'Installs ffmpeg and python3-venv with apt if they are missing, then creates separate Linux'
    echo 'environments under ~/.venvs with the dependencies. Run it again to update yt-dlp:'
    echo 'bash scripts/01-setup/run.sh download'
    exit 0
fi
case "$target" in all|transcription|roman|download) ;; *) echo "Unknown target: $target" >&2; exit 2 ;; esac
[[ "$(uname -s)" == Linux ]] || { echo 'Run setup in Ubuntu/WSL2.' >&2; exit 1; }
lock_pipeline
install_system_packages() {
    local missing=()
    command -v ffmpeg >/dev/null || missing+=(ffmpeg)
    python3 -c 'import ensurepip' 2>/dev/null || missing+=(python3-venv)
    ((${#missing[@]})) || return 0
    local sudo=()
    ((EUID == 0)) || sudo=(sudo)
    echo "Installing ${missing[*]} with apt-get"
    "${sudo[@]}" apt-get update
    "${sudo[@]}" apt-get install -y "${missing[@]}"
}
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
create_download_environment() {
    local venv="$HOME/.venvs/yt-dlp"
    [[ -x "$venv/bin/python" ]] || python3 -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install --upgrade -r "$PROJECT_ROOT/scripts/01-setup/requirements-download.txt"
    echo "yt-dlp $("$venv/bin/yt-dlp" --version), deno $("$venv/bin/deno" --version | head -n 1), $(ffmpeg -version | head -n 1)"
}
install_system_packages
if [[ "$target" == all || "$target" == download ]]; then create_download_environment; fi
if [[ "$target" == all || "$target" == transcription ]]; then create_environment ask-ganji-ct2 transcription.txt; fi
if [[ "$target" == all || "$target" == roman ]]; then create_environment ask-ganji-roman romanization.txt; fi
