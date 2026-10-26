"""Time every word of the original Crisper SRTs against the audio, for pacing the Roman subtitles.

Nothing is transcribed again. Each window of whole cues is replayed through CrisperWhisper's decoder
with its known text (teacher forcing), and every word is placed with the same cross-attention and
Viterbi timing the model uses when it transcribes. The decoder's token probabilities give each word a
confidence score, and stretches of six seconds or more without subtitles are transcribed on their own
so possible missed speech can be reviewed. Results are cached per episode in .cache/alignment/; the
original SRTs are only read.

--fill transcribes the uncovered stretches where speech was heard, and --loops transcribes again the
stretch of every decoding loop (pacing.decoding_loops), recording whether the fresh transcription
confirms the loop as a phantom. Both only add to the cache; pacing applies them to the Roman SRTs.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
from paths import ROOT, AUDIO, SOURCE, ROMAN, CACHE, REPORTS
from subtitles import parse, atomic_write, select_files
import pacing

os.chdir(ROOT)
ALIGNMENT = CACHE / 'alignment'
VERSION = 1
MODEL_PATH = os.environ.get('CRISPER_MODEL', 'CrisperWhisper2_Large' if Path('CrisperWhisper2_Large').is_dir() else 'large')
SAMPLE_RATE = 16_000
PAD = 0.25          # seconds of context around a window, never reaching into a neighbouring cue
MAX_WINDOW = 29.0   # Whisper encodes 30 s at a time
MAX_TOKENS = 400    # text tokens per window; the decoder holds 448 positions including the prompt
GAP_CHECK = 6.0     # uncovered stretches at least this long are transcribed for review
GAP_CHUNK = 28.0
FILL_PAD = 0.15     # --fill stays this far inside a gap, clear of the neighbouring cues
FILL_MIN_WORDS = 3  # spoken words (not tags) that make an uncovered stretch worth filling
TAG = re.compile(r'^\[[A-Za-z]+\][.,?!]*$')
# The transcription step's decoder profiles: context words and generation budget per attempt.
DECODER_PROFILES = [(4, 256), (2, 192), (1, 128)]


def seconds(stamp):
    h, m, rest = stamp.split(':')
    s, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cache_path(name):
    return ALIGNMENT / f'{name}.json'


def is_current(path):
    """A cache is current when it was made from this exact source SRT."""
    cached = cache_path(path.stem)
    if not cached.is_file():
        return False
    try:
        data = json.loads(cached.read_text(encoding='utf-8'))
    except ValueError:
        return False
    return data.get('version') == VERSION and data.get('source_sha256') == sha256(path)


def load_audio_copy(name):
    """Decode an episode to 16 kHz mono from a Linux-side copy (reading /mnt/c directly is slow).

    The MP3s are 48 kHz stereo and up to five and a half hours long, so they are decoded a minute at
    a time and resampled with soxr's streaming HQ resampler (the one CrisperWhisper uses) into one
    preallocated array, instead of holding the whole 48 kHz file in memory.
    """
    import numpy as np
    import soundfile as sf
    import soxr
    with tempfile.TemporaryDirectory(prefix='align-audio-') as tmp:
        local = Path(tmp) / f'{name}.mp3'
        shutil.copyfile(AUDIO / f'{name}.mp3', local)
        with sf.SoundFile(str(local)) as handle:
            out = np.empty(int(handle.frames * SAMPLE_RATE / handle.samplerate) + SAMPLE_RATE, dtype=np.float32)
            stream = soxr.ResampleStream(handle.samplerate, SAMPLE_RATE, 1, dtype='float32', quality='HQ')
            filled = 0
            for block in handle.blocks(blocksize=handle.samplerate * 60, dtype='float32', always_2d=True):
                part = stream.resample_chunk(block.mean(axis=1))
                out[filled:filled + len(part)] = part
                filled += len(part)
            part = stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
            out[filled:filled + len(part)] = part
            return out[:filled + len(part)]


def windows_for(spans, token_counts):
    """Consecutive whole cues per window, within MAX_WINDOW seconds and MAX_TOKENS tokens."""
    windows, i = [], 0
    while i < len(spans):
        j, tokens = i, token_counts[i]
        while (j + 1 < len(spans) and spans[j + 1][1] + PAD - (spans[i][0] - PAD) <= MAX_WINDOW
               and tokens + token_counts[j + 1] <= MAX_TOKENS):
            j += 1
            tokens += token_counts[j]
        windows.append((i, j))
        i = j + 1
    return windows


def time_window(engine, gen_ids, arrays, mel, offset, chunk_seconds, expected):
    """CPU half of a window: Viterbi word timing and per-word log-probabilities (runs in a worker thread)."""
    import numpy as np
    from crisperwhisper.word_timing import extract_word_timings, segment_tokens_into_words
    attn0, attn_rest, logits = arrays
    row0 = attn0.reshape(-1, attn0.shape[-1]).mean(axis=0)
    attention = np.vstack([row0[np.newaxis, :], attn_rest])
    logits = logits - logits.max(axis=1, keepdims=True)
    token_logp = logits[np.arange(len(gen_ids)), gen_ids] - np.log(np.exp(logits).sum(axis=1))
    pieces = [engine.tokenizer.decode([t]) for t in gen_ids]
    word_tokens, _ = segment_tokens_into_words(engine, gen_ids, pieces, language='ur')
    words = extract_word_timings(engine, gen_ids, attention, mel, audio_duration_s=chunk_seconds,
                                 language='ur', keep_unplaceable=True)
    if len(words) != len(expected) or len(word_tokens) != len(expected) or [w.word.strip() for w in words] != expected:
        return None
    return [(None if w.start is None else offset + w.start, None if w.end is None else offset + w.end,
             float(token_logp[idx].mean())) for w, idx in zip(words, word_tokens)]


def settle(words, start, end):
    """Keep a cue's words inside its original span, in order, and place any the Viterbi skipped."""
    placed = []
    for s, e, logp in words:
        if s is not None:
            s = min(max(s, start), end)
            e = min(max(e, s), end)
        placed.append([s, e, logp])
    previous = start
    for word in placed:
        if word[0] is not None:
            word[0] = max(word[0], previous)
            word[1] = max(word[1], word[0])
            previous = word[1]
    # Unplaced words share the time between their placed neighbours.
    k = 0
    while k < len(placed):
        if placed[k][0] is not None:
            k += 1
            continue
        m = k
        while m < len(placed) and placed[m][0] is None:
            m += 1
        lo = placed[k - 1][1] if k else start
        hi = placed[m][0] if m < len(placed) else end
        step = max(0.0, hi - lo) / (m - k)
        for n in range(k, m):
            placed[n][0] = lo + step * (n - k)
            placed[n][1] = lo + step * (n - k + 1)
        k = m
    return [[round(s, 3), round(e, 3), round(lp, 2)] for s, e, lp in placed]


def even_words(words, start, end):
    """Fallback when a window cannot be timed: spread a cue's words over its span by length."""
    total = sum(len(w) + 1 for w in words) or 1
    out, cursor = [], start
    for w in words:
        step = (end - start) * (len(w) + 1) / total
        out.append([round(cursor, 3), round(cursor + step, 3), None])
        cursor += step
    return out


def align_episode(path, audio, engine, prompt, pool):
    import numpy as np
    import ctranslate2
    from crisperwhisper.prompt import strip_prompt_artifacts

    def to_numpy(sv):
        return np.array(sv.to(ctranslate2.DataType.float32).to_device(ctranslate2.Device.cpu))

    name = path.stem
    roman_path = ROMAN / path.name
    source_cues = parse(path.read_text(encoding='utf-8-sig'))
    roman_cues = parse(roman_path.read_text(encoding='utf-8-sig'))
    if [c.timing for c in source_cues] != [c.timing for c in roman_cues]:
        raise ValueError(f'{roman_path.name} no longer matches the source cue for cue. Regenerate it with '
                         f'bash scripts/05-romanize/run.sh --episodes {int(name[-3:])} --overwrite --cached-only, then align again.')
    duration = len(audio) / SAMPLE_RATE
    spans = [(seconds(c.timing[:12]), seconds(c.timing[17:])) for c in source_cues]
    texts = [c.text.split() for c in source_cues]
    token_counts = [len(engine.encode_text(' ' + ' '.join(t))) for t in texts]
    windows = windows_for(spans, token_counts)
    jobs = []
    for i, j in windows:
        lo = max(0.0, spans[i][0] - PAD, spans[i - 1][1] if i else 0.0)
        hi = min(duration, spans[j][1] + PAD, spans[j + 1][0] if j + 1 < len(spans) else duration)
        lo, hi = min(lo, spans[i][0]), max(hi, spans[j][1])
        chunk = audio[int(lo * SAMPLE_RATE):int(hi * SAMPLE_RATE)]
        expected = [w for t in texts[i:j + 1] for w in t]
        gen_ids = engine.encode_text(' ' + ' '.join(expected)) + [engine.eot_id]
        features, mel = engine.extract_features_with_mel(chunk)
        encoded = engine.model.encode(features)
        state, logits0, attn0 = engine.model.prefill_with_attention(encoded, list(prompt))
        logits_rest, attn_rest = engine.model.forward_batch_with_attention(state, gen_ids[:-1])
        arrays = (to_numpy(attn0), np.array(attn_rest).astype(np.float32),
                  np.vstack([to_numpy(logits0).reshape(1, -1), to_numpy(logits_rest).reshape(len(gen_ids) - 1, -1)]))
        jobs.append(pool.submit(time_window, engine, gen_ids, arrays, mel, lo, len(chunk) / SAMPLE_RATE, expected))
        # Bound the queue so the numpy arrays of waiting windows stay small.
        while sum(not f.done() for f in jobs) > 6:
            time.sleep(0.005)

    cues, fallback, unplaced = [], 0, 0
    for (i, j), job in zip(windows, jobs):
        timed = job.result()
        k = 0
        for c in range(i, j + 1):
            n = len(texts[c])
            start, end = spans[c]
            if timed is None:
                words = even_words(texts[c], start, end)
            else:
                part = timed[k:k + n]
                unplaced += sum(w[0] is None for w in part)
                words = settle(part, start, end)
            k += n
            cues.append([start, end, source_cues[c].text, roman_cues[c].text, words])
        fallback += timed is None

    # Possible missed speech: stretches of GAP_CHECK seconds or more that no cue covers.
    edges = [0.0] + [x for s in spans for x in s] + [duration]
    gaps = []
    for lo, hi in zip(edges[::2], edges[1::2]):
        if hi - lo < GAP_CHECK:
            continue
        heard = []
        cursor = lo + 0.1
        while cursor < hi - 0.5:
            stop = min(hi - 0.1, cursor + GAP_CHUNK)
            features = engine.extract_features(audio[int(cursor * SAMPLE_RATE):int(stop * SAMPLE_RATE)])
            ids = engine.generate(features, [list(prompt)], max_length=128)[0]
            text = strip_prompt_artifacts(engine.decode_tokens(ids, skip_special=True))
            if text:
                heard.append(text)
            cursor = stop
        gaps.append([round(lo, 3), round(hi, 3), ' '.join(heard)])

    result = {'version': VERSION, 'episode': name, 'source_sha256': sha256(path), 'roman_sha256': sha256(roman_path),
              'duration': round(duration, 3), 'windows': len(windows), 'fallback_windows': fallback,
              'unplaced_words': unplaced, 'cues': cues, 'gaps': gaps}
    atomic_write(cache_path(name), json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return result


def spoken(text):
    return [w for w in text.split() if not TAG.match(w)]


def collapse_loops(words):
    """Transcription loops in a new passage: a tag repeated 3+ times keeps one, words or phrases
    repeated 5+ times keep two (people do say "nahi nahi nahi")."""
    out, i = [], 0
    while i < len(words):
        reps, size = 1, 1
        for n in range(1, 5):
            gram, r = [w[0] for w in words[i:i + n]], 1
            while [w[0] for w in words[i + r * n:i + (r + 1) * n]] == gram:
                r += 1
            if r >= 3 and r * n > reps * size:
                reps, size = r, n
        tag = all(TAG.match(w[0]) for w in words[i:i + size])
        if reps >= (3 if tag else 5):
            out.extend(words[i:i + (1 if tag else 2) * size])
            i += reps * size
        else:
            out.append(words[i])
            i += 1
    return out


def trim_edges(words, before, after):
    """Drop words at the ends of a passage that repeat the neighbouring cues' last or first words."""
    tokens = [w[0] for w in words]
    for n in range(min(4, len(tokens), len(before)), 0, -1):
        if tokens[:n] == before[-n:]:
            words, tokens = words[n:], tokens[n:]
            break
    for n in range(min(4, len(tokens), len(after)), 0, -1):
        if tokens[-n:] == after[:n]:
            words = words[:-n]
            break
    return words


def transcribe_stretch(model, audio, lo, hi):
    """Timed words CrisperWhisper hears between lo and hi seconds (FILL_PAD inside them), with the
    transcription step's settings."""
    a, b = lo + FILL_PAD, hi - FILL_PAD
    chunk = audio[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
    result = None
    for attempt, (context_words, max_new_tokens) in enumerate(DECODER_PROFILES, 1):
        try:
            result = model.transcribe(chunk, sr=SAMPLE_RATE, language='ur', mode='verbatim', word_timestamps=True,
                                      longform_strategy='continuation', context_words=context_words,
                                      max_new_tokens=max_new_tokens)
            break
        except (ValueError, RuntimeError) as exc:
            # As in transcription, only decoder-length errors are retried with a smaller budget.
            message = str(exc)
            limit = ('max_target_positions' in message or 'positions >= 448' in message
                     or ('decoder_input_ids' in message and 'max_new_tokens' in message))
            if not limit or attempt == len(DECODER_PROFILES):
                raise
    return [(w.word.strip(), min(max(a + w.start, lo), hi), min(max(a + w.end, lo), hi))
            for w in (result.words or []) if w.word and w.word.strip() and w.start is not None]


def fill_episode(path, audio, model):
    """Transcribe the stretches no cue covers where the audio check heard speech.

    The new passages, in the original's script with word times, go into the cache as additions;
    romanize.py --alignment romanises them and pacing inserts them into the Roman subtitles only.
    """
    cache = cache_path(path.stem)
    data = json.loads(cache.read_text(encoding='utf-8'))
    cues = data['cues']
    supplements = []
    for gap in data['gaps']:
        lo, hi, heard = gap[:3]
        if len(spoken(heard)) < FILL_MIN_WORDS:
            continue
        words = collapse_loops(transcribe_stretch(model, audio, lo, hi))
        previous = next((c for c in reversed(cues) if c[1] <= lo + 0.01), None)
        following = next((c for c in cues if c[0] >= hi - 0.01), None)
        words = trim_edges(words, previous[2].split() if previous else [], following[2].split() if following else [])
        # Keep it only if the full transcription confirms what the quick check heard.
        if len(spoken(' '.join(w[0] for w in words))) < FILL_MIN_WORDS:
            continue
        supplements.append({'gap': [lo, hi], 'start': round(words[0][1], 3), 'end': round(words[-1][2], 3),
                            'source': ' '.join(w[0] for w in words),
                            'words': [[round(s, 3), round(e, 3), None] for _, s, e in words],
                            'roman': None, 'applied': False})
    data['supplements'] = supplements
    atomic_write(cache, json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    return supplements


def fill(files, force=False):
    """--fill: transcribe the missed stretches of every aligned episode that has some."""
    todo = []
    for path in files:
        if not is_current(path):
            print(f'[SKIP] {path.stem}: not aligned yet', flush=True)
            continue
        data = json.loads(cache_path(path.stem).read_text(encoding='utf-8'))
        wanted = any(len(spoken(g[2])) >= FILL_MIN_WORDS for g in data['gaps'])
        if wanted and (force or 'supplements' not in data):
            todo.append(path)
    print(f'{len(todo)} episodes with missed speech to transcribe', flush=True)
    if not todo:
        return
    added = []

    def work(path, audio, model):
        passages = fill_episode(path, audio, model)
        added.append(sum(len(p['source'].split()) for p in passages))
        return f'[FILLED] {path.stem}: {len(passages)} passages, {added[-1]} words'

    minutes, failed = on_gpu(todo, work)
    print(f'Transcribed {sum(added):,} words of missed speech in {minutes:.0f} min. '
          'Next: romanize.py --alignment, then bash scripts/06-format/run.sh --skip-align.', flush=True)
    if failed:
        print('Failed:', ', '.join(failed), flush=True)
        raise SystemExit(1)


def on_gpu(todo, work):
    """Run work(path, audio, model) for each episode in todo; returns (minutes taken, failed episodes).

    Decoding is the slow part here, so the next three episodes are decoded while the GPU works.
    """
    from crisperwhisper import CrisperWhisperModel
    print('Loading CrisperWhisper on the GPU:', MODEL_PATH, flush=True)
    model = CrisperWhisperModel(MODEL_PATH, backend='ct2', device='cuda', compute_type='float16')
    started, failed = time.perf_counter(), []
    with ThreadPoolExecutor(3) as loader:
        upcoming = {i: loader.submit(load_audio_copy, todo[i].stem) for i in range(min(3, len(todo)))}
        for k, path in enumerate(todo):
            if k + 3 < len(todo):
                upcoming[k + 3] = loader.submit(load_audio_copy, todo[k + 3].stem)
            try:
                done = work(path, upcoming.pop(k).result(), model)
            except KeyboardInterrupt:
                print(f'\n[INTERRUPTED] {path.stem} not saved; rerun to continue.', flush=True)
                raise SystemExit(130)
            except Exception as exc:
                print(f'[ERROR] {path.stem}: {exc}', flush=True)
                failed.append(path.stem)
                continue
            print(f'{done}; {k + 1}/{len(todo)}, {(time.perf_counter() - started) / 60:.0f} min so far', flush=True)
    return (time.perf_counter() - started) / 60, failed


def occurrences(keys, phrase):
    """How many times phrase (a tuple of loop keys) occurs in keys without overlapping."""
    count, i, n = 0, 0, len(phrase)
    while n and i + n <= len(keys):
        if tuple(keys[i:i + n]) == phrase:
            count, i = count + 1, i + n
        else:
            i += 1
    return count


def looped_phrase(keys):
    """The phrase of up to eight words that covers most of a loop (the shorter one on a tie)."""
    best, covered = (), 0
    for n in range(1, 9):
        for phrase in dict.fromkeys(tuple(keys[i:i + n]) for i in range(len(keys) - n + 1)):
            if occurrences(keys, phrase) * n > covered:
                best, covered = phrase, occurrences(keys, phrase) * n
    return best


def confirms(loop, heard):
    """(phantom, reason): whether a fresh transcription of a loop's stretch shows the loop is not speech.

    It must hear at least three spoken words, hold no decoding loop of its own, say the phrase the
    loop repeats at most twice, and draw at most half of its words from the loop's own words (a
    transcription that circles the same words, if more briefly, is stuck too); otherwise the
    original is kept.
    """
    if len(spoken(' '.join(heard))) < FILL_MIN_WORDS:
        return False, 'the fresh transcription heard no speech'
    if pacing.decoding_loops([(0.0, 0.0, ' '.join(heard))]):
        return False, 'the fresh transcription loops too'
    keys = lambda words: [k for k in map(pacing.loop_key, words) if not pacing.LOOP_TAG.match(k)]
    fresh, looped = keys(heard), keys(loop)
    said = occurrences(fresh, looped_phrase(looped))
    if said > 2:
        return False, f'the fresh transcription repeats the looped phrase {said} times too'
    if sum(k in set(looped) for k in fresh) * 2 > len(fresh):
        return False, "most of the fresh transcription is the loop's own words again"
    return True, 'confirmed: the fresh transcription does not repeat the loop'


def relisten_episode(path, audio, model):
    """Transcribe the stretch of every decoding loop again and record whether it confirms the loop.

    A loop's stretch runs from the last word before it to the first word after it, so passages that
    --fill added inside it are heard again with it. The records go into the cache under 'loops';
    romanize.py --alignment romanises them and pacing replaces each confirmed loop in the Roman
    subtitles only. Records already applied are kept as they are.
    """
    cache = cache_path(path.stem)
    data = json.loads(cache.read_text(encoding='utf-8'))
    words = [(w, t[0], t[1]) for c in data['cues'] for w, t in zip(c[2].split(), c[4])]
    applied = {tuple(p['replaces']): p for p in data.get('loops', []) if p.get('applied')}
    records = []
    for first, end in pacing.decoding_loops([(c[0], c[1], c[2]) for c in data['cues']]):
        if (first, end) in applied:
            records.append(applied[(first, end)])
            continue
        lo = words[first - 1][2] if first else 0.0
        hi = words[end][1] if end < len(words) else data['duration']
        record = {'replaces': [first, end], 'span': [round(lo, 3), round(hi, 3)], 'phantom': False,
                  'reason': 'its stretch is too short to transcribe again', 'roman': None, 'applied': False}
        if hi - lo >= 1.0 + 2 * FILL_PAD:
            heard = transcribe_stretch(model, audio, lo, hi)
            phantom, reason = confirms([w for w, _, _ in words[first:end]], [w for w, _, _ in heard])
            passage = trim_edges(collapse_loops(heard), [w for w, _, _ in words[max(0, first - 4):first]],
                                 [w for w, _, _ in words[end:end + 4]])
            if phantom and len(spoken(' '.join(w for w, _, _ in passage))) < FILL_MIN_WORDS:
                phantom, reason = False, 'too few words remain without the edges that repeat the words around it'
            record.update(phantom=phantom, reason=reason)
            if passage:
                record.update(start=round(passage[0][1], 3), end=round(passage[-1][2], 3),
                              source=' '.join(w for w, _, _ in passage),
                              words=[[round(s, 3), round(e, 3), None] for _, s, e in passage])
        records.append(record)
    data['loops'] = records
    atomic_write(cache, json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    return records


def relisten(files, force=False):
    """--loops: transcribe the stretch of every decoding loop of the aligned episodes again."""
    todo = []
    for path in files:
        if not is_current(path):
            print(f'[SKIP] {path.stem}: not aligned yet', flush=True)
            continue
        data = json.loads(cache_path(path.stem).read_text(encoding='utf-8'))
        if (force or 'loops' not in data) and pacing.decoding_loops([(c[0], c[1], c[2]) for c in data['cues']]):
            todo.append(path)
    print(f'{len(todo)} episodes with decoding loops to transcribe again', flush=True)
    if not todo:
        return
    counts = [0, 0]

    def work(path, audio, model):
        records = relisten_episode(path, audio, model)
        confirmed = sum(bool(p['phantom']) for p in records)
        counts[0] += confirmed
        counts[1] += len(records) - confirmed
        return f'[LOOPS] {path.stem}: {confirmed} of {len(records)} confirmed as phantoms'

    minutes, failed = on_gpu(todo, work)
    print(f'{counts[0]} loops confirmed as phantoms, {counts[1]} kept, in {minutes:.0f} min. '
          'Next: romanize.py --alignment, then bash scripts/06-format/run.sh --skip-align.', flush=True)
    if failed:
        print('Failed:', ', '.join(failed), flush=True)
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--episodes', help='Comma-separated episode numbers')
    parser.add_argument('--force', action='store_true', help='Align (or with --fill, transcribe) again even when a current cache exists')
    parser.add_argument('--fill', action='store_true',
                        help='Instead of aligning, transcribe the uncovered stretches where the audio check heard speech')
    parser.add_argument('--loops', action='store_true',
                        help='Instead of aligning, transcribe the stretch of every decoding loop again')
    args = parser.parse_args()
    try:
        files = select_files(SOURCE, args.episodes)
    except ValueError as exc:
        parser.exit(1, f'Error: {exc}\n')
    if args.fill or args.loops:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            parser.exit(1, 'Error: CT2 cannot find a CUDA GPU. Check WSL2 NVIDIA GPU access.\n')
        if args.fill:
            fill(files, args.force)
        if args.loops:
            relisten(files, args.force)
        return
    todo = [p for p in files if args.force or not is_current(p)]
    print(f'{len(todo)} episodes to align; {len(files) - len(todo)} already cached in {ALIGNMENT}', flush=True)
    if not todo:
        return
    missing = [p.stem for p in todo if not (AUDIO / f'{p.stem}.mp3').is_file()]
    if missing:
        parser.exit(1, f'Error: missing audio for {", ".join(missing)}\n')

    import ctranslate2
    if ctranslate2.get_cuda_device_count() < 1:
        parser.exit(1, 'Error: CT2 cannot find a CUDA GPU. Check WSL2 NVIDIA GPU access.\n')
    from crisperwhisper import CrisperWhisperModel
    from crisperwhisper.prompt import PromptBuilder
    ALIGNMENT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    print('Loading CrisperWhisper on the GPU:', MODEL_PATH, flush=True)
    model = CrisperWhisperModel(MODEL_PATH, backend='ct2', device='cuda', compute_type='float16')
    engine = model._engine
    engine.enable_attention(None)
    prompt = PromptBuilder(engine, language='ur').verbatim()

    import soundfile
    # Episodes range from 20 minutes to over five hours, so progress is measured in audio time.
    total_seconds = sum(soundfile.info(str(AUDIO / f'{p.stem}.mp3')).duration for p in todo)
    started = time.perf_counter()
    audio_seconds = 0.0
    failed = []
    with ThreadPoolExecutor(3) as pool, ThreadPoolExecutor(1) as loader:
        upcoming = loader.submit(load_audio_copy, todo[0].stem)
        for k, path in enumerate(todo):
            began = time.perf_counter()
            try:
                audio = upcoming.result()
            except Exception as exc:  # decoding problems are reported per episode
                audio, error = None, exc
            if k + 1 < len(todo):
                upcoming = loader.submit(load_audio_copy, todo[k + 1].stem)
            if audio is None:
                print(f'[ERROR] {path.stem}: could not decode audio: {error}', flush=True)
                failed.append(path.stem)
                continue
            try:
                result = align_episode(path, audio, engine, prompt, pool)
            except KeyboardInterrupt:
                print(f'\n[INTERRUPTED] {path.stem} not saved; rerun to continue.', flush=True)
                raise SystemExit(130)
            except Exception as exc:
                print(f'[ERROR] {path.stem}: {exc}', flush=True)
                failed.append(path.stem)
                continue
            audio_seconds += result['duration']
            took = time.perf_counter() - began
            elapsed = time.perf_counter() - started
            remaining = elapsed / audio_seconds * max(0.0, total_seconds - audio_seconds)
            print(f'[DONE] {path.stem}: {len(result["cues"])} cues in {result["windows"]} windows, {took:.0f}s '
                  f'({result["duration"] / took:.0f}x real time); fallback windows {result["fallback_windows"]}, '
                  f'unplaced words {result["unplaced_words"]}, gaps checked {len(result["gaps"])}; '
                  f'{k + 1}/{len(todo)}, about {remaining / 60:.0f} min left', flush=True)
    print(f'Aligned {len(todo) - len(failed)} episodes ({audio_seconds / 3600:.1f} h of audio) in '
          f'{(time.perf_counter() - started) / 60:.0f} min.', flush=True)
    if failed:
        print('Failed:', ', '.join(failed), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
