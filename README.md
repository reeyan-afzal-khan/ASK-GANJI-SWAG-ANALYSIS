# Ask Ganji Swag — Transcript Pipeline

![Ask Ganji Swag](docs/logo.png)

A local workflow for transcribing Ask Ganji Swag episodes and producing **Roman Urdu subtitles with English preserved**. CrisperWhisper handles speech recognition; a separate transliteration stage converts script and writes one content line per subtitle.

**Workflow:** download audio → transcribe → romanize → validate.

[Episode index](docs/episode-index.md) · [Workflow details](docs/workflow.md) · [Reports](docs/reports.md) · [Analytics app](#analytics-app)

## Quick start on this machine

Open Ubuntu/WSL2 from PowerShell or CMD:

```powershell
wsl -d Ubuntu -u root
```

Then run the following in **Bash**, not PowerShell:

```bash
cd /mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS

# Check the current Roman Urdu collection; no GPU required.
bash scripts/07-validate/run.sh

# Transcribe missing MP3 episodes; completed SRTs are skipped.
bash scripts/04-transcribe/run.sh

# Convert missing Roman Urdu episodes; existing outputs are skipped.
bash scripts/05-romanize/run.sh

# Check the resulting collection.
bash scripts/07-validate/run.sh
```

The transcription environment already used on this machine is `~/.venvs/ask-ganji-ct2`. Before the first Linux Romanization run, create its separate environment and check the local model:

```bash
bash scripts/01-setup/run.sh roman
bash scripts/02-download-model/run.sh
```

The model files have been moved into `.cache/roman-model/`; the download command skips files already present. No old backup ZIP or Whisper folder is needed.

## Commands

Run the numbered shell scripts in the order below. Steps **01–02 are first-time setup**; for each new episode, run **03 → 04 → 05 → 07**. Step **06 is optional** because Romanization already produces single-line subtitles. Step **08 checks the code** and is useful after changes.

Every entry point supports `--help`. The scripts resolve the project directory themselves. `scripts/.shared/common.sh` and the Python files are helpers; you do not run them as workflow steps.

| Command | Purpose |
| --- | --- |
| `bash scripts/01-setup/run.sh [all\|transcription\|roman]` | Prepare the Linux environments |
| `bash scripts/02-download-model/run.sh` | Fetch the pinned Roman Urdu model and tokenizer |
| `bash scripts/03-download-audio/run.sh NUMBER VIDEO_URL` | Download one episode with an explicit filename |
| `bash scripts/04-transcribe/run.sh` | Transcribe missing MP3 episodes |
| `bash scripts/05-romanize/run.sh` | Convert missing outputs to single-line Roman Urdu |
| `bash scripts/06-format/run.sh` | Optional: join multiline subtitle text; back up changed files |
| `bash scripts/07-validate/run.sh` | Check script, structure, timing and English preservation |
| `bash scripts/08-test/run.sh` | Optional: run code regression tests after changes |

### Process a new episode

Use the video's watch URL and an explicit episode number. Playlist positions can change, so they should not silently determine your filenames.

```bash
bash scripts/03-download-audio/run.sh 243 "https://www.youtube.com/watch?v=REPLACE_WITH_VIDEO_ID"
bash scripts/04-transcribe/run.sh --episodes 243
bash scripts/05-romanize/run.sh --episodes 243
bash scripts/07-validate/run.sh --episodes 243
```

`243` is an example, not a claim that an episode has been published. The downloader preserves existing files and stores video metadata alongside the MP3.

### Select episodes or run a short transcription test

```bash
bash scripts/04-transcribe/run.sh --episodes 123,163,183
FIRST_EPISODE=240 LAST_EPISODE=242 bash scripts/04-transcribe/run.sh
bash scripts/04-transcribe/run.sh --smoke-test 48
```

The smoke test transcribes the first 20 seconds without writing an SRT. Normal transcription begins at episode 1 by default, stops at the highest available MP3 number, and skips nonempty outputs.

### Format or regenerate Roman subtitles

```bash
# Check whether any cues need joining, without changing files.
bash scripts/06-format/run.sh --check

# Join text lines in all Roman SRTs. Timestamps and wording stay intact.
bash scripts/06-format/run.sh

# Deliberately regenerate one existing Roman file; back it up first.
bash scripts/05-romanize/run.sh --episodes 243 --overwrite

# Use only the existing glossary/candidate cache; no GPU generation.
bash scripts/05-romanize/run.sh --episodes 243 --cached-only
```

New Roman output is already single-line. Formatting is useful for imported or manually edited files. An editor or player may still visually wrap a long line.

## Analytics app

`app/` is a self-contained web app for exploring the 1,422 viewer questions in the episode index: what people ask about, how each question fits one of 10 categories and 60 finer subcategories, how that changed across the show, and what Junaid said in reply, with every episode playable in a built-in YouTube player whose transcript follows the video in real time. It is plain HTML and JavaScript with no external libraries, and everything it reads is generated into `app/data/`, so the folder can be published as-is, for example on GitHub Pages. [app/README.md](app/README.md) covers publishing.

```bash
# Rebuild app/data/ after transcripts or the episode index change.
bash app/run.sh

# Rebuild, then preview the app the way a static host serves it: http://localhost:8765/
bash app/run.sh --serve

# Preview the existing data without rebuilding; --port changes the port.
bash app/run.sh --skip-build --port 8765
```

WSL2 forwards `localhost`, so open the printed address in your Windows browser; press Ctrl+C to stop the preview. Opening `app/index.html` straight from disk works too, except the built-in player: YouTube only plays embedded videos on pages served over http(s), so from disk the transcript's timestamps open YouTube instead. The builder needs no GPU, network access or extra packages, only Python's standard library, so it also runs on Windows: `python app\tools\build_data.py`. `bash scripts/08-test/run.sh` also runs the app's tests.

| Section | What it shows |
| --- | --- |
| Overview | A dashboard: headline figures, a pie (sunburst) of categories with their subcategories that zooms into a category on click, subjects over time as stacked columns, questions per episode, computed findings, the most common subcategories, rising and falling subjects, askers' ages, the longest answers and a random question spotlight |
| Categories | A card per category with its trend and top subcategories; each opens a page with its subcategories, trend, a subcategory-by-period heatmap, related categories, title words, ages and its questions |
| Questions | An explorer of every question: search, category and subcategory chips, sorting, the opening of each answer, and ▶ to play the answer in the episode explorer |
| Insights | Answer time per subject (one dot per question), answer length by position, askers' stated ages, places mentioned, subjects that come together, title words, and rising and falling subcategories |
| Episodes | Questions per episode, time per question, intro length and episode length, plus a sortable table of episodes with their subjects |
| Episode explorer | The episode in a built-in YouTube player, with the question being answered, a clickable timeline, the questions with their categories, a words-per-minute curve and a searchable transcript that highlights and scrolls to the line being spoken |
| About | How questions were categorised, every subcategory with its count, measure definitions, caveats and data-quality checks |

Sections sit in a left sidebar (a drawer on phones). Below them, a collapsible **Categories** tree lists every category with its subcategories and counts; picking one filters the Overview, Questions, Insights and Episodes sections, or opens its category page from elsewhere. Click any episode column to open that episode at the start, or any ▶ time to play from that moment. Every chart has a table view, the page follows the system light/dark theme (with a switch in the sidebar), and the current view, including the playback time when paused, is kept in the URL so it can be bookmarked or shared. Colours come from the skins in `app/skins/`: `bash app/run.sh` turns the light and dark skin into `app/assets/theme.css`.

Every question has one hand-checked subcategory, plus any clear second subject, in `app/tools/question_labels.json`: one line per episode, codes in index order, defined in `app/tools/config.json`. Correct a label by editing that line and rebuilding; an unknown code stops the build with the episode and question number. Episodes that are not in the labels file yet (new ones) are placed by the keyword lists in `config.json` and shown as "Not yet sorted" until you add them. *Answer length* is the time until the next indexed question, so it includes reading the question. Stated ages and places are read from the title and the opening of the answer, which is usually the letter being read out. The app's **About** tab lists every definition and caveat.

## Repository layout

```text
ASK-GANJI-SWAG-ANALYSIS/
├── README.md
├── scripts/
│   ├── 01-setup/                  # run.sh + dependency lists
│   ├── 02-download-model/         # run.sh + downloader + model settings
│   ├── 03-download-audio/         # run.sh
│   ├── 04-transcribe/             # run.sh + transcription + decoder guard
│   ├── 05-romanize/               # run.sh + Romanization + spelling glossary
│   ├── 06-format/                 # run.sh (optional)
│   ├── 07-validate/               # run.sh
│   ├── 08-test/                   # run.sh + regression tests
│   └── .shared/                    # Shell setup, paths and subtitle utilities
├── docs/                          # Workflow guide, episode index and logo
├── app/                           # Analytics web app, its generated data and builder
├── all_episodes/                  # Local MP3s (ignored by Git)
├── urdu_transcript_crisper/        # Original Crisper SRTs
├── urdu_transcript_crisper_roman/  # Roman Urdu SRTs, one text line per cue
└── .cache/                        # Local models, candidates, reports, backups and logs
```

Only two supporting folders remain: `scripts/` and `docs/`. Each numbered step in `scripts/` contains a `run.sh` entry point and its own supporting files; reusable helpers live in `scripts/.shared/`. The three data folders retain their original locations. Historical analysis and experiment snapshots are preserved under `.cache/reports/archive/2026-10-25/analysis/`; active commands no longer depend on them. See the [migration table](docs/workflow.md#migration-from-the-previous-layout) for renamed scripts. `app/` sits apart from the transcription pipeline: it only reads the Roman SRTs and the episode index, and keeps its generated `app/data/` under version control so it can be published without a rebuild.

## Installation on a new machine

Use Ubuntu/WSL2 with an NVIDIA GPU and CUDA-compatible Windows driver. Setup creates Python 3.12 environments and installs the repository's pinned stack. Linux `python3-venv` and `ffmpeg` are prerequisites:

```bash
# Run as root; otherwise use sudo for apt-get.
apt-get update
apt-get install -y python3-venv ffmpeg

bash scripts/01-setup/run.sh
bash scripts/02-download-model/run.sh
```

For audio downloads, keep yt-dlp in its own environment:

```bash
python3 -m venv "$HOME/.venvs/yt-dlp"
"$HOME/.venvs/yt-dlp/bin/python" -m pip install -U "yt-dlp[default]"
export PATH="$HOME/.venvs/yt-dlp/bin:$PATH"
```

Repeat the `export PATH` command in subsequent downloader sessions. Follow [yt-dlp's EJS instructions](https://github.com/yt-dlp/yt-dlp/wiki/EJS) if YouTube requests a JavaScript runtime or challenge solver.

Transcription and Romanization use separate environments to protect the Crisper CT2 fork. Do not replace it with upstream `ctranslate2` or `faster-whisper`. Models, caches, reports, backups, logs and local environments are excluded from Git. `.gitignore` also excludes audio/video, model-weight formats (`.safetensors`, `.pt`, `.pth`, `.onnx`, `.gguf`, `.ckpt`, `.bin`) and archive files. Git cannot ignore files by size; these directory and file-type rules cover the large artifacts. Subtitle SRTs, source code and the spelling glossary remain eligible for version control.

## Configuration

| Setting | Default / behavior |
| --- | --- |
| `GANJI_PYTHON` | Override the interpreter used by a shell entry point |
| `CRISPER_PYTHON` | Transcription-specific override; retains compatibility with the previous workflow |
| `CRISPER_MODEL` | `large`, or the legacy local `CrisperWhisper2_Large/` folder when present |
| `EPISODES` | Comma-separated transcription episode numbers |
| `FIRST_EPISODE` / `LAST_EPISODE` | Transcription range; defaults to 1 / highest MP3 |
| `scripts/05-romanize/roman_glossary.json` | Reviewed Urdu → Roman spelling overrides |
| `scripts/02-download-model/roman_model.json` | Pinned model and tokenizer revisions |
| `app/tools/question_labels.json` | Hand-checked subcategory of every indexed question, one line per episode |
| `app/tools/config.json` | Analytics app categories, subcategories, fallback keywords, places and stopwords |
| `app/skins/*.json` | Analytics app colours: the first light and first dark skin become `app/assets/theme.css` |

Romanization, formatting and validation also accept `--episodes`. Use `--source`, `--output` or `--directory` as shown by their `--help` output for alternate folders. `bash app/run.sh` also accepts `--index`, plus `--serve`, `--skip-build`, `--host` and `--port`.

## Validation and quality

Validation checks that every source episode has a corresponding Roman output, each cue contains one text line, cue IDs/timestamps match, non-Latin letters are absent, and existing English text is retained. It writes `.cache/reports/validation.json` and exits nonzero on failure. `--episodes` limits validation to selected episodes.

Romanization preserves the source transcript rather than correcting it against the recording. Uncertain names, missing vowels, malformed words and original recognition errors still need review. Per-run hashes and review queues are saved under `.cache/reports/romanization/`. A successful structural check is not a transcription accuracy score.

To save a transcription log:

```bash
mkdir -p .cache/logs
set -o pipefail
bash scripts/04-transcribe/run.sh 2>&1 | tee .cache/logs/transcribe.log
```

See [workflow notes and troubleshooting](docs/workflow.md) for resume behavior, retries, decoder protection and source-text warnings.

## Sources

- [Ask Ganji Swag playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B)
- [CrisperWhisper documentation](https://github.com/nyrahealth/CrisperWhisper/blob/main/DOCS.md)
- [CrisperWhisper 2.0 Large model and license](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [Urdu-to-Roman transliteration model](https://huggingface.co/Mavkif/m2m100_rup_ur_to_rur)

Model and source-media licenses remain those of their respective owners; this repository does not relicense them.
