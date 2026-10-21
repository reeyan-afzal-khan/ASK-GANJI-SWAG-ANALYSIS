#!/usr/bin/env python3
"""Resumable, full-corpus Whisper retranscription into Roman Urdu / English SRT.

Place beside:
    all_episodes/episode_001.mp3 .. episode_241.mp3
    urdu_transcript_whisper/episode_001.srt .. episode_241.srt

Run: python repair_transcripts.py

Uses local GPU-capable openai-whisper and uroman. Optionally uses urdunlp for
more natural Roman Urdu spelling when installed. It never modifies original
MP3s, subtitles, old audit results, or old pilot results.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "2.0.1"
# Keep ASR cache keys compatible with previously processed version 2.0.0 chunks.
ASR_CACHE_VERSION = "2.0.0"
ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "all_episodes"
ORIGINAL_DIR = ROOT / "urdu_transcript_whisper"
OUTPUT_DIR = ROOT / "all_episodes_repaired"
ARABIC_CHAR = r"[\u0600-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
DEVANAGARI_CHAR = r"[\u0900-\u097f]"
ARABIC_RUN = re.compile(rf"{ARABIC_CHAR}+(?:[ \t]+{ARABIC_CHAR}+)*")
DEVANAGARI_RUN = re.compile(rf"{DEVANAGARI_CHAR}+(?:[ \t]+{DEVANAGARI_CHAR}+)*")
SCRIPT_CHUNKS = re.compile(rf"({ARABIC_CHAR}+(?:[ \t]+{ARABIC_CHAR}+)*|{DEVANAGARI_CHAR}+(?:[ \t]+{DEVANAGARI_CHAR}+)*)")
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
PUNCT = str.maketrans({"،": ",", "؛": ";", "؟": "?", "۔": ".", "ـ": ""})


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fmt(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_text(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path: Path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def command_out(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr).strip()[:1600]
    except Exception as exc:
        return str(exc)


def audio_duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True, timeout=90)
    if p.returncode:
        raise RuntimeError(f"ffprobe failed: {p.stderr[-900:]}")
    duration = float(p.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid duration {duration}: {path}")
    return duration


def decode_slice(path: Path, start: float, seconds: float):
    """Decode only a small bounded audio window to 16 kHz mono float32."""
    import numpy as np
    p = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(path), "-t", f"{seconds:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_f32le",
        "-f", "f32le", "pipe:1"], capture_output=True,
        timeout=max(180, int(seconds * 6)))
    if p.returncode:
        raise RuntimeError(f"FFmpeg decode failed: {p.stderr[-900:].decode(errors='replace')}")
    arr = np.frombuffer(p.stdout, dtype="<f4").copy()
    if not len(arr):
        raise RuntimeError("Decoded audio is empty")
    return arr


def fingerprint(path: Path):
    stat = path.stat()
    return {"name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def csv_dump(path: Path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


class Romanizer:
    """Keep English in Latin. Convert Urdu and Devanagari to Latin.

    urdunlp (optional) produces more natural Roman Urdu. When it is not
    installed, uroman is a reliable script transliterator, but the phonetic
    spelling may not match conversational Roman Urdu conventions.
    """
    def __init__(self):
        import uroman
        self.universal = uroman.Uroman()
        self.urdu_to_roman = None
        self.engine = "uroman_only"
        try:
            from urdunlp import transliterate_to_roman
        except ImportError:
            pass  # The GitHub-only installation is not required to run.
        else:
            self.urdu_to_roman = transliterate_to_roman
            self.engine = "urdunlp_plus_uroman"

    @staticmethod
    def needs_romanization(text: str) -> bool:
        return any(unicodedata.category(c).startswith("L") and
                   not unicodedata.name(c, "").startswith("LATIN") for c in text)

    def convert(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text).translate(DIGITS).translate(PUNCT)
        parts = SCRIPT_CHUNKS.split(text)
        out = []
        for part in parts:
            if not part:
                continue
            if ARABIC_RUN.fullmatch(part):
                if self.urdu_to_roman is not None:
                    out.append(self.urdu_to_roman(part))
                else:
                    out.append(self.universal.romanize_string(part, lcode="urd"))
            elif DEVANAGARI_RUN.fullmatch(part):
                out.append(self.universal.romanize_string(part, lcode="hin"))
            elif self.needs_romanization(part):
                out.append(self.universal.romanize_string(part))
            else:
                out.append(part)  # Preserve spoken English words.
        roman = "".join(out).translate(DIGITS).translate(PUNCT)
        if self.needs_romanization(roman):
            roman = self.universal.romanize_string(roman)
        roman = " ".join(roman.split())
        if self.needs_romanization(roman):
            bad = sorted({c for c in roman if self.needs_romanization(c)})
            raise RuntimeError(f"Unromanized characters remain: {bad!r}, input={text[:120]!r}")
        return roman


def setup_logger(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("repair_full")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    log.addHandler(stream)
    return log


def machine_info(torch, model, args):
    info = {
        "timestamp_utc": utc(), "script_version": VERSION,
        "platform": platform.platform(), "python": sys.version,
        "model": model, "language_mode": args.language_mode,
        "chunk_seconds": args.chunk_seconds, "padding_seconds": args.padding_seconds,
        "word_timestamps": not args.no_word_timestamps,
        "torch_version": torch.__version__, "cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "ffmpeg": command_out(["ffmpeg", "-version"]).splitlines()[0],
        "ffprobe": command_out(["ffprobe", "-version"]).splitlines()[0],
        "free_disk_gb": round(shutil.disk_usage(ROOT).free / 1e9, 2),
    }
    if torch.cuda.is_available():
        info["gpu_name"] = torch.cuda.get_device_name(0)
        info["cuda_device_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 2)
    except ImportError:
        pass
    return info


def determine_language(whisper, model, audio, ep: int, mode: str):
    """Whisper confuses Urdu with Hindi. Decode Hindi/Urdu candidates as Urdu.

    English-majority windows are decoded with English to avoid corrupting long
    passages of English (seen in the partial pilot for episode 125).
    """
    if mode == "urdu":
        return "ur", {}
    if mode == "english":
        return "en", {}
    import numpy as np
    # Use up to 30 seconds near the centre, not exclusively an intro/silence.
    width = min(len(audio), 30 * 16000)
    st = max(0, (len(audio) - width) // 2)
    sample = audio[st:st + width]
    mel = whisper.log_mel_spectrogram(np.ascontiguousarray(sample), n_mels=model.dims.n_mels)
    mel = whisper.pad_or_trim(mel, 3000).to(model.device)
    _, probs = model.detect_language(mel)
    probs = probs[0]
    scores = {language: round(float(probs.get(language, 0.0)), 4) for language in ("en", "ur", "hi")}
    # Episode 1 is predominantly English; the heuristic still works normally.
    # An Urdu+Hindi majority is intentionally never decoded as Hindi.
    eng, hindustani = scores["en"], scores["hi"] + scores["ur"]
    chosen = "en" if eng >= 0.50 and eng > hindustani * 1.2 else "ur"
    return chosen, scores


def raw_cues_from_result(result, offset, core_start, core_end, use_words):
    """Keep speech in the non-overlapping core; padding is context, not output."""
    cues = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        words = seg.get("words") or [] if use_words else []
        if words:
            current = []
            for w in words:
                w_start, w_end = offset + float(w["start"]), offset + float(w["end"])
                midpoint = (w_start + w_end) / 2
                if not core_start <= midpoint < core_end:
                    continue
                token = w["word"]
                if not token.strip():
                    continue
                new_chars = len("".join(x[2] for x in current)) + len(token)
                if current and (w_end - current[0][0] > 5.5 or new_chars > 94 or
                                len(current) >= 16 or w_start - current[-1][1] > 1.2):
                    cues.append({"start": max(core_start, current[0][0]),
                                 "end": min(core_end, current[-1][1]),
                                 "text": "".join(x[2] for x in current).strip()})
                    current = []
                current.append((w_start, w_end, token))
            if current:
                cues.append({"start": max(core_start, current[0][0]),
                             "end": min(core_end, current[-1][1]),
                             "text": "".join(x[2] for x in current).strip()})
        else:
            a, b = offset + float(seg["start"]), offset + float(seg["end"])
            if b > core_start and a < core_end and core_start <= (a + b) / 2 < core_end:
                cues.append({"start": max(core_start, a), "end": min(core_end, b),
                             "text": text})
    return [c for c in cues if c["end"] > c["start"] and c["text"]]


def repetition_flags(cues):
    issues = []
    last, count, start = "", 0, 0
    for cue in list(cues) + [{"start": -1, "text": ""}]:
        normalized = re.sub(r"\W+", "", cue["text"].casefold())
        if normalized and len(normalized) >= 7 and normalized == last:
            count += 1
        else:
            if count >= 4:
                issues.append({"code": "repeated_adjacent_captions",
                               "start": start, "count": count, "sample": last[:100]})
            last, count, start = normalized, 1, cue["start"]
    return issues


def config_key(args, ep, audio_fp):
    fields = {
        "script": ASR_CACHE_VERSION, "model": args.model, "mode": args.language_mode,
        "chunk": args.chunk_seconds, "pad": args.padding_seconds,
        "word_timestamps": not args.no_word_timestamps,
        "episode": ep, "audio": audio_fp,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def save_srt(path, cues, column="roman"):
    blocks = []
    for cue in cues:
        text = cue.get(column, "").strip()
        if not text or cue["end"] <= cue["start"]:
            continue
        blocks.append(f"{len(blocks) + 1}\n{fmt(cue['start'])} --> {fmt(cue['end'])}\n{text}\n")
    write_text(path, "\n".join(blocks))


def report_update(output: Path):
    rows, flags = [], []
    for path in sorted((output / "Episodes").glob("episode_*.json")):
        try:
            x = read_json(path)
        except (ValueError, OSError):
            continue
        rows.append({key: x.get(key) for key in (
            "episode", "status", "duration_seconds", "chunks_total", "chunks_complete",
            "subtitle_cues", "english_chunks", "urdu_chunks", "hindi_detected_chunks",
            "low_logprob_segments", "repetitive_segments", "duration_runtime_seconds",
            "roman_srt", "message")})
        for f in x.get("flags", []):
            flags.append({"episode": x.get("episode"), **f})
    csv_dump(output / "Reports" / "episodes.csv", rows,
             ["episode", "status", "duration_seconds", "chunks_total", "chunks_complete",
              "subtitle_cues", "english_chunks", "urdu_chunks", "hindi_detected_chunks",
              "low_logprob_segments", "repetitive_segments", "duration_runtime_seconds",
              "roman_srt", "message"])
    csv_dump(output / "Reports" / "quality_flags.csv", flags,
             ["episode", "code", "start", "count", "sample"])
    counts = Counter(r["status"] for r in rows)
    write_json(output / "Reports" / "overview.json", {
        "generated_utc": utc(), "version": VERSION, "status_counts": dict(counts),
        "episode_rows": len(rows), "quality_flags": len(flags),
        "disclaimer": "ASR logs and repetition flags are NOT ground truth or WER.",
    })


def archive_results(output: Path, log):
    """No MP3s and no individual chunk cache in the shareable package."""
    archive = output / "Review_Package.zip"
    tmp = output / "Review_Package.zip.tmp"
    if tmp.exists():
        tmp.unlink()
    include = [output / "Logs" / "machine_info.json"]
    include += sorted((output / "Episodes").glob("episode_*.json"))
    include += sorted((output / "Reports").glob("*"))
    include += sorted((output / "Roman_Urdu_SRT").glob("episode_*.srt"))
    include += sorted((output / "Raw_Model_SRT").glob("episode_*.srt"))
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in include:
            if path.is_file():
                z.write(path, path.relative_to(output))
    os.replace(tmp, archive)
    log.info("Review package saved: %s (%.1f MB)", archive, archive.stat().st_size / 1e6)


def process_episode(ep, args, whisper, model, romanizer, log, out):
    audio = AUDIO_DIR / f"episode_{ep:03}.mp3"
    previous = ORIGINAL_DIR / f"episode_{ep:03}.srt"
    status_path = out / "Episodes" / f"episode_{ep:03}.json"
    episode_log_path = out / "Logs" / f"episode_{ep:03}.log"
    chunk_dir = out / "Chunks" / f"episode_{ep:03}"
    roman_path = out / "Roman_Urdu_SRT" / f"episode_{ep:03}.srt"
    raw_path = out / "Raw_Model_SRT" / f"episode_{ep:03}.srt"

    def note(message):
        log.info("[%03d] %s", ep, message)
        with episode_log_path.open("a", encoding="utf-8") as f:
            f.write(f"{utc()} {message}\n")

    if not audio.is_file():
        write_json(status_path, {"episode": ep, "status": "missing_audio", "message": str(audio)})
        note("Missing audio: skipping")
        return
    if not previous.is_file():
        note("WARNING: original subtitle missing, but new transcription can proceed")
    started = time.monotonic()
    duration = audio_duration(audio)
    audio_fp = fingerprint(audio)
    key = config_key(args, ep, audio_fp)
    chunks_total = math.ceil(duration / args.chunk_seconds)
    if not args.force and status_path.is_file():
        old = read_json(status_path)
        if (old.get("status") == "completed" and old.get("config_key") == key
                and roman_path.is_file() and raw_path.is_file()
                and old.get("romanizer") == romanizer.engine):
            note("Already completed; skipping")
            return
    if args.force and chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    note(f"Starting audio={duration/60:.1f}m chunks={chunks_total} model={args.model}")
    language_stats = Counter()
    low_logprob = 0
    repetitive_segments = 0
    all_cues = []
    try:
        for i in range(chunks_total):
            core_start = i * args.chunk_seconds
            core_end = min(duration, (i + 1) * args.chunk_seconds)
            pad_start = max(0, core_start - args.padding_seconds)
            pad_end = min(duration, core_end + args.padding_seconds)
            c_path = chunk_dir / f"chunk_{i:05}.json"
            chunk = None
            if not args.force and c_path.exists():
                try:
                    candidate = read_json(c_path)
                    if candidate.get("config_key") == key and candidate.get("chunk_index") == i:
                        chunk = candidate
                except (ValueError, OSError):
                    pass
            if chunk is None:
                t0 = time.monotonic()
                audio_slice = decode_slice(audio, pad_start, pad_end - pad_start)
                language, probabilities = determine_language(
                    whisper, model, audio_slice, ep, args.language_mode)
                result = model.transcribe(
                    audio_slice, language=language, task="transcribe", verbose=False,
                    condition_on_previous_text=False, temperature=(0, 0.2, 0.4),
                    beam_size=5, compression_ratio_threshold=2.4,
                    logprob_threshold=-1.0, no_speech_threshold=0.6,
                    word_timestamps=not args.no_word_timestamps,
                    hallucination_silence_threshold=(2.0 if not args.no_word_timestamps else None),
                    fp16=(str(model.device).startswith("cuda")),
                )
                original_cues = raw_cues_from_result(
                    result, pad_start, core_start, core_end, not args.no_word_timestamps)
                # Cache only the raw ASR cues. Roman Urdu formatting is a
                # separate, repeatable step and never requires re-transcription.
                cues = original_cues
                segment_stats = [{
                    "start": round(pad_start + float(s["start"]), 3),
                    "text": (s.get("text") or "")[:240],
                    "avg_logprob": round(float(s.get("avg_logprob", 0)), 4),
                    "compression_ratio": round(float(s.get("compression_ratio", 0)), 3),
                    "no_speech_prob": round(float(s.get("no_speech_prob", 0)), 4),
                } for s in result.get("segments", [])]
                chunk = {
                    "config_key": key, "chunk_index": i, "core_start": core_start,
                    "core_end": core_end, "window_start": pad_start, "window_end": pad_end,
                    "decoder_language": language, "detected_probabilities": probabilities,
                    "decoded_segments": segment_stats, "cues": cues,
                    "runtime_seconds": round(time.monotonic() - t0, 2), "created_utc": utc(),
                }
                write_json(c_path, chunk)
                note(f"chunk {i+1}/{chunks_total} {fmt(core_start)} -> {fmt(core_end)} "
                     f"language={language} probabilities={probabilities} "
                     f"cues={len(cues)} seconds={chunk['runtime_seconds']}")
            # Romanization is a postprocessing step: regenerate from cached
            # raw text, so changing/adding urdunlp never reruns the CUDA ASR.
            for cue in chunk["cues"]:
                roman_text = romanizer.convert(cue["text"])
                if roman_text:
                    all_cues.append({**cue, "roman": roman_text})
            language_stats[chunk["decoder_language"]] += 1
            if chunk.get("detected_probabilities", {}).get("hi", 0) > max(
                chunk.get("detected_probabilities", {}).get("ur", 0),
                chunk.get("detected_probabilities", {}).get("en", 0)):
                language_stats["hi_detected"] += 1
            for seg in chunk.get("decoded_segments", []):
                if seg.get("avg_logprob", 0) < -1.0:
                    low_logprob += 1
                if seg.get("compression_ratio", 0) > 2.4:
                    repetitive_segments += 1
        all_cues.sort(key=lambda x: (x["start"], x["end"]))
        save_srt(roman_path, all_cues, "roman")
        save_srt(raw_path, all_cues, "text")
        bad = repetition_flags(all_cues)
        info = {
            "episode": ep, "status": "completed", "created_utc": utc(),
            "config_key": key, "model": args.model, "mode": args.language_mode,
            "romanizer": romanizer.engine,
            "audio_fingerprint": audio_fp, "duration_seconds": round(duration, 3),
            "chunks_total": chunks_total, "chunks_complete": chunks_total,
            "subtitle_cues": len(all_cues), "english_chunks": language_stats["en"],
            "urdu_chunks": language_stats["ur"],
            "hindi_detected_chunks": language_stats["hi_detected"],
            "low_logprob_segments": low_logprob, "repetitive_segments": repetitive_segments,
            "flags": bad[:100], "duration_runtime_seconds": round(time.monotonic()-started, 1),
            "roman_srt": str(roman_path.relative_to(out)),
            "raw_model_srt": str(raw_path.relative_to(out)),
            "original_srt_present": previous.is_file(),
        }
        write_json(status_path, info)
        note(f"COMPLETED {len(all_cues)} subtitles; {len(bad)} repeated-text flags; "
             f"elapsed {info['duration_runtime_seconds']:.0f}s")
    except Exception as exc:
        done = sum(1 for p in chunk_dir.glob("chunk_*.json")
                   if p.is_file() and read_json(p).get("config_key") == key)
        write_json(status_path, {
            "episode": ep, "status": "interrupted_or_failed", "message": str(exc),
            "config_key": key, "duration_seconds": duration,
            "chunks_total": chunks_total, "chunks_complete": done,
            "traceback": traceback.format_exc()[-5000:], "updated_utc": utc(),
        })
        note(f"FAILED after {done}/{chunks_total} chunks: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser(description="All 241 episodes -> Roman Urdu + English SRT; local and resumable")
    parser.add_argument("--model", default="large-v3", choices=["large-v3", "turbo"],
                        help="Default large-v3 for full-quality ASR; turbo is faster")
    parser.add_argument("--language-mode", choices=["adaptive", "urdu", "english"], default="adaptive",
                        help="Adaptive = English if dominant, otherwise force Urdu (never Hindi)")
    parser.add_argument("--chunk-seconds", type=int, default=60)
    parser.add_argument("--padding-seconds", type=float, default=1.25)
    parser.add_argument("--offline", action="store_true", help="Never download model weights")
    parser.add_argument("--no-word-timestamps", action="store_true", help="Faster, coarser SRT timing")
    parser.add_argument("--force", action="store_true", help="Recompute all chunks from scratch")
    args = parser.parse_args()
    if not 20 <= args.chunk_seconds <= 240:
        parser.error("--chunk-seconds must be between 20 and 240")
    if not 0 <= args.padding_seconds <= 5:
        parser.error("--padding-seconds must be between 0 and 5")

    out = OUTPUT_DIR
    for name in ("Logs", "Episodes", "Roman_Urdu_SRT", "Raw_Model_SRT", "Chunks", "Reports"):
        (out / name).mkdir(parents=True, exist_ok=True)
    log = setup_logger(out / "Logs" / "transcription.log")
    if not AUDIO_DIR.is_dir():
        raise SystemExit(f"Missing audio folder: {AUDIO_DIR}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe must be available on PATH")
    for name in ("uroman", "whisper"):
        try:
            __import__(name)
        except ImportError as exc:
            raise SystemExit(f"Missing {name}: install with: python -m pip install openai-whisper uroman") from exc
    import torch
    import whisper
    if not torch.cuda.is_available():
        raise SystemExit("PyTorch CUDA is not available; stopping to avoid unexpectedly slow 367-hour CPU run")
    romanizer = Romanizer()
    log.info("Romanizer selected: %s", romanizer.engine)
    if romanizer.engine == "uroman_only":
        log.warning("urdunlp is unavailable; proceeding with uroman. The SRTs will contain only Latin script, but Urdu spelling may be less natural.")
    log.info("Starting full 241-episode offline-capable transcription. Model=%s", args.model)
    info = machine_info(torch, args.model, args)
    info["romanizer"] = romanizer.engine
    write_json(out / "Logs" / "machine_info.json", info)

    if args.offline:
        ckpt = Path(os.path.expanduser("~/.cache/whisper")) / (args.model + ".pt")
        if not ckpt.is_file():
            raise SystemExit(f"Model missing from cache: {ckpt}; run once without --offline")
        log.info("Loading cached model checkpoint: %s", ckpt)
        model = whisper.load_model(str(ckpt), device="cuda")
    else:
        model = whisper.load_model(args.model, device="cuda")
    failed = []
    try:
        for ep in range(1, 242):
            try:
                process_episode(ep, args, whisper, model, romanizer, log, out)
            except KeyboardInterrupt:
                raise
            except Exception:
                failed.append(ep)
                log.exception("Episode %03d failed; moving to next episode", ep)
            finally:
                report_update(out)
    except KeyboardInterrupt:
        log.warning("Interrupted by user. Completed chunks are safely saved. Re-run to resume.")
    finally:
        report_update(out)
        archive_results(out, log)
        log.info("Finished current run. Failed episodes: %s", failed or "none")
        log.info("Re-run the same command to resume. Originals have not been changed.")


if __name__ == "__main__":
    main()
