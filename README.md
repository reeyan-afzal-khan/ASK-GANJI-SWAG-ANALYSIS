# Ask Ganji Swag — Transcript Pipeline

![Ask Ganji Swag](docs/logo.png)

A local workflow for transcribing Ask Ganji Swag episodes and producing **Roman Urdu subtitles with English preserved**. CrisperWhisper handles speech recognition; a separate transliteration stage converts script and writes one content line per subtitle.

**Workflow:** download audio → transcribe → romanize → validate.

[Episode index](docs/episode-index.md) · [Workflow details](docs/workflow.md) · [Reports](docs/reports.md)

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
├── all_episodes/                  # Local MP3s (ignored by Git)
├── urdu_transcript_crisper/        # Original Crisper SRTs
├── urdu_transcript_crisper_roman/  # Roman Urdu SRTs, one text line per cue
└── .cache/                        # Local models, candidates, reports, backups and logs
```

Only two supporting folders remain: `scripts/` and `docs/`. Each numbered step in `scripts/` contains a `run.sh` entry point and its own supporting files; reusable helpers live in `scripts/.shared/`. The three data folders retain their original locations. Historical analysis and experiment snapshots are preserved under `.cache/reports/archive/2026-10-25/analysis/`; active commands no longer depend on them. See the [migration table](docs/workflow.md#migration-from-the-previous-layout) for renamed scripts.

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

Romanization, formatting and validation also accept `--episodes`. Use `--source`, `--output` or `--directory` as shown by their `--help` output for alternate folders.

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
