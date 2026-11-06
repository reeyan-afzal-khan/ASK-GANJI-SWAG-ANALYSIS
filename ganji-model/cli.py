"""The commands of the Ganji model. Run them as bash ganji-model/run.sh COMMAND; each takes --help."""
import argparse
import json
import shutil
from pathlib import Path

import corpus
import evaluate as evaluation
import ganji_model as G
from vectors import WordVectors, train_vectors

SAMPLE = ('shaadi', 'talaq', 'biwi', 'naukri', 'mohabbat', 'paisa', 'visa', 'depression')


def pretrain(args):
    vectors = train_vectors(corpus.read_subtitles(args.roman, args.english), aligned=0 if args.no_aligned else 2, passes=args.passes)
    args.save.mkdir(parents=True, exist_ok=True)
    vectors.save(args.save / 'vectors.npz')
    print(f'{len(vectors.vocabulary):,} words from {int(vectors.counts.sum()):,} in the subtitles. Saved in {args.save}')
    for word in SAMPLE:
        print(f'  {word}: {", ".join(vectors.nearest(word))}')
    print('Next: bash ganji-model/run.sh train')


def extra_questions(path):
    """Labelled questions from a file, one JSON object per line: {"title", "text", "label"}."""
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if line.strip():
            item = json.loads(line)
            if not item.get('title') or not (item.get('label') or item.get('labels')):
                raise ValueError(f'{path}, line {number}: needs a title and a label')
            text = item.get('text') or ''
            codes = item.get('labels') or [item['label']]
            rows.append({'episode': 0, 'order': number, 'title': item['title'], 'opening': text[:1200], 'answer': text, 'codes': codes})
    return rows


def train(args):
    rows = corpus.labelled_questions()
    print(f'Learning from {len(rows):,} questions a person has checked')
    model = G.GanjiModel(WordVectors.load(args.save / 'vectors.npz'))
    model.fit(rows, passes=args.passes, log=print)
    model.save(args.save)
    print(f'Saved in {args.save}. Next: bash ganji-model/run.sh evaluate')


def finetune(args):
    rows = corpus.labelled_questions() + (extra_questions(args.data) if args.data else [])
    model = G.GanjiModel.load(args.weights)
    known = len(model.codes)
    print(f'Carrying on from {args.weights} with {len(rows):,} questions (it learned from {model.trained_on:,} before)')
    new = model.fit(rows, passes=args.passes, resume=True, log=print)
    args.save.mkdir(parents=True, exist_ok=True)
    model.save(args.save)
    if args.save.resolve() != args.weights.resolve():
        shutil.copyfile(args.weights / 'vectors.npz', args.save / 'vectors.npz')
    if new:
        print(f'New subcategories, {known} became {len(model.codes)}: {", ".join(new)}')
    print(f'Saved in {args.save}')


def run_evaluation(args):
    rows = corpus.labelled_questions()
    vectors = WordVectors.load(args.weights / 'vectors.npz')
    prepared = G.GanjiModel(vectors).prepare(rows)
    report, _ = evaluation.run(rows, vectors, prepared, strict=args.strict)
    evaluation.show(report)
    # Only the shipped model's results go in the shared file; a trial's stay with its weights.
    path = evaluation.RESULTS if args.weights.resolve() == G.WEIGHTS.resolve() else args.weights / 'results.json'
    evaluation.save(report, path)
    print(f'Saved in {path}')


def predict(args):
    model = G.GanjiModel.load(args.weights)
    names = corpus.subcategories()
    for code, probability in model.predict(args.title, args.text or '', args.top):
        print(f'{probability:6.1%}  {code}  ({names.get(code, {}).get("name", code)})')


def label(args):
    import label as labelling
    labelling.label(args.episodes, args.force, args.review)


def main():
    parser = argparse.ArgumentParser(prog='bash ganji-model/run.sh', description='Train, fine-tune, test and use the Ganji model.')
    commands = parser.add_subparsers(dest='command', required=True)

    command = commands.add_parser('label', help='Sort the questions of new episodes')
    command.add_argument('--episodes', help='Comma-separated episode numbers (default: every episode in the index without labels)')
    command.add_argument('--force', action='store_true', help='Replace the labels of the chosen episodes')
    command.add_argument('--review', action='store_true', help='Go through the questions one by one, to keep or correct each label')
    command.set_defaults(run=label)

    command = commands.add_parser('predict', help='Sort one question')
    command.add_argument('title')
    command.add_argument('text', nargs='?', help='Its text, if any')
    command.add_argument('--top', type=int, default=3)
    command.add_argument('--weights', type=Path, default=G.WEIGHTS)
    command.set_defaults(run=predict)

    command = commands.add_parser('finetune', help='Carry on training from the saved model, on the checked labels and any more you give it')
    command.add_argument('--data', type=Path, help='More labelled questions, one JSON object per line: {"title", "text", "label"}')
    command.add_argument('--passes', type=int, default=3)
    command.add_argument('--weights', type=Path, default=G.WEIGHTS, help='The model to start from')
    command.add_argument('--save', type=Path, default=G.WEIGHTS, help='Where to save the result')
    command.set_defaults(run=finetune)

    command = commands.add_parser('train', help='Train the labelled part again from the start (seconds)')
    command.add_argument('--passes', type=int, default=G.PASSES)
    command.add_argument('--save', type=Path, default=G.WEIGHTS)
    command.set_defaults(run=train)

    command = commands.add_parser('pretrain', help='Learn the word vectors from all the subtitles again (GPU, minutes)')
    command.add_argument('--passes', type=int, default=5)
    command.add_argument('--no-aligned', action='store_true', help='Learn from the English subtitles alone, to measure what the Roman Urdu time line adds')
    command.add_argument('--roman', type=Path, default=corpus.ROMAN, help='Folder of Roman Urdu SRTs, episode_NNN.srt')
    command.add_argument('--english', type=Path, default=corpus.ENGLISH, help='Folder of English SRTs on the same time line')
    command.add_argument('--save', type=Path, default=G.WEIGHTS)
    command.set_defaults(run=pretrain)

    command = commands.add_parser('evaluate', help='Test it on episodes it has not seen, and write results.json')
    command.add_argument('--strict', action='store_true', help='Also learn the word vectors anew without the test episodes (GPU, about 22 minutes; if stopped, run it again to carry on)')
    command.add_argument('--weights', type=Path, default=G.WEIGHTS)
    command.set_defaults(run=run_evaluation)

    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, '\nStopped; finished episodes are saved.\n')


if __name__ == '__main__':
    main()
