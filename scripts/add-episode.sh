#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/.shared/common.sh"
usage() {
    echo 'Usage: bash scripts/add-episode.sh [--episodes 243,244]'
    echo 'The one command for a new episode. It downloads the newest playlist episode and its question list,'
    echo 'makes its subtitles (Urdu, then Roman Urdu with even timing, then English), checks them, sorts its'
    echo 'questions into categories and rebuilds the app. The subtitles need the GPU.'
    echo 'If it stops, run it again: finished work is skipped. --episodes works on audio that is already in'
    echo 'all_episodes/, without looking at the playlist.'
}
episodes=''
case "${1:-}" in
    '') ;;
    --help|-h) usage; exit 0 ;;
    --episodes) episodes="${2:?Missing episode list}" ;;
    *) usage >&2; exit 2 ;;
esac
step() { printf '\n=== %s ===\n' "$1"; }
# Episodes with audio but no English subtitles yet; English is made last, so these are unfinished.
unfinished() {
    local audio name
    for audio in all_episodes/episode_*.mp3; do
        name="$(basename "$audio" .mp3)"
        [[ ! -e "$audio" || -s "transcripts-english/$name.srt" ]] || echo "$((10#${name#episode_}))"
    done | paste -sd, -
}
if [[ -z "$episodes" ]]; then
    step 'Download'
    bash scripts/03-download-audio/run.sh
    episodes="$(unfinished)"
fi
if [[ -n "$episodes" ]]; then
    step "Transcribe episode $episodes (GPU)"
    bash scripts/04-transcribe/run.sh --episodes "$episodes"
    step 'Roman Urdu'
    bash scripts/05-romanize/run.sh --episodes "$episodes"
    step 'Word timing, missed speech and decoding loops (GPU)'
    bash scripts/06-format/run.sh --episodes "$episodes" --fill --loops --no-pace
    bash scripts/05-romanize/run.sh --alignment --episodes "$episodes"
    step 'Even timing'
    bash scripts/06-format/run.sh --episodes "$episodes" --skip-align
    step 'English (GPU)'
    bash scripts/06-format/run.sh --translate --episodes "$episodes"
    step 'Check the subtitles'
    bash scripts/07-validate/run.sh --episodes "$episodes"
else
    echo 'Every downloaded episode already has its subtitles.'
fi
step 'Sort the questions'
bash ganji-model/run.sh label
step 'Build the app'
bash app/run.sh
