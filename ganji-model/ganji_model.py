"""The Ganji model: sorts a viewer's question into one of the show's subcategories.

It reads the whole question and answer in English: the title, the letter as it is read out, and everything said
until the next question. Each subcategory has a profile, built from its labelled questions, and a question is
weighed against it on six kinds of evidence:

    title words, text words, letter words    tf-idf of each part (the title with its word pairs too)
    title vectors, text vectors              the meaning of each, from word vectors of the show's subtitles (vectors.py)
    keywords                                 the lists in app/tools/config.json, over the whole text

Training has three parts. The profiles are means of their questions. The vector side then trains for a few
passes: a learned projection and the profiles themselves, with a pull back towards where they started, because
1,400 questions overfit quickly. Last, the model learns a weight for each kind of evidence, from questions each
scored by a model that had not seen its episode, so that nothing gets credit for merely fitting its training data.

Predicting needs only numpy. Training and fine-tuning need torch too, and are quick even without a GPU.
"""
import collections
import json
import math
from pathlib import Path

import numpy as np

from corpus import CONFIG, category_rules, folds, keyword_scores, subcategories, words
from vectors import WordVectors

WEIGHTS = Path(__file__).resolve().parent / 'weights'
EVIDENCE = ('title_words', 'text_words', 'letter_words', 'title_vectors', 'text_vectors', 'keywords')
STARTING_WEIGHTS = (0.9, 0.9, 1.0, 0.45, 0.3, 0.1)   # used until weights are learned; about what is learned
STARTING_TEMPERATURE = 14.0
VIEWS = ('title', 'text')
SECOND_SUBJECT = 0.25   # how much a question counts towards the profile of its second subject
CROSS_FIT = 5           # groups of episodes for learning the evidence weights
PASSES = 5              # training stops early on purpose: more passes overfit
RATE = 5e-4
BATCH = 64
DROPOUT = 0.3
MAIN_SUBJECT = 0.8      # the share of a question's training target on its main subject
CATEGORY_LOSS = 0.5     # how much getting the category right counts next to the subcategory
PULL = 1e-3             # the pull back towards the starting point
SCALE = 16.0
SURE = 0.6              # a guess at least this likely is called sure, see results.json


def fold(word):
    """Plurals count as their singular: visas as visa, countries as country."""
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if word.endswith('s') and len(word) > 3 and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def softmax(scores):
    scores = scores - scores.max(axis=-1, keepdims=True)
    exponent = np.exp(scores)
    return exponent / exponent.sum(axis=-1, keepdims=True)


def unit(matrix):
    return matrix / np.maximum(np.linalg.norm(matrix, axis=-1, keepdims=True), 1e-9)


def take(prepared, chosen):
    """The prepared questions at the given positions."""
    return {name: [value[i] for i in chosen] if isinstance(value, list) else value[chosen] for name, value in prepared.items()}


class WordProfiles:
    """Tf-idf vectors of one kind of text, added up per subcategory: nearest centroid."""

    def fit(self, bags, targets, classes, seeds=None):
        """bags: a Counter per question; targets: [(class, weight)] per question; seeds: more bags per class."""
        df = collections.Counter(word for bag in bags for word in bag)
        self.words = list(df)
        self.index = {word: i for i, word in enumerate(self.words)}
        self.idf = np.array([math.log((1 + len(bags)) / (1 + df[word])) + 1 for word in self.words], dtype=np.float32)
        profiles = np.zeros((classes, len(self.words)), dtype=np.float32)
        for bag, target in zip(bags, targets):
            ids, values = self.vector(bag)
            for code, weight in target:
                profiles[code, ids] += weight * values
        for code, bag in (seeds or {}).items():
            ids, values = self.vector(bag)
            profiles[code, ids] += values
        self.profiles = unit(profiles)
        return self

    def vector(self, bag):
        ids = np.array([self.index[word] for word in bag if word in self.index], dtype=np.int64)
        if not len(ids):
            return ids, np.zeros(0, dtype=np.float32)
        counts = np.array([bag[word] for word in bag if word in self.index], dtype=np.float32)
        values = (1 + np.log(counts)) * self.idf[ids]
        return ids, values / max(float(np.linalg.norm(values)), 1e-9)

    def scores(self, bags):
        out = np.zeros((len(bags), self.profiles.shape[0]), dtype=np.float32)
        for row, bag in enumerate(bags):
            ids, values = self.vector(bag)
            if len(ids):
                out[row] = self.profiles[:, ids] @ values
        return out


class GanjiModel:
    def __init__(self, vectors, codes=None, config_path=CONFIG):
        self.vectors = vectors
        self.config_path = config_path
        self.codes = list(codes) if codes is not None else list(subcategories(config_path))
        config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        self.stopwords = set(config['stopwords'])
        self.rules = category_rules(config)
        self.described = {code: f"{sub['name']} {sub['description']}" for code, sub in subcategories(config_path).items()}
        self.title_words, self.text_words, self.letter_words = None, None, None
        self.common = {}       # for each view, the direction all documents share, removed before comparing
        self.projection = {}
        self.profiles = {}
        self.weights = np.array(STARTING_WEIGHTS, dtype=np.float32)
        self.temperature = STARTING_TEMPERATURE
        self.trained_on = 0

    # ---------- Reading questions ----------
    def word_bag(self, text):
        return collections.Counter(fold(w) for w in words(text) if len(w) > 2 and w not in self.stopwords)

    def title_bag(self, text):
        """A title is short, so its pairs of words count too, small words included: "should_move", "my_father"."""
        every = [fold(w) for w in words(text) if len(w) > 1]
        bag = self.word_bag(text)
        bag.update(f'{a}_{b}' for a, b in zip(every, every[1:]))
        return bag

    def document_vectors(self, rows, vectors, field):
        return np.stack([vectors.document([w for w in words(row.get(field) or '') if len(w) > 1]) for row in rows])

    def prepare(self, rows):
        """Everything the model needs from questions ({title, answer, opening}), worked out once. The answer is
        the English of the whole question and answer, and the opening is the part with the letter."""
        return {'title_bags': [self.title_bag(row['title']) for row in rows],
                'text_bags': [self.word_bag(row.get('answer') or '') for row in rows],
                'letter_bags': [self.word_bag(row.get('opening') or (row.get('answer') or '')[:1200]) for row in rows],
                'title': self.document_vectors(rows, self.vectors, 'title'),
                'text': self.document_vectors(rows, self.vectors, 'answer'),
                'keywords': self.keyword_matrix(rows)}

    def keyword_matrix(self, rows, whole_text=True):
        out = np.zeros((len(rows), len(self.codes)), dtype=np.float32)
        for row, question in enumerate(rows):
            text = question.get('answer') if whole_text else question.get('opening')
            hints = keyword_scores(self.rules, question['title'], text or '')
            best = max(hints.values(), default=0) or 1
            for c, code in enumerate(self.codes):
                out[row, c] = hints.get(code.split('.')[0], 0) / best
        return out

    def with_vectors(self, prepared, vectors, rows):
        """The same prepared questions, read with other word vectors (for testing without their episodes)."""
        return {**prepared, 'title': self.document_vectors(rows, vectors, 'title'), 'text': self.document_vectors(rows, vectors, 'answer')}

    # ---------- Training ----------
    def targets(self, rows, second=SECOND_SUBJECT):
        """[(class, weight)] per question, from its main subject and any second subjects."""
        out = []
        for row in rows:
            main, *others = row['codes']
            others = [code for code in others if code in self.codes]
            out.append([(self.codes.index(main), 1.0)] + [(self.codes.index(code), second / len(others)) for code in others])
        return out

    def add_labels(self, rows):
        """Labels the model has not met join it, so a new subcategory needs only some labelled questions."""
        new = sorted({row['codes'][0] for row in rows} - set(self.codes))
        if self.profiles and new:
            for view in self.profiles:
                self.profiles[view] = np.vstack([self.profiles[view], np.zeros((len(new), self.profiles[view].shape[1]), dtype=np.float32)])
        self.codes += new
        return new

    def vector_profiles(self, matrix, targets):
        profiles = np.zeros((len(self.codes), matrix.shape[1]), dtype=np.float32)
        for row, target in zip(matrix, targets):
            for code, weight in target:
                profiles[code] += weight * row
        return unit(profiles)

    def view_matrix(self, view, prepared):
        """Document vectors with the direction they all share taken out, at length one."""
        x = prepared[view]
        return unit(x - np.outer(x @ self.common[view], self.common[view]))

    def fit(self, rows, prepared=None, passes=PASSES, resume=False, learn=True, seed=7, log=None):
        """Learn from labelled questions. With resume, carries on from the current state, and the evidence
        weights stay as they are. Returns the labels it had not met."""
        prepared = self.prepare(rows) if prepared is None else prepared
        new = self.add_labels(rows)
        if learn and not resume:
            self.learn_weights(rows, prepared, passes, seed, log)
        targets = self.targets(rows)
        seeds = {self.codes.index(code): self.word_bag(text) for code, text in self.described.items() if code in self.codes}
        self.title_words = WordProfiles().fit(prepared['title_bags'], targets, len(self.codes), seeds)
        self.text_words = WordProfiles().fit(prepared['text_bags'], targets, len(self.codes))
        self.letter_words = WordProfiles().fit(prepared['letter_bags'], targets, len(self.codes))
        for view in VIEWS:
            if not (resume and view in self.common):
                self.common[view] = np.linalg.svd(prepared[view], full_matrices=False)[2][0].astype(np.float32)
            x = self.view_matrix(view, prepared)
            if resume and view in self.profiles:
                # A label that is new here starts from the mean of its own questions.
                fresh = self.vector_profiles(x @ self.projection[view], targets)
                missing = np.linalg.norm(self.profiles[view], axis=1) < 1e-6
                self.profiles[view][missing] = fresh[missing]
            else:
                self.profiles[view] = self.vector_profiles(x, targets)
                self.projection[view] = np.eye(x.shape[1], dtype=np.float32)
        if passes:
            self.train_vector_side(rows, prepared, passes, seed, log)
        self.trained_on = len(rows)
        return new

    def learn_weights(self, rows, prepared, passes, seed, log=None):
        """A weight for each kind of evidence, and the temperature that makes the probabilities honest, from
        questions each scored by a model that had not seen its episode. The weights cannot be compared directly:
        a title gives a sharp score and a long text a flat one, see evaluate.who_decides."""
        import torch
        import torch.nn.functional as F
        groups = [group for group in folds(rows, CROSS_FIT, seed) if group]
        if len(groups) < 2:
            return
        stack = np.zeros((len(rows), len(self.codes), len(EVIDENCE)), dtype=np.float32)
        for k, held in enumerate(groups):
            train = [i for i, row in enumerate(rows) if row['episode'] not in held]
            test = [i for i, row in enumerate(rows) if row['episode'] in held]
            inner = GanjiModel(self.vectors, self.codes, self.config_path)
            inner.fit([rows[i] for i in train], take(prepared, train), passes=passes, learn=False, seed=seed + k)
            stack[test] = inner.evidence(take(prepared, test))
        evidence = torch.tensor(stack)
        truth = torch.tensor([self.codes.index(row['codes'][0]) for row in rows])
        raw = torch.nn.Parameter(torch.full((len(EVIDENCE),), -0.5))
        temperature = torch.nn.Parameter(torch.tensor(STARTING_TEMPERATURE, dtype=torch.float32))
        optimizer = torch.optim.Adam([raw, temperature], lr=0.02)
        for _ in range(300):
            weights = F.softplus(raw)   # never below zero, so that evidence can only add
            loss = F.cross_entropy(temperature * (evidence * weights).sum(2), truth) + 1e-3 * (weights ** 2).sum()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        self.weights = F.softplus(raw).detach().numpy()
        self.temperature = float(temperature.detach())
        if log:
            log('Evidence weights: ' + ', '.join(f'{name.replace("_", " ")} {weight:.2f}' for name, weight in zip(EVIDENCE, self.weights)))

    def train_vector_side(self, rows, prepared, passes, seed, log):
        import torch
        import torch.nn.functional as F
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        torch.manual_seed(seed)
        categories = sorted({code.split('.')[0] for code in self.codes})
        category_of = torch.tensor([categories.index(code.split('.')[0]) for code in self.codes], device=device)
        xs = {view: torch.tensor(self.view_matrix(view, prepared), device=device) for view in VIEWS}
        goal = torch.zeros(len(rows), len(self.codes), device=device)
        for i, row in enumerate(rows):
            others = [code for code in row['codes'][1:] if code in self.codes]
            goal[i, self.codes.index(row['codes'][0])] = MAIN_SUBJECT if others else 1.0
            for code in others:
                goal[i, self.codes.index(code)] = (1 - MAIN_SUBJECT) / len(others)
        projection = {view: torch.nn.Parameter(torch.tensor(self.projection[view], device=device)) for view in VIEWS}
        profiles = {view: torch.nn.Parameter(torch.tensor(self.profiles[view], device=device)) for view in VIEWS}
        first_projection = {view: p.detach().clone() for view, p in projection.items()}
        first_profiles = {view: p.detach().clone() for view, p in profiles.items()}
        balance = torch.nn.Parameter(torch.ones(len(VIEWS), device=device))
        scale = torch.nn.Parameter(torch.tensor(SCALE, device=device))
        optimizer = torch.optim.AdamW([*projection.values(), *profiles.values(), balance, scale], lr=RATE, weight_decay=0.0)
        for done in range(passes):
            order = torch.randperm(len(rows), device=device)
            total = 0.0
            for i in range(0, len(order), BATCH):
                batch = order[i:i + BATCH]
                score = 0.0
                for k, view in enumerate(VIEWS):
                    z = F.normalize(F.dropout(xs[view][batch], DROPOUT, True) @ projection[view], dim=1)
                    score = score + balance[k] * (z @ F.normalize(profiles[view], dim=1).T)
                logits = scale * score
                target = goal[batch]
                loss = -(target * F.log_softmax(logits, 1)).sum(1).mean()
                category_logits = torch.stack([torch.logsumexp(logits[:, category_of == c], 1) for c in range(len(categories))], 1)
                category_target = torch.stack([target[:, category_of == c].sum(1) for c in range(len(categories))], 1)
                loss = loss - CATEGORY_LOSS * (category_target * F.log_softmax(category_logits, 1)).sum(1).mean()
                pull = sum(((projection[view] - first_projection[view]) ** 2).sum() + ((profiles[view] - first_profiles[view]) ** 2).sum() for view in VIEWS)
                loss = loss + PULL * pull
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                total += loss.item()
            if log:
                log(f'pass {done + 1}/{passes}: loss {total / max(1, len(order) // BATCH):.3f}')
        for view in VIEWS:
            self.projection[view] = projection[view].detach().cpu().numpy()
            self.profiles[view] = F.normalize(profiles[view], dim=1).detach().cpu().numpy()

    # ---------- Predicting ----------
    def evidence(self, prepared):
        """Each kind of evidence for each question and subcategory: questions x subcategories x EVIDENCE."""
        vector_side = {}
        for view in VIEWS:
            z = unit(self.view_matrix(view, prepared) @ self.projection[view])
            vector_side[view] = z @ unit(self.profiles[view]).T
        keywords = prepared['keywords']
        if keywords.shape[1] != len(self.codes):
            # Prepared before a new label joined: it has no keywords, so it gets no bonus.
            keywords = np.pad(keywords, ((0, 0), (0, len(self.codes) - keywords.shape[1])))
        return np.stack([self.title_words.scores(prepared['title_bags']), self.text_words.scores(prepared['text_bags']),
                         self.letter_words.scores(prepared['letter_bags']), vector_side['title'], vector_side['text'], keywords], axis=2)

    def scores(self, prepared):
        return self.evidence(prepared) @ self.weights

    def rank(self, prepared):
        """For each question, [(probability, code)], most likely first."""
        probabilities = softmax(self.temperature * self.scores(prepared))
        return [sorted(((float(p), code) for p, code in zip(row, self.codes)), key=lambda pair: (-pair[0], pair[1])) for row in probabilities]

    def predict(self, title, text='', top=3):
        """The most likely subcategories of one question, from its title and the text of its question and answer:
        [(code, probability)]."""
        ranked = self.rank(self.prepare([{'title': title, 'answer': text, 'opening': text[:1200]}]))[0]
        return [(code, probability) for probability, code in ranked[:top]]

    # ---------- Saving ----------
    def save(self, folder=WEIGHTS):
        """Writes the profiles and the trained parts. The word vectors are saved apart, see vectors.py."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        parts = {'codes': np.array(self.codes), 'weights': self.weights, 'temperature': np.array(self.temperature), 'trained_on': np.array(self.trained_on)}
        for name, profiles in (('title', self.title_words), ('text', self.text_words), ('letter', self.letter_words)):
            parts.update({f'{name}_vocabulary': np.array(profiles.words), f'{name}_idf': profiles.idf, f'{name}_profiles': profiles.profiles.astype(np.float16)})
        for view in VIEWS:
            parts.update({f'common_{view}': self.common[view], f'projection_{view}': self.projection[view], f'vector_profiles_{view}': self.profiles[view]})
        np.savez_compressed(folder / 'model.npz', **parts)

    @classmethod
    def load(cls, folder=WEIGHTS, vectors=None):
        folder = Path(folder)
        vectors = WordVectors.load(folder / 'vectors.npz') if vectors is None else vectors
        with np.load(folder / 'model.npz', allow_pickle=False) as data:
            model = cls(vectors, data['codes'].tolist())
            for name, attribute in (('title', 'title_words'), ('text', 'text_words'), ('letter', 'letter_words')):
                profiles = WordProfiles()
                profiles.words = data[f'{name}_vocabulary'].tolist()
                profiles.index = {word: i for i, word in enumerate(profiles.words)}
                profiles.idf = data[f'{name}_idf']
                profiles.profiles = data[f'{name}_profiles'].astype(np.float32)
                setattr(model, attribute, profiles)
            for view in VIEWS:
                model.common[view] = data[f'common_{view}']
                model.projection[view] = data[f'projection_{view}']
                model.profiles[view] = data[f'vector_profiles_{view}']
            model.weights = data['weights']
            model.temperature = float(data['temperature'])
            model.trained_on = int(data['trained_on'])
        return model
