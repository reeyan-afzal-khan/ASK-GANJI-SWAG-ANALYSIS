"""Build the analytics app data in app/data/ and optionally preview the app locally.

Reads the Roman Urdu SRTs and docs/episode-index.md; standard library only, no GPU or network.
Writes data/summary.js (all aggregates) and data/transcripts/episode_NNN.js (subtitle text for
search and the transcript viewer), so app/ is a self-contained static site. The original Crisper
SRTs are optional and only label each word as English or Urdu.

Each question's category comes from question_labels.json (hand-checked subcategories, one list per
episode in index order). Episodes missing there fall back to the keyword lists in config.json and
are flagged for review. Stated ages and places come from the title and the opening of the answer.
"""
import argparse, bisect, collections, http.server, json, math, re, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
# Allow this entry point to run directly as well as through app/run.sh.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / '.shared'))
from paths import ROMAN, SOURCE, INDEX, APP, CACHE
from subtitles import parse, atomic_write, select_files
from pacing import covers

CONFIG = Path(__file__).with_name('config.json')
LABELS = Path(__file__).with_name('question_labels.json')
ALIGNMENT = CACHE / 'alignment'
SKINS, THEME = APP / 'skins', APP / 'assets' / 'theme.css'
THEME_TOKENS = ('void rail surface surface-2 surface-3 line line-hot ink ink-soft muted acc acc-hi acc-dim acc-wash on-acc '
                'h1 h2 h3 h4 h5 h6 h7 h8 tail-1 tail-2 tail-3 seq-0 seq-1 seq-2 seq-3 seq-4 seq-5 seq-6 seq-7 '
                'seq-ink seq-ink-strong rise fall shadow').split()
PLAYLIST = 'https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B'
ITEM = re.compile(r'^\s*(\d+)\.\s+\[(.*)\]\((.*)\)\s*$')
MARKER = re.compile(r'\[([A-Za-z]+)\]')
WORD = re.compile(r"[a-z]+(?:'[a-z]+)*")
CLOCK = re.compile(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?')
GARBLED = re.compile(r"[^aeiouy']{4,}")
EXCERPT_SECONDS, TOPIC_SECONDS, EXCERPT_CHARS = 45, 90, 280
TOP_WORDS, SIGNATURE_WORDS, CORPUS_WORDS, STABLE_SPELLING = 60, 8, 60, 20
SPOKEN_TEENS = 'thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
SPOKEN_TENS = 'twenty thirty forty fifty sixty'.split()
SPOKEN_UNITS = 'one two three four five six seven eight nine'.split()
AGE = re.compile(r"\b(?:i'm|i am|aged?)\s+(?:an?\s+)?(1[3-9]|[2-6]\d)\b(?![%$]|[.,]\d|\s*(?:k\b|lakh|percent|hours?|minutes?|days?|weeks?|months?|times?|kg|km))"
                 r"|\b(1[3-9]|[2-6]\d)\s*-?\s*(?:years?|yrs?)\s*-?\s*old\b"
                 r"|\b(1[3-9]|[2-6]\d)\s*(?:yo|y/o|y\.o)\b"
                 rf"|\b({'|'.join(SPOKEN_TEENS)}|(?:{'|'.join(SPOKEN_TENS)})(?:[\s-](?:{'|'.join(SPOKEN_UNITS)}))?)[\s-](?:years?|yrs?)[\s-]old\b"
                 rf"|\b(?:i'm|i am)\s+(?:an?\s+)?({'|'.join(SPOKEN_TEENS)}|(?:{'|'.join(SPOKEN_TENS)})(?:[\s-](?:{'|'.join(SPOKEN_UNITS)}))?)\b"
                 r"(?![\s-]*(?:percent|hours?|minutes?|days?|weeks?|months?|times?|thousand|hundred|lakh|k)\b)", re.I)
TITLE_NOISE = {'question', 'questions', 'advice', 'help', 'seeking', 'guidance', 'need', 'needs', 'problem', 'problems',
               'issue', 'issues', 'dilemma', 'confused', 'confusion', 'story', 'tale', 'comments', 'youtube', 'update', 'request',
               'getting', 'living', 'feeling', 'trying', 'dealing', 'facing', 'struggling', 'wanting', 'stuck'}


def seconds(stamp):
    hours, minutes, rest = stamp.replace(',', '.').split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)

def span(cue):
    start, end = cue.timing.split(' --> ')
    return seconds(start), seconds(end)

def words(text):
    return WORD.findall(MARKER.sub(' ', text).lower())

def plain(text):
    return ' '.join(MARKER.sub(' ', text).split())

def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

def write_if_changed(path, text):
    if not (path.is_file() and path.read_text(encoding='utf-8') == text):
        atomic_write(path, text)

def video_and_start(url):
    """YouTube video id and start second of a watch or youtu.be link."""
    if not url:
        return None, None
    link = urlparse(url)
    query = parse_qs(link.query)
    video = (link.path.strip('/') or None) if link.netloc.endswith('youtu.be') else query.get('v', [None])[0]
    clock = CLOCK.fullmatch(query.get('t', [''])[0])
    if not clock or not any(clock.groups()):
        return video, None
    hours, minutes, rest = (int(part or 0) for part in clock.groups())
    return video, hours * 3600 + minutes * 60 + rest

def read_index(path):
    """{episode: [(title, video, start second)]} from the Markdown question index."""
    index = {}
    for block in re.split(r'<details\b[^>]*>', Path(path).read_text(encoding='utf-8'))[1:]:
        heading = re.search(r'Episode\s+(\d+)', block)
        if not heading:
            continue
        items = index.setdefault(int(heading.group(1)), [])
        for line in block.splitlines():
            if match := ITEM.match(line):
                items.append((match.group(2).strip(), *video_and_start(match.group(3).strip())))
    return index

def pattern(terms):
    """One regex for whole-word terms and phrases; a trailing * matches any word ending."""
    parts = sorted((re.escape(t[:-1]) + r"[\w']*" if t.endswith('*') else re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r'\b(?:' + '|'.join(parts) + r')\b') if parts else None

def category_rules(config):
    return [(c['id'], pattern(c.get('keywords', [])), pattern(c.get('weak', [])), c.get('title_only', False))
            for c in config['categories'] if c.get('keywords')]

def matching_text(text):
    return ' '.join(re.sub(r"[^\w']+", ' ', text.lower().replace('\N{RIGHT SINGLE QUOTATION MARK}', "'")).split())

def classify(rules, title, excerpt=''):
    """Keyword fallback for unlabelled questions: primary and secondary categories. Title terms
    decide; the opening transcript breaks ties and places vague titles, never outweighing a title term."""
    title, excerpt = matching_text(title), matching_text(excerpt)
    def score(strong, weak, text):
        return sum(factor * len(set(regex.findall(text))) for factor, regex in ((1, strong), (0.5, weak)) if regex and text)
    scores = {topic: 3 * score(strong, weak, title) + (0 if title_only else min(2.5, score(strong, weak, excerpt) / 2))
              for topic, strong, weak, title_only in rules}
    best = max(scores.values(), default=0)
    if best < 1:
        return 'other', []
    primary = next(topic for topic, *_ in rules if scores[topic] == best)
    return primary, [topic for topic, *_ in rules if topic != primary and scores[topic] >= 2]

def read_labels(path, known):
    """{episode: [subcategory codes per question]}; the first code is primary."""
    if not path or not Path(path).is_file():
        return {}
    labels = {}
    for episode, entries in json.loads(Path(path).read_text(encoding='utf-8')).items():
        labels[int(episode)] = [entry.split() for entry in entries]
        for order, codes in enumerate(labels[int(episode)], 1):
            unknown = [code for code in codes if code not in known]
            if not codes or unknown:
                raise ValueError(f'{Path(path).name}: episode {episode} question {order} has unknown subcategory {unknown or "(empty)"}')
    return labels

def stated_age(*texts):
    """The first age stated as '22 years old', '19 yo', "I'm 24", "I'm thirty six" or 'twenty-four year old'."""
    for text in texts:
        match = AGE.search(text.replace('\N{RIGHT SINGLE QUOTATION MARK}', "'"))
        if match:
            digits = next((g for g in match.groups()[:3] if g), None)
            if digits:
                return int(digits)
            spoken = (match.group(4) or match.group(5)).lower().replace('-', ' ').split()
            tens = SPOKEN_TENS.index(spoken[0]) * 10 + 20 if spoken[0] in SPOKEN_TENS else SPOKEN_TEENS.index(spoken[0]) + 13
            return tens + (SPOKEN_UNITS.index(spoken[1]) + 1 if len(spoken) > 1 else 0)
    return None

def place_rules(config):
    """Per place, one case-insensitive regex plus one exact-case regex for capitalised aliases (US, UK)."""
    rules = []
    for place in config.get('places', []):
        lower = [a for a in place['aliases'] if not a.isupper()]
        upper = [a for a in place['aliases'] if a.isupper()]
        rules.append((re.compile(r'\b(?:' + '|'.join(map(re.escape, lower)) + r')\b', re.I) if lower else None,
                      re.compile(r'\b(?:' + '|'.join(map(re.escape, upper)) + r')\b') if upper else None))
    return rules

def mentioned_places(rules, text):
    return [i for i, (lower, upper) in enumerate(rules) if (lower and lower.search(text)) or (upper and upper.search(text))]

def title_words(title, stopwords):
    seen = []
    for word in words(title.replace('\N{RIGHT SINGLE QUOTATION MARK}', "'")):
        if len(word) > 2 and word not in stopwords and word not in TITLE_NOISE and word not in seen:
            seen.append(word)
    return seen

def added_latin(alignment, number):
    """Latin words of passages that step 06 added for speech the original run skipped or looped over.

    They are not in the original SRT, so without this their English words would count as Urdu.
    The record lives in the local .cache/alignment/; without it nothing is added. A passage whose
    stretch a replaced loop covers is no longer in the subtitles, so it is left out.
    """
    cache = Path(alignment) / f'episode_{number:03d}.json' if alignment else None
    if not cache or not cache.is_file():
        return collections.Counter()
    data = json.loads(cache.read_text(encoding='utf-8'))
    replaced = [p for p in data.get('loops', []) if p.get('applied') and p.get('phantom')]
    kept = [s for s in data.get('supplements', []) if s.get('applied') and not any(covers(p, s) for p in replaced)]
    return collections.Counter(w for s in kept + replaced for w in words(s['source']))

def read_episode(path, source):
    """Cues with their spans, plus the original Crisper cues when present (they may be paced differently)."""
    cues = parse(path.read_text(encoding='utf-8-sig'))
    original = Path(source) / path.name if source else None
    originals = parse(original.read_text(encoding='utf-8-sig')) if original and original.is_file() else None
    return cues, [span(c) for c in cues], originals

def build(roman=ROMAN, source=SOURCE, index_path=INDEX, output=APP / 'data', labels_path=LABELS, alignment=ALIGNMENT):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    stopwords, rules, places = set(config['stopwords']), category_rules(config), place_rules(config)
    labels = read_labels(labels_path, {s['id'] for c in config['categories'] for s in c['subcategories']})
    index = read_index(index_path)
    files = select_files(roman)
    output, transcripts = Path(output), Path(output) / 'transcripts'
    episodes, questions, contents, written = [], [], {}, set()
    corpus, document_frequency = collections.Counter(), collections.Counter()
    english, urdu = collections.Counter(), collections.Counter()
    unaligned, unlabelled = [], []
    for path in files:
        number = int(re.search(r'\d+', path.stem).group())
        cues, spans, originals = read_episode(path, source)
        duration = spans[-1][1]
        minutes = [0] * (int(duration // 60) + 1)
        events, counts, latin = collections.Counter(), collections.Counter(), 0
        for cue, (start, end) in zip(cues, spans):
            events.update(m.lower() for m in MARKER.findall(cue.text))
            spoken = collections.Counter(words(cue.text))
            counts.update(spoken)
            minutes[min(len(minutes) - 1, int((start + end) / 2 // 60))] += sum(spoken.values())
        if originals:
            # Latin words in the original are the English ones; everything else in the Roman text is
            # romanised Urdu. Each English word appears once in both, so counting over the episode gives
            # the same totals as cue by cue and works when the Roman cues are paced differently.
            shared = counts & (collections.Counter(w for c in originals for w in words(c.text)) + added_latin(alignment, number))
            english.update(shared)
            urdu.update(counts - shared)
            latin = sum(shared.values())
        else:
            unaligned.append(number)
        name = f'episode_{number:03d}.js'
        write_if_changed(transcripts / name, f'GANJI_TRANSCRIPT({number},{compact([[round(s, 2), c.text] for c, (s, _) in zip(cues, spans)])});\n')
        written.add(name)
        total = sum(counts.values())
        content = collections.Counter({w: c for w, c in counts.items() if len(w) > 2 and w not in stopwords})
        contents[number] = content
        corpus.update(content)
        document_frequency.update(content.keys())
        items = index.get(number, [])
        starts = [start for _, _, start in items]
        cue_starts = [start for start, _ in spans]
        def text_between(low, high):
            first, last = bisect.bisect_left(cue_starts, low), bisect.bisect_left(cue_starts, high)
            return plain(' '.join(c.text for c in cues[first:last]))
        curated = labels.get(number)
        if items and (curated is None or len(curated) != len(items)):
            unlabelled.append(number)
            curated = None
        for order, (title, _, start) in enumerate(items, 1):
            following = next((t for t in starts[order:] if t is not None), None)
            finish = min(following if following is not None else duration, duration)
            length = round(finish - start, 1) if start is not None and finish > start else None
            reading = text_between(start - 1, min(start + EXCERPT_SECONDS, finish)) if length else ''
            opening = text_between(start - 1, min(start + TOPIC_SECONDS, finish)) if length else ''
            excerpt = reading[:EXCERPT_CHARS].rsplit(' ', 1)[0] + '\N{HORIZONTAL ELLIPSIS}' if len(reading) > EXCERPT_CHARS else reading
            if curated:
                sub, *also = curated[order - 1]
            else:
                category = classify(rules, title, opening)[0]
                sub, also = ('other.misc' if category == 'other' else f'{category}.auto'), []
            # Comment segments quote many viewers, so they have no single asker to describe.
            asker = sub != 'show.comments'
            questions.append({'ep': number, 'order': order, 'title': title, 'start': start, 'length': length,
                              'sub': sub, 'also': also, 'age': stated_age(title, opening) if asker else None,
                              'places': mentioned_places(places, f'{title} {reading}') if asker else [],
                              'words': title_words(title, stopwords), 'excerpt': excerpt})
        episodes.append({
            'n': number,
            'video': next((video for _, video, _ in items if video), None),
            'duration': round(duration, 2),
            'speech': round(sum(end - start for start, end in spans), 2),
            'cues': len(cues),
            'words': total,
            'english': latin if originals else None,
            'questions': len(items),
            'firstQuestion': next((t for t in starts if t is not None), None),
            'events': dict(sorted(events.items())),
            'replacement': sum(c.text.count('\N{REPLACEMENT CHARACTER}') for c in cues),
            'minutes': minutes,
            'top': content.most_common(TOP_WORDS),
        })
    for stale in transcripts.glob('episode_*.js'):
        if stale.name not in written:
            stale.unlink()
    count = len(episodes)
    # Romanized spellings of rare words are often recognition noise; English words come through intact.
    def distinctive(word):
        if document_frequency[word] < 2:
            return False
        if english or urdu:
            return english[word] > urdu[word] or document_frequency[word] >= STABLE_SPELLING
        return not GARBLED.search(word)
    for episode in episodes:
        content, total = contents[episode['n']], episode['words'] or 1
        scored = [(-(c / total) * math.log(count / document_frequency[w]), w) for w, c in content.items()
                  if c >= 3 and document_frequency[w] < count and distinctive(w)]
        episode['signature'] = [w for _, w in sorted(scored)[:SIGNATURE_WORDS]]
    language = not unaligned
    vocabulary = [w for w, _ in corpus.most_common(CORPUS_WORDS)]
    known = set(vocabulary)
    for episode in episodes:
        for w, _ in episode['top']:
            if w not in known:
                known.add(w)
                vocabulary.append(w)
    position = {w: i for i, w in enumerate(vocabulary)}
    for episode in episodes:
        episode['top'] = [value for w, c in episode['top'] for value in (position[w], c)]
    data = {
        'meta': {
            'episodes': count,
            'questions': len(questions),
            'cues': sum(e['cues'] for e in episodes),
            'words': sum(e['words'] for e in episodes),
            'seconds': round(sum(e['duration'] for e in episodes), 1),
            'language': language,
            'playlist': PLAYLIST,
        },
        'categories': [{'id': c['id'], 'name': c['name'], 'description': c['description'],
                        'subcategories': c['subcategories'] + ([{'id': f"{c['id']}.auto", 'name': 'Not yet sorted',
                                                                 'description': 'Placed by keywords; add the episode to question_labels.json.'}]
                                                               if any(q['sub'] == f"{c['id']}.auto" for q in questions) else [])}
                       for c in config['categories']],
        'places': [{'name': p['name'], 'region': p['region']} for p in config.get('places', [])],
        'episodes': episodes,
        'questions': questions,
        'vocabulary': vocabulary,
        'vocabularyLanguage': ''.join('e' if english[w] > urdu[w] else 'u' for w in vocabulary) if language else None,
        'corpus': [[position[w], corpus[w], document_frequency[w]] for w in vocabulary[:CORPUS_WORDS]],
        'quality': {
            'unindexed': [e['n'] for e in episodes if not e['questions']],
            'missingTranscripts': sorted(set(index) - {e['n'] for e in episodes}),
            'unaligned': unaligned,
            'unlabelled': unlabelled,
        },
    }
    write_if_changed(output / 'summary.js', f'window.GANJI_DATA = {compact(data)};\n')
    size = sum(p.stat().st_size for p in output.rglob('*.js'))
    print(f'Wrote {output}: {count} episodes, {len(questions):,} questions, {data["meta"]["words"]:,} words ({size / 1e6:.1f} MB).')
    if unaligned and len(unaligned) < count:
        print(f'English/Urdu labels unavailable for {len(unaligned)} episodes without an original Crisper SRT.')
    if unlabelled:
        print(f'Placed by keywords, add to {LABELS.name}: episodes {", ".join(map(str, unlabelled))}.')
    return data


def theme_css(skins=SKINS):
    """CSS custom properties from the first light and first dark skin (by "order") in app/skins/."""
    found = sorted((json.loads(p.read_text(encoding='utf-8')) | {'file': p.name} for p in Path(skins).glob('*.json')),
                   key=lambda skin: skin.get('order', 0))
    light = next((skin for skin in found if not skin.get('dark')), None)
    dark = next((skin for skin in found if skin.get('dark')), None)
    if not light:
        raise ValueError(f'{skins} needs a light skin ("dark": false)')
    def block(skin, indent):
        tokens = {'radius': skin.get('radius', '10px'), **skin['tokens']}
        missing = [t for t in THEME_TOKENS if t not in tokens]
        bad = [k for k, v in tokens.items() if not re.fullmatch(r'[a-z0-9-]+', k) or re.search(r'[;{}<>]', str(v))]
        if missing or bad:
            raise ValueError(f'{skin["file"]}: ' + '; '.join(filter(None, [missing and f'missing tokens {", ".join(missing)}', bad and f'invalid tokens {", ".join(bad)}'])))
        return [f'{indent}color-scheme: {"dark" if skin.get("dark") else "light"};'] + [f'{indent}--{k}: {v};' for k, v in tokens.items()]
    lines = [f'/* Generated by app/tools/build_data.py from app/skins/. Edit the skins, then run bash app/run.sh. */',
             f'/* Light: {light["name"]} ({light["file"]}). Dark: {dark["name"] if dark else "none"}{f" ({dark["file"]})" if dark else ""}. */',
             ':root {', *block(light, '  '), '}']
    if dark:
        lines += ['@media (prefers-color-scheme: dark) {', '  :root:not([data-theme="light"]) {', *block(dark, '    '), '  }', '}',
                  ':root[data-theme="dark"] {', *block(dark, '  '), '}']
    return '\n'.join(lines) + '\n'

def build_theme(skins=SKINS, target=THEME):
    write_if_changed(Path(target), theme_css(skins))


class AppHandler(http.server.SimpleHTTPRequestHandler):
    """Serves app/ the way a static host such as GitHub Pages would."""
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript; charset=utf-8'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_request(self, *args):
        pass

def serve(host, port):
    with http.server.ThreadingHTTPServer((host, port), AppHandler) as server:
        name = 'localhost' if host in ('127.0.0.1', '0.0.0.0', '::', '::1', '') else host
        print(f'App: http://{name}:{server.server_port}/  (Ctrl+C stops the server)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('Stopped.')

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', type=Path, default=ROMAN, help='Roman Urdu SRT folder')
    parser.add_argument('--source', type=Path, default=SOURCE, help='Original Crisper SRT folder (optional)')
    parser.add_argument('--index', type=Path, default=INDEX, help='Markdown question index')
    parser.add_argument('--labels', type=Path, default=LABELS, help='Hand-checked question subcategories')
    parser.add_argument('--output', type=Path, default=APP / 'data', help='Data folder the app reads')
    parser.add_argument('--serve', action='store_true', help='After building, preview app/ at http://localhost:PORT/')
    parser.add_argument('--skip-build', action='store_true', help='Preview the existing data without rebuilding')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        if not args.skip_build:
            build_theme()
            build(args.directory, args.source, args.index, args.output, args.labels)
        if args.serve or args.skip_build:
            serve(args.host, args.port)
        else:
            print('Open app/index.html in a browser, or add --serve to preview it as a website.')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')

if __name__ == '__main__':
    main()
