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

Run the numbered shell scripts in the order below. Steps **01–02 are first-time setup**; for each new episode, run **03 → 04 → 05 → 07**. Step **06 is optional** because Romanization already produces single-line subtitles. Step **08 checks the code** and is useful after changes. Step 06 now also evens out the pacing of the Roman subtitles: it times every word against the audio on the GPU and regroups the cues into lines of similar length (see [Even pacing](#even-pacing-and-the-audio-check)), so run it after 05 when you want evenly paced cues.

Every entry point supports `--help`. The scripts resolve the project directory themselves. `scripts/.shared/common.sh` and the Python files are helpers; you do not run them as workflow steps.

| Command | Purpose |
| --- | --- |
| `bash scripts/01-setup/run.sh [all\|transcription\|roman]` | Prepare the Linux environments |
| `bash scripts/02-download-model/run.sh` | Fetch the pinned Roman Urdu model and tokenizer |
| `bash scripts/03-download-audio/run.sh NUMBER VIDEO_URL` | Download one episode with an explicit filename |
| `bash scripts/04-transcribe/run.sh` | Transcribe missing MP3 episodes |
| `bash scripts/05-romanize/run.sh` | Convert missing outputs to single-line Roman Urdu |
| `bash scripts/06-format/run.sh` | Optional: join multiline subtitle text; back up changed files; time every word on the GPU and re-pace the Roman cues evenly |
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
# Since the pacing update this also re-times and regroups the cues; the wording still stays intact.
bash scripts/06-format/run.sh

# Deliberately regenerate one existing Roman file; back it up first.
bash scripts/05-romanize/run.sh --episodes 243 --overwrite

# Use only the existing glossary/candidate cache; no GPU generation.
bash scripts/05-romanize/run.sh --episodes 243 --cached-only
```

New Roman output is already single-line. Formatting is useful for imported or manually edited files. An editor or player may still visually wrap a long line.

### Even pacing and the audio check

The original transcription cut a new cue at every pause and every sentence end, up to 14 words, so cues ranged from a single word flashing by for a quarter of a second to 80-character lines. Step 06 evens this out without transcribing anything again and without touching `transcripts-urdu/`:

1. **Word timing on the GPU** (`scripts/06-format/align.py`). Each window of whole cues from the original Crisper SRT is replayed through CrisperWhisper's decoder with its known text, and every word is placed with the same cross-attention timing the model uses when it transcribes. Each Roman word inherits the time of the Urdu word it came from. Results are cached per episode in `.cache/alignment/`, so later runs only align new or changed episodes. On a laptop RTX 4060 this runs at about 75× real time (around five hours for all 371 hours of audio).
2. **Pacing** (`scripts/.shared/pacing.py`). The words are regrouped into single-line cues of at most 42 characters, about seven words each. A cue never spans a pause of 1.5 seconds or more, and breaks prefer sentence ends, commas and pauses over phrases such as "ke liye", "the" or "hai". Each cue stays up for at least a second when the next one allows, and cues never overlap. The changed files are backed up to `.cache/backups/` first.
3. **Clean-up of the original timing.** The long-form transcription sometimes transcribed the end of one chunk again at the start of the next and squeezed the copy into a fraction of a second. Such stitching duplicates (four or more words in an impossibly short time that closely repeat the words just before them) are left out and listed in `.cache/reports/pacing.json`. Other squeezed words are kept and held on screen for at least 0.7 seconds, letting the next cue start up to 1.5 seconds late rather than flash past.

Hand corrections in `transcripts-urdu-roman/` are kept: pacing reads the words from the files as they are, and a corrected word takes the timing of the word it replaced. Edit the Roman files freely, then re-pace with `--skip-align`.

```bash
# Report what pacing would change, without the GPU or writing files.
bash scripts/06-format/run.sh --check

# Align only episodes 243 and 244, then pace them.
bash scripts/06-format/run.sh --episodes 243,244

# Re-pace from the cached alignment after tuning pacing.py; no GPU needed.
bash scripts/06-format/run.sh --skip-align
```

The same pass checks the transcripts against the audio and writes `.cache/reports/audio_check.json` for listening review. It lists stretches of six seconds or more that no cue covers but where the model hears speech (possible missed passages), cues whose words the model finds unlikely given the audio, and words or tags repeated four or more times in a row. It also gives the status of every decoding loop (see "Replacing decoding loops" below). These findings change nothing by themselves; only `--fill` and `--loops`, described below, act on them, and only when you run them.

The report is written in Roman Urdu only. What the model heard in uncovered stretches is romanised with the subtitles' own rules (reviewed glossary first, then model candidates, generating any new words on the GPU), then the report is refreshed:

```bash
# Linux, in the romanization environment:
bash scripts/05-romanize/run.sh --alignment
# Or on Windows, where this repository's romanization has been run:
#   python scripts\05-romanize\romanize.py --alignment

# Refresh the report from the cache (re-pacing is a no-op when nothing changed).
bash scripts/06-format/run.sh --skip-align
```

If a Roman file is regenerated with step 05 after pacing, it returns to the original cue timing; run step 06 again to re-pace it from the cache.

#### Filling missed speech

The audio check found speech in hundreds of stretches the original run skipped, often where its loop guard threw away a whole chunk together with a run of `[lipsmack]` tags. `--fill` transcribes only those stretches, with the transcription step's own settings (verbatim Urdu, decoder profiles, hallucination guard), so nothing else is transcribed again. Tag loops are collapsed, words at the edges that repeat the neighbouring cues are dropped, and a stretch is kept only when the full transcription confirms speech. The passages are romanised like any subtitle word and inserted into `transcripts-urdu-roman/` at their own time; `transcripts-urdu/` is not changed. They are listed in `.cache/reports/pacing.json`, and once inserted they are treated like the rest of the file, so hand edits to them are kept and they are never added twice.

```bash
# Transcribe the missed stretches on the GPU (only those stretches).
bash scripts/06-format/run.sh --fill
# Romanise them (Linux romanization environment; on Windows: python scripts\05-romanize\romanize.py --alignment).
bash scripts/05-romanize/run.sh --alignment
# Pace them into the Roman subtitles.
bash scripts/06-format/run.sh --skip-align
```

#### Replacing decoding loops

Long-form transcription sometimes got stuck on one phrase and wrote it out dozens of times, spread in tiny cues over the stretch where the real answer was. In episode 7, for example, "I'm asking you. I don't know." fills two minutes. Cues cover those stretches, so the missed-speech check cannot see them. Step 06 finds them in the original transcript: any 40 words in a row that use at most 8 different words, or 32 that use at most 4. Stretches made mostly of tags are left alone. `--loops` transcribes each loop's stretch again with the same settings, from the last word before the loop to the first word after it.

A loop is replaced only when the fresh transcription confirms it is a phantom, which means three things:
- it hears at least three spoken words;
- it does not loop itself;
- it says the looped phrase at most twice.

Otherwise the original stays. A confirmed replacement is romanised and paced in like the missed passages, and it also replaces any passage that `--fill` added inside that stretch. `.cache/reports/pacing.json` lists what was replaced, and `.cache/reports/audio_check.json` gives every loop's status in Roman Urdu.

```bash
# Transcribe every loop's stretch again on the GPU (only those stretches).
bash scripts/06-format/run.sh --loops
# Romanise the new text, then pace the confirmed replacements in.
bash scripts/05-romanize/run.sh --alignment
bash scripts/06-format/run.sh --skip-align
```

### English translation

`transcripts-english/` holds English subtitles translated from the audio by CrisperWhisper 2.0, the model that made the transcription, running Whisper's translate task from the local Hugging Face cache. Each episode is cut into windows of whole Roman cues (at most 28 seconds, never across a pause of two seconds). A window under four seconds joins a neighbour, because Whisper invents speech for a lone second of audio, and one holding only tags such as [UH] is skipped. Eight windows at a time become timed English sentences. When a window's English repeats itself, as when the model echoes a stutter, it is decoded again a little warmer, the way Whisper does it. When it still looks wrong (repeating, not English, or under a third of the Roman words, as when the model stops where the speaker switches between Urdu and English), the window is translated again in pieces of about ten seconds, then five, and the pieces are kept where they do better. Stock phrases the model invents for unclear audio ("Thank you.", "Peace be upon you.") are dropped where nothing like them was said. Windows that still look wrong are listed in `.cache/reports/translation.json`. The English keeps its own timing. On a laptop RTX 4060 this runs at about 40× real time, roughly nine and a half hours for every episode; episodes already translated are skipped, and `--repair` translates again only the windows of existing files that need it. In a side-by-side test it gave more complete and more faithful English than Whisper large-v3, decoded greedily or with beam search (see `docs/workflow.md`).

```bash
# English, from the audio (GPU); --episodes translates a few, --force-align translates them again.
bash scripts/06-format/run.sh --translate
# Only the windows of existing English files that need another try (GPU).
bash scripts/06-format/run.sh --translate --repair
```

Once `transcripts-english/` exists, the app's episode explorer can switch its transcript between Roman Urdu and English.

The original Crisper transcription, `transcripts-urdu/`, has been removed from the working tree; it is still in the Git history under its earlier name, `urdu_transcript_crisper/`. The alignment cache keeps its words, so validation and the app's English labels read them from `.cache/alignment/` instead. Pacing (step 06 without `--translate`) needs the original folder back: restore `urdu_transcript_crisper/` from commit `91c2afd` and rename it `transcripts-urdu/`.

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
| Overview | A dashboard: a pie (sunburst) of categories with their subcategories that zooms into a category on click, beside a legend with every category's count and share; subjects over time as stacked columns; computed findings, including the most mentioned cities in Pakistan and abroad; questions per episode; the most common subcategories, rising and falling subjects and askers' ages |
| Categories | A card per category with its trend and top subcategories; each opens a page with its subcategories, trend, a subcategory-by-period heatmap, related categories, title words, ages and its questions |
| Questions | Every question, with category and subcategory chips, sorting, the opening of each answer, and ▶ to play the answer in the episode explorer |
| Insights | Answer time per subject (one dot per question), answer length by position, askers' stated ages, places mentioned, subjects that come together, title words, and rising and falling subcategories |
| Episodes | Questions per episode, time per question, intro length and episode length, plus a sortable table of episodes with their subjects |
| Episode explorer | The episode in a built-in YouTube player, with the question being answered, a clickable timeline, the questions with their categories, a words-per-minute curve and a transcript in Roman Urdu or English that highlights and scrolls to the line being spoken |
| About | How questions were categorised, every subcategory with its count, measure definitions, caveats and data-quality checks |

Sections sit in a left sidebar (a drawer on phones). Under **Categories**, right below the Overview, a collapsible tree lists every category with its subcategories nested beneath it and their counts; picking one filters the Overview, Questions, Insights and Episodes sections, or opens its category page from elsewhere. Click any episode column to open that episode at the start, or any ▶ time to play from that moment. Every chart has a table view, the page follows the system light/dark theme (with a switch in the sidebar), and the current view, including the playback time when paused, is kept in the URL so it can be bookmarked or shared. Colours come from the skins in `app/skins/`: `bash app/run.sh` turns the light and dark skin into `app/assets/theme.css`.

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
│   ├── 06-format/                 # run.sh (optional) + GPU word alignment for even pacing
│   ├── 07-validate/               # run.sh
│   ├── 08-test/                   # run.sh + regression tests
│   └── .shared/                    # Shell setup, paths and subtitle utilities
├── docs/                          # Workflow guide, episode index and logo
├── app/                           # Analytics web app, its generated data and builder
├── all_episodes/                  # Local MP3s (ignored by Git)
├── transcripts-urdu/              # Original Crisper SRTs (removed; in the Git history as urdu_transcript_crisper/)
├── transcripts-urdu-roman/        # Roman Urdu SRTs, one text line per cue
├── transcripts-english/           # English SRTs translated from the audio (step 06 --translate)
└── .cache/                        # Local models, candidates, reports, backups and logs
```

Only two supporting folders remain: `scripts/` and `docs/`. Each numbered step in `scripts/` contains a `run.sh` entry point and its own supporting files; reusable helpers live in `scripts/.shared/`. The three data folders retain their original locations. Historical analysis and experiment snapshots are preserved under `.cache/reports/archive/2026-10-25/analysis/`; active commands no longer depend on them. See the [migration table](docs/workflow.md#migration-from-earlier-layouts) for renamed scripts. `app/` sits apart from the transcription pipeline: it only reads the Roman SRTs and the episode index, and keeps its generated `app/data/` under version control so it can be published without a rebuild.

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

Validation checks that every source episode has a corresponding Roman output, each cue contains one text line, cue IDs/timestamps match, non-Latin letters are absent, and existing English text is retained. It writes `.cache/reports/validation.json` and exits nonzero on failure. `--episodes` limits validation to selected episodes. Roman files paced by step 06 no longer share the source's cue timings, so for them validation checks instead that cues are numbered consecutively, never overlap and stay within the source's time (widened by passages added for missed speech, which include intros and outros the original run skipped), and that every English word survives in order. The exceptions are stitching duplicates and decoding loops, which pacing may leave out; both are found from the original transcript alone, so this check works without the cache. While the alignment cache is present, words that differ from it are listed as hand corrections: a warning, not an error. Without `transcripts-urdu/`, the original cues come from the alignment cache, which holds them word for word, and every cached episode must have its Roman file. When `transcripts-english/` exists, each of its files must belong to a Roman file and be numbered in order, one line per cue, without overlaps.

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
