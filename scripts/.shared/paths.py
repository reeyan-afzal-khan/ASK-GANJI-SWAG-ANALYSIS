"""Repository locations, independent of the caller's working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / 'all_episodes'
SOURCE = ROOT / 'urdu_transcript_crisper'
ROMAN = ROOT / 'urdu_transcript_crisper_roman'
CACHE = ROOT / '.cache'
MODELS = CACHE / 'roman-model'
REPORTS = CACHE / 'reports'
GLOSSARY = ROOT / 'scripts' / '05-romanize' / 'roman_glossary.json'
INDEX = ROOT / 'docs' / 'episode-index.md'
APP = ROOT / 'app'
