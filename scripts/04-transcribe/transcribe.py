import gc
import logging
import shutil
import os
import tempfile
import time
import traceback
from pathlib import Path
# Allow this entry point to run directly as well as through run.sh.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
from paths import ROOT
os.chdir(ROOT)

import ctranslate2
from crisperwhisper import CrisperWhisperModel
from ct2_decoder_guard import install_decoder_guard

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("crisperwhisper.longform").setLevel(logging.INFO)

MODEL_PATH = os.environ.get("CRISPER_MODEL", "CrisperWhisper2_Large" if Path("CrisperWhisper2_Large").is_dir() else "large")
AUDIO_DIR = Path("all_episodes")
OUTPUT_DIR = Path("urdu_transcript_crisper")
FIRST_EPISODE = int(os.environ.get("FIRST_EPISODE", "1"))
LAST_EPISODE = int(os.environ.get("LAST_EPISODE", str(max(
    (int(p.stem.split("_")[-1]) for p in AUDIO_DIR.glob("episode_*.mp3")
     if p.stem.split("_")[-1].isdigit()), default=FIRST_EPISODE))))
EPISODES = sorted(set(int(n.strip()) for n in os.environ["EPISODES"].split(","))) if os.environ.get("EPISODES") else list(range(FIRST_EPISODE, LAST_EPISODE + 1))

# Subtitle formatting settings
MAX_DURATION = 5.0
MAX_WORDS = 14
MAX_CHARS = 78
PAUSE_THRESHOLD = 0.65

# Avoid overflowing Whisper's 448-token decoder limit on long Urdu episodes.
# First pass retains the original 256-token generation budget but uses less
# previous-text context (4 words instead of CrisperWhisper's default 12).
# If the backend reports a decoder-length error, retry that episode
# with a smaller prompt and generation budget. Completed SRTs are never rerun.
DECODER_PROFILES = [
    (4, 256),   # normal: maximum original decoding budget, shorter context
    (2, 192),   # overflow recovery: reduce both prompt and output budget
    (1, 128),   # last-resort recovery for unusual tokenization
]


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
    if not AUDIO_DIR.is_dir():
        raise SystemExit(f"Audio directory not found: {AUDIO_DIR.resolve()}")
    if ctranslate2.get_cuda_device_count() < 1:
        raise SystemExit("CT2 cannot find a CUDA GPU. Check WSL2 NVIDIA GPU access.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading CT2 model once onto CUDA GPU 0:", MODEL_PATH, flush=True)
    model = CrisperWhisperModel(
        MODEL_PATH,
        backend="ct2",
        device="cuda",
        compute_type="float16",
    )
    install_decoder_guard(model)

    # Exercise the real CT2 path without changing existing subtitle files.
    if os.environ.get("CT2_SMOKE_TEST") == "1":
        import soundfile as sf
        audio_path = AUDIO_DIR / f"episode_{FIRST_EPISODE:03d}.mp3"
        with sf.SoundFile(audio_path) as audio_file:
            sr = audio_file.samplerate
            clip = audio_file.read(frames=sr * 20, dtype="float32")
        if clip.ndim == 2:
            clip = clip.mean(axis=1)
        result = model.transcribe(clip, sr=sr, language="ur", word_timestamps=True)
        words = [w for w in (result.words or []) if w.word and w.word.strip()]
        if not words:
            raise RuntimeError("CT2 smoke test returned no word timestamps")
        print(f"[CT2 TEST OK] {len(words)} words; backend={model.backend}", flush=True)
        print(make_subtitles(words), flush=True)
        return

    completed = 0
    skipped = 0
    missing = 0
    failed = []

    for episode in EPISODES:
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
        audio_temp = tempfile.TemporaryDirectory(prefix="crisper-audio-")
        try:
            local_audio = Path(audio_temp.name) / audio_path.name
            print(f"[AUDIO] Copying {label} to Linux temporary storage", flush=True)
            shutil.copyfile(audio_path, local_audio)
            print(f"[AUDIO] {label} ready; starting transcription", flush=True)
            # Only token-limit errors are retried with safer decoding settings.
            # Each retry starts this ONE episode over; already saved SRTs stay intact.
            result = None
            for attempt, (context_words, max_new_tokens) in enumerate(DECODER_PROFILES, 1):
                try:
                    print(
                        f"[CONFIG] {label}: context_words={context_words}, "
                        f"max_new_tokens={max_new_tokens}",
                        flush=True,
                    )
                    result = model.transcribe(
                        str(local_audio),
                        language="ur",
                        mode="verbatim",
                        word_timestamps=True,
                        longform_strategy="continuation",
                        context_words=context_words,
                        max_new_tokens=max_new_tokens,
                    )
                    break
                except (ValueError, RuntimeError) as exc:
                    # Don't retry other errors: they need investigation.
                    message = str(exc)
                    is_decoder_limit = (
                        "max_target_positions" in message
                        or "No position encodings are defined for positions >= 448" in message
                        or (
                            "decoder_input_ids" in message
                            and "max_new_tokens" in message
                        )
                    )
                    if not is_decoder_limit or attempt == len(DECODER_PROFILES):
                        raise
                    next_context, next_budget = DECODER_PROFILES[attempt]
                    print(
                        f"[RETRY] {label}: decoder token limit reached; "
                        f"retrying this episode with context_words={next_context}, "
                        f"max_new_tokens={next_budget}",
                        flush=True,
                    )
                    gc.collect()
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
            traceback.print_exc()
            failed.append(episode)
            print("Continuing to the next episode; no SRT saved for this failure.", flush=True)
        finally:
            audio_temp.cleanup()

    print(f"\nFinished. New SRTs: {completed}, skipped: {skipped}, missing MP3s: {missing}")
    print(f"Output folder: {OUTPUT_DIR.resolve()}")
    if failed or missing:
        print(f"Failed episodes: {failed}; missing MP3s: {missing}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()