"""What the model reads: the hand-checked questions and the subtitles of every episode.

Standard library only. Everything comes from files already in the repository, so the training data
can always be rebuilt: docs/episode-index.md (the questions), transcripts-english/ and
transcripts-urdu-roman/ (the text), and app/tools/question_labels.json (the labels).
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / '.shared'))
sys.path.insert(0, str(ROOT / 'app' / 'tools'))
from paths import CACHE, ENGLISH, INDEX, ROMAN, UNREVIEWED
from subtitles import atomic_write, parse, span
from build_data import CONFIG, LABELS, TOPIC_SECONDS, category_rules, keyword_scores, read_index, text_in

MARKER = re.compile(r'\[[A-Za-z]+\]')
WORD = re.compile(r"[a-z]+(?:'[a-z]+)*")


def words(text):
    """The lower-case words of a text, without tags such as [UH]."""
    return WORD.findall(MARKER.sub(' ', text).lower().replace('\N{RIGHT SINGLE QUOTATION MARK}', "'"))


def read_subtitles(roman=ROMAN, english=ENGLISH):
    """{episode: {'roman': [(start second, end second, words)], 'english': [...]}} of every subtitle file."""
    subtitles = {}
    for language, folder in (('roman', roman), ('english', english)):
        for path in sorted(Path(folder).glob('episode_*.srt')):
            cues = [(*span(cue), words(cue.text)) for cue in parse(path.read_text(encoding='utf-8-sig'))]
            subtitles.setdefault(int(path.stem.split('_')[1]), {})[language] = [cue for cue in cues if cue[2]]
    return subtitles


def read_labels(path=LABELS):
    """{episode: [codes of each question]}; the first code of each is its main subcategory."""
    return {int(episode): entries for episode, entries in json.loads(Path(path).read_text(encoding='utf-8')).items()}


def write_labels(labels, path=LABELS):
    """One line per episode, as the file has always been laid out."""
    lines = [f'  "{episode}": {json.dumps(labels[episode], ensure_ascii=False)}' for episode in sorted(labels)]
    atomic_write(path, '{\n' + ',\n'.join(lines) + '\n}\n')


def subcategories(config_path=CONFIG):
    """{code: its name and description}, in the order of the config file."""
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    return {sub['id']: {'name': sub['name'], 'description': sub['description']}
            for category in config['categories'] for sub in category['subcategories']}


def read_questions(index=None, english=ENGLISH, roman=ROMAN):
    """{episode: [{title, opening, answer}]}: the English of each question's first 90 seconds and of its
    whole answer, up to the next question. Roman Urdu where an episode has no English yet, and only the
    title where it has no subtitles at all."""
    index = read_index(INDEX) if index is None else index
    questions = {}
    for episode, items in index.items():
        name = f'episode_{episode:03d}.srt'
        path = next((Path(folder) / name for folder in (english, roman) if (Path(folder) / name).is_file()), None)
        cues = parse(path.read_text(encoding='utf-8-sig')) if path else []
        starts = [span(cue)[0] for cue in cues]
        duration = span(cues[-1])[1] if cues else 0
        times = [start for _, _, start in items]
        found = []
        for order, (title, _, start) in enumerate(items):
            following = next((t for t in times[order + 1:] if t is not None), None)
            finish = min(following if following is not None else duration, duration)
            timed = start is not None and finish > start
            found.append({'title': title,
                          'opening': text_in(cues, starts, start - 1, min(start + TOPIC_SECONDS, finish)) if timed else '',
                          'answer': text_in(cues, starts, start - 1, finish) if timed else ''})
        questions[episode] = found
    return questions


def unreviewed(path=UNREVIEWED):
    """The episodes whose labels are the model's own guesses, not yet checked by a person."""
    return set(json.loads(Path(path).read_text(encoding='utf-8'))) if Path(path).is_file() else set()


def write_unreviewed(episodes, path=UNREVIEWED):
    atomic_write(path, json.dumps(sorted(episodes)) + '\n')


def labelled_questions(questions=None, labels=None, skip=None):
    """Every question a person has checked: {episode, order, title, opening, answer, codes}. The model's own
    guesses are left out, or it would learn from them and be marked by them. So is an episode whose count no
    longer matches the index, since its labels cannot be matched to its questions."""
    questions = read_questions() if questions is None else questions
    labels = read_labels() if labels is None else labels
    skip = unreviewed() if skip is None else skip
    rows = []
    for episode, found in questions.items():
        entries = labels.get(episode, [])
        if episode not in skip and len(entries) == len(found):
            rows += [{'episode': episode, 'order': order, **question, 'codes': entry.split()}
                     for order, (question, entry) in enumerate(zip(found, entries), 1)]
    return rows


def folds(rows, count=10, seed=7):
    """Groups of episodes for testing: a question is never tested by a model trained on its own episode."""
    episodes = sorted({row['episode'] for row in rows})
    random.Random(seed).shuffle(episodes)
    return [set(episodes[k::count]) for k in range(count)]
