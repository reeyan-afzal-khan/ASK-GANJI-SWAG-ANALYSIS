#!/usr/bin/env python3
"""Offline-capable, resumable Urdu/English Whisper comparison pilot.

Copy this file into ASK-GANJI-SWAG-ANALYSIS/ next to all_episodes/,
urdu_transcript_whisper/, and all_episodes_audit/. Run:
    python repair_transcripts.py

Models are downloaded once on the first run unless --offline is specified.
Original SRT and MP3 files are NEVER modified. This is a controlled comparison,
not an automatic claim that Whisper's new text is correct.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VERSION = "1.0"
ROOT = Path(__file__).resolve().parent
SRT_ROOT = ROOT / "urdu_transcript_whisper"
MP3_ROOT = ROOT / "all_episodes"
AUDIT_ROOT = ROOT / "all_episodes_audit"
OUTPUT_ROOT = ROOT / "transcript_repair_pilot"
DEFAULT_EPISODES = [35, 113, 125, 163, 216, 230, 241]
CONTROL_EPISODES = [91, 115]  # Routine-rated in the supplied 241-episode audit.
TS_RE = re.compile(r"(\d{2,}):(\d\d):(\d\d)[,.](\d{3})")
SRT_LINE_RE = re.compile(r"(\d{2,}:\d\d:\d\d[,.]\d{3})\s*-->\s*(\d{2,}:\d\d:\d\d[,.]\d{3})")
MUSIC_RE = re.compile(r"^\W*(?:موسیقی|music|applause|clapping)\W*$", re.I)
ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f]")
LATIN_RE = re.compile(r"[A-Za-z]")
PARAMETERS = {
    "task": "transcribe", "condition_on_previous_text": False,
    "temperature": (0.0, 0.2, 0.4), "beam_size": 5,
    "compression_ratio_threshold": 2.4,
    "logprob_threshold": -1.0, "no_speech_threshold": 0.6,
    "word_timestamps": False,
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ts(seconds, sep="."):
    ms = round(max(0.0, float(seconds)) * 1000)
    h, rest = divmod(ms, 3600_000)
    m, rest = divmod(rest, 60_000)
    s, milli = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{milli:03}"


def sec(value):
    match = TS_RE.search(str(value))
    if not match:
        raise ValueError(f"Unrecognized timestamp: {value!r}")
    h, m, s, milli = map(int, match.groups())
    return 3600 * h + 60 * m + s + milli / 1000


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def save_json(path, obj):
    atomic_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def csv_write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def read_subtitles(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        for idx, line in enumerate(lines[:3]):
            match = SRT_LINE_RE.search(line)
            if match:
                a, b = sec(match.group(1)), sec(match.group(2))
                if b >= a:
                    cues.append({"start": a, "end": b, "text": " ".join(lines[idx + 1:])})
                break
    return cues


def original_excerpt(cues, start, end):
    overlaps = [c for c in cues if c["end"] > start and c["start"] < end]
    return {
        "cue_count": len(overlaps),
        "text": " ".join(c["text"] for c in overlaps).strip(),
        "cues": [{"start": ts(c["start"]), "end": ts(c["end"]), "text": c["text"]} for c in overlaps],
    }


def audio_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if proc.returncode:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[-600:]}")
    return float(proc.stdout.strip())


def sample_audio(path, start, seconds):
    """Precisely seek one short piece of audio; never load the whole MP3."""
    import numpy as np
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}",
           "-i", str(path), "-t", f"{seconds:.3f}", "-vn", "-ac", "1", "-ar", "16000",
           "-acodec", "pcm_f32le", "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(120, int(seconds * 5)))
    if proc.returncode:
        raise RuntimeError(f"ffmpeg decode failed: {proc.stderr[-600:].decode(errors='replace')}")
    result = np.frombuffer(proc.stdout, dtype="<f4").copy()
    if len(result) < 16000:
        raise RuntimeError("Audio clip is unexpectedly shorter than one second")
    return result


def range_candidates(ep, duration, flags, clip_seconds):
    """Prefer repeated hallucination-like spans and text corruption, avoid music."""
    cands = []
    for fl in flags:
        if int(fl.get("episode") or -1) != ep:
            continue
        try:
            start = sec(fl["start"])
        except (ValueError, KeyError):
            continue
        issue = fl.get("issue", "")
        if issue == "near_identical_cue_run":
            if MUSIC_RE.match(fl.get("text", "").strip()):
                continue
            match = re.search(r"through\s+(\d+:\d\d:\d\d[.,]\d{3})", fl.get("details", ""))
            try:
                last = sec(match.group(1)) if match else sec(fl["end"])
            except ValueError:
                last = start + clip_seconds
            span = last - start
            if span >= 100:
                cands.extend((start + span * pct, 1000 - j * 25, "long_repeated_subtitle_run")
                             for j, pct in enumerate((0.22, 0.72)))
            else:
                cands.append((start + min(span / 2, 10), 520, "repeated_subtitle_run"))
        elif issue == "encoding_replacement_character":
            cands.append((start, 640, "corrupted_unicode"))
        elif issue == "detected_speech_without_caption":
            cands.append((start, 450, "speech_without_subtitle"))
        elif issue == "caption_without_detected_voice":
            cands.append((start, 220, "caption_without_voice"))
        elif issue in ("implausible_character_rate", "cue_under_100ms"):
            # Estimate the density of anomalies within each candidate 45-second window.
            cands.append((start, 160 if issue == "implausible_character_rate" else 50, issue))
    # Normal speech control for every selected episode; controls never include ep 001.
    cands.extend([(duration * 0.35, 35, "general_position_check"),
                  (duration * 0.65, 34, "general_position_check"),
                  (duration * 0.85, 33, "general_position_check")])
    return cands


def choose_samples(ep, duration, flags, clip_len, count, control=False):
    usable_len = min(clip_len, duration)
    raw = range_candidates(ep, duration, [] if control else flags, usable_len)
    windows = []
    for anchor, weight, label in raw:
        start = max(0.0, min(duration - usable_len, anchor - usable_len / 2))
        windows.append({"start": round(start, 3), "seconds": round(usable_len, 3),
                        "reason": label, "weight": weight})
    # A dense cluster of tiny subtitles may matter more than one random glitch.
    for item in windows:
        if item["reason"] in {"implausible_character_rate", "cue_under_100ms"}:
            close = sum(1 for other in windows if other["reason"] in
                        {"implausible_character_rate", "cue_under_100ms"} and
                        abs(other["start"] - item["start"]) < clip_len / 2)
            item["weight"] += min(200, close * 2)
    windows.sort(key=lambda x: (-x["weight"], x["start"]))
    chosen = []
    for item in windows:
        if all(abs(item["start"] - prev["start"]) >= usable_len * 0.85 for prev in chosen):
            chosen.append(item)
        if len(chosen) >= count:
            break
    # Some episodes have few diagnostic flags; sample a spread across the recording.
    if len(chosen) < count:
        for frac in (0.1, 0.4, 0.7, 0.9, 0.0):
            start = round(max(0.0, (duration - usable_len) * frac), 3)
            if all(abs(start - p["start"]) >= usable_len * 0.85 for p in chosen):
                chosen.append({"start": start, "seconds": round(usable_len, 3),
                               "reason": "distributed_control", "weight": 0})
                if len(chosen) >= count:
                    break
    chosen = sorted(chosen, key=lambda x: x["start"])[:count]
    for i, x in enumerate(chosen, 1):
        x["clip_id"] = f"clip_{i:02}"
        x.pop("weight", None)
        x["episode"] = ep
        x["start_clock"] = ts(x["start"])
        x["end_clock"] = ts(x["start"] + x["seconds"])
        x["control_episode"] = control
    return chosen


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_id(model, mode, clip, mp3_path, srt_path, whisper_version):
    st = mp3_path.stat()
    ss = srt_path.stat()
    data = {"version": VERSION, "model": model, "mode": mode,
            "clip": clip, "parameters": PARAMETERS, "whisper": whisper_version,
            "mp3_stat": [st.st_size, st.st_mtime_ns], "srt_stat": [ss.st_size, ss.st_mtime_ns]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def text_stats(text):
    letters = ARABIC_RE.findall(text)
    latin = LATIN_RE.findall(text)
    all_letters = len(letters) + len(latin)
    words = text.split()
    trigrams = [tuple(words[i:i + 3]) for i in range(max(0, len(words) - 2))]
    most = Counter(trigrams).most_common(1)
    return {
        "word_count": len(words),
        "latin_letters": len(latin), "urdu_letters": len(letters),
        "latin_letter_fraction": round(len(latin) / max(1, all_letters), 3),
        "repeated_trigram_fraction": round(most[0][1] / len(trigrams), 3) if most else 0,
        "replacement_characters": text.count("\ufffd"),
    }


def model_cache_location(model, whisper, cache):
    if model not in whisper.available_models():
        raise ValueError(f"Unknown model {model}. Available: {whisper.available_models()}")
    url = whisper._MODELS[model]
    path = cache / Path(urlparse(url).path).name
    sha = url.rstrip("/").split("/")[-2]
    return path, sha


def ensure_cached(model, whisper, cache, offline):
    path, expected_sha = model_cache_location(model, whisper, cache)
    if path.exists() and sha_file(path) == expected_sha:
        return path
    if offline:
        raise RuntimeError(f"Offline mode: missing or corrupt model {model}: {path}. "
                           "Download once using --download-only with internet access.")
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Downloading/verifying model {model} in {cache} (requires internet only this first time)...", flush=True)
    whisper._download(whisper._MODELS[model], str(cache), in_memory=False)
    if not path.is_file() or sha_file(path) != expected_sha:
        raise RuntimeError(f"Model download checksum validation failed: {model}")
    return path


def make_review_audio_samples(output, manifest, log):
    """Low-bitrate excerpts for actually listening to transcription candidates.

    These are NEVER full episodes. Each excerpt is taken from an input MP3;
    existing source files are only read, never changed.
    """
    successes = 0
    for c in manifest:
        mp3 = MP3_ROOT / f"episode_{c['episode']:03}.mp3"
        dest = output / "Audio_Samples" / f"episode_{c['episode']:03}" / f"{c['clip_id']}.mp3"
        if dest.exists() and dest.stat().st_size > 1500:
            successes += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".temp.mp3")
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
               "-ss", f"{c['start']:.3f}", "-i", str(mp3), "-t", f"{c['seconds']:.3f}",
               "-vn", "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "64k", str(tmp)]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=160)
            if result.returncode or not tmp.is_file() or tmp.stat().st_size < 1500:
                raise RuntimeError(result.stderr[-500:].decode(errors="replace"))
            os.replace(tmp, dest)
            successes += 1
        except Exception as exc:
            log.warning("Could not export review clip %s / %s: %s", c['episode'], c['clip_id'], exc)
            tmp.unlink(missing_ok=True)
    log.info("Audio excerpts for review: %d/%d", successes, len(manifest))


def package_results(output, include_audio=True):
    """Copy transcripts/logs and optionally short review MP3 excerpts, never full audio."""
    target = output / "Review_Package.zip"
    tmp = output / "Review_Package.zip.tmp"
    folders = [output / "Reports", output / "Clips", output / "Logs"]
    if include_audio:
        folders.append(output / "Audio_Samples")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for folder in folders:
            if folder.exists():
                for p in sorted(folder.rglob("*")):
                    if p.is_file() and p.suffix.lower() in ({".txt", ".log", ".json", ".csv", ".srt", ".mp3"}
                                                           if include_audio else {".txt", ".log", ".json", ".csv", ".srt"}):
                        archive.write(p, arcname=p.relative_to(output).as_posix())
        archive.writestr("READ_ME_FIRST.txt", "Whisper comparison pilot; originals are untouched.\n"
                         "Contains transcript snippets, machine information and "
                         + ("short MP3 excerpts (not full episodes).\n" if include_audio else "no audio.\n")
                         + "IMPORTANT: No reference transcript was collected automatically;\n"
                         "similarity and agreement ARE NOT accuracy or WER measurements.\n"
                         "Review log files for private path information before sharing.\n")
    os.replace(tmp, target)
    return target


def display_comparison(result_dir, ep, clip, results_for_clip):
    lines = [f"EPISODE {ep:03} / {clip['clip_id']} | {clip['start_clock']} --> {clip['end_clock']}",
             f"Selection: {clip['reason']}", "", "=== ORIGINAL WHISPER SRT (UNVERIFIED) ===",
             clip["original"]["text"] or "[empty]", ""]
    for (model, mode), result in sorted(results_for_clip.items()):
        lines += [f"=== {model} / {mode} / {result.get('status', '?')} ===",
                  result.get("text", "") or "[empty]",
                  f"Detected language: {result.get('detected_language', '?')}",
                  f"Runtime: {result.get('processing_seconds', '?')} seconds", ""]
    atomic_text(result_dir / "comparison.txt", "\n".join(lines) + "\n")


def to_srt(segments):
    lines = []
    for i, s in enumerate(segments, 1):
        if not s["text"].strip() or s["end"] <= s["start"]:
            continue
        lines.extend([str(i), f"{ts(s['start'], ',')} --> {ts(s['end'], ',')}", s["text"].strip(), ""])
    return "\n".join(lines) + "\n"


def get_logger(output):
    log = logging.getLogger("repair_pilot")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(output / "Logs" / "pilot.log", encoding="utf-8")
    fh.setFormatter(formatter)
    log.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    log.addHandler(ch)
    return log


def snapshot_machine(torch, whisper):
    info = {
        "time_utc": utc_now(), "os": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "torch": torch.__version__,
        "whisper": getattr(whisper, "__version__", "unknown"),
        "cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "total_system_ram_gb": None,
        "free_disk_gb_at_start": round(shutil.disk_usage(ROOT).free / 1e9, 2),
        "script_version": VERSION,
    }
    try:
        import psutil
        info["total_system_ram_gb"] = round(psutil.virtual_memory().total / 1e9, 2)
    except ImportError:
        pass
    return info


def build_manifest(args, all_flags, selected):
    manifest = []
    missing = []
    for ep in selected:
        mp3 = MP3_ROOT / f"episode_{ep:03}.mp3"
        srt = SRT_ROOT / f"episode_{ep:03}.srt"
        if not mp3.is_file() or not srt.is_file():
            missing.append({"episode": ep, "mp3_exists": mp3.is_file(), "srt_exists": srt.is_file()})
            continue
        duration = audio_duration(mp3)
        clips = choose_samples(ep, duration, all_flags, args.clip_seconds,
                               args.control_clips if ep in CONTROL_EPISODES else args.clips_per_episode,
                               control=(ep in CONTROL_EPISODES))
        cues = read_subtitles(srt)
        for item in clips:
            item["original"] = original_excerpt(cues, item["start"], item["start"] + item["seconds"])
            manifest.append(item)
    return manifest, missing


def generate_reports(output, manifest, models, modes):
    rows = []
    manual = []
    # Preserve any notes/ground-truth text a reviewer added before resuming.
    old_reviews = {(str(r.get("episode")), str(r.get("clip"))): r
                   for r in read_csv(output / "Reports" / "manual_review.csv")}
    summary = Counter()
    for c in manifest:
        ep = c["episode"]
        clip_dir = output / "Clips" / f"episode_{ep:03}" / c["clip_id"]
        preds = {}
        for model in models:
            for mode in modes:
                path = clip_dir / f"{model}_{mode}.json"
                if path.exists():
                    try:
                        result = read_json(path)
                    except Exception:
                        continue
                    status = result.get("status", "unknown")
                    summary[status] += 1
                    if status == "completed":
                        preds[(model, mode)] = result
                    stats = result.get("stats", {})
                    rows.append({
                        "episode": ep, "clip": c["clip_id"], "start": c["start_clock"],
                        "end": c["end_clock"], "reason": c["reason"], "model": model,
                        "mode": mode, "status": status, "detected_language": result.get("detected_language", ""),
                        "seconds_to_transcribe": result.get("processing_seconds", ""),
                        "original_words": text_stats(c["original"]["text"])["word_count"],
                        "new_words": stats.get("word_count", ""),
                        "new_latin_fraction": stats.get("latin_letter_fraction", ""),
                        "repeated_trigram_fraction": stats.get("repeated_trigram_fraction", ""),
                        "original_similarity_not_accuracy": result.get("similarity_to_original", ""),
                        "mean_segment_logprob": result.get("mean_segment_logprob", ""),
                        "new_text": result.get("text", ""),
                        "original_text": c["original"]["text"],
                        "error": result.get("error", ""),
                    })
                else:
                    summary["not_run"] += 1
        display_comparison(clip_dir, ep, c, preds)
        manual_row = {"episode": ep, "clip": c["clip_id"], "start": c["start_clock"],
                      "end": c["end_clock"], "reason": c["reason"],
                      "original_text": c["original"]["text"],
                      "manual_verified_text": "", "preferred_candidate": "", "notes": ""}
        for model in models:
            for mode in modes:
                manual_row[f"{model}_{mode}"] = preds.get((model, mode), {}).get("text", "")
        prior_review = old_reviews.get((str(ep), c["clip_id"]), {})
        for editable in ("manual_verified_text", "preferred_candidate", "notes"):
            manual_row[editable] = prior_review.get(editable, "")
        manual.append(manual_row)
    fieldnames = ["episode", "clip", "start", "end", "reason", "model", "mode", "status",
                  "detected_language", "seconds_to_transcribe", "original_words", "new_words",
                  "new_latin_fraction", "repeated_trigram_fraction", "original_similarity_not_accuracy",
                  "mean_segment_logprob", "new_text", "original_text", "error"]
    csv_write(output / "Reports" / "clip_comparisons.csv", rows, fieldnames)
    manual_fields = ["episode", "clip", "start", "end", "reason", "original_text"] + [
        f"{m}_{mode}" for m in models for mode in modes] + ["manual_verified_text", "preferred_candidate", "notes"]
    csv_write(output / "Reports" / "manual_review.csv", manual, manual_fields)
    save_json(output / "Reports" / "pilot_overview.json", {
        "generated_utc": utc_now(), "version": VERSION,
        "episodes": sorted(set(c["episode"] for c in manifest)),
        "clips": len(manifest), "models": models, "language_modes": modes,
        "expected_comparisons": len(manifest) * len(models) * len(modes),
        "comparison_statuses": dict(summary),
        "warning": "These are automated candidates, not verified ground truth. "
                   "Transcription similarity and log probabilities do not measure WER or certify accuracy.",
    })
    return summary


def parse_args():
    p = argparse.ArgumentParser(description="Offline Urdu-English transcription pilot, not a full-corpus repair")
    p.add_argument("--models", default="turbo,large-v3",
                   help="Comma-separated official Whisper models (default turbo,large-v3). Use turbo for a smaller first run")
    p.add_argument("--language-modes", default="auto,ur", choices=["auto", "ur", "auto,ur", "ur,auto"],
                   help="Automatic language detection, forced Urdu, or both")
    p.add_argument("--episodes", default="", help="Optional comma-separated episode numbers (defaults to 7 flagged + 2 controls)")
    p.add_argument("--clips-per-episode", type=int, default=3, help="Problem-episode clips (default 3)")
    p.add_argument("--control-clips", type=int, default=1, help="Clips per healthy control episode (default 1)")
    p.add_argument("--clip-seconds", type=float, default=45.0, help="Duration of each test clip (default 45s)")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--allow-cpu", action="store_true", help="Allow slow CPU transcription explicitly")
    p.add_argument("--download-only", action="store_true", help="Download model weights without running the pilot")
    p.add_argument("--offline", action="store_true", help="Require already cached, checksum-valid models; no download")
    p.add_argument("--plan-only", action="store_true", help="Select clips and write manifest without loading models")
    p.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache" / "whisper",
                   help="Checkpoint directory (default ~/.cache/whisper)")
    p.add_argument("--no-audio-samples", action="store_true",
                   help="Exclude short review MP3 excerpts from the shared ZIP (limits audio accuracy review)")
    p.add_argument("--out", type=Path, default=OUTPUT_ROOT, help="Result directory")
    p.add_argument("--retry-failed", action="store_true", help="Retry previous error results")
    return p.parse_args()


def main():
    args = parse_args()
    if args.clip_seconds < 12 or args.clip_seconds > 100:
        raise SystemExit("--clip-seconds must be between 12 and 100")
    if not (1 <= args.clips_per_episode <= 12 and 1 <= args.control_clips <= 12):
        raise SystemExit("Clip counts must be between 1 and 12")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m.strip() for m in args.language_modes.split(",") if m.strip()]
    if not models or len(models) != len(set(models)):
        raise SystemExit("Choose unique models (e.g. --models turbo,large-v3)")
    out = args.out.expanduser().resolve()
    (out / "Logs").mkdir(parents=True, exist_ok=True)
    (out / "Clips").mkdir(exist_ok=True)
    (out / "Reports").mkdir(exist_ok=True)
    log = get_logger(out)
    log.info("Transcript pilot v%s", VERSION)
    log.info("Models: %s / modes: %s", models, modes)
    if args.download_only:
        import whisper
        for model in models:
            ensure_cached(model, whisper, args.cache_dir, args.offline)
            log.info("Model downloaded/verified: %s", model)
        log.info("Download finished. Next: python repair_transcripts.py --offline")
        return
    if not SRT_ROOT.is_dir() or not MP3_ROOT.is_dir():
        raise SystemExit(f"Missing expected directories. Put this script beside:\n  {SRT_ROOT}\n  {MP3_ROOT}")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg and ffprobe must be installed and visible on PATH")
    if args.episodes.strip():
        try:
            episodes = list(dict.fromkeys(int(v) for v in args.episodes.split(",")))
        except ValueError:
            raise SystemExit("--episodes must be comma-separated integers, e.g. 113,125,216")
        if any(v < 1 or v > 241 for v in episodes):
            raise SystemExit("Episode numbers must be 1..241")
    else:
        episodes = DEFAULT_EPISODES + CONTROL_EPISODES
    flags = read_csv(AUDIT_ROOT / "Reports" / "review_flags.csv")
    log.info("Loaded %s prior-audit flags from %s", len(flags), AUDIT_ROOT)
    manifest, missing = build_manifest(args, flags, episodes)
    if missing:
        log.warning("Missing inputs: %s", missing)
    save_json(out / "Reports" / "clip_manifest.json", {
        "created_utc": utc_now(), "selected_episodes": episodes, "missing_inputs": missing,
        "clips": manifest, "models": models, "language_modes": modes,
        "note": "Selection uses anomalies from all_episodes_audit when available; each clip is independent.",
    })
    if not manifest:
        raise SystemExit("No valid MP3/SRT pairs could be selected")
    log.info("Selected %d clips (~%.1f audio minutes per model/mode).", len(manifest),
             sum(c["seconds"] for c in manifest) / 60)
    if args.plan_only:
        log.info("Plan written: %s", out / "Reports" / "clip_manifest.json")
        return
    import torch
    import whisper
    machine = snapshot_machine(torch, whisper)
    save_json(out / "Logs" / "machine_info.json", machine)
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but torch.cuda.is_available() is False; check your Jetson PyTorch install")
    if device == "cpu" and not args.allow_cpu:
        raise SystemExit("Torch CUDA not found. CPU processing may take a very long time. "
                         "Check torch.cuda.is_available() or pass --allow-cpu to proceed intentionally.")
    log.info("PyTorch %s, device %s, GPU %s", torch.__version__, device, machine["gpu_name"])
    for model in models:
        ensure_cached(model, whisper, args.cache_dir, args.offline)

    # When resuming, only models with missing results are loaded.
    def clip_result_path(c, model, mode):
        return out / "Clips" / f"episode_{c['episode']:03}" / c["clip_id"] / f"{model}_{mode}.json"

    try:
        for model_name in models:
            outstanding = []
            for c in manifest:
                mp3 = MP3_ROOT / f"episode_{c['episode']:03}.mp3"
                srt = SRT_ROOT / f"episode_{c['episode']:03}.srt"
                for mode in modes:
                    sig = checkpoint_id(model_name, mode, c, mp3, srt, getattr(whisper, "__version__", "unknown"))
                    path = clip_result_path(c, model_name, mode)
                    prior = read_json(path) if path.exists() else {}
                    if prior.get("checkpoint_id") == sig and (
                            prior.get("status") == "completed" or
                            (prior.get("status") == "error" and not args.retry_failed)):
                        continue
                    outstanding.append((c, mode, sig))
            if not outstanding:
                log.info("%s already completed; skipping load", model_name)
                continue
            log.info("Loading %s on %s (%d remaining jobs)...", model_name, device, len(outstanding))
            model_obj = whisper.load_model(model_name, device=device, download_root=str(args.cache_dir))
            for idx, (c, mode, sig) in enumerate(outstanding, 1):
                ep = c["episode"]
                job_name = f"episode_{ep:03}/{c['clip_id']}/{model_name}/{mode}"
                job_path = clip_result_path(c, model_name, mode)
                job_path.parent.mkdir(parents=True, exist_ok=True)
                episode_log = out / "Logs" / f"episode_{ep:03}.log"
                beginning = time.monotonic()
                msg = f"[{idx}/{len(outstanding)}] {job_name} {c['start_clock']} - {c['end_clock']}"
                log.info(msg)
                with episode_log.open("a", encoding="utf-8") as e_log:
                    e_log.write(f"{utc_now()} BEGIN {msg}\n")
                try:
                    mp3 = MP3_ROOT / f"episode_{ep:03}.mp3"
                    waveform = sample_audio(mp3, c["start"], c["seconds"])
                    # 'ur' means Urdu language prompting; task=transcribe retains original spoken language.
                    result = model_obj.transcribe(waveform, language=None if mode == "auto" else "ur",
                                                  fp16=(device == "cuda"), verbose=False, **PARAMETERS)
                    segments = []
                    for s in result.get("segments", []):
                        start = max(0.0, float(s.get("start", 0)))
                        end = max(start, float(s.get("end", start)))
                        # Clamp clip-end errors to the actual decoded duration.
                        end = min(end, len(waveform) / 16000)
                        if end <= start:
                            continue
                        segments.append({
                            "start": round(c["start"] + start, 3),
                            "end": round(c["start"] + end, 3),
                            "text": str(s.get("text", "")).strip(),
                            "avg_logprob": s.get("avg_logprob"),
                            "no_speech_prob": s.get("no_speech_prob"),
                            "compression_ratio": s.get("compression_ratio"),
                        })
                    text = " ".join(s["text"] for s in segments).strip()
                    logps = [s["avg_logprob"] for s in segments if isinstance(s.get("avg_logprob"), (float, int))]
                    record = {
                        "status": "completed", "checkpoint_id": sig,
                        "created_utc": utc_now(), "episode": ep, "clip_id": c["clip_id"],
                        "start": c["start_clock"], "end": c["end_clock"], "reason": c["reason"],
                        "model": model_name, "language_mode": mode, "device": device,
                        "detected_language": result.get("language", "unknown"),
                        "text": text, "segments": segments, "stats": text_stats(text),
                        "original_text": c["original"]["text"],
                        "similarity_to_original": round(difflib.SequenceMatcher(
                            None, c["original"]["text"].lower(), text.lower()).ratio(), 3),
                        "mean_segment_logprob": round(sum(logps)/len(logps), 4) if logps else None,
                        "processing_seconds": round(time.monotonic() - beginning, 2),
                    }
                    save_json(job_path, record)
                    atomic_text(job_path.with_suffix(".srt"), to_srt(segments))
                    message = f"completed {job_name} ({record['processing_seconds']}s), words={len(text.split())}, detected={record['detected_language']}"
                    log.info(message)
                    with episode_log.open("a", encoding="utf-8") as e_log:
                        e_log.write(f"{utc_now()} {message}\n")
                except Exception as exc:
                    message = f"FAILED {job_name}: {type(exc).__name__}: {exc}"
                    log.error(message)
                    with episode_log.open("a", encoding="utf-8") as e_log:
                        e_log.write(f"{utc_now()} {message}\n{traceback.format_exc()}\n")
                    save_json(job_path, {"status": "error", "checkpoint_id": sig, "episode": ep,
                                         "clip_id": c["clip_id"], "model": model_name, "language_mode": mode,
                                         "error": message, "processing_seconds": round(time.monotonic() - beginning, 2)})
                    if "out of memory" in str(exc).lower() or "cuda error" in str(exc).lower():
                        log.error("CUDA error; stopping to avoid a cascade. Try --models turbo or shorter clips.")
                        raise
            del model_obj
            if device == "cuda":
                torch.cuda.empty_cache()
    finally:
        status = generate_reports(out, manifest, models, modes)
        if not args.no_audio_samples:
            make_review_audio_samples(out, manifest, log)
        pkg = package_results(out, include_audio=(not args.no_audio_samples))
        log.info("Current results: %s", dict(status))
        log.info("Upload this package: %s", pkg)
        log.info("Original MP3/SRT files were not modified")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Existing results are saved; rerun the same command to resume.", file=sys.stderr)
        sys.exit(130)
