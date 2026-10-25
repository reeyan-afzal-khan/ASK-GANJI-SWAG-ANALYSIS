# Workflow and operational notes

## Data flow

`scripts/03-download-audio/run.sh` → `all_episodes/` → `scripts/04-transcribe/run.sh` → `urdu_transcript_crisper/` → `scripts/05-romanize/run.sh` → `urdu_transcript_crisper_roman/` → `scripts/07-validate/run.sh`

Run scripts with Bash in Ubuntu/WSL2. Each resolves the repository root from its own location, so it also works when invoked by absolute path from another directory. Paths with spaces are quoted. Each numbered folder under `scripts/` contains its `run.sh` command and step-specific helpers or settings. `scripts/.shared/` contains the shell environment helper, repository paths, subtitle parser and the management code shared by formatting, validation and tests. Run steps 01–02 once, then 03 → 04 → 05 → 07 for each new episode; step 06 is optional formatting and step 08 runs code tests. Runtime files are kept in the ignored `.cache/` folder. The shared `.ct2-batch.lock` prevents overlapping download, setup, transcription, romanization and formatting commands. Do not remove a lock to bypass a running process.

## Transcription

The original CrisperWhisper 2.0 Large/CT2 workflow is now in `scripts/04-transcribe/transcribe.py`. CUDA float16, verbatim mode, word timestamps, continuation, retry profiles and the decoder guard are retained. The default episode range now begins at 1 and ends at the highest available MP3 number. Existing nonempty SRTs skip; they are not proof of transcription accuracy.

The decoder guard reserves space inside Whisper's 448-position decoder. Normal decoding uses four context words and 256 generated tokens, with smaller profiles for recognized decoder-limit failures. An interrupted episode is restarted on the next run; already completed episodes remain intact. SRT files are published atomically after an episode completes. Audio is staged in Linux temporary storage for decoding.

To retry a bad original, stop the batch, move that SRT into your own backup folder, then run `scripts/04-transcribe/run.sh --episodes NUMBER`. A subsequent Roman output is preserved unless `scripts/05-romanize/run.sh --episodes NUMBER --overwrite` is requested. Overwrite creates a backup of the old Roman file.

## Roman Urdu

Romanization now reads the live source directory. It no longer requires the old 242-episode backup ZIP or a fixed episode count. The spelling glossary is `scripts/05-romanize/roman_glossary.json`; edit this JSON rather than the historical text glossary. Model revisions are pinned in `scripts/02-download-model/roman_model.json`. The model download is a separate, explicit command.

The conversion order is: reviewed spelling → cached model candidates checked for consonant agreement → conservative fallback with a review entry. Remaining scripts are romanized locally. Existing English and Roman text remain intact, including their earlier spelling variations. Urdu punctuation and digits are normalized. Output has one text line per cue; timestamps and cue IDs are retained.

This is script conversion, not an audio-corrected transcript. Ambiguous vowels, names, malformed words and inherited recognition errors need review. Some source files contain the replacement character `�`; validation reports it without inventing missing content. Validation checks structure and preservation, not linguistic accuracy or audio alignment. Screen wrapping in an editor/player is independent of the single physical text line in each SRT block.

New vocabulary requires the local CUDA model. `--cached-only` uses existing model candidates and the glossary without GPU generation; it fails clearly if a necessary word is missing. The append-only candidate cache lives in `.cache/roman_candidates.jsonl`. Do not delete it unless you intend to regenerate candidates.

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

The former `assets/`, `config/`, `requirements/`, `src/`, `tests/`, `models/` and `reports/` root folders have been consolidated.

The audio and both Crisper transcript folders retain their original names and locations. User-deleted folders, including Whisper transcripts and old backups, have not been restored.

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
