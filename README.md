# Ask Ganji Swag — Transcripts and Analytics

<p align="center">
  <img src="docs/logo.png" alt="Ask Ganji Swag" width="200" />
</p>

Subtitles and an analytics app for every episode of Ask Ganji Swag.

- **Roman Urdu subtitles**, with English kept as spoken
- **English subtitles**, translated from the audio
- **An analytics app** for the 1,422 viewer questions: [open the dashboard](https://reeyan-afzal-khan.github.io/ASK-GANJI-SWAG-ANALYSIS/)

[Workflow guide](docs/workflow.md) · [Episode index](docs/episode-index.md) · [Reports](docs/reports.md) · [App guide](app/README.md)

## What's where

| Folder | Contents |
| --- | --- |
| `transcripts-urdu-roman/` | Roman Urdu subtitles, one line per cue |
| `transcripts-english/` | English subtitles |
| `app/` | The analytics app and its data |
| `scripts/` | The pipeline, steps 01–08 |
| `docs/` | Guides, the episode index and the logo |
| `all_episodes/`, `.cache/` | Audio, models, caches and reports (not in Git) |

## Quick start

Open Ubuntu from PowerShell:

```powershell
wsl -d Ubuntu -u root
```

Then, in Bash:

```bash
cd /mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS
bash scripts/07-validate/run.sh   # check the subtitles
bash app/run.sh --serve           # open the app at http://localhost:8765/
```

## Add a new episode

```bash
bash scripts/03-download-audio/run.sh 243 "https://www.youtube.com/watch?v=VIDEO_ID"
bash scripts/04-transcribe/run.sh --episodes 243            # GPU
bash scripts/05-romanize/run.sh --episodes 243
bash scripts/06-format/run.sh --episodes 243                # even timing, optional, GPU
bash scripts/06-format/run.sh --translate --episodes 243    # English, GPU
bash scripts/07-validate/run.sh --episodes 243
bash app/run.sh
```

Then label its questions in `app/tools/question_labels.json`. Until then they show as "Not yet sorted".

## Pipeline

| Step | What it does |
| --- | --- |
| 01 setup | Python environments (once) |
| 02 download-model | Roman Urdu model (once) |
| 03 download-audio | One episode's audio |
| 04 transcribe | Speech to text with CrisperWhisper (GPU) |
| 05 romanize | Urdu script to Roman Urdu |
| 06 format | Even subtitle timing; `--translate` for English (GPU) |
| 07 validate | Check the subtitles |
| 08 test | Run the tests |

Run each as `bash scripts/NN-name/run.sh`. Every step takes `--help`. Options, settings and setup on a new machine: [docs/workflow.md](docs/workflow.md).

## The app

Plain HTML and JavaScript. Open `app/index.html`, or preview with `bash app/run.sh --serve` (the built-in video player needs the preview).

| Section | Shows |
| --- | --- |
| Overview | What viewers ask about, trends and key findings |
| Categories | Each category, how subjects connect, what answers talk about |
| Questions | Every question, its opening and ▶ to play the answer |
| Insights | Answer lengths, ages, cities and words |
| Episodes | Length, pace and subjects of every episode |
| Episode explorer | The video with a live transcript, Roman Urdu or English |
| About | How to use the app and how the data was made |

Run `bash app/run.sh` again after changing the subtitles, the labels (`app/tools/question_labels.json`), the categories (`app/tools/config.json`) or the colours (`app/skins/`).

## Good to know

- Subtitles are machine-made. Names and rare words can be wrong.
- Validation checks structure, not accuracy.
- Hand edits to `transcripts-urdu-roman/` are kept when re-pacing.
- The original transcription is in Git history as `urdu_transcript_crisper/` (commit `91c2afd`).

## Sources

- [Ask Ganji Swag playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B)
- [CrisperWhisper](https://github.com/nyrahealth/CrisperWhisper/blob/main/DOCS.md) and its [2.0 Large model](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [Urdu-to-Roman model](https://huggingface.co/Mavkif/m2m100_rup_ur_to_rur)

Model and media licences belong to their owners.
