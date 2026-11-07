"""Repository locations, independent of the caller's working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# A new episode's audio, episode_NNN.mp3, waits in the root folder only until it has both subtitles:
# scripts/add-episode.sh then deletes it, and later steps work from the subtitles and .cache/alignment/.
AUDIO = ROOT
ROMAN = ROOT / 'transcripts-urdu-roman'
# English subtitles, translated from the audio (scripts/06-format/translate.py).
ENGLISH = ROOT / 'transcripts-english'
CACHE = ROOT / '.cache'
# yt-dlp's working folder: unfinished downloads and each video's metadata (episode_NNN.info.json).
DOWNLOADS = CACHE / 'downloads'
# The original transcription in Urdu script: a working file on the way to the Roman subtitles.
SOURCE = CACHE / 'transcripts-urdu'
MODELS = CACHE / 'roman-model'
REPORTS = CACHE / 'reports'
GLOSSARY = ROOT / 'scripts' / '05-romanize' / 'roman_glossary.json'
INDEX = ROOT / 'docs' / 'episode-index.md'
APP = ROOT / 'app'
# Episodes whose labels are the Ganji model's guesses, until a person has checked them.
UNREVIEWED = ROOT / 'ganji-model' / 'unreviewed.json'
PLAYLIST = 'https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B'
