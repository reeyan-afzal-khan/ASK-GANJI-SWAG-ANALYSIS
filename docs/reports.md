# Local reports and large files

Generated files live under `.cache/` and are excluded from Git. They are preserved locally when the repository is reorganized.

| Location | Contents |
| --- | --- |
| `.cache/roman-model/` | Downloaded model weights and tokenizer (about 1.94 GB) |
| `.cache/roman_candidates.jsonl` | Reusable transliteration candidates |
| `.cache/reports/validation.json` | Latest validation of live Roman SRTs |
| `.cache/reports/romanization/<run-id>/` | Per-run manifests and review queues |
| `.cache/reports/roman_word_review.json` | Latest vocabulary decisions |
| `.cache/reports/archive/` | Historical analysis and experiment snapshots |
| `.cache/backups/` | Backups made before replacing or formatting outputs |
| `.cache/logs/` | Optional run logs |
| `.cache/alignment/` | Per-episode word timings and confidence from step 06 (about 0.5 MB per hour of audio, some 170 MB in all) |
| `.cache/reports/pacing.json` | Cue statistics before and after the latest pacing, plus the stitching duplicates left out, missed speech added and decoding loops replaced |
| `.cache/reports/audio_check.json` | Possible missed speech, low-confidence cues and repetition loops for listening review, plus each decoding loop's status (Roman Urdu only) |
| `.cache/reports/alignment.log` | Progress of a long alignment run, when started with `tee` |

Run `bash scripts/07-validate/run.sh` for current results. Historical reports are reference snapshots: their old paths and hashes may predate formatting or reorganizations.

`.gitignore` covers the entire `.cache/` and `all_episodes/` trees, along with model-weight, media, archive and temporary-file extensions. Git does not offer a file-size threshold in `.gitignore`. Already tracked files are not untracked by adding ignore rules; the large-file audit found no currently tracked files at or above 5 MiB.

The existing audio and model data have not been deleted. Model/framework packages retain their internal directories inside `.cache/`; the user-facing `scripts/` and `docs/` folders are flat.
