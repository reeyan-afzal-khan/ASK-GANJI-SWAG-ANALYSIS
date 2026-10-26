"""SRT parsing and lossless text-line normalization (standard library only)."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import tempfile

TIMING = re.compile(r'^\d{2,}:\d{2}:\d{2},\d{3} --> \d{2,}:\d{2}:\d{2},\d{3}$')

@dataclass(frozen=True)
class Cue:
    number: str
    timing: str
    lines: tuple[str, ...]

    @property
    def text(self):
        return ' '.join(line.strip() for line in self.lines)

def parse(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.lstrip('\ufeff').replace('\r\n', '\n').strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isascii() or not lines[0].isdigit() or not TIMING.fullmatch(lines[1]):
            raise ValueError(f'Invalid SRT block: {block[:120]!r}')
        if not any(line.strip() for line in lines[2:]):
            raise ValueError(f'Empty subtitle {lines[0]}')
        cues.append(Cue(lines[0], lines[1], tuple(lines[2:])))
    return cues

def seconds(stamp):
    hours, minutes, rest = stamp.split(':')
    secs, ms = rest.split(',')
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(ms) / 1000

def span(cue):
    """(start, end) of a cue in seconds."""
    start, end = cue.timing.split(' --> ')
    return seconds(start), seconds(end)

def render(cues):
    return ''.join(f'{c.number}\n{c.timing}\n{c.text}\n\n' for c in cues)

def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, suffix='.tmp', delete=False) as handle:
            name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)

def select_files(folder, episodes=None):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f'Folder not found: {folder}')
    if episodes:
        numbers = sorted(set(int(n.strip()) for n in episodes.split(',')))
        if any(n < 1 for n in numbers):
            raise ValueError('Episode numbers must be positive')
        files = [folder / f'episode_{n:03d}.srt' for n in numbers]
        missing = [p.name for p in files if not p.is_file()]
        if missing:
            raise ValueError(f'Missing subtitles: {", ".join(missing)}')
    else:
        files = sorted(folder.glob('episode_*.srt'))
    if not files:
        raise ValueError(f'No episode SRT files in {folder}')
    return files
