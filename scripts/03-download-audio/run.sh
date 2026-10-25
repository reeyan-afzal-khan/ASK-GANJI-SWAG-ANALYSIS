#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/../.shared/common.sh"
if [[ $# -ne 2 || "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash scripts/03-download-audio/run.sh EPISODE_NUMBER VIDEO_URL'
    echo 'Example: bash scripts/03-download-audio/run.sh 243 "https://www.youtube.com/watch?v=VIDEO_ID"'
    [[ "${1:-}" == --help || "${1:-}" == -h ]] && exit 0
    exit 2
fi
[[ "$1" =~ ^[0-9]+$ ]] || { echo 'Episode number must be a positive integer.' >&2; exit 2; }
episode=$((10#$1))
((episode > 0)) || { echo 'Episode number must be positive.' >&2; exit 2; }
command -v yt-dlp >/dev/null || { echo 'Install yt-dlp in your downloader environment; see README.md.' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg first.' >&2; exit 1; }
lock_pipeline
mkdir -p "$PROJECT_ROOT/all_episodes"
printf -v filename 'episode_%03d.%%(ext)s' "$episode"
exec yt-dlp --no-playlist --extract-audio --audio-format mp3 --audio-quality 0 \
    --no-overwrites --write-info-json --sleep-interval 5 --max-sleep-interval 15 \
    -P "$PROJECT_ROOT/all_episodes" -o "$filename" -- "$2"
