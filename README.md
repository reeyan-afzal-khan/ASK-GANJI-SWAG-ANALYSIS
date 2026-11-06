# Ask Ganji Swag — Transcripts and Analytics

<img src="docs/logo.png" alt="Ask Ganji Swag" width="170" align="left" hspace="20" />

**Subtitles and an analytics app for every episode of Ask Ganji Swag.**

**Roman Urdu subtitles**, with English kept as spoken<br>
**English subtitles**, translated from the audio<br>
**Analytics app** for all the viewed questions

**[Open the dashboard →](https://reeyan-afzal-khan.github.io/ASK-GANJI-SWAG-ANALYSIS/)**

[Workflow guide](docs/workflow.md) · [Episode index](docs/episode-index.md) · [Reports](docs/reports.md) · [App guide](app/README.md)

<br clear="left" />

## What's where

| Folder | Contents |
| --- | --- |
| `transcripts-urdu-roman/` | Roman Urdu subtitles, one line per cue |
| `transcripts-english/` | English subtitles |
| `app/` | The analytics app and its data |
| `ganji-model/` | The model that sorts questions into categories |
| `scripts/` | `add-episode.sh` and the pipeline, steps 01–08 |
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

On a new machine, first run `bash scripts/01-setup/run.sh` and `bash scripts/02-download-model/run.sh`.

## Add a new episode

```bash
bash scripts/add-episode.sh
```

This takes the newest episode in the playlist all the way into the app. It needs the GPU. If it stops, run it again: finished work is skipped.

| Part | What happens |
| --- | --- |
| Download | Audio, and the questions from the video's chapters into `docs/episode-index.md` |
| Subtitles | Urdu, then Roman Urdu with even timing, then English |
| Check | Validates the subtitles |
| Categories | The [Ganji model](ganji-model/README.md) sorts each question into a subcategory |
| App | Rebuilds `app/data/` |

Already have the audio in `all_episodes/`? Use `bash scripts/add-episode.sh --episodes "new-episode-number"`.

The categories are the model's best guesses. To check them one by one, then teach it your corrections:

```bash
bash ganji-model/run.sh label --review --episodes "new-episode-number"
bash ganji-model/run.sh finetune
bash app/run.sh
```

## Pipeline

| Step | What it does |
| --- | --- |
| 01 setup | Python environments, yt-dlp and ffmpeg (once) |
| 02 download-model | Roman Urdu model (once) |
| 03 download-audio | Newest playlist episode: audio and questions |
| 04 transcribe | Speech to text with CrisperWhisper (GPU) |
| 05 romanize | Urdu script to Roman Urdu |
| 06 format | Even subtitle timing; `--translate` for English (GPU) |
| 07 validate | Check the subtitles |
| 08 test | Run the tests |

`add-episode.sh` runs these for you; run one yourself only to redo that part, as `bash scripts/NN-name/run.sh`. Every step takes `--help`. Options, settings and setup on a new machine: [docs/workflow.md](docs/workflow.md).

## The Ganji model

[`ganji-model/`](ganji-model/README.md) is a trained model that sorts each question into a subcategory and says how sure it is. It decides on the whole question and answer, read in English, and learns from the data how to weigh the title against the rest. It learned from this show's own data alone: word vectors from the English subtitles, with Roman Urdu mapped onto them by time, then the hand-checked labels. Anyone can fine-tune it with more questions, or even new subcategories.

| Tested on episodes it had not seen | Category | Subcategory |
| --- | --- | --- |
| Word counts only | 71.2% | 46.6% |
| Ganji model | 73.5% | 51.1% |

```bash
bash ganji-model/run.sh predict "Should I move to Canada on a student visa?"
bash ganji-model/run.sh finetune --data my_questions.jsonl --save my-model
```

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

## Sources

- [Ask Ganji Swag playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B)
- [CrisperWhisper](https://github.com/nyrahealth/CrisperWhisper/blob/main/DOCS.md) and its [2.0 Large model](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [Urdu-to-Roman model](https://huggingface.co/Mavkif/m2m100_rup_ur_to_rur)

Model and media licences belong to their owners.
