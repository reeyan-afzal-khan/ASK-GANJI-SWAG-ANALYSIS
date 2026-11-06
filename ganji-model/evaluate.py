"""How far the Ganji model agrees with labels checked by hand, on episodes it has not seen.

Ten groups of episodes take turns as the test: a model learns from the rest and sorts their questions. Strict
mode also learns the word vectors anew each time without the test episodes, as a brand-new episode would be
met; it takes about 22 minutes on a laptop GPU, and a run that stops carries on from its last finished group. The
word-count baseline is the same test with word counts alone, as a plain nearest-centroid classifier.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np

import ganji_model as G
from corpus import CACHE, folds, read_subtitles
from vectors import train_vectors

RESULTS = Path(__file__).resolve().parent / 'results.json'
BASELINE_KEYWORDS = 0.1
# Common Roman Urdu words and their English, written down before looking at any vectors. No word of this
# list is used in training: it only checks whether the time alignment teaches the two languages together.
TRANSLATIONS = {'shaadi': 'marriage', 'talaq': 'divorce', 'biwi': 'wife', 'shohar': 'husband', 'naukri': 'job', 'paisa': 'money',
                'mohabbat': 'love', 'dost': 'friend', 'ghar': 'house', 'bachay': 'children', 'beti': 'daughter', 'beta': 'son',
                'maa': 'mother', 'baap': 'father', 'bhai': 'brother', 'behen': 'sister', 'mulk': 'country', 'namaz': 'prayer',
                'kitaab': 'book', 'khana': 'food', 'gaari': 'car', 'shehar': 'city', 'zindagi': 'life', 'khushi': 'happiness',
                'darr': 'fear', 'jhoot': 'lie', 'sach': 'truth', 'kaam': 'work', 'bimari': 'disease', 'taleem': 'education'}


def translation_check(vectors, reach=20):
    """How many of the words above have their English among their nearest words."""
    found = [word for word, english in TRANSLATIONS.items() if english in vectors.nearest(word, reach)]
    return {'words': len(TRANSLATIONS), 'reach': reach, 'found': len(found), 'which': found}


def progress_folder(rows):
    """Where a strict run keeps its finished groups. The name depends on this code and these questions, so a
    run only carries on from groups that would come out the same."""
    digest = hashlib.sha256()
    for name in ('evaluate.py', 'ganji_model.py', 'vectors.py'):
        digest.update((Path(__file__).resolve().parent / name).read_bytes())
    digest.update(json.dumps([[row['episode'], row['title'], row['codes'], row['answer']] for row in rows], ensure_ascii=False).encode('utf-8'))
    return CACHE / 'ganji-model' / f'strict-{digest.hexdigest()[:12]}'


def out_of_fold(rows, vectors, prepared, groups, subtitles=None, log=print, progress=None):
    """Scores of every question from models that had not seen its episode, and each model's evidence weights.
    With a progress folder, each finished group is kept there, so that a stopped run carries on from it."""
    model = G.GanjiModel(vectors)
    codes = model.codes
    out = {name: np.zeros((len(rows), len(codes))) for name in ('words', 'untrained', 'model', 'title_only', 'text_only')}
    weights = []
    # The baseline keeps the keywords of the classifier it stands for, which read only the opening.
    opening_keywords = model.keyword_matrix(rows, whole_text=False)
    title_part = [G.EVIDENCE.index(name) for name in ('title_words', 'title_vectors')]
    text_part = [G.EVIDENCE.index(name) for name in ('text_words', 'letter_words', 'text_vectors')]
    for k, held in enumerate(groups):
        train = [i for i, row in enumerate(rows) if row['episode'] not in held]
        test = [i for i, row in enumerate(rows) if row['episode'] in held]
        kept = Path(progress) / f'group_{k}.npz' if progress else None
        if kept and kept.is_file():
            with np.load(kept) as data:
                for name in out:
                    out[name][test] = data[name]
                weights.append(data['weights'])
            if log:
                log(f'group {k + 1}/{len(groups)}: already finished')
            continue
        fold_vectors = vectors
        fold_prepared = prepared
        if subtitles is not None:
            fold_vectors = train_vectors(subtitles, skip=held, log=None)
            fold_prepared = model.with_vectors(prepared, fold_vectors, rows)
        train_rows = [rows[i] for i in train]
        train_part, test_part = G.take(fold_prepared, train), G.take(fold_prepared, test)
        # The baseline: word profiles alone, where a second subject does not count.
        baseline = G.GanjiModel(fold_vectors, codes)
        targets = baseline.targets(train_rows, second=0.0)
        seeds = {baseline.codes.index(code): baseline.word_bag(text) for code, text in baseline.described.items()}
        title_words = G.WordProfiles().fit(train_part['title_bags'], targets, len(codes), seeds)
        text_words = G.WordProfiles().fit(train_part['text_bags'], targets, len(codes))
        out['words'][test] = title_words.scores(test_part['title_bags']) + text_words.scores(test_part['text_bags']) + BASELINE_KEYWORDS * opening_keywords[test]
        untrained = G.GanjiModel(fold_vectors, codes)
        untrained.fit(train_rows, train_part, passes=0, seed=7 + k)
        out['untrained'][test] = untrained.temperature * untrained.scores(test_part)
        fitted = G.GanjiModel(fold_vectors, codes)
        fitted.fit(train_rows, train_part, seed=7 + k)
        evidence = fitted.evidence(test_part)
        out['model'][test] = fitted.temperature * (evidence @ fitted.weights)
        out['title_only'][test] = evidence[:, :, title_part] @ fitted.weights[title_part]
        out['text_only'][test] = evidence[:, :, text_part] @ fitted.weights[text_part]
        weights.append(fitted.weights)
        if kept:
            kept.parent.mkdir(parents=True, exist_ok=True)
            unfinished = kept.with_suffix('.tmp.npz')
            np.savez(unfinished, weights=fitted.weights, **{name: out[name][test] for name in out})
            os.replace(unfinished, kept)
        if log:
            right = (out['model'][test].argmax(1) == np.array([codes.index(rows[i]['codes'][0]) for i in test])).mean()
            log(f'group {k + 1}/{len(groups)}: {len(test)} questions, {right:.1%} of subcategories right')
    return out, codes, np.mean(weights, axis=0)


def agreement(scores, rows, codes, weights=None):
    """How often a set of scores agrees with the labels; weights are per question, for resampling."""
    weights = np.ones(len(rows)) if weights is None else weights
    order = np.argsort(-scores, axis=1)
    top = order[:, 0]
    truth = np.array([codes.index(row['codes'][0]) for row in rows])
    category = np.array([code.split('.')[0] for code in codes])
    total = weights.sum()
    return {'category': float(((category[top] == category[truth]) * weights).sum() / total),
            'subcategory': float(((top == truth) * weights).sum() / total),
            'any_subject': float((np.array([codes[t] in row['codes'] for t, row in zip(top, rows)]) * weights).sum() / total),
            'best_three': float(((order[:, :3] == truth[:, None]).any(1) * weights).sum() / total)}


def resampled(scores_a, scores_b, rows, codes, rounds=2000, seed=7):
    """95% ranges for the model and for its gain over the baseline, resampling whole episodes."""
    rng = np.random.default_rng(seed)
    episodes = sorted({row['episode'] for row in rows})
    position = {episode: i for i, episode in enumerate(episodes)}
    of = np.array([position[row['episode']] for row in rows])
    draws = {'subcategory': [], 'category': [], 'gain_subcategory': [], 'gain_category': []}
    for _ in range(rounds):
        weights = np.bincount(rng.integers(0, len(episodes), len(episodes)), minlength=len(episodes))[of].astype(float)
        a, b = agreement(scores_a, rows, codes, weights), agreement(scores_b, rows, codes, weights)
        draws['subcategory'].append(b['subcategory'])
        draws['category'].append(b['category'])
        draws['gain_subcategory'].append(b['subcategory'] - a['subcategory'])
        draws['gain_category'].append(b['category'] - a['category'])
    return {name: [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] for name, values in draws.items()}


def by_category(scores, rows, codes):
    """Per category: how many it has, how many of them are found, and how many guesses of it are right."""
    top = scores.argmax(1)
    category = [code.split('.')[0] for code in codes]
    truth = [row['codes'][0].split('.')[0] for row in rows]
    guess = [category[t] for t in top]
    table = {}
    for name in sorted(set(category)):
        has = sum(t == name for t in truth)
        guessed = sum(g == name for g in guess)
        right = sum(t == name and g == name for t, g in zip(truth, guess))
        table[name] = {'questions': has, 'found': right / max(has, 1), 'guesses_right': right / max(guessed, 1)}
    return table


def calibrate(scores, rows, codes):
    """How often a guess is right at each level of confidence. Scores are as the model gives them, so a best
    scale near 1 means that its probabilities are honest."""
    truth = np.array([codes.index(row['codes'][0]) for row in rows])
    best, best_loss = None, 1e18
    for scale in np.arange(0.5, 2.01, 0.05):
        p = G.softmax(scale * scores)[np.arange(len(truth)), truth]
        loss = -np.log(np.maximum(p, 1e-12)).mean()
        if loss < best_loss:
            best, best_loss = float(scale), float(loss)
    probabilities = G.softmax(scores)
    top, right = probabilities.max(1), probabilities.argmax(1) == truth
    bands = []
    for low, high in ((0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
        mask = (top >= low) & (top < high)
        bands.append({'from': low, 'to': min(high, 1.0), 'questions': int(mask.sum()), 'right': float(right[mask].mean()) if mask.any() else None})
    sure = {f'{threshold:.2f}': {'share': float((top >= threshold).mean()), 'right': float(right[top >= threshold].mean()) if (top >= threshold).any() else None}
            for threshold in (.3, .4, .5, .6, .7, .8)}
    return {'best_scale': best, 'loss': best_loss, 'bands': bands, 'sure_at': sure}


def overrides(scores, title_scores, rows, codes):
    """How often the whole question and answer changes the title's guess, and which of the two is right then."""
    truth = np.array([codes.index(row['codes'][0]) for row in rows])
    choice, title_choice = scores.argmax(1), title_scores.argmax(1)
    changed = choice != title_choice
    return {'share': float(changed.mean()), 'model_right': float((choice[changed] == truth[changed]).mean()), 'title_right': float((title_choice[changed] == truth[changed]).mean())}


def who_decides(scores, title_scores, text_scores, rows, codes):
    """Where the title and the text, each alone, point to different subcategories: what the answer goes with, how
    often each is right, and what each adds to the margin between the model's best two guesses. The evidence
    weights cannot show this, because a title gives a sharp score and a long text a flat one."""
    truth = np.array([codes.index(row['codes'][0]) for row in rows])
    choice, title, text = scores.argmax(1), title_scores.argmax(1), text_scores.argmax(1)
    differ = title != text
    with_title, with_text = choice[differ] == title[differ], choice[differ] == text[differ]
    order = np.argsort(-scores, axis=1)
    every = np.arange(len(rows))
    margin = lambda part: float((part[every, order[:, 0]] - part[every, order[:, 1]]).mean())
    return {'share': float(differ.mean()),
            'with_title': float(with_title.mean()), 'with_text': float(with_text.mean()), 'with_neither': float((~with_title & ~with_text).mean()),
            'model_right': float((choice[differ] == truth[differ]).mean()),
            'title_right': float((title[differ] == truth[differ]).mean()),
            'text_right': float((text[differ] == truth[differ]).mean()),
            'margin_from_title': margin(title_scores), 'margin_from_text': margin(text_scores)}


def more_text(title_scores, text_scores, rows, codes):
    """What if the text counted for more or less than the model learned (keywords left out): the agreement, and
    how often the answer goes with the text where the two disagree."""
    text = text_scores.argmax(1)
    differ = title_scores.argmax(1) != text
    table = {}
    for scale in (0.5, 1.0, 1.5, 2.0, 3.0):
        mixed = title_scores + scale * text_scores
        table[f'{scale:g}'] = {**agreement(mixed, rows, codes), 'with_text': float((mixed.argmax(1)[differ] == text[differ]).mean())}
    return table


def run(rows, vectors, prepared, strict=False, log=print):
    groups = folds(rows)
    subtitles = read_subtitles() if strict else None
    progress = progress_folder(rows) if strict else None
    scores, codes, weights = out_of_fold(rows, vectors, prepared, groups, subtitles, log, progress)
    if progress:
        shutil.rmtree(progress)
    report = {'questions': len(rows), 'episodes': len({row['episode'] for row in rows}), 'strict': strict,
              'word_counts': agreement(scores['words'], rows, codes),
              'untrained': agreement(scores['untrained'], rows, codes),
              'model': agreement(scores['model'], rows, codes),
              'title_only': agreement(scores['title_only'], rows, codes),
              'text_only': agreement(scores['text_only'], rows, codes),
              'evidence_weights': dict(zip(G.EVIDENCE, [round(float(w), 3) for w in weights])),
              'overrides': overrides(scores['model'], scores['title_only'], rows, codes),
              'who_decides': who_decides(scores['model'], scores['title_only'], scores['text_only'], rows, codes),
              'more_text': more_text(scores['title_only'], scores['text_only'], rows, codes),
              'ranges': resampled(scores['words'], scores['model'], rows, codes),
              'by_category': by_category(scores['model'], rows, codes),
              'calibration': calibrate(scores['model'], rows, codes),
              'translations': translation_check(vectors)}
    return report, scores


def show(report, log=print):
    log(f"{report['questions']:,} questions in {report['episodes']} episodes, each sorted by a model that had not seen its episode"
        f"{' or read it for its word vectors' if report['strict'] else ''}:")
    log(f"{'':28}{'category':>10}{'subcategory':>13}{'any subject':>13}{'best three':>12}")
    for name, label in (('word_counts', 'Word counts (baseline)'), ('title_only', 'Title alone'), ('text_only', 'Question and answer alone'), ('untrained', 'All evidence, untrained'), ('model', 'Ganji model')):
        r = report[name]
        log(f"{label:28}{r['category']:>10.1%}{r['subcategory']:>13.1%}{r['any_subject']:>13.1%}{r['best_three']:>12.1%}")
    ranges = report['ranges']
    log(f"95% range: subcategory {ranges['subcategory'][0]:.1%} to {ranges['subcategory'][1]:.1%}, category {ranges['category'][0]:.1%} to {ranges['category'][1]:.1%}")
    log(f"Gain over the baseline: subcategory {ranges['gain_subcategory'][0]:+.1%} to {ranges['gain_subcategory'][1]:+.1%}, category {ranges['gain_category'][0]:+.1%} to {ranges['gain_category'][1]:+.1%}")
    t = report['translations']
    log(f"Roman Urdu words with their English among their {t['reach']} nearest words: {t['found']} of {t['words']}")
    log('Evidence weights: ' + ', '.join(f"{name.replace('_', ' ')} {weight:.2f}" for name, weight in report['evidence_weights'].items()))
    o = report['overrides']
    log(f"The whole question and answer changes the title's guess on {o['share']:.0%} of questions: right then {o['model_right']:.0%}, where the title would be right {o['title_right']:.0%}")
    d = report['who_decides']
    log(f"Title and text alone differ on {d['share']:.0%} of questions: the answer goes with the title {d['with_title']:.0%}, the text {d['with_text']:.0%}, neither {d['with_neither']:.0%};"
        f" right {d['model_right']:.0%}, where the title alone would be right {d['title_right']:.0%} and the text alone {d['text_right']:.0%}")
    log(f"The margin between its best two guesses: {d['margin_from_title']:.3f} from the title, {d['margin_from_text']:.3f} from the text")
    log('If the text counted more or less, keywords left out:')
    for scale, r in report['more_text'].items():
        log(f"  {scale} times: category {r['category']:.1%}, subcategory {r['subcategory']:.1%}, goes with the text on {r['with_text']:.0%} of differences")
    log(f"Probabilities: best scale {report['calibration']['best_scale']:.2f} (1 means honest); sure at:")
    for threshold, part in report['calibration']['sure_at'].items():
        log(f"  {threshold}: {part['share']:.0%} of questions, {part['right']:.1%} right" if part['right'] is not None else f"  {threshold}: none")


def save(report, path=RESULTS):
    """Results are kept per kind of test, so a quick run does not overwrite a strict one."""
    path = Path(path)
    saved = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    saved['strict' if report['strict'] else 'quick'] = report
    path.write_text(json.dumps(saved, indent=1) + '\n', encoding='utf-8', newline='\n')
