# Deep Transcript Audit — 241 episodes

One purpose: **audit every MP3 against its existing SRT**, locally, without editing or retranscribing subtitles. The tool processes every minute of audio (not just samples), saves separate per-episode logs, captures machine information, and produces an archive of the findings.

> **Important:** This identifies *suspicious passages*, not proven Whisper hallucinations. A voice detector can tell whether speech-like sound is present, but cannot tell whether the transcription contains the correct Urdu or English words. Word accuracy will require a later audio/ASR comparison.

## Only three files

- `deep_audit.py` — **the only script**; scans episodes 001–241, creates all reports, resumes interruptions.
- `requirements.txt` — packages needed to run the script.
- `README.md` — these instructions.

## Prepare

You need Python 3.10+, **FFmpeg and FFprobe** installed and on your PATH, and the required Python libraries installed. Installation may require internet *once*; the audit itself does not access the internet or download transcription model weights.

```bash
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

Arrange your files, for example:

```text
MyProject/
├── ASK-GANJI-SWAG-ANALYSIS.zip       # Original ZIP with the 241 SRTs
├── all_epsidoes/                      # Original MP3 folder (your spelling)
│   ├── episode_001.mp3
│   ├── ...
│   ├── episode_241.mp3
    ├── deep_audit.py
    └── README.md
```

## Run the complete audit

From inside `Deep_Transcript_Audit`, execute **one command** (works in PowerShell, CMD, Linux shells and macOS terminals):

```bash
python deep_audit.py --srt-source ../ASK-GANJI-SWAG-ANALYSIS.zip --audio-dir ../all_epsidoes --out ../Audit_Results
```

If you have already extracted the ZIP, use the folder containing `episode_001.srt` instead of the ZIP; nested subtitle folders are supported.

**No episode selection is needed.** Every run targets **all 241 episodes**. Each MP3 is decoded in small streaming chunks so the whole corpus is never loaded into RAM. The episode and run logs record progress while it works. If you stop the program, rerun the identical command to skip unchanged episodes that finished successfully. To redo all 241 episodes from scratch, append `--force`.

## What it checks

- File existence and MP3 codec, bitrate, sample rate and duration; full FFmpeg decoding and decoding failures.
- Audio volume, clipping, approximate acoustic silence and locally detected speech regions (Silero VAD).
- Subtitle timing, overlaps, gaps, unusually short/long cues, improbable reading rates, corrupt SRT blocks and broken text encodings.
- Repeated and looping captions, frequently recurring phrases, captions in stretches without detected voice and speech-like audio without nearby subtitles.
- Subtitle vs. MP3 duration mismatches. Flags include **episode IDs and timestamps** to make spot-checking easy.

The audit never converts text to Roman Urdu, re-transcribes, changes the original MP3s/SRTs, or sends their contents to a remote service.

## Output (created after running)

```text
Audit_Results/
├── Logs/
│   ├── machine_info.json             # OS, CPU, RAM, disk, GPU, FFmpeg, versions
│   ├── run_config.json               # Inputs, settings and time of run
│   ├── run_outcome.json              # End status
│   ├── run.log                       # Whole-run progress
│   ├── episode_001.log               # Detailed diagnostics per episode
│   ├── ...
│   └── episode_241.log
├── Episodes/
│   ├── episode_001.json              # Independent saved findings + timestamps
│   ├── ...
│   └── episode_241.json
├── Reports/
│   ├── episode_summary.csv           # All episode status and health metrics
│   ├── review_flags.csv              # Every suspicious timestamp/issue
│   └── audit_overview.json           # Dataset-level totals
└── Review_Package.zip                # All reports and logs, ready to share
```

FFmpeg error logs are saved for episodes where FFmpeg prints diagnostics. Logs and reports are saved locally; they may grow while the process is running. A missing MP3 or failed episode is marked as incomplete and **does not stop the remaining episodes**. You can track progress in `Audit_Results/Logs/run.log`.

## After it finishes

Send me **`Audit_Results/Review_Package.zip`**. I can analyze the machine specifications, compare problematic episodes, and recommend a separate, free offline transcription/repair strategy based on the actual results.

**Privacy:** The review package includes your computer hostname, hardware data, software versions, local file paths and short excerpts of flagged subtitle text. Check it before sharing. It does **not** include any MP3 files or complete SRT files.
