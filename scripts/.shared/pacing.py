"""Even, single-line pacing for the Roman subtitles (standard library only).

Word timings come from .cache/alignment/ (scripts/06-format/align.py): each Roman word inherits the time
of the Urdu word it was romanised from. The words are then regrouped into cues of about one subtitle
line each by dynamic programming: every cue is scored by how far its length is from the ideal, how
long it lasts and any pause inside it, and every break by how natural it is (end of a sentence, a
comma, a pause, never after "the" or before "hai"). The cheapest grouping of the whole episode wins,
so cues come out evenly sized instead of being cut greedily. No word is changed or reordered, and
hand corrections in the Roman files are kept; the only words left out are stitching duplicates
(see duplicates()), the same speech transcribed twice and squeezed into a fraction of a second, and
decoding loops (see decoding_loops()) whose stretch a fresh transcription heard differently. The
only words added are passages transcribed for stretches the original transcription skipped or
looped over.
"""
import difflib
import re

MAX_CHARS = 42       # one subtitle line; only a single word longer than this gets a cue of its own
IDEAL_CHARS = 34     # cues gather around this length
HARD_PAUSE = 1.5     # a cue never spans a silence this long
SOFT_PAUSE = 0.6     # pauses inside a cue cost more beyond this
MAX_SECONDS = 6.0    # cues lasting longer are penalised
MIN_SECONDS = 1.0    # a cue stays up at least this long when the next one allows
LINGER = 0.3         # and lingers this long after its last word, gaps permitting
CHAIN_GAP = 0.6      # shorter gaps are closed so cues follow each other without flicker
MIN_GAP = 0.08       # between consecutive cues (two frames)
MIN_VISIBLE = 0.7    # where the original timing squeezed words together, a cue is still held this long
MAX_DRIFT = 1.5      # by letting the next cue start a little late, but never by more than this

# Words that should not end a cue: they lead into what follows.
NO_END = set('''a an the of to in on at for with from by and or but my your his her our their its i we you they he she
this that these those is are am was were be been have has had do does did not very if because when as than
aur ya lekin magar balke agar jab jo jis jin kyun ke ki ka mera meri mere tera teri tere apna apni apne
us is un in ek aik bohat bahut itna itni itne sab koi kuch har ye yeh woh wo'''.split())
# Words that should not start a cue: they close the phrase before them.
NO_START = set('''hai hain hoon hun ho tha thi the ga gi ge gaya gayi gaye raha rahi rahe sakta sakti sakte chahiye
ko se ne par pe tak wala wali wale ka ki ke hi bhi na'''.split())
# Compound postpositions stay whole: ke liye, ke baad, ki taraf, se pehle.
LINKS = {'ke', 'ki', 'ka', 'se'}
COMPOUND = set('''liye baad saath andar upar neeche bare baare zariye taraf wajah khilaf siwa bina jaisa jaisi jaise
mutabiq dauran pehle peeche piche samne saamne beech qareeb paas'''.split())
TAG = re.compile(r'^\[[A-Za-z]+\]$')
SENTENCE_END = re.compile(r'[.?!]["\')\]]*$')
CLAUSE_END = re.compile(r'[,;:]["\')\]]*$')


def bare(word):
    return re.sub(r"[^a-z']", '', word.lower())


def stamp(seconds):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1_000)
    return f'{hours:02}:{minutes:02}:{secs:02},{ms:03}'


def transfer(known, times, words):
    """Timed `words` from `known` words at `times` [(start, end), ...], as (word, start, end, origin).

    Identical words keep their time and `origin` is the index of the known word they match; each
    changed run shares the time of the run it replaced (or the gap where it was inserted) in
    proportion to its letters, with no origin.
    """
    if known == words:
        return [(word, s, e, k) for k, (word, (s, e)) in enumerate(zip(words, times))]
    out = []
    for tag, i0, i1, j0, j1 in difflib.SequenceMatcher(None, known, words, autojunk=False).get_opcodes():
        if tag == 'equal':
            out.extend((words[j0 + k], times[i0 + k][0], times[i0 + k][1], i0 + k) for k in range(i1 - i0))
        elif j1 > j0:
            if i1 > i0:
                lo, hi = times[i0][0], times[i1 - 1][1]
            else:
                lo = times[i0 - 1][1] if i0 else (times[0][0] if times else 0.0)
                hi = times[i0][0] if i0 < len(times) else lo
            total = sum(len(w) + 1 for w in words[j0:j1])
            cursor = lo
            for word in words[j0:j1]:
                step = (hi - lo) * (len(word) + 1) / total
                out.append((word, cursor, cursor + step, None))
                cursor += step
    return out


SQUEEZED_SECONDS = 0.25      # four or more words in less time than this cannot be real speech,
SQUEEZED_PER_WORD = 0.08     # nor can more than about twelve words a second
DUPLICATE_SIMILARITY = 0.75  # how closely such a cue must repeat the words just before it


def similarity(previous, tokens):
    """Best match between `tokens` and any contiguous stretch of `previous` of about the same length."""
    best, n = 0.0, len(tokens)
    for size in range(max(1, n - 3), n + 4):
        for i in range(max(1, len(previous) - size + 1)):
            best = max(best, difflib.SequenceMatcher(None, previous[i:i + size], tokens, autojunk=False).ratio())
    return best


def duplicates(cues):
    """Indexes of original cues that repeat the speech just before them.

    `cues` are (start, end, text) of the original Crisper SRT. Long-form transcription sometimes
    transcribes the end of one chunk again at the start of the next and squeezes the copy into a
    fraction of a second. A cue counts when it packs four or more words into impossibly little time
    (under a quarter of a second, or faster than about twelve words a second) and closely matches
    one contiguous stretch of the 40 words before it.
    """
    found = set()
    for k, (start, end, text) in enumerate(cues):
        tokens = text.split()
        if len(tokens) < 4 or end - start >= max(SQUEEZED_SECONDS, SQUEEZED_PER_WORD * len(tokens)):
            continue
        previous = ' '.join(c[2] for c in cues[max(0, k - 3):k]).split()[-40:]
        if previous and similarity(previous, tokens) >= DUPLICATE_SIMILARITY:
            found.add(k)
    return found


LOOP_RULES = ((40, 8), (32, 4))   # (words in a row, different words among them) that make a loop
LOOP_TAG = re.compile(r'^\[[a-z]+\]$')


def loop_key(word):
    """A word as loops compare it, in any script: lower case, punctuation and hyphens dropped."""
    return re.sub(r"[^\w\[\]']", '', word.lower())


def decoding_loops(cues):
    """Decoding loops in the original transcript, as (first, end) ranges over all of its words in order.

    `cues` are (start, end, text) of the original Crisper SRT. Long-form transcription sometimes gets
    stuck on a phrase ("I'm asking you. I don't know." twenty times) and spreads the copies over the
    stretch that follows, where the real speech is lost. A loop is every word inside a window of 40
    words in a row that uses at most 8 different words, or of 32 that uses at most 4; runs made mostly
    of tags such as [lipsmack] are left alone. align.py --loops transcribes each loop's stretch again,
    and only a transcription that confirms the loop as a phantom replaces it.
    """
    keys = [loop_key(w) for c in cues for w in c[2].split()]
    marked = [False] * len(keys)
    for window, distinct in LOOP_RULES:
        counts = {}
        for i, key in enumerate(keys):
            counts[key] = counts.get(key, 0) + 1
            if i >= window:
                old = keys[i - window]
                counts[old] -= 1
                if not counts[old]:
                    del counts[old]
            if i >= window - 1 and len(counts) <= distinct:
                marked[i - window + 1:i + 1] = [True] * window
    found, i = [], 0
    while i < len(keys):
        if not marked[i]:
            i += 1
            continue
        j = i
        while j < len(keys) and marked[j]:
            j += 1
        if sum(bool(LOOP_TAG.match(k)) for k in keys[i:j]) * 2 < j - i:
            found.append((i, j))
        i = j
    return found


def replacements(cues, loops):
    """The loop transcriptions that replace their loop: confirmed as a phantom, romanised, and for a
    loop decoding_loops() still finds in the cached cues."""
    found = set(decoding_loops([(c[0], c[1], c[2]) for c in cues]))
    return [p for p in loops if p.get('phantom') and p.get('roman') and tuple(p['replaces']) in found]


def covers(loop, passage):
    """Whether a passage added for missed speech was transcribed inside a loop's stretch."""
    middle = (passage['start'] + passage['end']) / 2
    return loop['span'][0] <= middle <= loop['span'][1]


def roman_words(source, roman, times):
    """Give each Roman word of a cue the timing of the source word it came from.

    Most cues pair one to one. Where one Urdu word became several Roman words (kyun ke, do hazaar),
    the identical Latin words of both cues anchor the pairing and each unmatched Roman run shares
    the time of the Urdu run it replaced, in proportion to its letters.
    """
    src, rom = source.split(), roman.split()
    if len(src) == len(rom):
        return [(word, s, e) for word, (s, e, *_) in zip(rom, times)]
    return [(word, s, e) for word, s, e, _ in transfer(src, [(t[0], t[1]) for t in times], rom)]


def origins(source, roman):
    """Index of the source word each Roman word of a cue came from, pairing them as roman_words() does.

    Inside a run where Urdu words became a different number of Roman words, each Roman word belongs to
    the Urdu word at the same share of the run's letters.
    """
    src, rom = source.split(), roman.split()
    if len(src) == len(rom):
        return list(range(len(rom)))
    out = []
    for tag, i0, i1, j0, j1 in difflib.SequenceMatcher(None, src, rom, autojunk=False).get_opcodes():
        if tag == 'equal':
            out.extend(range(i0, i1))
        elif j1 > j0 and i1 == i0:
            out.extend([min(max(i0 - 1, 0), len(src) - 1)] * (j1 - j0))
        elif j1 > j0:
            total, ends = sum(len(w) + 1 for w in src[i0:i1]), []
            for word in src[i0:i1]:
                ends.append((ends[-1] if ends else 0) + (len(word) + 1) / total)
            size, cursor = sum(len(w) + 1 for w in rom[j0:j1]), 0
            for word in rom[j0:j1]:
                middle = (cursor + (len(word) + 1) / 2) / size
                cursor += len(word) + 1
                out.append(i0 + next((k for k, end in enumerate(ends) if middle <= end), len(ends) - 1))
    return out


def roman_range(cues, first, end):
    """The Roman words that came from source words first..end-1 of the cached cues (for reports)."""
    out, offset = [], 0
    for c in cues:
        size = len(c[2].split())
        if offset < end and offset + size > first:
            out.extend(w for w, k in zip(c[3].split(), origins(c[2], c[3])) if first <= offset + k < end)
        offset += size
    return ' '.join(out)


def break_cost(words, k):
    """Cost of ending a cue after word k (lower is more natural)."""
    word, nxt = words[k][0], words[k + 1][0]
    pause = words[k + 1][1] - words[k][2]
    # Hesitations under a fifth of a second are not phrase boundaries; a full second pause is.
    cost = 2.0 - 1.4 * min(max((pause - 0.2) / 0.8, 0.0), 1.0)
    if SENTENCE_END.search(word):
        cost -= 1.6
    elif CLAUSE_END.search(word):
        cost -= 0.8
    if bare(word) in NO_END and not TAG.match(word):
        cost += 1.5
    if bare(nxt) in NO_START:
        cost += 1.0
    if bare(word) in LINKS and bare(nxt) in COMPOUND:
        cost += 2.0
    if not re.search(r'[A-Za-z0-9]', nxt):
        cost += 4.0
    elif TAG.match(nxt):
        cost -= 0.3
    # Do not strand the last word of a sentence at the start of the next cue.
    if SENTENCE_END.search(nxt):
        cost += 1.5
    elif CLAUSE_END.search(nxt):
        cost += 0.6
    return max(cost, 0.0)


def segment(words):
    """Group words into cues; returns (first, last) word index pairs."""
    n = len(words)
    if not n:
        return []
    best = [0.0] + [float('inf')] * n
    back = [0] * (n + 1)
    for j in range(n):
        chars = -1
        inner = 0.0
        hard = False
        for i in range(j, -1, -1):
            chars += len(words[i][0]) + 1
            if i < j:
                pause = words[i + 1][1] - words[i][2]
                if pause >= HARD_PAUSE:
                    hard = True
                inner += max(0.0, pause - SOFT_PAUSE) * 4.0
            if hard or (chars > MAX_CHARS and i < j):
                break
            seconds = words[j][2] - words[i][1]
            cost = 0.3 + ((chars - IDEAL_CHARS) / 10) ** 2 + inner + max(0.0, seconds - MAX_SECONDS) * 1.5
            if j + 1 < n:
                cost += break_cost(words, j)
            total = best[i] + cost
            if total < best[j + 1]:
                best[j + 1], back[j + 1] = total, i
    cues, j = [], n
    while j > 0:
        i = back[j]
        cues.append((i, j - 1))
        j = i
    return cues[::-1]


def timed(words, groups, duration=None):
    """(start, end, text) per cue: shown from the first word, held for reading, never overlapping."""
    out, floor = [], 0.0
    for k, (i, j) in enumerate(groups):
        start = max(words[i][1], floor)
        last = max(words[j][2], start)
        end = max(last + LINGER, start + MIN_SECONDS)
        if k + 1 < len(groups):
            natural = words[groups[k + 1][0]][1]
            following = max(natural, start)
            if following - last <= CHAIN_GAP:
                end = following - MIN_GAP
            end = min(end, following - MIN_GAP)
            # Squeezed words still get time to be read; the next cue gives way, within MAX_DRIFT.
            end = max(end, min(start + MIN_VISIBLE, natural + MAX_DRIFT - MIN_GAP))
        else:
            end = max(end, start + MIN_VISIBLE)
        if duration is not None:
            end = min(end, max(duration, last))
        end = max(end, start + 0.01)
        out.append((start, end, ' '.join(w[0] for w in words[i:j + 1])))
        floor = end + MIN_GAP
    return out


def words_for(cues, current=None, supplements=(), loops=()):
    """(kept, dropped, inserted) for cached alignment cues [start, end, source, roman, word times].

    `kept` are the episode's timed Roman words; `dropped` lists (cue index, start, Roman text) of
    stitching duplicates left out. `current` is the Roman text as it is now, word by word: hand
    corrections made after alignment are kept (matching words keep their measured time, edited ones
    take the time of the words they replaced) and are never dropped.

    `supplements` are passages transcribed later for stretches no cue covered (dicts with start,
    source, roman, words and applied). Applied ones are part of the file like any cue, so edits to
    them are kept too; romanised ones not applied yet are inserted at their own time.

    `loops` are fresh transcriptions of the stretches where decoding_loops() found a loop (the same
    fields, plus replaces: the loop's word range, span: the stretch transcribed, and phantom). One of
    replacements() takes the place of its loop's words and of any passage added inside its stretch,
    and once applied is part of the file in the same way. The passages that go in now, from either
    list, come back in `inserted`.
    """
    repeated = duplicates([(c[0], c[1], c[2]) for c in cues])
    replacing = replacements(cues, loops)
    # What goes is marked 'old' when a file paced before no longer has it and 'new' when it is still
    # there because its replacement has not been applied yet.
    stage = lambda p: 'old' if p.get('applied') else 'new'
    replaced = {i: stage(p) for p in replacing for i in range(*p['replaces'])}
    inside = lambda s: next((stage(p) for p in replacing if covers(p, s)), None)
    parts = sorted([(c[0], 0, k) for k, c in enumerate(cues)]
                   + [(s['start'], 1, k) for k, s in enumerate(supplements) if s.get('applied') and s.get('roman')])
    offsets = [0]
    for c in cues:
        offsets.append(offsets[-1] + len(c[2].split()))
    words, drop = [], []
    for _start, kind, k in parts:
        if kind == 0:
            timed_words = roman_words(cues[k][2], cues[k][3], cues[k][4])
            if k in repeated:
                drop.extend(['old'] * len(timed_words))
            else:
                drop.extend(replaced.get(offsets[k] + i) for i in origins(cues[k][2], cues[k][3]))
        else:
            s = supplements[k]
            timed_words = roman_words(s['source'], s['roman'], s['words'])
            drop.extend([inside(s)] * len(timed_words))
        words.extend(timed_words)
    # An applied replacement is part of the file, where its loop was.
    for p in replacing:
        if p.get('applied'):
            block = roman_words(p['source'], p['roman'], p['words'])
            at = next((k for k, (w, d) in enumerate(zip(words, drop)) if d is None and w[1] >= p['start']), len(words))
            words[at:at] = block
            drop[at:at] = [None] * len(block)
    if current is None:
        kept = [w for w, d in zip(words, drop) if d is None]
    else:
        # Match the file against the version of the cached words it agrees with, preferring the one
        # with least left in: a file paced before no longer has the stitching duplicates, one never
        # paced still does, and a duplicate copy must never stand in for the real words around it
        # (it repeats them), or they would be dropped.
        current, choices = list(current), []
        for allowed in ((None,), (None, 'new'), (None, 'new', 'old')):
            base = [(w, d) for w, d in zip(words, drop) if d in allowed]
            moved = transfer([w for (w, _, _), _ in base], [(s, e) for (_, s, e), _ in base], current)
            choices.append((sum(origin is not None for *_, origin in moved), moved, [d is not None for _, d in base]))
            if choices[-1][0] == len(current):
                break
        _, moved, flags = max(choices, key=lambda choice: choice[0])
        kept = [(w, s, e) for w, s, e, origin in moved if origin is None or not flags[origin]]
    inserted = ([s for s in supplements if s.get('roman') and not s.get('applied') and inside(s) is None]
                + [p for p in replacing if not p.get('applied')])
    # A new passage fills a gap of six seconds or more (or a loop's stretch), so every word before it
    # starts earlier and every word after it later; it goes in as a block there, leaving the other
    # words' order alone.
    blocks = []
    for n, p in enumerate(inserted):
        at = sum(1 for w in kept if w[1] < p['start'])
        blocks.append((at, n, roman_words(p['source'], p['roman'], p['words'])))
    for at, _, block in sorted(blocks, reverse=True):
        kept[at:at] = block
    dropped = [(k, cues[k][0], cues[k][3]) for k in sorted(repeated)]
    return kept, dropped, inserted


def pace(cues, duration=None, current=None, supplements=(), loops=()):
    """Paced (start, end, text) cues from cached alignment cues; see words_for()."""
    return pace_words(words_for(cues, current, supplements, loops)[0], duration)


def pace_words(words, duration=None):
    """Paced (start, end, text) cues from timed (word, start, end) in spoken order."""
    # Guard against any residual disorder between cues.
    previous = 0.0
    ordered = []
    for word, s, e in words:
        s = max(s, previous)
        e = max(e, s)
        ordered.append((word, s, e))
        previous = s
    return timed(ordered, segment(ordered), duration)


def describe(cues):
    """Pacing summary of (start, end, text) cues."""
    if not cues:
        return {}
    lengths = sorted(len(t) for _, _, t in cues)
    words = sorted(len(t.split()) for _, _, t in cues)
    seconds = sorted(max(0.0, e - s) for s, e, _ in cues)
    cps = sorted(len(t) / max(e - s, 0.001) for s, e, t in cues)
    q = lambda xs, p: xs[min(len(xs) - 1, int(len(xs) * p))]
    return {
        'cues': len(cues),
        'chars': {'p10': q(lengths, .1), 'median': q(lengths, .5), 'p90': q(lengths, .9), 'max': lengths[-1]},
        'words': {'p10': q(words, .1), 'median': q(words, .5), 'p90': q(words, .9)},
        'seconds': {'p10': round(q(seconds, .1), 2), 'median': round(q(seconds, .5), 2), 'p90': round(q(seconds, .9), 2)},
        'chars_per_second': {'median': round(q(cps, .5), 1), 'p95': round(q(cps, .95), 1)},
        'one_or_two_words': sum(n <= 2 for n in words),
        'over_max_chars': sum(n > MAX_CHARS for n in lengths),
    }
