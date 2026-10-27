"""English subtitles for every episode, translated from the audio by CrisperWhisper on the GPU.

CrisperWhisper 2.0, the model that made the transcription, also does Whisper's translate task. Each
episode is cut into windows of whole Roman cues: at most 28 seconds, never across a pause of two
seconds or more, so no word is cut. A window under four seconds joins a neighbour, because Whisper
invents speech for a lone second of audio, and one holding only tags such as [UH] is skipped. Eight
windows at a time become timed English sentences. As in Whisper, a window whose English repeats
itself (it compresses more than 2.4 times, as when the model echoes a stutter) is decoded again a
little warmer. A window whose English still looks wrong (repeating, not English, or under a third
of its Roman words, as when the model stops where the speaker switches between Urdu and English) is
translated again in pieces of about ten seconds, and a piece that still looks wrong in pieces of
about five; pieces that do better are kept. Whisper's stock phrases ("Thank you.", "Peace be upon
you.") are dropped where nothing like them is said, and a sentence looping four times or more is kept
once. The model times
groups of sentences; a group longer than seven seconds is split between its sentences, which share
its spoken time (the Roman cues inside it) by length. Speech is translated as heard, and English is
kept as spoken.

Results go to transcripts-english/episode_NNN.srt; episodes already there are skipped unless --force,
and --repair translates again only the windows of existing files that need it. Windows that still
look wrong are listed in .cache/reports/translation.json. Only the audio and the Roman subtitles
are read.

The model is nyralabs/CrisperWhisper2.0_large from a Hugging Face cache; TRANSLATE_MODEL can point at
its folder instead.
"""
import argparse
import bisect
import collections
import glob
import json
import os
import re
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
from paths import AUDIO, ROMAN, ENGLISH, REPORTS
from subtitles import Cue, parse, render, atomic_write, select_files, span
from align import load_audio_copy, SAMPLE_RATE
import pacing

WINDOW = 28.0      # seconds of whole cues per window (Whisper hears 30 s at a time)
PAUSE = 2.0        # a window never spans a silence this long
SHORT = 4.0        # seconds; a shorter window joins a neighbour
STEPS = (10.0, 5.0)  # seconds; further tries translate a doubtful window, then a doubtful piece, in pieces this long
EDGE = 0.2         # seconds of audio kept either side of a window's cues
BATCH = 8          # windows per GPU call
MIN_GAP = 0.08     # between consecutive English cues
LONG = 7.0         # seconds; a longer English segment is split between its sentences
CLAUSE = 90        # characters; a longer sentence there is cut at commas into parts about this long
SENTENCE = re.compile(r'(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bDr\.)(?<=[.?!])\s+(?=\S)')
TAG = re.compile(r'^\[[A-Za-z]+\][.,?!]*$')
# Whisper's rule for runaway repetition: English that compresses more than 2.4 times is decoded again,
# a little warmer. Warmer still only invents text; the pieces of a second try do better.
REPEATS = 2.4
FALLBACK = dict(temperature=(0.0, 0.2, 0.4), compression_ratio_threshold=REPEATS)
THIN = 0.35        # English words per spoken Roman word below which a window has lost speech
LOOP = 4           # a sentence said this many times in a row or more is a decoding loop, kept once
# Whisper's stock phrases for unclear audio, each with what someone saying it would say in the Roman text.
STOCK = [(re.compile(r"(?:thank ?you(?: (?:so|very) much)?(?: for watching)?|thanks(?: for watching)?)[.!,]*", re.I),
          re.compile(r'thank|shukr|meherbani|jazak', re.I)),
         (re.compile(r"(?:good ?bye|bye(?: bye)?|see you(?: again| later| soon| next time)?|that's all for today|we are done)[.!,]*", re.I),
          re.compile(r'bye|hafiz|ijaz|mulaqaat|\bmil|dobara|see you|done|khatam', re.I)),
         (re.compile(r'peace be upon you[.!,]*', re.I), re.compile(r'sala+m|alaikum|alaykum|aleikum', re.I)),
         (re.compile(r'please (?:like|subscribe|share)[^.!?]*[.!?]*', re.I),
          re.compile(r'subscri|sbskr|bell|\b(?:like|share)\s+(?:k|aur|and)', re.I))]
GLUED = re.compile(r'(?<=[.!?])(?=[A-Z])')  # sentences the model ran together ("subscribe..Thankyou.")
REPO = 'models--nyralabs--CrisperWhisper2.0_large'
NOT_ENGLISH = re.compile('[%s-%s%s-%s]' % tuple(map(chr, (0x0600, 0x06FF, 0x0900, 0x097F))))  # Urdu or Hindi letters


def model_folder():
    """The CrisperWhisper 2.0 snapshot: TRANSLATE_MODEL, or the first Hugging Face cache holding it."""
    if os.environ.get('TRANSLATE_MODEL'):
        return Path(os.environ['TRANSLATE_MODEL'])
    caches = [os.environ.get('HF_HUB_CACHE', ''), os.path.join(os.environ.get('HF_HOME', ''), 'hub'),
              os.path.expanduser('~/.cache/huggingface/hub'), *glob.glob('/mnt/c/Users/*/.cache/huggingface/hub')]
    for cache in filter(None, caches):
        snapshots = sorted(Path(cache, REPO, 'snapshots').glob('*/model.safetensors'))
        if snapshots:
            return snapshots[-1].parent
    raise ValueError('CrisperWhisper 2.0 not found; set TRANSLATE_MODEL to its folder')


def windows_for(spans, longest=WINDOW, short=SHORT):
    """(start, end) windows of whole cues: at most `longest` seconds, closed at any pause of PAUSE or
    more. A window shorter than `short` joins the one before it, or else the one after, if they fit."""
    groups = []
    for start, end in spans:
        if groups and end - groups[-1][0] <= longest and start - groups[-1][1] < PAUSE:
            groups[-1][1] = max(groups[-1][1], end)
        else:
            groups.append([start, end])
    merged = []
    for first, last in groups:
        if merged and last - merged[-1][0] <= longest and (last - first < short or merged[-1][1] - merged[-1][0] < short):
            merged[-1][1] = last
        else:
            merged.append([first, last])
    return [(max(0.0, first - EDGE), last + EDGE) for first, last in merged]


def spoken(text):
    """The words of a Roman cue that are speech rather than tags such as [UH] or [breath]."""
    return [w for w in text.split() if not TAG.match(w)]


def segments_of(ids, window, first_stamp, decode, specials=None):
    """Timed English sentences from one window's tokens: text between Whisper's timestamp tokens
    (<|0.00|> is first_stamp, each step 0.02 s). Other tokens from `specials` up (the prompt, end of
    text, the model's own tags after <|30.00|>) are skipped."""
    lo, hi = window
    specials = first_stamp if specials is None else specials
    out, opened, text = [], None, []
    for i in ids:
        if first_stamp <= i <= first_stamp + 1500:
            stamp = (i - first_stamp) * 0.02
            if opened is None:
                opened = stamp
            else:
                if text:
                    out.append((lo + opened, min(hi, lo + stamp), decode(text).strip()))
                opened, text = None, []
        elif i < specials:
            text.append(i)
    if text:
        out.append((lo + (opened or 0.0), hi, decode(text).strip()))
    return [(s, e, t) for s, e, t in out if t]


def pieces(text):
    """A segment's sentences, with any longer than CLAUSE characters cut at commas into parts about that long."""
    out = []
    for sentence in SENTENCE.split(text):
        part = ''
        for clause in re.split(r'(?<=,)\s+', sentence) if len(sentence) > CLAUSE else [sentence]:
            if part and len(part) + 1 + len(clause) > CLAUSE:
                out.append(part)
                part = clause
            else:
                part = f'{part} {clause}' if part else clause
        out.append(part)
    return out


def sentences(segments, speech):
    """Segments longer than LONG seconds split between their sentences (see pieces), which share the
    segment's spoken time (the `speech` spans inside it, else all of it) in proportion to their length."""
    out = []
    for start, end, text in segments:
        parts = pieces(text)
        if end - start <= LONG or len(parts) < 2:
            out.append((start, end, text))
            continue
        spans = [(max(s, start), min(e, end)) for s, e in speech if s < end and e > start] or [(start, end)]
        total, whole = sum(e - s for s, e in spans), sum(map(len, parts))

        def at(x, opening=False):
            """The moment x seconds of speech into the segment; a part opens after a silence, not before it."""
            for s, e in spans:
                if x < e - s or (not opening and x <= e - s):
                    return s + x
                x -= e - s
            return spans[-1][1]
        done = 0
        for part in parts:
            out.append((at(total * done / whole, True), at(total * (done + len(part)) / whole), part))
            done += len(part)
    return out


def words_of(text):
    """A cue's words for comparing two cues: lower case, punctuation left out."""
    return re.sub(r'\W+', ' ', text).lower().split()


def within(part, whole):
    """Whether `part` (four words or more) runs unbroken inside `whole`."""
    return len(part) >= 4 and any(whole[i:i + len(part)] == part for i in range(len(whole) - len(part) + 1))


def cues_of(segments):
    """Numbered SRT cues in order. A sentence that repeats the one before it is left out, whatever its
    capitals and punctuation, and so is a fragment that two pieces both heard (the shorter of two cues
    in a row, when its words run unbroken inside the other). Where two overlap, the earlier one ends
    sooner, so every sentence still starts when it is spoken."""
    cues = []
    for start, end, text in sorted(segments):
        words, previous = words_of(text), words_of(cues[-1][2]) if cues else []
        if words == previous or within(words, previous):
            continue
        if within(previous, words):
            start = cues.pop()[0]
        if cues and start < cues[-1][1] + MIN_GAP:
            cues[-1][1] = max(cues[-1][0] + 0.3, start - MIN_GAP)
            start = max(start, cues[-1][1] + MIN_GAP)
        cues.append([start, max(end, start + 0.5), text])
    return [Cue(str(n), f'{pacing.stamp(s)} --> {pacing.stamp(e)}', (t,)) for n, (s, e, t) in enumerate(cues, 1)]


def repeats(text):
    """Whisper's compression ratio: how many times the text shrinks under zlib (about 2.4+ when looping)."""
    data = text.encode('utf-8')
    return len(data) / len(zlib.compress(data)) if data else 0.0


def english_of(segments):
    return ' '.join(t for *_, t in segments)


def doubts(english, heard):
    """Why one window's English needs another try, if it does: still repeating, not English, or empty
    or thin (under THIN of the words) where the Roman cues have `heard` spoken words."""
    words = len(english.split())
    return [reason for reason, bad in (('repeats', repeats(english) > REPEATS), ('not English', bool(NOT_ENGLISH.search(english))),
                                       ('empty', not words and heard >= 12), ('thin', 0 < words < THIN * heard and heard >= 15)) if bad]


def score(segments, heard):
    """How one try at a window compares with another (lower is better): not repeating and in English
    first (a thin try beats an invented one), then fewer doubts, then more words."""
    english = english_of(segments)
    why = doubts(english, heard)
    return bool({'repeats', 'not English'} & set(why)), len(why), -len(english.split())


def clean(segments, roman):
    """Segments without what the model invents: a stock phrase (see STOCK) that nothing in the Roman cues
    within four seconds supports, and all but one of a sentence said LOOP times in a row or more."""
    out = []
    for start, end, text in segments:
        near = ' '.join(t for (s, e), t in roman if e > start - 4 and s < end + 4)
        invented = lambda bit: any(phrase.fullmatch(bit.strip()) and not said.search(near) for phrase, said in STOCK)
        kept = [part for part in (''.join(bit for bit in GLUED.split(part) if not invented(bit)) for part in SENTENCE.split(text))
                if part.strip()]
        tidy, k = [], 0
        while k < len(kept):
            j = k
            while j + 1 < len(kept) and words_of(kept[j + 1]) == words_of(kept[k]):
                j += 1
            tidy.extend(kept[k:j + 1] if j + 1 - k < LOOP else kept[k:k + 1])
            k = j + 1
        if tidy:
            out.append((start, end, ' '.join(tidy)))
    return out


def existing(path, windows, spans):
    """The segments of the English file at `path`, as {index: segments} for each of `windows` that is
    also one of the windows it was made with (before short windows joined their neighbours)."""
    made = windows_for(spans, short=0)
    starts = [lo - 0.05 for lo, _ in made]
    said = collections.defaultdict(list)
    for cue in parse(path.read_text(encoding='utf-8-sig')):
        s, e = span(cue)
        said[max(0, bisect.bisect_right(starts, s) - 1)].append((s, e, cue.text))
    index = {w: k for k, w in enumerate(made)}
    return {k: said[index[w]] for k, w in enumerate(windows) if w in index}


def translate(files, force=False, output=ENGLISH, repair=False):
    import torch
    import transformers
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    if not torch.cuda.is_available():
        raise ValueError('PyTorch cannot find a CUDA GPU. Check WSL2 NVIDIA GPU access.')
    output = Path(output)
    have = [p for p in files if (output / p.name).is_file()]
    if repair:
        todo = have
        print(f'{len(todo)} episodes in {output.name}/ to check again', flush=True)
    else:
        todo = [p for p in files if force or p not in have]
        print(f'{len(todo)} episodes to translate; {len(files) - len(todo)} already in {output.name}/', flush=True)
    if not todo:
        return
    folder = model_folder()
    print('Loading CrisperWhisper 2.0 on the GPU:', folder, flush=True)
    transformers.logging.set_verbosity_error()
    transformers.logging.disable_progress_bar()
    processor = WhisperProcessor.from_pretrained(folder)
    model = WhisperForConditionalGeneration.from_pretrained(folder, dtype=torch.float16).to('cuda').eval()
    tokenizer = processor.tokenizer
    first_stamp, specials = tokenizer.convert_tokens_to_ids('<|0.00|>'), tokenizer.convert_tokens_to_ids('<|endoftext|>')
    decode = lambda ids: tokenizer.decode(ids, skip_special_tokens=True)

    def run(audio, windows, roman):
        """English segments for each of `windows`, decoded BATCH at a time."""
        out = []
        for b in range(0, len(windows), BATCH):
            group = windows[b:b + BATCH]
            inputs = processor([audio[int(lo * SAMPLE_RATE):int(hi * SAMPLE_RATE)] for lo, hi in group],
                               sampling_rate=SAMPLE_RATE, return_tensors='pt')
            with torch.no_grad():
                ids = model.generate(inputs.input_features.to('cuda', torch.float16), language='ur', task='translate',
                                     return_timestamps=True, **FALLBACK)
            for window, row in zip(group, ids.tolist()):
                speech = [(s, e) for (s, e), _ in roman if window[0] <= s < window[1]]
                out.append(sentences(segments_of(row, window, first_stamp, decode, specials), speech))
        return out

    import soundfile
    total = sum(soundfile.info(str(AUDIO / f'{p.stem}.mp3')).duration for p in todo)
    report_path = REPORTS / 'translation.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    started, done, failed = time.perf_counter(), 0.0, []
    with ThreadPoolExecutor(2) as loader:
        upcoming = {i: loader.submit(load_audio_copy, todo[i].stem) for i in range(min(2, len(todo)))}
        for k, path in enumerate(todo):
            if k + 2 < len(todo):
                upcoming[k + 2] = loader.submit(load_audio_copy, todo[k + 2].stem)
            try:
                audio = upcoming.pop(k).result()
                roman = [(span(c), c.text) for c in parse(path.read_text(encoding='utf-8-sig'))]
                spans = [s for s, _ in roman]
                heard = lambda w: sum(len(spoken(t)) for (s, _), t in roman if w[0] <= s < w[1])
                windows = [w for w in windows_for(spans) if heard(w)]
                results = existing(output / path.name, windows, spans) if repair else {}
                fresh = [i for i in range(len(windows)) if i not in results]
                results.update(zip(fresh, run(audio, [windows[i] for i in fresh], roman)))
                # Further tries for English that looks wrong: a window's cues in pieces of STEPS[0] seconds,
                # then a piece that still looks wrong in pieces of STEPS[1]; pieces that do better are kept.
                parts = {i: [(windows[i], results[i])] for i in range(len(windows))}
                tried = better = 0
                for longest in STEPS:
                    retry = {(i, j): [p for p in windows_for([s for s in spans if piece[0] <= s[0] < piece[1]], longest=longest) if heard(p)]
                             for i, found in parts.items() for j, (piece, segments) in enumerate(found)
                             if doubts(english_of(segments), heard(piece))}
                    retry = {key: subs for key, subs in retry.items() if len(subs) > 1}
                    got, swaps = iter(run(audio, [p for subs in retry.values() for p in subs], roman)), {}
                    for (i, j), subs in retry.items():
                        candidate = [(p, next(got)) for p in subs]
                        piece, segments = parts[i][j]
                        tried += 1
                        if score([s for _, found in candidate for s in found], heard(piece)) < score(segments, heard(piece)):
                            swaps[i, j] = candidate
                    better += len(swaps)
                    for i, j in sorted(swaps, reverse=True):
                        parts[i][j:j + 1] = swaps[i, j]
                results = {i: [s for _, found in parts[i] for s in found] for i in parts}
                segments = clean([segment for i in range(len(windows)) for segment in results[i]], roman)
                atomic_write(output / path.name, render(cues_of(segments)))
                report[path.stem] = [{'start': round(w[0], 2), 'end': round(w[1], 2), 'why': why}
                                     for i, w in enumerate(windows) if (why := doubts(english_of(results[i]), heard(w)))]
                REPORTS.mkdir(parents=True, exist_ok=True)
                atomic_write(report_path, json.dumps(dict(sorted(report.items())), indent=1))
            except KeyboardInterrupt:
                print(f'\n[INTERRUPTED] {path.stem} not saved; rerun to continue.', flush=True)
                raise SystemExit(130)
            except Exception as exc:
                print(f'[ERROR] {path.stem}: {exc}', flush=True)
                failed.append(path.stem)
                continue
            done += len(audio) / SAMPLE_RATE
            elapsed = time.perf_counter() - started
            left = report[path.stem]
            print(f'[DONE] {path.stem}: {len(fresh)} windows translated, {tried} tried again in pieces ({better} kept)'
                  f'{f", {len(left)} to check" if left else ""}; {k + 1}/{len(todo)}, {done / elapsed:.0f}x real time, '
                  f'about {elapsed / done * max(0.0, total - done) / 60:.0f} min left', flush=True)
    print(f'{"Checked" if repair else "Translated"} {len(todo) - len(failed)} episodes in {(time.perf_counter() - started) / 60:.0f} min.', flush=True)
    if failed:
        print('Failed:', ', '.join(failed), flush=True)
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--episodes', help='Comma-separated episode numbers')
    parser.add_argument('--force', action='store_true', help='Translate again even when the English file exists')
    parser.add_argument('--repair', action='store_true', help='Translate again only the windows of existing English files that need it')
    parser.add_argument('--output', type=Path, default=ENGLISH, help='Folder for the English SRTs')
    args = parser.parse_args()
    try:
        translate(select_files(ROMAN, args.episodes), args.force, args.output, args.repair)
    except ValueError as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
