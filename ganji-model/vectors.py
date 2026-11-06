"""Word vectors learned from the show's own subtitles, with no outside model or dictionary.

English comes first, because the model reads questions and answers in English: English words learn from their
English neighbours (skip-gram with negative sampling), which shapes the space. The subtitles also exist as Roman
Urdu on the same time line, so a Roman Urdu word learns from the English spoken in the same ten seconds, which
maps it onto that space. That is how "biwi" comes to sit near "wife" and "naukri" near "job" with nothing telling
it so. Each word is also the sum of its pieces of three to five letters (as in fastText), because Roman Urdu has
no fixed spelling: "shaadi" and "shadi" share pieces, and a spelling never seen before still gets a vector.

Reading vectors needs only numpy; training them needs torch, and a GPU to take minutes rather than hours.
"""
import collections
import time

import numpy as np

DIMENSIONS = 128
BUCKETS = 32768      # hashed letter pieces
MIN_COUNT = 5        # rarer words get their vector from their letter pieces alone
PASSES = 5
WINDOW = 5           # English neighbours either side
ALIGNED = 2          # English words per Roman Urdu word, from the same stretch of time
SLICE = 10.0         # seconds; words in the same slice count as spoken together
NEGATIVES = 5
BATCH = 16384
RATE = 3e-3
SUBSAMPLE = 1e-4     # very common words are mostly skipped
SMOOTHING = 1e-4     # in a document, a word counts SMOOTHING / (SMOOTHING + its frequency) (Arora et al. 2017)
UNSEEN = 1e-7        # the frequency given to a word not in the vocabulary


def piece_hash(text):
    """FNV-1a, so the same piece lands in the same bucket on every machine."""
    value = 2166136261
    for byte in text.encode('utf-8'):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


def pieces(word, buckets=BUCKETS):
    """The buckets of a word's letter pieces, three to five letters long, with its ends marked."""
    marked = f'<{word}>'
    found = {marked[i:i + n] for n in (3, 4, 5) for i in range(len(marked) - n + 1)}
    found.discard(marked)
    return sorted({piece_hash(piece) % buckets for piece in found})


class WordVectors:
    def __init__(self, vocabulary, counts, vectors, grams):
        self.vocabulary = list(vocabulary)
        self.index = {word: i for i, word in enumerate(self.vocabulary)}
        self.counts = np.asarray(counts, dtype=np.float64)
        self.frequencies = self.counts / max(self.counts.sum(), 1.0)
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.grams = np.asarray(grams, dtype=np.float32)
        self.unseen = {}

    def __getitem__(self, word):
        """A word's vector; a word never seen gets one from its letter pieces."""
        i = self.index.get(word)
        if i is not None:
            return self.vectors[i]
        vector = self.unseen.get(word)
        if vector is None:
            found = pieces(word, len(self.grams))
            vector = self.grams[found].sum(0) / (1 + len(found))
            self.unseen[word] = vector
        return vector

    def document(self, words):
        """The weighted mean of a text's word vectors: rare words count for more, common ones for less."""
        if not words:
            return np.zeros(self.vectors.shape[1], dtype=np.float32)
        known = [self.index.get(word, -1) for word in words]
        probability = np.array([self.frequencies[i] if i >= 0 else UNSEEN for i in known])
        weights = (SMOOTHING / (SMOOTHING + probability)).astype(np.float32)
        matrix = np.stack([self.vectors[i] if i >= 0 else self[word] for i, word in zip(known, words)])
        return (matrix * weights[:, None]).sum(0) / max(float(weights.sum()), 1e-9)

    def nearest(self, word, count=8):
        """The words closest to a word, to see what the vectors have learned."""
        unit = self.vectors / np.maximum(np.linalg.norm(self.vectors, axis=1, keepdims=True), 1e-9)
        target = self[word] / max(float(np.linalg.norm(self[word])), 1e-9)
        order = np.argsort(-(unit @ target))
        return [self.vocabulary[i] for i in order if self.vocabulary[i] != word][:count]

    def save(self, path):
        np.savez_compressed(path, vocabulary=np.array(self.vocabulary), counts=self.counts.astype(np.float32),
                            vectors=self.vectors.astype(np.float16), grams=self.grams.astype(np.float16))

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls(data['vocabulary'].tolist(), data['counts'], data['vectors'], data['grams'])


def word_streams(subtitles, index, skip):
    """For each episode and language, in time order: the word numbers, and the time slice of each word."""
    streams = []
    for episode in sorted(subtitles):
        if episode in skip:
            continue
        entry = {}
        for language, cues in subtitles[episode].items():
            ids, slices = [], []
            for start, end, words in cues:
                for k, word in enumerate(words):
                    i = index.get(word)
                    if i is not None:
                        ids.append(i)
                        slices.append(int((start + (end - start) * (k + 0.5) / len(words)) // SLICE))
            entry[language] = (np.array(ids, dtype=np.int32), np.array(slices, dtype=np.int32))
        streams.append(entry)
    return streams


def neighbour_pairs(tokens, rng, window=WINDOW):
    """Word pairs within a window whose size varies, so that nearer words count for more."""
    chunks = []
    if len(tokens) < 2:
        return chunks
    reach = rng.integers(1, window + 1, size=len(tokens))
    for distance in range(1, window + 1):
        forward = reach[:-distance] >= distance
        chunks.append(np.stack([tokens[:-distance][forward], tokens[distance:][forward]], 1))
        backward = reach[distance:] >= distance
        chunks.append(np.stack([tokens[distance:][backward], tokens[:-distance][backward]], 1))
    return chunks


def aligned_pairs(first, first_slices, second, second_slices, rng, count=ALIGNED):
    """Each word of the first language with random words of the second from the same time slice."""
    chunks = []
    if not len(first) or not len(second):
        return chunks
    left = np.searchsorted(second_slices, first_slices, 'left')
    right = np.searchsorted(second_slices, first_slices, 'right')
    spoken = right > left
    words, low, high = first[spoken], left[spoken], right[spoken]
    for _ in range(count):
        picks = low + (rng.random(len(words)) * (high - low)).astype(np.int64)
        chunks.append(np.stack([words, second[picks]], 1))
    return chunks


def training_pairs(streams, keep, rng, aligned=ALIGNED):
    """One pass of (word, context) pairs, shuffled. Every context is English: English words learn from their
    neighbours, and Roman Urdu words only from the English of the same moment."""
    chunks = []
    for entry in streams:
        if 'english' not in entry:
            continue
        kept = {}
        for language, (ids, slices) in entry.items():
            mask = rng.random(len(ids)) < keep[ids]
            kept[language] = (ids[mask], slices[mask])
        chunks += neighbour_pairs(kept['english'][0], rng)
        if aligned and 'roman' in kept:
            chunks += aligned_pairs(*kept['roman'], *kept['english'], rng, aligned)
    pairs = np.concatenate(chunks)
    rng.shuffle(pairs)
    return pairs


def train_vectors(subtitles, skip=frozenset(), aligned=ALIGNED, passes=PASSES, seed=7, log=print):
    """Learn word vectors from {episode: {language: cues}}, leaving out the episodes in skip. With aligned=0
    they come from the English subtitles alone, and know no Roman Urdu."""
    import torch
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    if not aligned:
        subtitles = {episode: {'english': languages['english']} for episode, languages in subtitles.items() if 'english' in languages}
    counts = collections.Counter()
    for episode, languages in subtitles.items():
        if episode not in skip:
            for cues in languages.values():
                for _, _, words in cues:
                    counts.update(words)
    vocabulary = [word for word, count in counts.most_common() if count >= MIN_COUNT]
    index = {word: i for i, word in enumerate(vocabulary)}
    frequency = np.array([counts[word] for word in vocabulary], dtype=np.float64)
    total = frequency.sum()
    keep = np.minimum(1.0, (np.sqrt(frequency / total / SUBSAMPLE) + 1) * (SUBSAMPLE * total / frequency))
    found = [pieces(word) for word in vocabulary]
    table = np.full((len(vocabulary), max(map(len, found))), BUCKETS, dtype=np.int64)
    for i, row in enumerate(found):
        table[i, :len(row)] = row
    streams = word_streams(subtitles, index, skip)

    word = torch.nn.Embedding(len(vocabulary), DIMENSIONS).to(device)
    gram = torch.nn.Embedding(BUCKETS + 1, DIMENSIONS, padding_idx=BUCKETS).to(device)
    context = torch.nn.Embedding(len(vocabulary), DIMENSIONS).to(device)
    torch.nn.init.uniform_(word.weight, -0.5 / DIMENSIONS, 0.5 / DIMENSIONS)
    with torch.no_grad():
        torch.nn.init.uniform_(gram.weight, -0.5 / DIMENSIONS, 0.5 / DIMENSIONS)
        gram.weight[BUCKETS].zero_()
    torch.nn.init.zeros_(context.weight)
    table_t = torch.tensor(table, device=device)
    sizes = torch.tensor([len(row) for row in found], dtype=torch.float32, device=device)
    noise = torch.cumsum(torch.tensor(frequency ** 0.75 / (frequency ** 0.75).sum(), dtype=torch.float64, device=device), 0).float()
    optimizer = torch.optim.Adam([*word.parameters(), *gram.parameters(), *context.parameters()], lr=RATE)

    def vectors(ids):
        return (word(ids) + gram(table_t[ids]).sum(1)) / (1 + sizes[ids]).unsqueeze(1)

    started = time.time()
    for done in range(passes):
        pairs = torch.from_numpy(training_pairs(streams, keep, rng, aligned).astype(np.int64))
        for group in optimizer.param_groups:
            group['lr'] = RATE * (1 - 0.95 * done / passes)
        running, steps = 0.0, 0
        for i in range(0, len(pairs), BATCH):
            batch = pairs[i:i + BATCH].to(device, non_blocking=True)
            inputs = vectors(batch[:, 0])
            positive = (inputs * context(batch[:, 1])).sum(1)
            drawn = torch.searchsorted(noise, torch.rand(len(batch), NEGATIVES, device=device)).clamp(max=len(vocabulary) - 1)
            negative = torch.bmm(context(drawn), inputs.unsqueeze(2)).squeeze(2)
            loss = torch.nn.functional.softplus(-positive).mean() + torch.nn.functional.softplus(negative).sum(1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            running += loss.item()
            steps += 1
        if log:
            log(f'pass {done + 1}/{passes}: {len(pairs):,} word pairs, loss {running / steps:.3f}, {time.time() - started:.0f} s')
    with torch.no_grad():
        final = [vectors(torch.arange(i, min(i + BATCH, len(vocabulary)), device=device)).cpu().numpy() for i in range(0, len(vocabulary), BATCH)]
    return WordVectors(vocabulary, frequency, np.concatenate(final), gram.weight.detach().cpu().numpy()[:BUCKETS])
