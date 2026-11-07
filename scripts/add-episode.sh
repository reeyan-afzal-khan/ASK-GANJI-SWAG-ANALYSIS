#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/.shared/common.sh"
usage() {
    echo 'Usage: bash scripts/add-episode.sh [--episodes 243,244]'
    echo 'The one command for a new episode. It downloads the newest playlist episode and its question list,'
    echo 'makes its subtitles (Urdu, then Roman Urdu with even timing, then English), checks them, sorts its'
    echo 'questions into categories and rebuilds the app. The subtitles need the GPU.'
    echo 'The audio waits in the root folder as episode_NNN.mp3, NNN being the episode number, and is deleted'
    echo 'once both subtitles pass the check; an episode that has them is never made again. Audio put there'
    echo 'by hand is used instead of a download.'
    echo 'If it stops, run it again: finished work is skipped. --episodes works on audio in the root folder,'
    echo 'without looking at the playlist.'
}
episodes=''
case "${1:-}" in
    '') ;;
    --help|-h) usage; exit 0 ;;
    --episodes) episodes="${2:?Missing episode list}" ;;
    *) usage >&2; exit 2 ;;
esac
step() { printf '\n=== %s ===\n' "$1"; }
# An episode has all it needs its audio for once both subtitles are made.
has_subtitles() { [[ -s "transcripts-urdu-roman/$1.srt" && -s "transcripts-english/$1.srt" ]]; }
# The numbers of the episodes whose audio waits in the root folder: those not made yet, or with --made the rest.
waiting() {
    local audio name
    for audio in episode_*.mp3; do
        name="${audio%.mp3}"
        [[ -f "$audio" && "$name" =~ ^episode_[0-9]+$ ]] || continue
        if has_subtitles "$name"; then [[ "${1:-}" == --made ]] || continue
        elif [[ "${1:-}" == --made ]]; then continue
        fi
        echo "$((10#${name#episode_}))"
    done | paste -sd, -
}
if [[ -n "$episodes" ]]; then
    for number in ${episodes//,/ }; do
        audio="episode_$(printf '%03d' "$((10#$number))").mp3"
        [[ -f "$audio" ]] || { echo "Put the episode's audio in the root folder first, as $audio" >&2; exit 1; }
    done
else
    step 'Download'
    bash scripts/03-download-audio/run.sh
    episodes="$(waiting)"
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
fi
made="$(waiting --made)"
if [[ -n "$made" ]]; then
    step "Check the subtitles of episode $made"
    bash scripts/07-validate/run.sh --episodes "$made"
    step 'Delete the audio'
    for number in ${made//,/ }; do
        audio="episode_$(printf '%03d' "$number").mp3"
        rm -- "$audio"
        echo "Deleted $audio: the episode has its Roman Urdu and English subtitles."
    done
elif [[ -z "$episodes" ]]; then
    echo 'No new episode to make subtitles for.'
fi
step 'Sort the questions'
bash ganji-model/run.sh label
step 'Build the app'
bash app/run.sh
