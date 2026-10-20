# Ask Ganji Swag — Urdu–English Subtitle Verification & Repair

**CrisperWhisper 2.0 Large · Full second-pass ASR · 241 episodes · Local MP3s · SRT output**

This project improves an existing library of Whisper Large-v3 subtitles by checking **every episode's audio a second time** with CrisperWhisper 2.0 Large. It focuses on transcription quality—not translation or transliteration. Spoken Urdu remains in **Urdu script**, and English remains in **English** where correctly recognized.

The workflow is intentionally conservative: it **repairs strong hallucinations and supported missing-speech regions**, while logging other disagreements for review rather than replacing plausible text automatically. A full second ASR pass is **not** a guarantee that every word is correct.

> **Start here:** If your 241 MP3s are already in `all_episodes/` and the original SRTs are in `urdu_transcript_srt_raw_old/`, use the [Quick start](#quick-start). You do **not** need to download the playlist, convert the entire library to WAV, or install a Roman Urdu model.

## Contents

- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [Prerequisites and Jetson setup](#prerequisites-and-jetson-setup)
- [Processing workflow](#processing-workflow)
- [Commands and options](#commands-and-options)
- [Outputs and quality review](#outputs-and-quality-review)
- [Resuming, caching, and storage](#resuming-caching-and-storage)
- [Troubleshooting](#troubleshooting)
- [Validation and limitations](#validation-and-limitations)
- [Optional: downloading audio again](#optional-downloading-audio-again)

## Quick start

Run the following commands from the **project root** in your existing `(jetson_torch)` environment.

```bash
# 1. Install only the lightweight project dependencies.
python -m pip install -r requirements.txt

# 2. Check installed libraries and audio utilities.
python repair.py doctor

# 3. Inspect the existing subtitle files without loading ASR.
python -u repair.py audit

# 4. Test one episode with the FULL second audio pass.
python -u repair.py run \
  --only 1 \
  --deep-scan \
  --repair-code-switch \
  --offline

# 5. Process all remaining episodes; completed episodes are skipped.
python -u repair.py run \
  --deep-scan \
  --repair-code-switch \
  --offline

# 6. Inspect completion markers.
python repair.py status
```

**Primary outputs:** `urdu_transcript_srt_crisper/episode_001.srt` through `episode_241.srt` as each episode successfully completes. The review report and processing cache are stored separately in `audit/results/`.

`--offline` assumes the **CrisperWhisper 2.0 Large weights are already cached** on your machine. It disables Hugging Face downloads while the command runs.

## Project layout

```text
ASK-GANJI-SWAG-ANALYSIS/
├── all_episodes/                          # Local MP3 recordings (read-only inputs)
│   ├── episode_001.mp3
│   ├── episode_002.mp3
│   └── ... episode_241.mp3
│
├── urdu_transcript_srt_raw_old/           # Original Whisper Large-v3 SRTs (unchanged)
│   ├── episode_001.srt
│   ├── episode_002.srt
│   └── ... episode_241.srt
│
├── urdu_transcript_srt_crisper/           # Finished SRT files ONLY
│   ├── episode_001.srt
│   ├── episode_002.srt
│   └── ...
│
├── audit/
│   ├── episode_audit.csv                 # Text-only audit summary (optional)
│   ├── repair_windows.csv                # Text-only candidate repair windows (optional)
│   └── results/
│       ├── repair_cache.sqlite3          # ASR chunks, VAD scans, resume state
│       └── review.csv                    # Episode status and flagged segments
│
├── repair.py                              # Main CLI: doctor, audit, run, status
├── requirements.txt                      # Lightweight supplementary dependency
├── test_pipeline.py                      # Offline unit tests
└── README.md
```

**Keep the two input folders unchanged.** The program reads MP3s and raw SRTs; it writes corrected subtitles to `urdu_transcript_srt_crisper/`. It does not place logs or databases in the subtitle-output folder.

If an older version left a cache or review CSV under `subtitles/` or `subtitles_cleaned/`, this version can migrate those files to `audit/results/` when no destination file already exists. Keep a backup before upgrading; do not remove old folders until the new cache and outputs are confirmed.

### Naming requirements

Pair each audio file with the SRT that covers **the same recording**:

```text
episode_001.mp3  ↔  episode_001.srt
episode_002.mp3  ↔  episode_002.srt
```

The runner selects source files matching `episode_*.srt` and looks for a corresponding numbered MP3. If playlist ordering or audio filenames have changed, check the mapping **before** running the full library. An incorrectly paired MP3 and SRT will generate misleading comparisons.

## Prerequisites and Jetson setup

This version is designed for the existing **NVIDIA Jetson AGX Orin / Ubuntu / Python** setup used for the project.

- **Python environment:** the existing `(jetson_torch)` environment with its CUDA-enabled PyTorch installation.
- **ASR:** the existing, working `crisperwhisper` package and cached **CrisperWhisper 2.0 Large** model.
- **Audio utilities:** `ffmpeg` and `ffprobe` must be available in `PATH`.
- **Deep scan:** `webrtcvad-wheels`, installed through this project's `requirements.txt`.
- **Data:** local MP3s in `all_episodes/` and original SRTs in `urdu_transcript_srt_raw_old/`.

```bash
# If needed, activate your existing environment first.
conda activate jetson_torch

# FFmpeg provides ffmpeg and ffprobe.
sudo apt-get update
sudo apt-get install -y ffmpeg

# Adds WebRTC VAD only; do not replace the working Jetson PyTorch build.
python -m pip install -r requirements.txt

# Preflight: checks the CrisperWhisper package, VAD, FFmpeg, and CUDA visibility.
python repair.py doctor
```

**Do not casually upgrade or reinstall `torch` on Jetson.** Its CUDA build is platform-specific. CrisperWhisper weights are fetched only if needed when not running in offline mode; use your existing Hugging Face cache for the `--offline` commands.

**Not required:** Mavkif, SentencePiece, uroman, Ollama, Roman Urdu adapters, or a second text-generation model. This pipeline deliberately does not romanize subtitles.

## Processing workflow

For each matched MP3/SRT pair, the full second-pass runner:

1. **Loads the original SRT.** Checks for repeated-text hallucination patterns, unusually long cues, and some English words written phonetically in Urdu script.
2. **Checks audio coverage.** By default, WebRTC voice activity detection (VAD) scans the complete MP3 for likely uncaptioned speech and text-over-silence warnings. VAD is a screening tool, not a transcript verifier.
3. **Retranscribes the entire audio.** The MP3 timeline is divided into consecutive windows of about **55 seconds**. CrisperWhisper runs on **every window**, including sections whose original subtitles look normal. Small context overlaps are used when extracting audio.
4. **Compares both transcriptions.** Significant disagreements are recorded as review items. Similarity scores are **heuristics, not confidence percentages**.
5. **Repairs conservatively.** Strong repetition loops, certain supported missing-speech gaps, and selected code-switching regions are eligible for replacement when the new ASR has usable, timed text. Otherwise, the original subtitle remains.
6. **Cleans formatting.** Normalizes whitespace and punctuation spacing without translating, Romanizing, paraphrasing, or removing genuine spoken repetitions.
7. **Writes outputs safely.** Produces one SRT using an atomic file replacement, records review items and completion status, then advances to the next episode.
8. **Cleans up temporary media.** Each short 16 kHz mono WAV is removed after processing, including ordinary error paths. The original MP3s stay untouched.

**Important distinction:** *Every episode receives a complete second audio pass; not every cue is rewritten.* This prevents a secondary recognizer from unnecessarily replacing acceptable source text with a different error.

## Commands and options

All commands are run from the project root.

### A. Audit original SRTs (no audio transcription)

```bash
python -u repair.py audit
```

Creates `audit/episode_audit.csv` and `audit/repair_windows.csv`. These describe text-based risk indicators, **not verified speech-recognition accuracy**.

### B. Full second-pass pilot

```bash
python -u repair.py run \
  --only 1,2,100 \
  --deep-scan \
  --repair-code-switch \
  --offline
```

Use `--only` with comma-separated episode numbers. A missing input MP3 prevents that episode from completing its second pass.

### C. Full-library processing

```bash
python -u repair.py run \
  --deep-scan \
  --repair-code-switch \
  --offline
```

This processes all available `episode_*.srt` files. **The full-audio second pass and `--deep-scan` are already enabled by default**; they are shown explicitly above for readability.

### D. Resume and monitor

```bash
python repair.py status
```

Stop a run with `Ctrl+C` if needed, then rerun command **C**. Completed episodes are skipped when their saved completion signature matches the source SRT, MP3, model, and relevant processing settings. Individual successful ASR chunks from incomplete episodes are cached and can be reused.

### E. Rebuild one episode's SRT, retaining cached ASR

```bash
python -u repair.py run \
  --only 1 \
  --force \
  --deep-scan \
  --repair-code-switch \
  --offline
```

`--force` rebuilds the output using existing cached ASR chunks when applicable. **It is not equivalent to retranscribing all audio.**

### F. Rerun the underlying ASR, ignoring cached chunks

```bash
python -u repair.py run \
  --only 1 \
  --force \
  --no-cache \
  --deep-scan \
  --repair-code-switch \
  --offline
```

Use this if the ASR configuration or its previous transcription was problematic, or if you specifically need fresh model inference.

### G. Formatting-only mode (not a second pass)

```bash
python -u repair.py run --only 1 --clean-only
```

This generates a formatting-only draft without listening to the audio. It **does not** mark an episode as second-pass complete and can invalidate an existing completion marker for that episode. Do not mistake it for the primary production workflow.

### Common options

| Option | Effect |
| --- | --- |
| `--only 1,2,100` | Process selected episodes. |
| `--offline` | Disable Hugging Face/model network lookups; use cached weights. |
| `--deep-scan` / `--no-deep-scan` | Enable/disable full MP3 VAD coverage scan (enabled by default). |
| `--repair-code-switch` | Consider heuristic phonetic-English regions for repairs; **not** comprehensive code-switch detection. |
| `--chunk-seconds 55` | Set second-pass core-window length (allowed range: 25–75 seconds). |
| `--force` | Rebuild an episode's SRT despite a matching completion marker. |
| `--no-cache` | Ignore cached ASR/VAD results and run inference again. |
| `--allow-incomplete` | Export an explicitly partial draft when some ASR chunks fail. **Not recommended for final subtitles.** |
| `--clean-only` | Formatting only; no audio verification. |
| `--language ur` | Set the language requested of CrisperWhisper (default: Urdu). |
| `--engine whisper` | Optional alternative backend; requires its own installed package. |
| `--limit N` | Stop after N newly written episodes. |

See the actual installed program's full interface:

```bash
python repair.py run --help
```

## Outputs and quality review

### Completed subtitle files

The resulting subtitle directory contains **SRT files only**:

```text
urdu_transcript_srt_crisper/
├── episode_001.srt
├── episode_002.srt
└── ...
```

An episode SRT is emitted after a successful full second pass even when all of its original text was retained. A missing, failed, or unfinished episode is **not** treated as verified simply because its raw SRT exists.

### Audit files

| File | Purpose |
| --- | --- |
| `audit/episode_audit.csv` | Per-episode text-only risk indicators from `audit`. |
| `audit/repair_windows.csv` | Timestamp ranges of strongly repetitive regions found by `audit`. |
| `audit/results/review.csv` | Per-episode full-pass status, transcription disagreements, warnings, and repairs. |
| `audit/results/repair_cache.sqlite3` | Cached VAD scans and ASR chunks, plus completion markers for resume. |

### Understanding `review.csv`

The report includes an episode number, optional timestamps, a status, a reason, and a comment. The most useful statuses are:

| Status | Meaning | Recommended action |
| --- | --- | --- |
| `SECOND_PASS_COMPLETE` | Every audio window was processed successfully. **Not a word-level accuracy certificate.** | Spot-check the episode, especially flagged windows. |
| `REPAIRED` | A high-priority region was replaced using second-pass ASR. | Listen to confirm the replacement. |
| `DISAGREEMENT_REVIEW` | The two transcripts differ substantially; no automatic choice was made on that basis alone. | Compare the MP3 and SRT at that interval. |
| `CODE_SWITCH_WARNING` / `CODE_SWITCH_UNRESOLVED` | Possible English-in-Urdu-script issue or unresolved replacement. | Review the actual code-switched speech. |
| `POSSIBLE_SILENT_TEXT` / `VOICE_WITHOUT_ASR` | VAD/audio-coverage disagreement. | Check for silence, background noise, or missed speech. |
| `NEEDS_REVIEW` / `GAP_REVIEW` / `RESIDUAL_REPETITION` | A suspicious region remains uncertain or repetitive. | Listen and correct manually if required. |
| `SECOND_PASS_ERROR` / `INCOMPLETE_SECOND_PASS` / `EPISODE_ERROR` | A chunk or episode failed. | Fix the issue and resume; no finished SRT is published by default. |
| `SECOND_PASS_PARTIAL` | Output was exported despite incomplete audio processing via `--allow-incomplete`. | **Treat as an unverified draft.** |

Other warnings, such as `LONG_CUE_WARNING` and `TIMING_WARNING`, flag formatting or timing problems for inspection.

## Resuming, caching, and storage

- **Inputs preserved:** `all_episodes/` and `urdu_transcript_srt_raw_old/` are not modified.
- **Minimal disk use:** only **one short temporary WAV** is generated at a time; there is no library-wide WAV conversion.
- **Cleanup:** the short WAV is removed even if ordinary processing fails. If the process is forcibly killed, the system may leave an operating-system temporary directory behind.
- **Resume:** successful chunk transcriptions are stored in `audit/results/repair_cache.sqlite3`; interrupted episodes can continue without recomputing those chunks.
- **Completion markers:** a previously written SRT is skipped **only** when a matching full-pass completion record exists (unless forced).
- **Cache size:** SQLite grows as full-library chunk results accumulate. Keep adequate disk space for this file even though temporary WAVs are deleted.
- **Concurrency:** run **one instance at a time** against the SQLite database and output folder.
- **Cache migration:** older `subtitles/` or `subtitles_cleaned/` caches/reviews may be moved into `audit/results/` if the destination does not already exist.

**MP3 → WAV does not restore information lost in MP3 compression.** The temporary WAV is just a standardized input format for audio inference.

## Troubleshooting

**`python repair.py` reports that an `action` is required.**  
Use a subcommand: `doctor`, `audit`, `run`, or `status`. Example: `python repair.py run --only 1 --offline`.

**CrisperWhisper/model files are requested while using `--offline`.**  
Check that the weights are fully present in the **same Hugging Face cache/environment** used by the current shell. Offline mode intentionally fails rather than downloading missing weights.

**`doctor` reports missing `webrtcvad`, `ffmpeg`, or `ffprobe`.**  
Install the project requirements and FFmpeg as shown above. Check that `which ffmpeg` and `which ffprobe` resolve to executable programs.

**An episode says `No corresponding MP3`.**  
Verify that its number matches between `all_episodes/` and `urdu_transcript_srt_raw_old/`. Check for incorrectly indexed playlist downloads.

**A completed SRT is skipped despite `--force` not being used.**  
This is expected when the completion signature matches the current inputs and configuration. Use `--force` to rebuild the SRT; add `--no-cache` if you need fresh ASR inference.

**The program reports disagreement but does not change a subtitle.**  
This is deliberate. CrisperWhisper and Whisper Large-v3 can disagree without either being guaranteed correct. `DISAGREEMENT_REVIEW` identifies a segment for listening rather than silently selecting one transcript.

**CUDA memory use is high on Jetson.**  
Use the existing environment and inspect `tegrastats`. Avoid running other GPU-heavy applications simultaneously. Reducing `--chunk-seconds` can reduce per-chunk processing demands, although that also changes chunk boundaries and may affect transcription quality.

**A second pass fails partway through an episode.**  
Read `audit/results/review.csv` for the failing time range. Fix the environment or input, then rerun; saved successful chunks can be reused. `--allow-incomplete` is available for diagnostics, but should not be used to claim a finished transcript.

## Validation and limitations

Run the bundled **offline** test suite:

```bash
python -m unittest test_pipeline -v
```

The 11 bundled tests cover SRT cleanup, full-episode window coverage, conservative repairs, output-folder placement, resumption, interruption recovery, temporary WAV deletion, and cache migration. They use simulated transcription; **they do not measure real Urdu–English ASR accuracy**.

This system can identify many obvious hallucinations and missing-speech regions, but it cannot guarantee that every word matches the source MP3. In particular:

- Both recognizers can mishear conversational Urdu or code-switched English.
- VAD cannot establish what was said or whether an apparently plausible subtitle is correct.
- Automatic comparison is a triage signal, not a calibrated confidence estimate.
- The script does not translate, Romanize, guess English spellings, or silently edit genuine spoken repetitions.

**Before publication**, listen to the repaired intervals, inspect major disagreements, and spot-check apparently unchanged passages. Prioritize English-heavy speech, low-volume audio, overlapping voices, and episodes previously affected by repeated hallucinations.

## Optional: downloading audio again

Your 241 MP3s are already local, so **this step is not part of the normal workflow**. The following command is retained only for rebuilding the audio collection from the [original playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B) if needed:

```bash
mkdir -p all_episodes

yt-dlp \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --sleep-interval 5 \
  --max-sleep-interval 15 \
  -o 'all_episodes/episode_%(playlist_index)03d.%(ext)s' \
  'https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B'
```

**Verify the episode numbers against the original SRTs** after a fresh download. Playlist positions can change, and this framework depends on correctly matched audio/subtitle pairs. Downloading may also depend on current YouTube/yt-dlp compatibility and your authorization to access the recordings.

---

**Project principle:** *Verify the audio, repair only when supported by evidence, preserve the original material, and expose uncertainty instead of concealing it.*
