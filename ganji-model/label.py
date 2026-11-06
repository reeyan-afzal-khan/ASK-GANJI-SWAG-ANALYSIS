"""Sort the questions of new episodes with the Ganji model, and let a person check them.

Guesses go to app/tools/question_labels.json, one line per episode as a person would write it, and the episode
is noted in unreviewed.json until someone goes through it with --review. An episode that has labels is never
changed unless told to with --force.
"""
from pathlib import Path

import ganji_model as G
from corpus import INDEX, LABELS, read_index, read_labels, read_questions, subcategories, unreviewed, write_labels, write_unreviewed


def is_sure(ranked):
    return ranked[0][0] >= G.SURE


def clip(text, limit=280):
    return text[:limit].rsplit(' ', 1)[0] + '…' if len(text) > limit else text


def review_question(episode, order, count, question, ranked, current, names):
    """Show one question and ask about it. Returns its codes, or None to stop."""
    print(f'\nEpisode {episode}, question {order} of {count}: {question["title"]}')
    if question['opening']:
        print(f'  {clip(question["opening"])}')
    print(f'  Now: {" ".join(current)} ({", ".join(names.get(code, code) for code in current)})')
    choices = [code for _, code in ranked[:5]]
    for number, (probability, code) in enumerate(ranked[:5], 1):
        print(f'  {number}. {code} ({names.get(code, code)}) {probability:.0%}')
    while True:
        answer = input('  Enter keeps it. Or a number, codes such as "love.rishta career.path", ? for all codes, q to stop: ').strip()
        if not answer:
            return current
        if answer.lower() == 'q':
            return None
        if answer == '?':
            print('\n'.join(f'  {code} ({name})' for code, name in names.items()))
        elif answer.isdigit() and 1 <= int(answer) <= len(choices):
            return [choices[int(answer) - 1]]
        elif all(code in names for code in answer.split()):
            return answer.split()
        else:
            print('  Not a code. Type ? to list them.')


def label(episodes=None, force=False, review=False, index_path=INDEX, labels_path=LABELS, unreviewed_path=None, model=None, questions=None):
    """Label the chosen episodes, or else every episode in the index without labels."""
    names = {code: sub['name'] for code, sub in subcategories().items()}
    index, labels = read_index(index_path), read_labels(labels_path)
    guessed = unreviewed(unreviewed_path) if unreviewed_path else unreviewed()
    chosen = sorted(int(n) for n in episodes.split(',')) if episodes else sorted(index)
    missing = [n for n in chosen if not index.get(n)]
    if episodes and missing:
        raise ValueError(f'not in {Path(index_path).name}: episodes {", ".join(map(str, missing))}')
    # Chosen for --review, an episode keeps its labels as the starting point.
    todo = [n for n in chosen if index.get(n) and (n not in labels or force or (review and episodes))]
    for n in chosen:
        if n in labels and n not in todo and len(labels[n]) != len(index[n]):
            print(f'Episode {n} has {len(labels[n])} labels but {len(index[n])} questions in the index. Label it again with --episodes {n} --force.')
    if not todo:
        print('Nothing to label: every question in the index has its label.')
        return
    questions = read_questions(index) if questions is None else questions
    model = G.GanjiModel.load() if model is None else model
    stopped = False
    for episode in todo:
        print(f'Episode {episode}: {len(index[episode])} questions')
        guessing = episode not in labels or force
        ranked_all = model.rank(model.prepare(questions[episode]))
        entries, doubtful = [], 0
        for order, (question, ranked) in enumerate(zip(questions[episode], ranked_all), 1):
            codes = [ranked[0][1]] if guessing else labels[episode][order - 1].split()
            if review:
                if not stopped:
                    answer = review_question(episode, order, len(questions[episode]), question, ranked, codes, names)
                    stopped = answer is None
                    codes = codes if stopped else answer
            else:
                doubtful += not is_sure(ranked)
                print(f'  {order:2}. {question["title"][:58]:58} {" ".join(codes)} {ranked[0][0]:.0%}{"" if is_sure(ranked) else "  (unsure)"}')
            entries.append(' '.join(codes))
        labels[episode] = entries
        write_labels(labels, labels_path)
        if review and not stopped:
            guessed.discard(episode)
        elif guessing:
            guessed.add(episode)
        write_unreviewed(guessed, unreviewed_path) if unreviewed_path else write_unreviewed(guessed)
        if doubtful:
            print(f'  {doubtful} unsure. To check them: bash ganji-model/run.sh label --review --episodes {episode}')
    print(f'Saved in {Path(labels_path).name}. Next: bash app/run.sh')
