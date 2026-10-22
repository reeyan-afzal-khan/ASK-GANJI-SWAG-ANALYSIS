#!/usr/bin/env bash
set -euo pipefail

# Keep model, input audio and output paths relative to this script.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

python3 - <<'PY'
import gc
import os
import tempfile
import time
from pathlib import Path

import torch
from crisperwhisper import CrisperWhisperModel

MODEL_PATH = Path("CrisperWhisper2_Large")
AUDIO_DIR = Path("all_episodes")
OUTPUT_DIR = Path("urdu_transcript_crisper")
FIRST_EPISODE = 3
LAST_EPISODE = 241

# Subtitle formatting settings
MAX_DURATION = 5.0
MAX_WORDS = 14
MAX_CHARS = 78
PAUSE_THRESHOLD = 0.65


def timestamp(seconds):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def wrap_text(text, max_width=42):
    lines = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def make_subtitles(words):
    segments = []
    current = []
    character_count = 0

    for index, word in enumerate(words):
        current.append(word)
        character_count += len(word.word) + 1
        duration = current[-1].end - current[0].start
        next_word = words[index + 1] if index + 1 < len(words) else None
        pause = (next_word is not None
                 and next_word.start - word.end > PAUSE_THRESHOLD)
        end_of_sentence = word.word.strip().endswith((".", "!", "?", "۔", "؟"))

        if (duration >= MAX_DURATION
            or len(current) >= MAX_WORDS
            or character_count >= MAX_CHARS
            or pause
            or (end_of_sentence and len(current) >= 3)):
            segments.append(current)
            current = []
            character_count = 0

    if current:
        segments.append(current)

    entries = []
    for number, segment in enumerate(segments, start=1):
        start_ms = max(0, round(segment[0].start * 1000))
        end_ms = max(start_ms + 100, round(segment[-1].end * 1000))
        text = wrap_text(" ".join(w.word.strip() for w in segment))
        entries.append(
            f"{number}\n"
            f"{timestamp(start_ms / 1000)} --> {timestamp(end_ms / 1000)}\n"
            f"{text}\n\n"
        )
    return "".join(entries)


def save_atomically(destination, contents):
    """Only publish a completed SRT; never leave a truncated .srt on Ctrl+C."""
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.stem}.", suffix=".tmp", delete=False
        ) as handle:
            tmp_name = handle.name
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def main():
    if not MODEL_PATH.is_dir():
        raise SystemExit(f"Model directory not found: {MODEL_PATH.resolve()}")
    if not AUDIO_DIR.is_dir():
        raise SystemExit(f"Audio directory not found: {AUDIO_DIR.resolve()}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA not found. Check your Jetson GPU/PyTorch setup.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.backends.cuda.matmul.allow_tf32 = True
    print("Loading model once onto:", torch.cuda.get_device_name(0), flush=True)
    model = CrisperWhisperModel(
        str(MODEL_PATH.resolve()),
        backend="transformers",
        device="cuda",
        compute_type="float16",
    )

    completed = 0
    skipped = 0
    missing = 0

    for episode in range(FIRST_EPISODE, LAST_EPISODE + 1):
        label = f"episode_{episode:03d}"
        audio_path = AUDIO_DIR / f"{label}.mp3"
        srt_path = OUTPUT_DIR / f"{label}.srt"

        # Resume: an existing, nonempty .srt is considered complete.
        if srt_path.is_file() and srt_path.stat().st_size > 0:
            print(f"[SKIP] {label}: already completed", flush=True)
            skipped += 1
            continue

        if not audio_path.is_file():
            print(f"[MISSING] {audio_path}", flush=True)
            missing += 1
            continue

        print(f"[START] {audio_path}", flush=True)
        started = time.perf_counter()
        try:
            with torch.inference_mode():
                result = model.transcribe(
                    str(audio_path),
                    language="ur",
                    mode="verbatim",
                    word_timestamps=True,
                    longform_strategy="continuation",
                )
            words = [w for w in (result.words or []) if w.word and w.word.strip()]
            if not words:
                raise RuntimeError("No word timestamps returned; SRT not created")

            # Writing and replacing happen as one operation from the reader's view.
            save_atomically(srt_path, make_subtitles(words))
            completed += 1
            print(f"[DONE] {srt_path} ({time.perf_counter() - started:.1f}s)", flush=True)

            del result, words
            gc.collect()
        except KeyboardInterrupt:
            print(f"\n[INTERRUPTED] {label} not saved. Rerun script to retry it.", flush=True)
            raise SystemExit(130)
        except Exception as exc:
            print(f"[ERROR] {label}: {exc}", flush=True)
            print("Stopping; rerun this script to retry the unfinished episode.", flush=True)
            raise SystemExit(1)

    print(f"\nFinished. New SRTs: {completed}, skipped: {skipped}, missing MP3s: {missing}")
    print(f"Output folder: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
PY
