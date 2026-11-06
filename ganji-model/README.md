# Ganji model

Sorts a viewer's question from Ask Ganji Swag into one of the show's 61 subcategories, and says how sure it is. It decides on the whole question and answer, read in English, and it is trained only on this show's own data, with no outside model and no dictionary.

| | |
| --- | --- |
| Reads | The title, the letter as it is read out, and everything said until the next question, in English |
| Gives | Its subcategories, most likely first, each with a probability |
| Learned from | 8.3 million subtitle words, then 1,432 questions checked by hand |
| Size | 16 MB, kept in Git |
| To predict | numpy; no GPU |
| To train | torch too; word vectors take under 3 minutes on a laptop GPU, the rest under a minute |

## What makes it its own

- **The whole question and answer decides, not the title alone.** The title, the letter and the whole text are separate evidence, and the model learns from the data how to weigh them. The title stays the strongest single clue, and the question and answer changes its guess on 34% of questions.
- **English first, with Roman Urdu mapped onto it.** Word meanings are learned from the English subtitles. Each Roman Urdu word then learns from the English spoken at the same moment, so `biwi` ends up near `wife` and `naukri` near `job` without anyone saying so. Of 30 common Roman Urdu words, 17 find their English among their 20 nearest words; from the English subtitles alone, 1 of 30 do.
- **Roman Urdu has no fixed spelling.** A word's vector is built from its letter pieces, so `shaadi` and `shadi` end up close, and a spelling never seen before still gets a vector.
- **Its own labelled data.** 1,432 questions from 243 episodes, checked by hand, in 61 subcategories under 11 categories. All of it can be rebuilt from this repository.
- **Open to fine-tuning.** New questions and even new subcategories take seconds to teach, and the result can be kept apart from the shipped model.

## Use it

Run these in Ubuntu/WSL2, in the Python environment that `bash scripts/01-setup/run.sh roman` makes.

```bash
# Sort one question.
bash ganji-model/run.sh predict "Should I move to Canada on a student visa?"
# Sort every question in docs/episode-index.md that has no label yet.
bash ganji-model/run.sh label
# Go through an episode's questions one by one, to keep or correct each guess.
bash ganji-model/run.sh label --review --episodes 244
```

`bash scripts/add-episode.sh` already runs `label`. Guesses go to `app/tools/question_labels.json`, and the episode is listed in `unreviewed.json` until someone reviews it, so that the model neither learns from its own guesses nor is marked by them.

From Python, with the title and, for a real decision, the text of the question and answer:

```python
import sys; sys.path.insert(0, 'ganji-model')
from ganji_model import GanjiModel

model = GanjiModel.load()
model.predict('Should I move to Canada on a student visa?')
# [('abroad.move', 0.58), ('abroad.visa', 0.18), ('abroad.return', 0.09)]
```

## Fine-tune it

| You want to | Run |
| --- | --- |
| Teach it your corrections and newly checked episodes | `bash ganji-model/run.sh finetune` |
| Teach it more questions of your own, in a model of your own | `bash ganji-model/run.sh finetune --data my_questions.jsonl --save my-model` |
| Use that model | `bash ganji-model/run.sh predict "..." --weights my-model` |
| Train the labelled part from the start, weights included | `bash ganji-model/run.sh train` |
| Learn the word vectors again, after many new episodes | `bash ganji-model/run.sh pretrain`, then `train` |
| Start from another show's subtitles | `bash ganji-model/run.sh pretrain --roman ROMAN_FOLDER --english ENGLISH_FOLDER --save my-model`, then `train --save my-model` |
| See what a change did | `bash ganji-model/run.sh evaluate` |

Your own questions go in a file with one JSON object per line. Each needs a title and a label; the text is optional but helps a lot, and `labels` can give second subjects after the main one.

```json
{"title": "Is my bitcoin investment halal?", "text": "I put my savings into bitcoin and ...", "label": "money.crypto"}
{"title": "My brother wants me to join his group", "labels": ["money.crypto", "family.siblings"]}
```

A label the model has not met becomes a new subcategory. In a try-out, six questions about crypto were enough: "Should I put my savings in bitcoin?" went from Saving & Investing at 31% to the new label at 95%, in 15 seconds, and other subjects still worked. To show a new subcategory in the app, add it to `app/tools/config.json` as well.

Fine-tuning is safe to repeat: eight rounds in a row left it at 74.2% of categories and 51.3% of subcategories, against 74.1% and 52.0% before them.

## How it works

1. **Word vectors** (`vectors.py`). Skip-gram with negative sampling (Mikolov et al. 2013) over letter pieces of three to five letters (Bojanowski et al. 2017), 128 numbers per word, for 29,194 words. English words learn from their English neighbours. Roman Urdu words learn only from the English of the same ten seconds, so they are mapped onto the English space and do not shape it.
2. **Reading a question** (`ganji_model.py`). The title, the letter (the first 90 seconds) and the whole text each become a tf-idf word count, and the title and whole text also a weighted mean of word vectors (Arora et al. 2017), with the direction all documents share taken out. The keyword lists in `app/tools/config.json` read the whole text too.
3. **Profiles.** Each subcategory gets a profile from its questions for each of those views (nearest centroid, as in Snell et al. 2017). A question's second subject counts a quarter towards that profile.
4. **Training the vector side.** Five passes on the checked labels: a learned projection and the profiles, with a loss on the subcategory and on its category. A pull back to the start and an early stop hold back overfitting, which sets in quickly on 1,432 questions.
5. **Learning what counts.** Questions are scored by models that had not seen their episode, and from those scores the model learns a weight for each of the six kinds of evidence and the temperature that turns scores into probabilities. So nothing gets credit for merely fitting its training data, and no weight is set by hand.

## How good it is

Tested on all 1,432 questions, each sorted by a model that had not seen its episode, in ten groups of episodes. The word vectors were also learned again each time without the test episodes (`evaluate --strict`, 22 minutes on a laptop GPU), as with a brand-new episode. A quicker test that lets the word vectors read the test episodes (`evaluate`) gives 74.1% of categories and 52.0% of subcategories, so that makes no real difference.

| Agreement with the labels checked by hand | Category | Subcategory | One of its subjects | Right one in best three |
| --- | --- | --- | --- | --- |
| Word counts only (baseline) | 71.2% | 46.6% | 52.7% | 68.3% |
| Title alone | 65.4% | 44.1% | 50.6% | 64.5% |
| Question and answer alone | 59.1% | 32.8% | 39.2% | 56.7% |
| All evidence, vector side untrained | 73.2% | 49.9% | 57.1% | 72.5% |
| **Ganji model** | **73.5%** | **51.1%** | **58.4%** | **73.4%** |

95% ranges, resampling whole episodes: subcategory 48.5% to 53.6%, category 70.9% to 75.7%. Gain over the baseline: subcategory +2.4 to +6.6 points, category +0.5 to +4.1 points.

**What decides.** The title is the strongest single clue, and reading it together with the text is what gets more answers right. The figures here are from the quick test.

The title and the text, each alone, point to different subcategories on 73% of questions. There, the final answer goes with the title 53% of the time, with the text 24%, and with neither alone 22%. It is right 43% of the time, where the title alone would be right 32% and the text alone 18%.

The question and answer changes the title's guess on 34% of questions. On those, the model is right 36% of the time, where the title's guess would be right 12%.

The weights it learned are letter words 0.93, title words 0.81, whole text words 0.72, title vectors 0.40, whole text vectors 0.26 and keywords 0.12. They cannot be compared directly: a title gives a sharp score and a long text a flat one, so in the margin between its best two guesses the title adds about 4 times as much as the text.

Giving the text more say than it learned does not help, because the text is long and wanders. Here is the title with the text at different strengths, with keywords left out:

| The text counts | Category | Subcategory | Where they differ, the answer goes with the text |
| --- | --- | --- | --- |
| Half as much | 70.5% | 49.8% | 14% |
| **As it learned** | 71.6% | 50.9% | 25% |
| 1.5 times | 71.9% | 50.2% | 35% |
| 2 times | 70.9% | 48.5% | 43% |
| 3 times | 69.4% | 46.5% | 54% |

**Its confidence is about right.** Guesses it rates higher come true more often, and about as often as it says. The ones it rates at 80% or more come true 89% of the time.

| It says | Questions | Right |
| --- | --- | --- |
| 0%–20% | 218 | 23% |
| 20%–30% | 213 | 28% |
| 30%–40% | 212 | 38% |
| 40%–50% | 185 | 47% |
| 50%–60% | 151 | 58% |
| 60%–70% | 95 | 65% |
| 70%–80% | 103 | 75% |
| 80%–100% | 255 | 89% |

Guesses under 60% are marked as unsure when labelling. A guess at 60% or more is right about 81% of the time, and that covers 32% of questions.

**By category** (of the questions that are in it, how many it finds; of its guesses at it, how many are right):

| Category | Questions | Found | Guesses right |
| --- | --- | --- | --- |
| Love & Marriage | 301 | 80% | 78% |
| Society & Culture | 289 | 82% | 69% |
| Family & Friends | 194 | 76% | 73% |
| Mental Health & Self | 143 | 64% | 66% |
| The Show & Junaid | 139 | 75% | 90% |
| Migration & Abroad | 125 | 76% | 71% |
| Career & Work | 91 | 70% | 75% |
| Money & Business | 59 | 59% | 67% |
| Health & Daily Life | 42 | 33% | 82% |
| Education | 36 | 61% | 65% |
| Other | 13 | 0% | 0% |

**What the Roman Urdu adds.** It links the two languages, and it helps a Roman Urdu title that has no text with it. Once the text is there, it does not measurably improve the labels: 97% of titles are mostly English, and the answers are read in English. In this comparison, both sets of word vectors had read the test episodes.

| | English first, Roman Urdu mapped on | English subtitles alone |
| --- | --- | --- |
| Of 30 Roman Urdu words, English among the 20 nearest words | 17 | 1 |
| All questions: category, subcategory | 74.1%, 52.0% | 73.2%, 50.7% |
| The 45 mostly Roman Urdu titles: category, subcategory | 57.8%, 37.8% | 57.8%, 35.6% |
| The same titles, with no text: category, subcategory | 60.0%, 28.9% | 44.4%, 22.2% |

**What else was tried**, on the same kind of test. The pre-trained ones here could read the test episodes, which can only have helped them, except the first row, which had the strict test too.

| Tried | Category | Subcategory | Verdict |
| --- | --- | --- | --- |
| Word vectors learned equally from both languages, with hand-set weights: the first version of this model | 73.7% | 51.8% | Within the noise of this one, which is simpler, trains in half the time and learns its weights |
| Naive Bayes, logistic regression and linear SVM on word counts | 58–60% | 37–39% | Weaker than word-count profiles |
| A small transformer (4 layers) trained from nothing on the subtitles by hiding words, then on the labels | 63.7% | 37.6% | Too few labels for it; adds about a point at best next to the rest |
| The same, also taught that passages of one answer belong together | 61.2% | 35.5% | No better |
| Word vectors that also learn from words of the same answer | 64.9% | 41.7% | Same as plain word vectors alone (64.5%, 41.2%) |
| Scoring the text passage by passage and counting the strongest | 73.4% | 51.7% | No better than the whole text as one |
| Every kind of evidence put on one scale, which might have given the text more say | 74.4% | 51.7% | No better, and the answer goes with the title as often (56% of differences) |

## What it cannot do

- **It is a first sort, not a person.** About half its subcategories and a quarter of its categories differ from the hand-checked labels, so use `--review` where it matters. Subjects overlap, and many misses are near ones: the right subcategory is in its best three 73.4% of the time.
- **Titles can still mislead it.** The title stays the strongest clue, so a title that says little about the letter can pull it the wrong way. A letter in episode 243 called "Thank You After 5 years of listening" is about being cheated on. From the title alone, a model that had not seen that episode's labels says `show.feedback` at 63%. With the text it still says `show.feedback`, but at 36% and marked as unsure.
- **The agreement has a ceiling nobody has measured.** The labels were checked once, not by several people apart, so it is unknown how far two people would agree.
- **Some settings were chosen on these same test groups,** such as what evidence to use, so the figures may be slightly high. The evidence weights are not among them: they are learned without the test episodes. The real test is new episodes after a `--review`.
- **It knows one show.** Answers are read through machine translation, and Roman Urdu titles do worse than the rest.

## Files

| File | What it is |
| --- | --- |
| `run.sh`, `cli.py` | The commands; each takes `--help` |
| `ganji_model.py` | The model: reading, training, predicting, saving |
| `vectors.py` | The word vectors and how they are learned |
| `corpus.py` | The training data, rebuilt from the repository |
| `label.py` | Labelling new episodes and reviewing them |
| `evaluate.py`, `results.json` | The tests above and their results |
| `unreviewed.json` | Episodes whose labels are the model's guesses (made when first needed) |
| `weights/` | The trained model: `vectors.npz` and `model.npz` |
| `test_ganji_model.py` | Its tests, also run by `bash scripts/08-test/run.sh` |

## References

- Mikolov et al. (2013), Distributed Representations of Words and Phrases and their Compositionality.
- Bojanowski et al. (2017), Enriching Word Vectors with Subword Information.
- Arora, Liang & Ma (2017), A Simple but Tough-to-Beat Baseline for Sentence Embeddings.
- Snell, Swersky & Zemel (2017), Prototypical Networks for Few-shot Learning.
