# Ask Ganji Swag — Urdu Podcast Transcription Pipeline

A resumable, GPU-accelerated workflow for turning **Ask Ganji Swag** podcast audio into **timestamped Urdu–English subtitles** using **CrisperWhisper 2.0 Large** on an NVIDIA Jetson. The subtitle files will later serve as the source for a separate **Roman Urdu** conversion stage.

## 1. Project overview

### What this project does

The project starts with a YouTube playlist of **241 podcast episodes**, downloaded as MP3 audio files and named `episode_001.mp3` through `episode_241.mp3`. A local CrisperWhisper model processes the audio, identifies the spoken words and their timings, groups those words into readable subtitle cues, and saves **one `.srt` file per episode**.

The process is designed for a large, long-running batch: **each completed subtitle file is saved immediately**, and restarting the script skips completed episodes instead of starting the entire collection again.

| Item | Current configuration |
|---|---|
| Project | Ask Ganji Swag podcast transcription |
| Source | [YouTube playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B) |
| Audio collection | `all_episodes/episode_001.mp3` → `episode_241.mp3` |
| Automated batch range | **Episodes 001–241**, inclusive (239 episode numbers) |
| Speech recognition model | **CrisperWhisper 2.0 Large** (standard Large, **not** Large Pro) |
| Model directory | `CrisperWhisper2_Large/` |
| Hardware | NVIDIA Jetson with CUDA-enabled PyTorch |
| Inference backend | Transformers with CUDA + FP16 |
| Transcription language | Urdu (`language="ur"`), with Urdu–English code-switching |
| Transcription style | Verbatim, with word-level timestamps |
| Current output | `urdu_transcript_crisper/episode_XXX.srt` |
| Future output | Roman Urdu SRTs (conversion **not yet implemented**) |

**Important distinction:** The *audio collection* covers episodes **001–241**.

### End-to-end workflow

```text
YouTube playlist (241 episodes)
              │
              ▼
     yt-dlp + FFmpeg
              │
              ▼
  all_episodes/episode_XXX.mp3
              │
              ▼
  CrisperWhisper 2.0 Large
  • loaded from a local directory
  • Transformers / CUDA / FP16
  • Urdu + English speech
  • word-level timestamps
              │
              ▼
   Subtitle cue segmentation
  • split at pauses/punctuation
  • limit approximate duration
  • wrap long subtitle lines
              │
              ▼
 urdu_transcript_crisper/episode_XXX.srt
  • saved once per completed episode
  • safely resumable on rerun
              │
              ▼
      Future conversion step
  • correct ASR errors
  • transliterate Urdu → Roman Urdu
  • keep English words where appropriate
  • retain cue numbers and times
              │
              ▼
 roman_urdu_transcripts/episode_XXX.srt
          (planned)
```

### Why this approach?

- **Local inference:** After the model is downloaded, the script loads it from disk instead of fetching it on every run.
- **Detailed transcripts:** Verbatim mode is intended to retain hesitations, repetitions, and other speech details that can matter during later review.
- **Useful timestamps:** Word-level timing supports subtitle cues aligned to the original recording.
- **Batch efficiency:** One model load per script run, followed by sequential processing of the episode range.
- **Recoverability:** Individual completed SRTs survive interruption, so an unfinished run can resume without retranscribing earlier completed episodes.
- **Future flexibility:** Original Urdu–English SRTs remain available even after a cleaner Roman Urdu version is created.

CrisperWhisper was chosen for this workflow following an informal comparison with Whisper Large V3 outputs. That comparison is a **qualitative project decision**, not an audio-verified word-error-rate benchmark; neither model is guaranteed to be accurate on every episode.

---

## 2. Repository layout

Keep the script, model directory, and audio directory together:

```text
ask-ganji-swag/
├── README.md
├── run_urdu_batch.sh
│
├── CrisperWhisper2_Large/            # Downloaded model files
│   ├── config.json
│   └── ...
│
├── all_episodes/                    # Original MP3 audio
│   ├── episode_001.mp3
│   ├── episode_002.mp3
│   ├── episode_003.mp3
│   ├── ...
│   └── episode_241.mp3
│
├── urdu_transcript_crisper/         # Automatically created by the script
│   ├── episode_003.srt
│   ├── episode_004.srt
│   ├── ...
│   └── episode_241.srt
│
└── urdu_transcript_roman/          # Planned, not produced by this script
```

The directory names are significant because the current script uses the following relative paths:

```python
MODEL_PATH = Path("CrisperWhisper2_Large")
AUDIO_DIR = Path("all_episodes")
OUTPUT_DIR = Path("urdu_transcript_crisper")
FIRST_EPISODE = 1
LAST_EPISODE = 241
```

`run_urdu_batch.sh` automatically switches to its own directory at startup. This means you can launch it from another working directory without breaking these relative paths, as long as the files are arranged as shown.

---

## 3. Step-by-step setup

If the MP3s, model, and dependencies are **already installed on your Jetson**, skip to [Step 4: Run the transcription batch](#step-4-run-the-transcription-batch).

### Step 1: Download and organize the audio files

The source is the [Ask Ganji Swag YouTube playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B). The episodes were downloaded using `yt-dlp`, with `ffmpeg` converting/extracting the audio as MP3.

For a **fresh download**, run the following from the project directory:

```bash
mkdir -p all_episodes

yt-dlp \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --sleep-interval 5 \
  --max-sleep-interval 15 \
  -o "all_episodes/episode_%(playlist_index)03d.%(ext)s" \
  "https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B"
```

**What these options mean:**

| Option | Purpose |
|---|---|
| `--extract-audio` | Produces an audio-only file instead of retaining the full video. |
| `--audio-format mp3` | Requests MP3 audio via the postprocessor. |
| `--audio-quality 0` | Requests the best quality setting for the selected audio conversion. |
| `--sleep-interval 5` | Introduces a delay between downloads. |
| `--max-sleep-interval 15` | Allows a variable delay up to 15 seconds. |
| `-o "all_episodes/episode_%(playlist_index)03d.%(ext)s"` | Saves files into `all_episodes/`, with zero-padded episode numbers such as `episode_003.mp3`. |

**Already have `all_episodes/`?** Do not repeat this step. The transcription script consumes those local MP3s directly. Note that playlist indexes depend on playlist ordering; if the online playlist changes, a new download may no longer have exactly the same numbering as an earlier snapshot.

Confirm the downloaded files are present:

```bash
ls all_episodes/episode_001.mp3
ls all_episodes/episode_002.mp3
ls all_episodes/episode_241.mp3
```

The batch script expects names exactly like `episode_001.mp3`, not `Episode 1.mp3` or `001.mp3`. If an episode number is missing, the script reports it and proceeds to the next number.

### Step 2: Check Jetson requirements

This pipeline is configured for **GPU inference** and intentionally exits if CUDA is unavailable.

**You need:**

1. An NVIDIA Jetson running a compatible JetPack environment.
2. Python 3 and **CUDA-enabled PyTorch built for your JetPack version**.
3. The `crisperwhisper` Python package and its Transformers backend dependencies.
4. `ffmpeg` to decode MP3 audio.
5. Enough device memory and free storage for the Large model and source audio.

Check your installation:

```bash
python3 --version

python3 -c 'import torch; print("PyTorch:", torch.__version__); print("CUDA:", torch.cuda.is_available())'

python3 -c 'from crisperwhisper import CrisperWhisperModel; print("CrisperWhisper import OK")'

ffmpeg -version
```

A working GPU setup should report **`CUDA: True`**, and the import test should finish without an exception. If `ffmpeg` is absent, install it:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

**Jetson caution:** Do **not** blindly reinstall or upgrade PyTorch using a generic `pip install torch`. Generic wheels may replace your working JetPack-compatible CUDA build. If CrisperWhisper is missing, follow the [official CrisperWhisper installation instructions](https://github.com/nyrahealth/CrisperWhisper) for the Transformers backend, while preserving your compatible PyTorch installation.

### Step 3: Download CrisperWhisper 2.0 Large once

The current script expects the **standard Large** model in `./CrisperWhisper2_Large`. If that folder already contains the model, **skip this step**.

From the project directory:

```bash
python3 -m pip install huggingface_hub

python3 - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="nyralabs/CrisperWhisper2.0_large",
    local_dir="./CrisperWhisper2_Large",
)

print("Model saved to ./CrisperWhisper2_Large")
PY
```

`huggingface_hub.snapshot_download()` places the model repository's files in the specified local directory. Subsequent transcription runs load **that directory**, so no model download is needed at transcription time. The initial download requires internet access and may require accepting any access terms applicable to the model.

**Standard Large vs. Large Pro:** `nyralabs/CrisperWhisper2.0_large` is not the Pro variant. A different model requires its appropriate local files and an updated `MODEL_PATH` in the script; different versions may have different access and licensing conditions.

### Step 4: Run the transcription batch

From the project directory:

```bash
chmod +x run_urdu_batch.sh
./run_urdu_batch.sh
```

The first command grants execute permission to the shell script. The second launches Python, checks CUDA and the required directories, **loads the model once**, and starts processing audio sequentially.

On the current settings it checks:

```text
all_episodes/episode_001.mp3
all_episodes/episode_002.mp3
...
all_episodes/episode_241.mp3
```

For every episode that has an input MP3 and does **not** already have a nonempty SRT, the script:

1. Starts transcription using the locally stored model.
2. Requests Urdu verbatim text with word-level timestamps.
3. Converts the returned words into subtitle segments using duration, pause, punctuation, and length rules.
4. Formats each segment as an SRT cue with an index, start time, end time, and text.
5. Writes the result to a temporary file, flushes it, and renames it to the final `.srt` filename.
6. Prints `[DONE]` and continues to the next episode.

Typical terminal output (times are **illustrative**):

```text
Loading model once onto: NVIDIA ...
[START] all_episodes/episode_001.mp3
[DONE] urdu_transcript_crisper/episode_001.srt (123.4s)
[START] all_episodes/episode_002.mp3
[DONE] urdu_transcript_crisper/episode_002.srt (118.2s)
...
Finished. New SRTs: ..., skipped: ..., missing MP3s: ...
Output folder: /path/to/project/urdu_transcript_crisper
```

You may also launch the script by an absolute path from elsewhere:

```bash
/path/to/ask-ganji-swag/run_urdu_batch.sh
```

### Step 5: Find and inspect the output

Each input MP3 produces **one SRT file** with the same episode number:

```text
all_episodes/episode_001.mp3
                  │
                  ▼
urdu_transcript_crisper/episode_001.srt
```

The script does **not** create a plain-text `.txt` transcript. To preview an SRT:

```bash
sed -n '1,24p' urdu_transcript_crisper/episode_001.srt
```

To count currently saved SRT files:

```bash
find urdu_transcript_crisper -maxdepth 1 -type f -name 'episode_*.srt' | wc -l
```

This count tells you how many matching output files exist; it does **not** by itself verify subtitle quality or prove that each file contains a complete recording. If your full target remains episodes 003–241, there are **239 expected episode numbers** in the batch, assuming none are missing.

---

## 4. Pause, resume, and retry safely

Resumability is a central feature of this project: **the unit of progress is one completed episode**, not a partially processed audio segment.

### Stopping the batch

Press **Ctrl+C** to interrupt a running batch. The script catches a keyboard interruption during an episode, reports that the episode was not saved, and exits. Previously completed `.srt` files remain untouched.

Suppose the script finishes episodes 001, 002, and 003 but stops while transcribing 004. The output folder will contain:

```text
urdu_transcript_crisper/
├── episode_001.srt    # Finished
├── episode_002.srt    # Finished
└── episode_003.srt    # Finished
```

### Restarting the batch

Run the **same** command again:

```bash
./run_urdu_batch.sh
```

Expected behavior:

```text
[SKIP] episode_001: already completed
[SKIP] episode_002: already completed
[SKIP] episode_003: already completed
[START] all_episodes/episode_004.mp3
```

Episode 006 is processed **from the beginning**, because mid-episode checkpointing is not implemented. The model is loaded once again at the start of this new script run.

### What counts as completed?

The skip check is deliberately simple: an existing `.srt` file with a size greater than zero bytes is treated as completed. Therefore:

- A correctly finished episode is skipped, saving processing time.
- A corrupt or manually edited **nonempty** SRT is *also* skipped; the script does not validate its contents.
- An empty SRT is eligible to be regenerated.
- Missing MP3s produce a `[MISSING]` log entry, and the script moves on.
- A transcription exception produces `[ERROR]`; processing stops so you can investigate and rerun later.

### Why saving is safe

The script first writes to a temporary file in the **same output directory**, flushes the data, and only then uses an atomic replace operation to publish the `.srt` filename. This helps prevent an interrupted write from appearing as a completed final SRT. An abrupt power loss can still leave behind a hidden `.tmp` file, but this does not count as a finished episode and can be reviewed or removed later.

**Do not run two copies of this script against the same output folder simultaneously.** They would both see missing outputs and could transcribe the same episode concurrently.

### Rerun one specific episode

Remove only its output subtitle file and start the batch again:

```bash
rm urdu_transcript_crisper/episode_005.srt
./run_urdu_batch.sh
```

### Changing the episode range

Open `run_urdu_batch.sh` and change the two constants in the embedded Python section:

```python
FIRST_EPISODE = 1
LAST_EPISODE = 241
```

---

## 5. How timestamped SRT subtitles are created

An `.srt` file (SubRip subtitle format) is a sequence of numbered captions. Each caption has a start/end time and corresponding text. For example:

```srt
1
00:00:01,200 --> 00:00:04,800
السلام علیکم، آج ہم ایک نئے سوال
پر بات کریں گے۔

2
00:00:04,800 --> 00:00:07,600
Let's get started.
```

*These lines and times are illustrative, not validated against a specific audio episode.*

### A. Get word timings from the model

The current script calls:

```python
result = model.transcribe(
    str(audio_path),
    language="ur",
    mode="verbatim",
    word_timestamps=True,
    longform_strategy="continuation",
)
```

| Setting | Why it is used |
|---|---|
| `language="ur"` | Sets Urdu as the primary recognition language; spoken English may still appear as English text. |
| `mode="verbatim"` | Aims to preserve hesitations, repetitions, and vocal-event annotations where detected. |
| `word_timestamps=True` | Requests word start/end times, which the script uses to create subtitle boundaries. |
| `longform_strategy="continuation"` | Uses the model's long-audio continuation strategy, appropriate to the project's full podcast episodes. |

Word timestamps are **model estimates**; they may be imperfect, especially around overlapping speech, background sound, or code-switching.

### B. Group words into readable subtitle cues

The script accumulates successive words, then closes a caption if one of several conditions is met:

| Setting in `run_urdu_batch.sh` | Default | Behavior |
|---|---:|---|
| `MAX_DURATION` | `5.0` | Split when the accumulated word timing reaches about five seconds. |
| `MAX_WORDS` | `14` | Split after roughly 14 words. |
| `MAX_CHARS` | `78` | Split when text approaches 78 characters. |
| `PAUSE_THRESHOLD` | `0.65` | Split if the pause before the next word exceeds 0.65 seconds. |
| Sentence punctuation | `. ! ? ۔ ؟` | Split at sentence endings when the current cue has at least three words. |
| `wrap_text(..., max_width=42)` | `42` | Wrap long cue text into multiple display lines. |

These are **heuristics rather than hard limits**. They operate on the timestamps and text returned by the model; for example, a single unusually long recognized span can exceed the intended duration. The script is not a professional subtitle-layout or diarization system.

### C. Save the SRT

Times are formatted as `HH:MM:SS,mmm` using a comma before milliseconds, as required by the SRT format. The script numbers cues sequentially and writes the complete text using UTF-8 so Urdu characters are preserved.

Subtitles are saved under `urdu_transcript_crisper/`. Existing nonempty outputs are never overwritten automatically by a normal resumed run.

---

## 6. Transcription quality and cleanup decisions

### Verbatim versus cleaner transcription

The project currently uses **`mode="verbatim"`**. It can retain conversational features such as fillers (`[UH]`, `[UM]`), laughter/breathing markers, and repeated or interrupted words. This is useful when you want the closest possible representation of what was spoken before making editorial decisions.

The trade-off is that these annotations may clutter public-facing subtitles. If you want cleaner *source* subtitles, you can experiment by replacing:

```python
mode="verbatim"
```

### Urdu–English code-switching

Episodes contain a mixture of Urdu, English phrases, names, and sometimes Romanized words. Even with `language="ur"`, the model may alternate between Urdu script and Latin characters or make inconsistent spelling choices. A later Roman Urdu stage can normalize the writing system, but **transliteration cannot recover words that were originally misheard or omitted**.

### Recommended quality checks

Before converting the full collection to Roman Urdu:

1. Check a few SRTs against their original MP3s, especially the **beginning, middle, and end** of each sample.
2. Look for long silence interpreted as repeated or invented text, unusually short/long subtitles, and skipped introductions.
3. Review Urdu/English switches, names, locations, and English technical terms.
4. Check whether subtitle times track the speech rather than preceding or trailing it noticeably.
5. Keep the original model-generated files as a reference when correcting text.

An informal side-by-side review with Whisper Large V3 suggested CrisperWhisper was a practical fit for these episodes, but **a trustworthy accuracy comparison requires reference transcripts and/or listening to the source audio**. The presence of more text is not automatically proof of greater correctness.

---

## 7. Future stage: Roman Urdu subtitles

**Not implemented in `run_urdu_batch.sh` yet.** The present script stops after producing the original Urdu–English SRTs.

The planned conversion should read each `.srt`, preserve its caption index and timestamps, and transliterate **only the spoken text** into consistent Roman Urdu. It should not re-run speech recognition or move caption boundaries unless a separate subtitle-quality review finds a timing error.

Example of the intended transformation:

**Original SRT:**

```srt
12
00:01:23,100 --> 00:01:26,200
آپ اپنے career پر focus کریں۔
```

**Roman Urdu SRT:**

```srt
12
00:01:23,100 --> 00:01:26,200
Aap apne career par focus karein.
```

The wording is illustrative; your eventual style guide can choose spellings such as `karein`/`karen` and apply them consistently.

### Principles for the conversion

- **Preserve SRT structure:** Keep cue numbers, timestamps, order, and blank-line separators intact.
- **Transliterate rather than translate:** Convert Urdu into Latin/Roman Urdu writing, not into an English-language translation.
- **Keep English expressions readable:** For words originally spoken in English (e.g., `career`, `focus`, `time management`), retain the English spelling when appropriate.
- **Normalize spelling consistently:** Choose one convention for recurring words and apply it across episodes.
- **Handle annotations intentionally:** Decide whether markers such as `[lipsmack]`, `[UH]`, and `[breath]` should be retained, normalized, or removed in the *derived* version.
- **Avoid propagating ASR mistakes:** Correct important recognition errors against the audio before or during conversion when possible.
- **Do not overwrite the source:** Write new files to a separate directory, such as `roman_urdu_transcripts/`.

This approach lets you improve Roman Urdu readability repeatedly **without having to transcribe the MP3s again**.

---

## 9. Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| `Model directory not found` | `CrisperWhisper2_Large/` is missing or named differently. | Confirm the folder exists beside `run_urdu_batch.sh`, or update `MODEL_PATH`. |
| `Audio directory not found` | The expected `all_episodes/` directory is absent. | Place the MP3 directory beside the script, or update `AUDIO_DIR`. |
| `CUDA not found` | The Python environment cannot access a CUDA-enabled PyTorch build. | Run the PyTorch/CUDA check in Step 2; verify JetPack/PyTorch compatibility. |
| `ModuleNotFoundError: crisperwhisper` | The package is missing from the Python environment running the script. | Install it in that environment following the official guide, without replacing your working Jetson PyTorch build. |
| `[MISSING] all_episodes/episode_XXX.mp3` | An episode file is absent or named differently. | Compare the expected filename with the files in `all_episodes/`. |
| `[ERROR] ... No word timestamps returned` | The model did not return usable word timing data. | Check the audio, decoding, and model behavior on that episode before retrying. |
| CUDA out-of-memory | Large model or inference needs more memory than is currently available. | Monitor memory, stop competing workloads, and test another model if required. |
| Very slow processing | Model size, long audio, Jetson performance, or thermal/power limits. | Check GPU use, device temperatures, power settings, and the per-episode time logs. |
| Existing SRT isn't regenerated | The script skips every nonempty SRT. | Review the file; remove only the specific output you intend to regenerate. |
| Output has `[UH]` or `[breath]` | Verbatim transcription includes speech-event markers. | Keep source verbatim, and remove unwanted markers in the future cleanup stage. |
| SRT text looks wrong or is misaligned | Recognition/timing errors or source audio difficulties. | Compare affected cues with the MP3; correct the derived transcript as needed. |

**Interrupted or failed job?** Read the last log line, fix the immediate issue, and rerun `./run_urdu_batch.sh`. Finished nonempty SRTs will be skipped.

---

## 10. References and model terms

- [Ask Ganji Swag YouTube playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B)
- [CrisperWhisper GitHub repository](https://github.com/nyrahealth/CrisperWhisper)
- [CrisperWhisper API documentation](https://github.com/nyrahealth/CrisperWhisper/blob/main/DOCS.md)
- [CrisperWhisper 2.0 Large model page](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

Review the **current license and access conditions** of the exact model weights before commercial or public deployment. Standard Large and Pro variants may carry different conditions. Also review applicable rights and platform terms for downloading, processing, and redistributing audio or transcripts.

---

## 11. Current status and next steps

**Implemented:** Local audio collection, CrisperWhisper 2.0 Large transcription on Jetson, automatic Urdu–English SRT generation, episode-level resume behavior, and safe per-file saving.

**Planned:** Roman Urdu transliteration, consistent spelling and English-term handling, optional removal of non-speech annotations, and quality review against source audio.

The core operating command remains:

```bash
./run_urdu_batch.sh
```

You can stop and rerun it without discarding already completed, nonempty `.srt` files.
