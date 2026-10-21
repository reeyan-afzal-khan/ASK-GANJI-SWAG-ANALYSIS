# Deep Transcript Audit — 241 episodes

Run a full offline MP3/SRT health audit without changing any source files.

## One-time setup

Requires Python 3.10+, FFmpeg and FFprobe on your system PATH, and these locally installed Python packages:

```bash
python -m pip install numpy faster-whisper psutil
```

Verify FFmpeg is available by running `ffmpeg -version` and `ffprobe -version`.

## Run

```bash
python deep_audit.py
```

The script automatically checks episodes 001–241, including full streaming audio decoding, voice detection, subtitle timing and repetition, and speech/caption coverage. It records machine information. The auditor does **not** retranscribe audio and cannot independently confirm exact word accuracy.

Output is written into `all_episodes_audit/` in the repository root:

```text
all_episodes_audit/
├── Logs/                    # Machine inventory, one run log + episode logs
├── Episodes/                # One JSON result per episode
├── Reports/                 # Summary CSV, timestamp flags, overview JSON
└── Review_Package.zip       # Shareable report, not the source audio
```

Interruptions are resumable: rerun `python deep_audit.py` to skip episodes that completed successfully with unchanged inputs. To redo every episode, run `python deep_audit.py --force`.

To override folder locations, optional switches remain available:

```bash
python deep_audit.py --srt-dir "/path/to/urdu_transcript_whisper" --audio-dir "/path/to/all_episodes" --out "/path/to/all_episodes_audit"
```

All audio and transcript processing is local after installation. Reports may contain excerpts of transcripts and your computer's hostname/path information; review before sharing.
