# Ask Ganji Swag — CrisperWhisper 2.0 Large

Resumable Urdu–English podcast transcription using **nyralabs/CrisperWhisper2.0_large**, **CTranslate2 (CT2)**, CUDA and float16 under **Ubuntu / WSL2**. Audio is read from `all_episodes/`; completed subtitles are saved to `urdu_transcript_crisper/`.

## 1. IMPORTANT — Download the audio first

> **This is the first workflow step.** Transcription does not download audio. The input files must exist in `all_episodes/` before you run the batch.

Source: [Ask Ganji Swag YouTube playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B).

The same audio folder is accessible at:

- Windows: `C:\Users\irvin\Desktop\ASK-GANJI-SWAG-ANALYSIS\all_episodes`
- WSL: `/mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS/all_episodes`

### Open the correct terminal

Open **CMD** in Windows and run:

```cmd
wsl -d Ubuntu -u root
```

Then run these commands in the Ubuntu terminal:

```bash
cd /mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS
mkdir -p all_episodes
```

All multiline download examples below are **Bash/WSL commands**, not CMD commands. A backslash must be the last character on each continued line.

### Download tools (one-time prerequisite)

If `yt-dlp --version` and `ffmpeg -version` already work, skip this step. Otherwise, inside Ubuntu:

```bash
apt-get update
apt-get install -y ffmpeg python3-venv
python3 -m venv /root/.venvs/yt-dlp
/root/.venvs/yt-dlp/bin/python -m pip install -U "yt-dlp[default]"
export PATH="/root/.venvs/yt-dlp/bin:$PATH"
```

For a later terminal session, repeat the `export PATH=...` line if using this download environment. If YouTube reports a missing JavaScript runtime or challenge support, follow [yt-dlp's current EJS instructions](https://github.com/yt-dlp/yt-dlp/wiki/EJS). This downloader environment is separate from CT2.

### Download the complete playlist

From the **project directory**, use your command with an explicit destination:

```bash
yt-dlp \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --sleep-interval 5 \
  --max-sleep-interval 15 \
  --no-overwrites \
  -P "all_episodes" \
  -o "episode_%(playlist_index)03d.%(ext)s" \
  "https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B"
```

This writes `all_episodes/episode_001.mp3`, `episode_002.mp3`, and so on. `--no-overwrites` preserves existing files. In your original command, the files are written into whichever directory the terminal is currently in; `-P all_episodes` makes the intended destination explicit.

**Numbering matters:** `playlist_index` is the video's current position in the playlist, not necessarily the number in its title. Verify the mapping before downloading; reordered playlists can change these numbers. Existing files can be skipped by name even if that position now refers to a different video. Keep a stable episode-to-video mapping in your project notes.

### Download only one new episode — example 243

Recommended when you have the video's watch URL: assign its filename explicitly and prevent downloading an associated playlist.

```bash
yt-dlp \
  --no-playlist \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --no-overwrites \
  -P "all_episodes" \
  -o "episode_243.%(ext)s" \
  "https://www.youtube.com/watch?v=REPLACE_WITH_VIDEO_ID"
```

Replace the placeholder with the actual episode 243 video URL. This creates **`all_episodes/episode_243.mp3`**. Do not use `playlist_index` for a standalone video: there may be no playlist index.

Alternatively, if you have verified that episode 243 is currently **item 243 in the playlist**, download just that item:

```bash
yt-dlp \
  --playlist-items 243 \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --no-overwrites \
  -P "all_episodes" \
  -o "episode_%(playlist_index)03d.%(ext)s" \
  "https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B"
```

Check the file before transcribing:

```bash
ls -lh all_episodes/episode_243.mp3
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 all_episodes/episode_243.mp3
```

Change `243` to the next episode number as needed. These commands are examples; they do not assert that episode 243 has been published.

## 2. Run transcription on this machine

From **CMD**, enter Ubuntu:

```cmd
wsl -d Ubuntu -u root
```

Then, at the Ubuntu prompt:

```bash
cd /mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS
source /root/.venvs/ask-ganji-ct2/bin/activate
bash run_urdu_batch_crisper_fixed.sh
```

You are already root: **do not run `sudo -i` after `cd`**, because it changes the directory to `/root`. If starting as the Ubuntu user `irvin`, run `sudo -i` first, then the commands above.

The script always uses the Linux CT2 environment; no Anaconda or Windows `.venv` is needed. Keep the terminal open. `[SKIP]` means an existing nonempty SRT was preserved, `[START]` identifies the current episode, and `Chunk N/total` shows transcription progress.

### Run only the new episode

```bash
EPISODES=243 bash run_urdu_batch_crisper_fixed.sh
```

### Retry a specific list

```bash
mkdir -p logs
set -o pipefail
EPISODES=123,163,183,189,203,236,242 bash run_urdu_batch_crisper_fixed.sh 2>&1 | tee logs/retry-selected.log
```

`EPISODES` overrides the first/last range. Existing nonempty SRTs still skip. To regenerate a bad existing SRT, preserve it before rerunning, for example:

```bash
mkdir -p backups
mv -n urdu_transcript_crisper/episode_123.srt "backups/episode_123.$(date +%Y%m%d-%H%M%S).srt"
EPISODES=123 bash run_urdu_batch_crisper_fixed.sh
```

Only move a file when no batch is writing it. If no SRT exists, simply rerun. Never delete the source MP3 to retry transcription.

### Verify GPU access and monitor a run

Inside the activated WSL environment:

```bash
python -c "import torch, ctranslate2; print(torch.__version__); print('Torch CUDA:', torch.cuda.is_available()); print('CT2 GPUs:', ctranslate2.get_cuda_device_count())"
python -m pip check
```

Expected: CUDA-enabled PyTorch, `Torch CUDA: True`, `CT2 GPUs: 1`, and no broken requirements. In a second CMD or WSL terminal, run `nvidia-smi -l 1`. Ctrl+C there stops only the monitor; Ctrl+C in the transcription terminal stops the batch.

## Repository layout

| Path | Purpose |
| --- | --- |
| `run_urdu_batch_crisper_fixed.sh` | CT2 batch, progress reporting, subtitle formatting and resume logic |
| `setup_crisper_ct2.sh` | Install the Linux Python environment and dependencies |
| `requirements-ct2.txt` | Pinned core CT2 and conversion packages |
| `ct2_decoder_guard.py` | Keeps CT2 prompt plus generated tokens within Whisper's decoder capacity |
| `all_episodes/` | Input MP3s, excluded from Git |
| `urdu_transcript_crisper/` | CrisperWhisper SRT outputs |
| `urdu_transcript_whisper/` | Preserved earlier Whisper transcripts for comparison |
| `YT_Questions_Timestamps.md` | Existing project reference material |
| `ask-ganji-swag-logo.png` | Project artwork |

The repository contains only the WSL/CT2 workflow and project data. The Linux environment and large-model caches live outside this repo and remain installed.

## 3. Fresh WSL / CT2 installation (new machines only)

1. Install an NVIDIA Windows driver supporting CUDA 12.8. On this machine, the RTX 4060 is already working. WSL uses the Windows driver; do not install a Linux display driver inside Ubuntu.
2. In an **Administrator PowerShell**, run:

   ```powershell
   wsl --install -d Ubuntu
   ```

   Restart if Windows requests it. If the WSL bootstrap fails, install Microsoft's WSL package first:

   ```powershell
   winget install --id Microsoft.WSL --exact
   wsl --install -d Ubuntu
   ```

3. Enter the Linux account used for this setup:

   ```powershell
   wsl -d Ubuntu -u root
   ```

4. Inside Ubuntu, install the prerequisites and run setup:

   ```bash
   apt-get update
   apt-get install -y python3-venv
   cd /mnt/c/Users/irvin/Desktop/ASK-GANJI-SWAG-ANALYSIS
   bash setup_crisper_ct2.sh
   source /root/.venvs/ask-ganji-ct2/bin/activate
   python -m pip check
   ```

   Adjust the project path for a different Windows user. Setup uses `uv` in a small bootstrap environment to install Python 3.12, then creates `~/.venvs/ask-ganji-ct2`. It installs CUDA PyTorch 2.11.0 (CUDA 12.8), CrisperWhisper 2.0.3 and the CrisperWhisper CT2 fork. Internet access and several GB of free disk space are needed.

   You may instead install under a regular Ubuntu user: use `sudo` for the two apt commands, then run setup as that user. In that case enter WSL with that username and launch the Bash script from that user's terminal. Environments and model caches are per Linux user.

5. Put input files in `all_episodes/` as `episode_001.mp3`, `episode_002.mp3`, etc. The source collection is the [Ask Ganji Swag playlist](https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B).
6. Run a short test before the batch:

   ```bash
   CT2_SMOKE_TEST=1 FIRST_EPISODE=48 bash run_urdu_batch_crisper_fixed.sh
   ```

   Choose an episode that exists locally. This tests 20 seconds and word timestamps without writing subtitles. First use downloads and converts the large model; later runs reuse it.

## 4. Model and CUDA details

The batch defaults to `large`, resolving to `nyralabs/CrisperWhisper2.0_large` (standard v2 Large). If `CrisperWhisper2_Large/` exists in the repo, it uses that local folder instead. `CRISPER_MODEL` can explicitly supply a model ID or local path.

For the installed root environment:

- Python: `/root/.venvs/ask-ganji-ct2/bin/python`
- Original weights: `/root/.cache/huggingface/hub/`
- Converted CT2 weights: `/root/.cache/crisperwhisper/` (large float16 model is about 2.9 GB)
- Each conversion folder contains `conversion_meta.json`, recording its source model.

CT2 performs GPU inference independently of PyTorch. CUDA PyTorch is also installed for direct GPU workloads and model conversion. Do not install upstream `ctranslate2` or `faster-whisper` into this environment: they can overwrite the CrisperWhisper fork.

## 5. Progress, stopping and resuming

The default range starts at **episode 3** and ends at the **highest numbered `episode_*.mp3` currently in `all_episodes/`**. New episodes such as 242 or 243 are included automatically. Set `FIRST_EPISODE=1` to include the first two episodes if needed. Existing nonempty SRTs are skipped. To choose a range in WSL:

```bash
FIRST_EPISODE=48 LAST_EPISODE=50 bash run_urdu_batch_crisper_fixed.sh
```

The terminal prints audio staging, configuration and `Chunk N/total` progress. Each MP3 is copied to Linux temporary storage for faster decoding, then removed after the episode. A completed SRT is published atomically only after the entire episode finishes.

Press **Ctrl+C** to stop. Run the same command to resume; the interrupted episode starts again from its beginning. Existing nonempty SRTs are treated as completed without checking their contents, so review or move an existing file aside yourself if you want that episode regenerated. An episode failure prints a traceback and the batch continues to the next selected episode; the final exit code is nonzero if any episode failed or an input was missing. A lock prevents concurrent batches in the same folder; the empty `.ct2-batch.lock` file can remain after exit.

For persistent logs, run inside WSL:

```bash
mkdir -p logs
set -o pipefail
bash run_urdu_batch_crisper_fixed.sh 2>&1 | tee logs/ct2-batch.log
```

To watch an existing log from **PowerShell**, without starting another batch:

```powershell
Get-Content "C:\Users\irvin\Desktop\ASK-GANJI-SWAG-ANALYSIS\logs\retry-2026-10-25.log" -Tail 20 -Wait
```

Substitute the log filename used by your run. Ctrl+C in this window stops only the log viewer. A saved log is not itself a background scheduler; keep the transcription session alive.

Monitor GPU activity in another terminal with `nvidia-smi -l 1`. Task Manager's default 3D/video graphs do not represent CUDA activity. Avoid sleep or shutting down WSL while a batch is running.

## 6. Troubleshooting

| Symptom | Action |
| --- | --- |
| Environment missing | Use the Linux account where setup ran (currently root), or run setup under your chosen user. |
| `torch` shows `+cpu` | Activate the correct Linux environment; install `torch==2.11.0` from `https://download.pytorch.org/whl/cu128`. Run the GPU verification command in section 2. |
| No CUDA GPU | Check `nvidia-smi` in Windows and Ubuntu; verify the Windows NVIDIA driver and WSL2 installation. |
| Batch already running | Use the existing terminal. Do not delete the lock file to bypass a running batch. |
| Download connection reset | Check WSL internet/proxy access and retry setup. A cached model can run with `HF_HUB_OFFLINE=1` once all needed files are present. |
| Output appears paused | Read the chunk counter and check GPU activity. Long episodes take time; SRT output appears only after completion. |
| `No position encodings ... >= 448` | The pinned CT2 decoder can overrun its positional capacity with long prompts. The local decoder guard caps each generation budget using the actual prompt token count; the batch also retries recognized limit errors with less context. Use both the updated script and `ct2_decoder_guard.py`. |
| Missing MP3 | Check the `all_episodes/episode_XXX.mp3` filename. |

## 7. Transcript review and references

Output is verbatim Urdu–English, including disfluencies and code-switching. Review names, mixed-script words, repetitions and timing before publishing. Subtitle boundaries are derived from word timestamps, pauses, punctuation and approximate length limits. Roman Urdu conversion is a possible later stage, not implemented here.

- [CrisperWhisper documentation](https://github.com/nyrahealth/CrisperWhisper/blob/main/DOCS.md)
- [Large v2 model and model license](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [Microsoft WSL installation guide](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch CUDA packages](https://pytorch.org/get-started/previous-versions/)

Download option reference: [yt-dlp usage and output templates](https://github.com/yt-dlp/yt-dlp#usage-and-options).
