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

Run `bash scripts/07-validate/run.sh` for current results. Historical reports are reference snapshots: their old paths and hashes may predate formatting or reorganizations.

`.gitignore` covers the entire `.cache/` and `all_episodes/` trees, along with model-weight, media, archive and temporary-file extensions. Git does not offer a file-size threshold in `.gitignore`. Already tracked files are not untracked by adding ignore rules; the large-file audit found no currently tracked files at or above 5 MiB.

The existing audio and model data have not been deleted. Model/framework packages retain their internal directories inside `.cache/`; the user-facing `scripts/` and `docs/` folders are flat.
