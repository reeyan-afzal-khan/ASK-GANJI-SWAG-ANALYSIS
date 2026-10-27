# Workflow and operational notes

## Data flow

`scripts/03-download-audio/run.sh` → `all_episodes/` → `scripts/04-transcribe/run.sh` → `transcripts-urdu/` → `scripts/05-romanize/run.sh` → `transcripts-urdu-roman/` → `scripts/07-validate/run.sh`

`transcripts-urdu-roman/` + `docs/episode-index.md` → `app/run.sh` → `app/data/` → `app/index.html`

`all_episodes/` + `transcripts-urdu-roman/` → `scripts/06-format/run.sh --translate` → `transcripts-english/`, which the app's transcript can switch to. `transcripts-urdu/` itself has been removed (it is in the Git history as `urdu_transcript_crisper/`); `.cache/alignment/` keeps its words.

`all_episodes/` + `transcripts-urdu/` + `transcripts-urdu-roman/` → `scripts/06-format/run.sh` → `.cache/alignment/` → evenly paced `transcripts-urdu-roman/` (optional, between 05 and 07)

Run scripts with Bash in Ubuntu/WSL2. Each resolves the repository root from its own location, so it also works when invoked by absolute path from another directory. Paths with spaces are quoted. Each numbered folder under `scripts/` contains its `run.sh` command and step-specific helpers or settings. `scripts/.shared/` contains the shell environment helper, repository paths, subtitle parser and the management code shared by formatting, validation and tests. Run steps 01–02 once, then 03 → 04 → 05 → 07 for each new episode; step 06 is optional formatting and step 08 runs code tests. The analytics app in `app/` is rebuilt with `bash app/run.sh`; it takes no lock because it only reads subtitles and writes `app/data/`. Runtime files are kept in the ignored `.cache/` folder. The shared `.ct2-batch.lock` prevents overlapping download, setup, transcription, romanization and formatting commands. Do not remove a lock to bypass a running process.

## Transcription

The original CrisperWhisper 2.0 Large/CT2 workflow is now in `scripts/04-transcribe/transcribe.py`. CUDA float16, verbatim mode, word timestamps, continuation, retry profiles and the decoder guard are retained. The default episode range now begins at 1 and ends at the highest available MP3 number. Existing nonempty SRTs skip; they are not proof of transcription accuracy.

The decoder guard reserves space inside Whisper's 448-position decoder. Normal decoding uses four context words and 256 generated tokens, with smaller profiles for recognized decoder-limit failures. An interrupted episode is restarted on the next run; already completed episodes remain intact. SRT files are published atomically after an episode completes. Audio is staged in Linux temporary storage for decoding.

To retry a bad original, stop the batch, move that SRT into your own backup folder, then run `scripts/04-transcribe/run.sh --episodes NUMBER`. A subsequent Roman output is preserved unless `scripts/05-romanize/run.sh --episodes NUMBER --overwrite` is requested. Overwrite creates a backup of the old Roman file.

## Roman Urdu

Romanization now reads the live source directory. It no longer requires the old 242-episode backup ZIP or a fixed episode count. The spelling glossary is `scripts/05-romanize/roman_glossary.json`; edit this JSON rather than the historical text glossary. Model revisions are pinned in `scripts/02-download-model/roman_model.json`. The model download is a separate, explicit command.

The conversion order is: reviewed spelling → cached model candidates checked for consonant agreement → conservative fallback with a review entry. Remaining scripts are romanized locally. Existing English and Roman text remain intact, including their earlier spelling variations. Urdu punctuation and digits are normalized. Output has one text line per cue; timestamps and cue IDs are retained.

This is script conversion, not an audio-corrected transcript. Ambiguous vowels, names, malformed words and inherited recognition errors need review. Some source files contain the replacement character `�`; validation reports it without inventing missing content. Validation checks structure and preservation, not linguistic accuracy or audio alignment. Screen wrapping in an editor/player is independent of the single physical text line in each SRT block.

New vocabulary requires the local CUDA model. `--cached-only` uses existing model candidates and the glossary without GPU generation; it fails clearly if a necessary word is missing. The append-only candidate cache lives in `.cache/roman_candidates.jsonl`. Do not delete it unless you intend to regenerate candidates.

## Word timing and even pacing

`scripts/06-format/align.py` runs in the transcription environment (`~/.venvs/ask-ganji-ct2`) and only reads `all_episodes/`, `transcripts-urdu/` and the Roman SRTs. It groups whole cues of the original SRT into windows of at most 29 seconds and 400 text tokens, without reaching into neighbouring cues, and replays each window's text through CrisperWhisper's decoder with the transcription prompt (verbatim mode, Urdu). The cross-attention of that single teacher-forced pass goes through CrisperWhisper's own Viterbi word timing (`extract_word_timings`), the same method it uses while transcribing. Each word is then kept inside its original cue, and the rare word the Viterbi cannot place shares the time of its neighbours. On sampled episodes the aligned cue edges agree with the original timings to a median of 0.01 s. The decoder's logits also give every word a log-probability, used as a confidence score. Stretches of six seconds or more that no cue covers are transcribed on their own (greedy, verbatim) so that possible missed speech can be listened to. MP3s are decoded a minute at a time through soxr's HQ resampler, bit-identical to CrisperWhisper's loader, so even the 5.6-hour episode needs about 1.3 GB of memory. The encoder dominates the cost (about 0.22 s per 30-second window on a laptop RTX 4060, already saturated at batch size one), so the mel spectrograms, Viterbi and decoding of the next episode run on worker threads.

The cache, `.cache/alignment/episode_NNN.json`, records the SHA-256 of the source SRT it was made from, and every original cue with its Urdu text, its Roman text and `[start, end, log-probability]` per word, plus the uncovered stretches with what the model heard in them. A cache whose source hash no longer matches is ignored, and that episode is aligned again. Alignment needs the Roman file to still match the source cue for cue (as step 05 writes it); after pacing, the cache is the record of that pairing.

`scripts/.shared/pacing.py` (standard library) pairs each Roman word with its Urdu word, one to one in about 99% of cues; where one Urdu word became several Roman words, the identical Latin words of both anchor the pairing and the rest share the Urdu word's time by length. It then chooses the cue breaks for a whole episode by dynamic programming. A cue's cost grows with the square of its distance from 34 characters and with pauses longer than 0.6 s inside it, and it cannot exceed 42 characters (unless it is a single word) or span a pause of 1.5 s or more. A break's cost falls with sentence ends, commas and pauses over 0.2 s, and rises before closing words (hai, ko, se, hi), after lead-in words (the, aur, agar, ke) and inside compound postpositions (ke liye, se pehle). Each cue starts at its first word, lingers 0.3 s after its last word, stays up at least a second, closes gaps shorter than 0.6 s to two frames (80 ms), and never overlaps the next cue. Where the original timing squeezed words together, a cue is still held for 0.7 s and the next cue starts late to make room, never by more than 1.5 s. The words come from the Roman file as it is, so hand corrections survive: they are matched to the cached words with `difflib`, and edited runs take the time of the words they replaced. Stitching duplicates are left out: an original cue of four or more words lasting under 0.25 s (or under 0.08 s a word) whose words match a contiguous stretch of the 40 words before it with a `difflib` ratio of at least 0.75. The rule runs on the original Crisper cues, so validation can apply it without the cache and skips those cues when checking that every English word survives. `manage_subtitles.py format` writes the paced files after a verified ZIP backup and refuses if the result's words differ from the cache in any way; `review` writes the audio check to `.cache/reports/audio_check.json`. `align.py --fill` transcribes the uncovered stretches where that check heard at least three spoken words (not tags): each stretch, 0.15 s inside its neighbouring cues, goes through `CrisperWhisperModel.transcribe` with the transcription step's settings (verbatim, Urdu, word timestamps, continuation with four context words, the same decoder retry profiles, hallucination mitigation). A tag repeated three or more times keeps one copy and a word or phrase repeated five or more times keeps two; up to four words at either end that repeat the neighbouring cue's last or first words are dropped; and the passage is kept only if three spoken words remain. Episodes are decoded on three worker threads while the GPU transcribes. Each passage is stored in the cache under `supplements` with its gap, its text in the original script, per-word times, its Roman text (filled in by `romanize.py --alignment`) and an `applied` flag. Pacing inserts a romanised, unapplied passage as a block where its gap is, without reordering other words, and sets `applied` after the paced file is written; applied passages are then matched against the file like the original words, so they are never inserted twice and hand edits or deletions are respected. Passages without Roman text are skipped and reported. Validation widens the source's time span by the applied passages, since some are intros or outros the original run left out entirely.

`align.py --loops` deals with decoding loops, which `pacing.decoding_loops` finds in the original cues. A loop is every word inside a window of 40 words that uses at most 8 different words, or of 32 that uses at most 4. Case and punctuation are ignored, so words compare the same in either script, and runs that are mostly tags are skipped.

Each loop's stretch runs from the end of the last word before it to the start of the first word after it, using the aligned word times, and is transcribed again with the fill settings. The fresh transcription confirms the loop as a phantom only if it meets all three conditions:
- it has at least three spoken words;
- it has no loop of its own under the same rule;
- it contains the loop's most repeated phrase at most twice (that phrase is the run of up to eight words that covers most of the loop).

Each loop gets a record under `loops` in the cache. The record holds the loop's word range, the stretch, the decision and its reason, and the new passage with word times. It also holds the Roman text, added by `romanize.py --alignment`, and an `applied` flag.

For a confirmed loop, pacing removes the loop's words. That includes words at the loop's edges inside cues that are only partly looped; where the word counts differ, each Roman word is traced to its Urdu word by its share of the letters. Pacing also removes any `--fill` passage whose midpoint lies inside the stretch, and inserts the new passage once; after that, the passage is matched like the rest of the file. A loop that the fresh transcription repeats, or where it hears nothing, is kept.

Validation applies the same rule to the original SRT and skips loop words in its English check, so it needs no cache; when the cache is present, it checks the words exactly.

The report is Roman Urdu only: `romanize.py --alignment` passes every heard passage through the unchanged SRT conversion (as cues of a temporary file, so new words get model candidates on the GPU or glossary entries like any subtitle word) and stores the result as a fourth field of each gap in the cache; passages not romanised yet are listed by time and word count without their text.

## English translation

`scripts/06-format/translate.py` (`run.sh --translate`, in the transcription environment) translates speech to English with CrisperWhisper 2.0, the model that made the transcription. It loads `nyralabs/CrisperWhisper2.0_large` with transformers, from a Hugging Face cache or from `TRANSLATE_MODEL`, and runs Whisper's translate task (`<|ur|><|translate|>`) with timestamps. Windows hold whole Roman cues (at most 28 s, closed at any pause of 2 s, with 0.2 s of audio either side). A window under 4 s joins the window before it, or else the one after, if the two fit in 28 s: alone, a second of audio comes back as invented English ("Thank you very much." for "thoughts. So"). Windows holding only tags such as [UH] or [breath] are skipped. The rest are decoded greedily, eight at a time. As in Whisper, a window whose English compresses more than 2.4 times under zlib is decoded again at temperatures 0.2 and 0.4. That happens when the model, trained to transcribe verbatim, echoes a stutter ("over-over-over…"). Warmer tries were dropped: where every temperature failed, the warmest try was invented text.

English that still looks wrong gets further tries. A window is doubtful when it still repeats, or holds Urdu or Hindi letters (the model sometimes writes an Urdu phrase inside English speech in Urdu or Devanagari script), or is empty, or has under a third as many words as the window's spoken Roman words, tags not counted. That last one is how it looks when the model stops at a switch between Urdu and English and drops the rest. A doubtful window is translated again as pieces of whole cues of about 10 s, and a piece that is still doubtful as pieces of about 5 s. Pieces replace what they were cut from when they do better. A try that neither repeats nor leaves English beats one that does, whatever its length; after that, fewer doubts win, then more words. In the first full run, 1,088 of 50,422 windows were thin, 26 still repeating, 9 not English and 5 empty.

Two more habits of the model are cleaned up in every window. Whisper's stock phrases for unclear audio ("Thank you.", "Peace be upon you.", "Please like and share this video.", "Good bye.") are dropped where the Roman cues within four seconds hold nothing like them (shukriya, salaam, Allah hafiz, subscribe…). In the first full run, about 80 of some 600 such cues had nothing like them nearby, for example "Peace be upon you." in the middle of an answer. A sentence said four times or more in a row is kept once ("Good bye." thirty times). Said three times it stays, as people do say "It's okay" three times.

The timestamp tokens give groups of sentences. A group longer than 7 s is split between its sentences, and any sentence there of more than about 90 characters is cut at its commas. The parts share the group's spoken time, taken from the Roman cues inside it, in proportion to their length. A sentence that repeats the one before it is dropped, whatever its capitals and punctuation, and so is a fragment that two pieces both heard: of two cues in a row, the shorter goes when its words, four or more, run unbroken inside the other. Where two overlap, the earlier one ends sooner, so each still starts when it is spoken. `.cache/reports/translation.json` lists, per episode, the windows that still look doubtful after every try.

`--repair` (`run.sh --translate --repair`) reads the existing English files instead of starting over. It keeps the English of every window that is still a window under the current rules and is not doubtful, and translates the rest: windows joined by the four-second rule (their English is replaced whole) and doubtful windows (which go straight to the pieces). Run over the first full translation, it translated 274 joined windows and tried 1,682 windows or pieces again, keeping 1,677, in 43 minutes. Thin windows fell from 1,088 to 15, about 70,000 English words came back, and about 90 stock-phrase cues went; 7 windows stay doubtful, all short and thin. Validation checks that the English files are numbered in order, one line per cue, without overlaps.

The model was chosen side by side on episodes 2 and 3, read against the Roman text. Whisper large-v3 (CTranslate2) was tried decoded greedily (45× real time), with beam search (27×), and with the previous window's English as context, which once repeated one sentence for a whole window. CrisperWhisper gave the most complete English (0.92 English words per Roman word, against 0.84 for greedy Whisper) and the most faithful: it kept clauses and names the others dropped, and got idioms right ("taare tod ke laana"). With the fallback it runs at about 40× real time on a laptop RTX 4060, roughly nine and a half hours for all episodes.

## Analytics app

`app/tools/build_data.py` parses every Roman SRT with the shared subtitle parser, joins it to `docs/episode-index.md` by episode number, and writes `app/data/summary.js` (all aggregates) plus `app/data/transcripts/episode_NNN.js` (subtitle text for the episode explorer, where it follows the embedded YouTube player). It also turns the light and dark skins in `app/skins/` into `app/assets/theme.css`. Output is deterministic: unchanged files are not rewritten, and transcripts of removed episodes are deleted. The data files are JavaScript that the page loads with script tags, so the app works from disk, from the preview server and on static hosts such as GitHub Pages. The YouTube video for each episode comes from its index links, and question timestamps come from their `t=` parameter. When `transcripts-urdu/` is present, each word is labelled English (Latin script in the source) or Urdu (romanised), counted over the whole episode so it also works after the Roman cues are re-paced. Passages that step 06 added for missed speech are not in the original SRT, so when `.cache/alignment/` is present their Latin words count as English too. The same goes for passages that replaced decoding loops, while a missed-speech passage inside a replaced loop's stretch no longer counts. Without `transcripts-urdu/`, the original cues are read from `.cache/alignment/`, which holds them word for word. The builder also writes `app/data/transcripts-english/` from `transcripts-english/` when it exists; these files call `GANJI_TRANSCRIPT(n, cues, 'english')`, load only when chosen, and are removed when the folder is gone. `meta.scripts` lists what the transcript can switch to. Without the original SRTs or the cache, the app hides the language views.

Categories, subcategories, places and stopwords live in `app/tools/config.json`. Each question's subcategory comes from `app/tools/question_labels.json`, which holds one list per episode in index order; the first code is the main subcategory and any further codes are second subjects. The labels were checked by hand from each title and, for vague titles, the opening of the answer. If an episode is missing from that file or its count no longer matches the index, its questions are placed by the category keyword lists instead (keywords ending in `*` match word endings; `weak` hints count half; `title_only` categories ignore the transcript), shown as "Not yet sorted", and listed in the build output and the app's data-quality table. Stated ages come from the title and the first 90 seconds of the answer, places from the title and the first 45 seconds; YouTube comment segments are skipped for both.

`--serve` previews `app/` with a small standard-library web server that serves that folder only, as a static host would, with caching disabled so edits show on reload. Use `--host 0.0.0.0` only if you deliberately want other devices on your network to reach it.

## Environments and local files

| Component | Default location |
| --- | --- |
| Crisper/CT2 Linux environment | `~/.venvs/ask-ganji-ct2` |
| Romanization Linux environment | `~/.venvs/ask-ganji-roman` |
| CUDA model and tokenizer | `.cache/roman-model/` |
| Original Crisper model caches | `~/.cache/huggingface/`, `~/.cache/crisperwhisper/` |
| Candidate cache | `.cache/roman_candidates.jsonl` |
| Preserved Windows helper dependencies | `.cache/windows-roman-dependencies/` |

The Windows helper directory is loaded only on Windows. Linux installs its own dependencies into its separate environment. Do not install upstream `ctranslate2` or `faster-whisper` over the Crisper-specific fork. Formatting, validation and tests use only Python's standard library and do not require either model environment.

## Migration from earlier layouts

| Previous path | Current path |
| --- | --- |
| `run_urdu_batch_crisper_fixed.sh` | `scripts/04-transcribe/run.sh` |
| `setup_crisper_ct2.sh` | `scripts/01-setup/run.sh transcription` |
| `ct2_decoder_guard.py` | `scripts/04-transcribe/ct2_decoder_guard.py` |
| `requirements-ct2.txt` | `scripts/01-setup/requirements-transcription.txt` |
| `analysis/romanize_crisper.py` | `scripts/05-romanize/run.sh` / `scripts/05-romanize/romanize.py` |
| `analysis/validate_roman_output.py` | `scripts/07-validate/run.sh` |
| `analysis/roman_model/` | `.cache/roman-model/` |
| `analysis/roman_glossary.json` | `scripts/05-romanize/roman_glossary.json` |
| `YT_Questions_Timestamps.md` | `docs/episode-index.md` |
| `ask-ganji-swag-logo.png` | `docs/logo.png` |
| Historical analysis files | `.cache/reports/archive/2026-10-25/analysis/` |
| `urdu_transcript_crisper/` | `transcripts-urdu/` |
| `urdu_transcript_crisper_roman/` | `transcripts-urdu-roman/` |
| `english_transcript/` | `transcripts-english/` |

The former `assets/`, `config/`, `requirements/`, `src/`, `tests/`, `models/` and `reports/` root folders have been consolidated.

The audio folder keeps its original name and location, and the transcript folders keep their locations under the names above. User-deleted folders, including Whisper transcripts and old backups, have not been restored.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing environment | Run `bash scripts/01-setup/run.sh transcription` or `bash scripts/01-setup/run.sh roman` in the same Linux user account. |
| No CUDA GPU | Check `nvidia-smi` in Windows and WSL. The installed Windows NVIDIA driver supplies WSL GPU support. |
| Missing local Roman model | Run `bash scripts/02-download-model/run.sh`. |
| Missing cached word | Omit `--cached-only` to generate candidates, or add a reviewed spelling to the glossary. |
| Existing output skipped | Use `--overwrite` only when you want to regenerate it; it is backed up first. |
| Validation warns about `�` | Check the corresponding source audio; the missing character cannot be recovered by formatting. |
| `flock` unavailable | Use Ubuntu/WSL2 for mutating shell workflows. |
| Interrupted candidate cache line | Preserve the cache and repair its final incomplete JSON line before retrying. Completed entries remain reusable. |
