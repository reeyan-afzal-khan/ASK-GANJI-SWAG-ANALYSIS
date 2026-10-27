"""Repository locations, independent of the caller's working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / 'all_episodes'
SOURCE = ROOT / 'transcripts-urdu'
ROMAN = ROOT / 'transcripts-urdu-roman'
# English subtitles, translated from the audio (scripts/06-format/translate.py).
ENGLISH = ROOT / 'transcripts-english'
CACHE = ROOT / '.cache'
MODELS = CACHE / 'roman-model'
REPORTS = CACHE / 'reports'
GLOSSARY = ROOT / 'scripts' / '05-romanize' / 'roman_glossary.json'
INDEX = ROOT / 'docs' / 'episode-index.md'
APP = ROOT / 'app'
