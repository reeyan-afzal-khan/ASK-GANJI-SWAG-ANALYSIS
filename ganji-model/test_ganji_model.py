import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cli
import corpus
import evaluate as evaluation
import ganji_model as G
import label as labelling
import vectors as V

TEST_TEMP = HERE.parent / '.cache' / 'test-tmp'
TEST_TEMP.mkdir(parents=True, exist_ok=True)
HAS_TORCH = importlib.util.find_spec('torch') is not None
WEIGHTS_THERE = (G.WEIGHTS / 'model.npz').is_file() and (G.WEIGHTS / 'vectors.npz').is_file()

LOVE = 'my wife wants a divorce after the wedding and the marriage is over'
VISA = 'the embassy refused my visa for canada and the passport came back'
SHOW = 'thanks for the comments everyone these youtube comments are lovely'
WORDS = sorted(set(f'{LOVE} {VISA} {SHOW} talaq biwi shaadi'.split()))


def small_vectors(size=16):
    """Vectors where the words of one subject point the same way, so that meaning can be tested."""
    rng = np.random.default_rng(3)
    topics = {'love': rng.normal(size=size), 'visa': rng.normal(size=size), 'show': rng.normal(size=size)}
    table = []
    for word in WORDS:
        if word in LOVE.split() or word in ('talaq', 'biwi', 'shaadi'):
            topic = topics['love']
        elif word in VISA.split():
            topic = topics['visa']
        else:
            topic = topics['show']
        table.append(topic + 0.3 * rng.normal(size=size))
    return V.WordVectors(WORDS, np.full(len(WORDS), 50.0), np.array(table, dtype=np.float32), np.zeros((64, size), dtype=np.float32))


def question(title, text, codes, episode=1, order=1):
    return {'episode': episode, 'order': order, 'title': title, 'opening': text, 'answer': text, 'codes': codes.split()}


def small_rows():
    rows = []
    for episode in (1, 2, 3, 4):
        rows += [question('My wife wants a divorce', LOVE, 'love.divorce', episode, 1),
                 question('Visa for Canada refused', VISA, 'abroad.visa love.across', episode, 2),
                 question('Youtube Comments', SHOW, 'show.comments', episode, 3)]
    return rows


def fitted(passes=0):
    model = G.GanjiModel(small_vectors())
    model.fit(small_rows(), passes=passes, learn=False)
    return model


def block(number, titles):
    items = '\n'.join(f'{k}. [{title}](https://youtu.be/v{number}?t={k * 100})' for k, title in enumerate(titles, 1))
    return f'<details open>\n<summary><strong>Episode {number:03d}</strong></summary>\n\n{items}\n\n</details>\n\n'


INDEX = '# Index\n\n' + block(1, ['My wife wants a divorce', 'Visa for Canada refused', 'Youtube Comments']) \
    + block(3, ['Wife and husband in court', 'Visa to Canada', 'Youtube Comments'])


def srt(lines):
    """One cue at each question's start: 100, 200 and 300 seconds."""
    stamp = lambda seconds: f'00:{seconds // 60:02d}:{seconds % 60:02d},000'
    return ''.join(f'{k}\n{stamp(k * 100)} --> {stamp(k * 100 + 10)}\n{line}\n\n' for k, line in enumerate(lines, 1))


class VectorTests(unittest.TestCase):
    def test_piece_hash_is_fnv1a(self):
        self.assertEqual(V.piece_hash('a'), 0xE40C292C)
        self.assertEqual(V.piece_hash('foobar'), 0xBF9CF968)

    def test_spellings_share_pieces(self):
        shaadi, shadi = set(V.pieces('shaadi')), set(V.pieces('shadi'))
        self.assertTrue(shaadi & shadi)
        self.assertTrue(all(0 <= bucket < V.BUCKETS for bucket in shaadi))
        self.assertEqual(V.pieces('shaadi'), V.pieces('shaadi'))

    def test_word_never_seen_gets_a_vector_from_its_pieces(self):
        grams = np.eye(64, 8, dtype=np.float32)
        vectors = V.WordVectors(['known'], [10], np.ones((1, 8), dtype=np.float32), grams)
        self.assertTrue((vectors['known'] == 1).all())
        self.assertEqual(vectors['unheard'].shape, (8,))
        self.assertFalse((vectors['unheard'] == 1).all())

    def test_document_gives_rare_words_more_weight(self):
        table = np.array([[1, 0], [0, 1]], dtype=np.float32)
        vectors = V.WordVectors(['common', 'rare'], [1_000_000, 10], table, np.zeros((8, 2), dtype=np.float32))
        mean = vectors.document(['common', 'rare'])
        self.assertGreater(mean[1], mean[0])
        self.assertTrue((vectors.document([]) == 0).all())

    def test_saved_vectors_read_back(self):
        vectors = small_vectors()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path = Path(d) / 'vectors.npz'
            vectors.save(path)
            again = V.WordVectors.load(path)
        self.assertEqual(again.vocabulary, vectors.vocabulary)
        self.assertTrue(np.allclose(again.vectors, vectors.vectors, atol=1e-2))

    def test_aligned_pairs_stay_within_their_time_slice(self):
        rng = np.random.default_rng(1)
        first, first_slices = np.array([1, 2, 3]), np.array([0, 0, 5])
        second, second_slices = np.array([10, 11, 12]), np.array([0, 1, 7])
        pairs = np.concatenate(V.aligned_pairs(first, first_slices, second, second_slices, rng, count=3))
        self.assertEqual({tuple(pair) for pair in pairs.tolist()}, {(1, 10), (2, 10)})

    def test_neighbour_pairs_stay_within_the_window(self):
        rng = np.random.default_rng(1)
        tokens = np.arange(50, dtype=np.int32)
        pairs = np.concatenate(V.neighbour_pairs(tokens, rng, window=3))
        self.assertTrue((np.abs(pairs[:, 0] - pairs[:, 1]) <= 3).all())
        self.assertTrue((pairs[:, 0] != pairs[:, 1]).all())

    def test_english_shapes_the_space_and_roman_urdu_is_mapped_onto_it(self):
        rng = np.random.default_rng(1)
        roman, english = np.arange(0, 40, dtype=np.int32), np.arange(100, 140, dtype=np.int32)
        slices = np.repeat(np.arange(4, dtype=np.int32), 10)
        streams = [{'roman': (roman, slices), 'english': (english, slices)}]
        keep = np.ones(200)
        alone = V.training_pairs(streams, keep, rng, aligned=0)
        self.assertTrue((alone >= 100).all())
        both = V.training_pairs(streams, keep, rng, aligned=2)
        # Every context is English; a Roman Urdu word learns only from the English of the same moment.
        self.assertTrue((both[:, 1] >= 100).all())
        learners = both[both[:, 0] < 100]
        self.assertGreater(len(learners), 0)
        self.assertTrue((learners[:, 0] // 10 == (learners[:, 1] - 100) // 10).all())

    def test_an_episode_without_english_teaches_nothing(self):
        rng = np.random.default_rng(1)
        ids, slices = np.arange(0, 40, dtype=np.int32), np.zeros(40, dtype=np.int32)
        pairs = V.training_pairs([{'roman': (ids, slices)}, {'english': (ids, slices)}], np.ones(40), rng)
        self.assertGreater(len(pairs), 0)

    @unittest.skipUnless(HAS_TORCH, 'needs torch')
    def test_training_gives_every_word_a_vector(self):
        cue = lambda start, words: (start, start + 5.0, words)
        subtitles = {n: {'roman': [cue(k * 10.0, 'shaadi ka rishta'.split()) for k in range(20)],
                         'english': [cue(k * 10.0, 'the marriage proposal'.split()) for k in range(20)]} for n in (1, 2)}
        vectors = V.train_vectors(subtitles, skip={2}, passes=1, log=None)
        self.assertEqual(set(vectors.vocabulary), {'shaadi', 'ka', 'rishta', 'the', 'marriage', 'proposal'})
        self.assertEqual(vectors.vectors.shape, (6, V.DIMENSIONS))
        self.assertEqual(vectors.counts.sum(), 120)
        english_only = V.train_vectors(subtitles, aligned=0, passes=1, log=None)
        self.assertEqual(set(english_only.vocabulary), {'the', 'marriage', 'proposal'})


class CorpusTests(unittest.TestCase):
    def test_real_labels_file_is_written_back_unchanged(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            copy = Path(d) / 'labels.json'
            corpus.write_labels(corpus.read_labels(), copy)
            self.assertEqual(copy.read_bytes(), corpus.LABELS.read_bytes())

    def test_words_leave_out_tags(self):
        self.assertEqual(corpus.words("Hi [UH] I\N{RIGHT SINGLE QUOTATION MARK}m fine, 22."), ['hi', "i'm", 'fine'])

    def test_questions_are_cut_at_the_next_question(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            (root / 'en').mkdir()
            (root / 'en' / 'episode_001.srt').write_text(srt(['First answer.', 'Second answer.', 'Third answer.']), encoding='utf-8')
            (root / 'index.md').write_text(INDEX, encoding='utf-8')
            found = corpus.read_questions(corpus.read_index(root / 'index.md'), root / 'en', root / 'none')
        self.assertEqual([q['answer'] for q in found[1]], ['First answer.', 'Second answer.', 'Third answer.'])
        self.assertEqual(found[3][0]['answer'], '')

    def test_the_models_own_guesses_are_not_learned_from(self):
        questions = {1: [{'title': 'A', 'opening': '', 'answer': ''}], 2: [{'title': 'B', 'opening': '', 'answer': ''}], 3: [{'title': 'C', 'opening': '', 'answer': ''}, {'title': 'D', 'opening': '', 'answer': ''}]}
        labels = {1: ['love.divorce'], 2: ['abroad.visa'], 3: ['show.comments']}
        rows = corpus.labelled_questions(questions, labels, skip={2})
        self.assertEqual([row['title'] for row in rows], ['A'])

    def test_groups_cover_every_episode_once(self):
        groups = corpus.folds(small_rows() + [question('x', 'y', 'love.divorce', 9)], count=2)
        self.assertEqual(sorted(e for group in groups for e in group), [1, 2, 3, 4, 9])


class ModelTests(unittest.TestCase):
    def test_sorts_by_words(self):
        best, *_ = fitted().predict('My wife wants a divorce', LOVE)
        self.assertEqual(best[0], 'love.divorce')

    def test_sorts_by_meaning_when_no_word_is_shared(self):
        # None of these words is in the training titles or answers, only in the vectors.
        best, *_ = fitted().predict('talaq biwi shaadi', '')
        self.assertTrue(best[0].startswith('love.'), best)

    def test_the_text_decides_when_the_title_says_nothing(self):
        best, *_ = fitted().predict('A question from a viewer', LOVE)
        self.assertTrue(best[0].startswith('love.'), best)
        best, *_ = fitted().predict('A question from a viewer', VISA)
        self.assertTrue(best[0].startswith('abroad.'), best)

    def test_keywords_read_the_whole_text(self):
        model = G.GanjiModel(small_vectors())
        late = 'nothing much at first ' * 50 + 'my visa and my passport'
        whole, opening = (model.keyword_matrix([{'title': 'A question', 'answer': late, 'opening': 'nothing much at first'}], whole_text=flag) for flag in (True, False))
        self.assertGreater(whole[0, model.codes.index('abroad.visa')], 0)
        self.assertEqual(opening[0, model.codes.index('abroad.visa')], 0)

    def test_the_letter_is_taken_from_the_text_when_not_given(self):
        model = G.GanjiModel(small_vectors())
        bags = model.prepare([{'title': 'A', 'answer': 'embassy refused'}, {'title': 'B', 'answer': 'embassy', 'opening': 'wedding'}])['letter_bags']
        self.assertIn('embassy', bags[0])
        self.assertEqual(list(bags[1]), ['wedding'])

    @unittest.skipUnless(HAS_TORCH, 'needs torch')
    def test_evidence_weights_are_learned_and_never_negative(self):
        model = G.GanjiModel(small_vectors())
        model.fit(small_rows(), passes=0)
        self.assertEqual(len(model.weights), len(G.EVIDENCE))
        self.assertTrue((model.weights > 0).all())
        self.assertFalse(np.allclose(model.weights, G.STARTING_WEIGHTS))
        self.assertGreater(model.temperature, 0)
        self.assertEqual(model.predict('My wife wants a divorce', LOVE)[0][0], 'love.divorce')

    def test_one_episode_keeps_the_starting_weights(self):
        rows = [dict(row, episode=1) for row in small_rows()]
        model = G.GanjiModel(small_vectors())
        model.fit(rows, passes=0)
        self.assertTrue(np.allclose(model.weights, G.STARTING_WEIGHTS))

    def test_probabilities_add_up(self):
        model = fitted()
        ranked = model.rank(model.prepare(small_rows()[:1]))[0]
        self.assertAlmostEqual(sum(p for p, _ in ranked), 1.0, places=4)
        self.assertEqual(len(ranked), len(model.codes))
        self.assertEqual([p for p, _ in ranked], sorted((p for p, _ in ranked), reverse=True))

    def test_second_subject_counts_towards_its_profile(self):
        model = fitted()
        self.assertGreater(np.linalg.norm(model.profiles['title'][model.codes.index('love.across')]), 0.5)
        self.assertLess(np.linalg.norm(model.profiles['title'][model.codes.index('money.scam')]), 0.5)

    def test_saved_model_scores_the_same(self):
        model = fitted()
        prepared = model.prepare(small_rows()[:3])
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            model.vectors.save(Path(d) / 'vectors.npz')
            model.save(d)
            again = G.GanjiModel.load(d)
        self.assertEqual(again.codes, model.codes)
        self.assertEqual(again.trained_on, 12)
        self.assertEqual(again.temperature, model.temperature)
        self.assertTrue(np.allclose(again.weights, model.weights))
        self.assertTrue(np.allclose(again.scores(again.prepare(small_rows()[:3])), model.scores(prepared), atol=2e-2))

    def test_empty_text_does_not_break_it(self):
        self.assertEqual(len(fitted().predict('zzz qqq', '', top=2)), 2)

    @unittest.skipUnless(HAS_TORCH, 'needs torch')
    def test_training_keeps_it_right_and_moves_the_vector_side(self):
        model = fitted(passes=2)
        self.assertEqual(model.predict('My wife wants a divorce', LOVE)[0][0], 'love.divorce')
        self.assertFalse(np.allclose(model.projection['title'], np.eye(16), atol=1e-6))

    def test_fine_tuning_adds_a_new_subcategory_and_keeps_the_old(self):
        model = fitted()
        before = list(model.codes)
        extra = [question('Should I buy gold coins', 'gold coins and silver coins', 'money.gold', 9, k) for k in range(1, 4)]
        new = model.fit(small_rows() + extra, passes=0, resume=True)
        self.assertEqual(new, ['money.gold'])
        self.assertEqual(model.codes, before + ['money.gold'])
        self.assertEqual(model.predict('Should I buy gold coins', 'gold coins')[0][0], 'money.gold')
        self.assertEqual(model.predict('My wife wants a divorce', LOVE)[0][0], 'love.divorce')

    @unittest.skipUnless(HAS_TORCH, 'needs torch')
    def test_fine_tuning_carries_on_from_the_trained_state(self):
        model = fitted(passes=1)
        trained = model.projection['title'].copy()
        model.fit(small_rows(), passes=0, resume=True)
        self.assertTrue(np.allclose(model.projection['title'], trained))
        model.fit(small_rows(), passes=1, resume=True)
        self.assertFalse(np.allclose(model.projection['title'], trained, atol=1e-7))

    def test_extra_questions_are_read_and_checked(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path = Path(d) / 'extra.jsonl'
            path.write_text('{"title": "A", "text": "b", "label": "love.divorce"}\n\n{"title": "C", "labels": ["love.dating", "mind.growth"]}\n', encoding='utf-8')
            rows = cli.extra_questions(path)
            self.assertEqual([row['codes'] for row in rows], [['love.divorce'], ['love.dating', 'mind.growth']])
            path.write_text('{"title": "No label"}\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                cli.extra_questions(path)


class EvaluationTests(unittest.TestCase):
    ROWS = [question('A', '', 'love.divorce love.rishta', 1), question('B', '', 'abroad.visa', 2), question('C', '', 'abroad.visa', 3), question('D', '', 'show.comments', 4)]
    CODES = ['love.divorce', 'love.rishta', 'abroad.visa', 'abroad.move', 'show.comments']

    def scores(self):
        s = np.zeros((4, 5))
        s[0, 1] = 2; s[0, 0] = 1     # a second subject: right category, one of its subjects
        s[1, 2] = 1                  # right
        s[2, 3] = 1; s[2, 2] = 0.5   # right category only
        s[3, 0] = 1; s[3, 4] = -1    # wrong, and last of all
        return s

    def test_agreement(self):
        r = evaluation.agreement(self.scores(), self.ROWS, self.CODES)
        self.assertEqual((r['subcategory'], r['category'], r['any_subject']), (0.25, 0.75, 0.5))
        self.assertEqual(r['best_three'], 0.75)

    def test_by_category_counts(self):
        table = evaluation.by_category(self.scores(), self.ROWS, self.CODES)
        self.assertEqual(table['abroad'], {'questions': 2, 'found': 1.0, 'guesses_right': 1.0})
        self.assertEqual(table['show']['found'], 0.0)
        self.assertEqual(table['love']['guesses_right'], 0.5)

    def test_ranges_hold_the_measure(self):
        ranges = evaluation.resampled(self.scores() * 0, self.scores(), self.ROWS, self.CODES, rounds=50)
        self.assertLessEqual(ranges['subcategory'][0], ranges['subcategory'][1])
        self.assertEqual(set(ranges), {'subcategory', 'category', 'gain_subcategory', 'gain_category'})

    def test_calibration_checks_the_probabilities(self):
        out = evaluation.calibrate(self.scores(), self.ROWS, self.CODES)
        self.assertGreater(out['best_scale'], 0)
        self.assertEqual(sum(band['questions'] for band in out['bands']), 4)

    def test_overrides_count_where_the_text_changes_the_titles_guess(self):
        title = np.zeros((4, 5))
        title[:, 3] = 1    # the title says abroad.move every time: wrong for all four
        out = evaluation.overrides(self.scores(), title, self.ROWS, self.CODES)
        self.assertEqual(out, {'share': 0.75, 'model_right': 1 / 3, 'title_right': 0.0})

    def title_and_text(self):
        title, text = np.zeros((4, 5)), np.zeros((4, 5))
        title[:, 2] = 1          # the title says abroad.visa every time
        text[[0, 1], 2] = 0.5    # the text agrees on the first two
        text[[2, 3], 4] = 0.5    # and says show.comments on the others
        return title, text

    def test_who_decides_counts_what_the_answer_goes_with(self):
        final = np.zeros((4, 5))
        final[:, 0] = 0.5                       # the second guess of every question
        final[[0, 1, 2], 2] = 1; final[3, 4] = 1   # with the title on question 3, with the text on question 4
        out = evaluation.who_decides(final, *self.title_and_text(), self.ROWS, self.CODES)
        self.assertEqual((out['share'], out['with_title'], out['with_text'], out['with_neither']), (0.5, 0.5, 0.5, 0.0))
        self.assertEqual((out['model_right'], out['title_right'], out['text_right']), (1.0, 0.5, 0.5))
        self.assertEqual((out['margin_from_title'], out['margin_from_text']), (0.75, 0.375))

    def test_more_text_moves_the_answer_towards_the_text(self):
        table = evaluation.more_text(*self.title_and_text(), self.ROWS, self.CODES)
        self.assertEqual((table['1']['with_text'], table['3']['with_text']), (0.0, 1.0))
        self.assertIn('subcategory', table['1.5'])

    @unittest.skipUnless(HAS_TORCH, 'needs torch')
    def test_a_stopped_run_carries_on_from_its_finished_groups(self):
        rows, vectors = small_rows(), small_vectors()
        prepared = G.GanjiModel(vectors).prepare(rows)
        groups = corpus.folds(rows, count=2)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            first, _, weights = evaluation.out_of_fold(rows, vectors, prepared, groups, log=None, progress=d)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ['group_0.npz', 'group_1.npz'])
            with patch.object(G.GanjiModel, 'fit', side_effect=AssertionError('finished groups must not train again')):
                again, _, weights_again = evaluation.out_of_fold(rows, vectors, prepared, groups, log=None, progress=d)
        self.assertTrue(all(np.array_equal(first[name], again[name]) for name in first))
        self.assertTrue(np.allclose(weights, weights_again))

    def test_saved_results_keep_the_other_kind_of_test(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path = Path(d) / 'results.json'
            evaluation.save({'strict': True, 'a': 1}, path)
            evaluation.save({'strict': False, 'a': 2}, path)
            saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((saved['strict']['a'], saved['quick']['a']), (1, 2))


class LabelTests(unittest.TestCase):
    def fixture(self, root, labels=None):
        (root / 'index.md').write_text(INDEX, encoding='utf-8')
        corpus.write_labels(labels if labels is not None else {1: ['love.divorce', 'abroad.visa', 'show.comments']}, root / 'labels.json')
        return {3: [{'title': title, 'opening': text, 'answer': text} for title, text in (('Wife and husband in court', LOVE), ('Visa to Canada', VISA), ('Youtube Comments', SHOW))]}

    def run_label(self, root, questions, **options):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            labelling.label(options.pop('episodes', None), options.pop('force', False), options.pop('review', False), root / 'index.md', root / 'labels.json', root / 'unreviewed.json', fitted(), questions)
        return out.getvalue(), corpus.read_labels(root / 'labels.json'), corpus.unreviewed(root / 'unreviewed.json')

    def test_new_episode_is_sorted_and_noted_as_unchecked(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            printed, labels, guessed = self.run_label(root, self.fixture(root))
            self.assertEqual(labels[3], ['love.divorce', 'abroad.visa', 'show.comments'])
            self.assertEqual(labels[1], ['love.divorce', 'abroad.visa', 'show.comments'])
            self.assertEqual(guessed, {3})
            self.assertIn('Episode 3: 3 questions', printed)
            self.assertIn('Nothing to label', self.run_label(root, {})[0])

    def test_labels_there_are_kept_unless_forced(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            questions = self.fixture(root, {1: ['other.misc'] * 3, 3: ['other.misc'] * 3})
            self.assertEqual(self.run_label(root, questions)[1][3], ['other.misc'] * 3)
            labels = self.run_label(root, questions, episodes='3', force=True)[1]
            self.assertEqual(labels[3][1], 'abroad.visa')
            self.assertEqual(labels[1], ['other.misc'] * 3)

    def test_count_that_differs_from_the_index_is_reported_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            questions = self.fixture(root, {1: ['other.misc'] * 3, 3: ['other.misc']})
            printed, labels, _ = self.run_label(root, questions)
            self.assertIn('Episode 3 has 1 labels but 3 questions', printed)
            self.assertEqual(labels[3], ['other.misc'])

    def test_unknown_episode_is_an_error(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                self.run_label(root, self.fixture(root), episodes='9')

    def test_review_keeps_corrects_and_stops(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root = Path(d)
            questions = self.fixture(root)
            # Keep the first, type codes for the second, then stop: the rest stay as guessed and it stays unchecked.
            with patch('builtins.input', side_effect=['', 'abroad.life society.world', 'q']):
                _, labels, guessed = self.run_label(root, questions, episodes='3', review=True)
            self.assertEqual(labels[3], ['love.divorce', 'abroad.life society.world', 'show.comments'])
            self.assertEqual(guessed, {3})
            # A number picks from the list and a wrong code is asked again; going through to the end checks it.
            with patch('builtins.input', side_effect=['nonsense.code', '1', '', '']):
                _, labels, guessed = self.run_label(root, questions, episodes='3', review=True)
            self.assertEqual(labels[3][1], 'abroad.life society.world')
            self.assertEqual(guessed, set())


@unittest.skipUnless(WEIGHTS_THERE, 'the model has not been trained')
class ShippedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = G.GanjiModel.load()

    def test_knows_every_subcategory(self):
        self.assertTrue(set(corpus.subcategories()) <= set(self.model.codes))

    def test_plain_questions_land_in_their_category(self):
        for title, category in (('Should I move to Canada on a student visa?', 'abroad'), ('My husband is cheating on me and I want a divorce', 'love'),
                                ('Youtube Comments', 'show'), ('I lost my job and my boss is terrible', 'career')):
            self.assertEqual(self.model.predict(title)[0][0].split('.')[0], category, title)

    def test_learned_the_two_languages_together(self):
        self.assertGreaterEqual(evaluation.translation_check(self.model.vectors)['found'], 15)


if __name__ == '__main__':
    unittest.main()
