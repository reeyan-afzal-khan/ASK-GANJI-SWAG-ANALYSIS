"""Download new episodes of the playlist and add their questions to docs/episode-index.md.

With no arguments, every video in the playlist that the index does not list yet counts as new: normally
just the last one. Its number comes from its title ("... | Ask Ganjiswag #243"), or else it is the next
number after the highest in the index. Its audio goes to the root folder as episode_NNN.mp3, where it
waits until the episode has its subtitles. Audio already there is used as it is, and an episode that
already has both subtitles is not downloaded again. The video's chapters become the episode's questions
in the index; a video without chapters yet gets them when this runs again.

NUMBER and URL download one chosen video instead.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app' / 'tools'))
from paths import AUDIO, DOWNLOADS, ENGLISH, INDEX, PLAYLIST, ROMAN
from subtitles import atomic_write
from build_data import read_index

PLAYLIST_ID = PLAYLIST.split('list=')[1]
# "Ask Ganjiswag #243" or "Ask Ganjiswag Special Episode #225", but not "#1 mistake | Ask Ganjiswag".
NUMBER = re.compile(r'ganji\s*swag[^|#]*#\s*(\d+)', re.I)
# Chapters that are not questions, and the name the index gives the comments segment.
NOT_A_QUESTION = re.compile(r'(?:intro(?:duction)?|outro|ending|end screen)', re.I)
COMMENTS = re.compile(r'(?:youtube )?comments?', re.I)
TIMESTAMP = re.compile(r'^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[-–—:]?\s*(.+?)\s*$')


def episode_number(title):
    """The episode number in a video's title, if it has one."""
    match = NUMBER.search(title or '')
    return int(match.group(1)) if match else None


def new_episodes(entries, index):
    """(number, video id, title) of the playlist's videos that the index does not list, oldest first.
    A title without a number takes the next one, in playlist order; a place in the playlist is not
    used, since a removed video shifts every place after it."""
    known = {video for items in index.values() for _, video, _ in items}
    last, found = max(index, default=0), []
    for entry in entries:
        if entry.get('id') not in known:
            number = episode_number(entry.get('title')) or last + 1
            last = max(last, number)
            found.append((number, entry['id'], entry.get('title') or ''))
    return sorted(found)


def chapters_of(info):
    """(title, start second) of a video's chapters, or else of the timestamps in its description."""
    chapters = [(chapter.get('title') or '', int(chapter['start_time'])) for chapter in info.get('chapters') or []]
    if chapters:
        return chapters
    found = []
    for line in (info.get('description') or '').splitlines():
        if match := TIMESTAMP.match(line):
            hours, minutes, seconds, title = match.groups()
            found.append((title, int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)))
    # A lone time in the description's text is not a chapter list, which starts at zero.
    return found if len(found) > 1 and found[0][1] == 0 else []


def questions_of(chapters):
    """The chapters as index entries: without the intro and outro, the comments named as elsewhere."""
    questions = []
    for title, start in chapters:
        title = title.strip()
        if COMMENTS.fullmatch(title):
            questions.append(('Youtube Comments', start))
        elif title and not NOT_A_QUESTION.fullmatch(title):
            questions.append((title, start))
    return questions


def index_block(number, video, questions):
    items = [f'{order}. [{title}](https://youtu.be/{video}?list={PLAYLIST_ID}&t={start})'
             for order, (title, start) in enumerate(questions, 1)]
    return '\n'.join(['<details open>', f'<summary><strong>Episode {number:03d}</strong></summary>', '', *items, '', '</details>'])


def add_to_index(path, number, video, questions):
    """Add the episode's block after the last one; what the index already holds is never changed."""
    text = Path(path).read_text(encoding='utf-8')
    end = text.rfind('</details>')
    block = index_block(number, video, questions)
    if end < 0:
        updated = f'{text.rstrip()}\n\n{block}\n'
    else:
        end += len('</details>')
        updated = f'{text[:end]}\n\n{block}{text[end:]}'
    atomic_write(path, updated)


def yt_dlp(*arguments):
    return subprocess.run(['yt-dlp', '--no-warnings', *arguments], check=True, stdout=subprocess.PIPE, encoding='utf-8').stdout


def has_subtitles(name):
    """Whether the episode has its Roman Urdu and English subtitles, which is all it needs its audio for."""
    return all((folder / f'{name}.srt').is_file() and (folder / f'{name}.srt').stat().st_size > 0 for folder in (ROMAN, ENGLISH))


def download(number, url):
    """The episode's audio, unless it is in the root folder already or the episode has its subtitles, and
    always its metadata, which may have changed. yt-dlp works in .cache/downloads/, so a download that stops
    leaves nothing in the root folder; only the finished audio moves there."""
    name = f'episode_{number:03d}'
    audio = AUDIO / f'{name}.mp3'
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    common = ['--no-playlist', '--write-info-json', '-P', str(DOWNLOADS), '-o', f'{name}.%(ext)s', '--', url]
    if audio.is_file() or has_subtitles(name):
        why = f'{audio.name} is in the root folder' if audio.is_file() else 'it already has both subtitles'
        print(f'[SKIP] {name}: {why}; reading its chapters', flush=True)
        subprocess.run(['yt-dlp', '--no-warnings', '--skip-download', *common], check=True)
    else:
        print(f'[START] {name}: {url}', flush=True)
        subprocess.run(['yt-dlp', '--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0',
                        '--sleep-interval', '5', '--max-sleep-interval', '15', *common], check=True)
        (DOWNLOADS / audio.name).replace(audio)
    return json.loads((DOWNLOADS / f'{name}.info.json').read_text(encoding='utf-8'))


def index_episode(number, info, index_path=INDEX):
    """Add the episode to the index, once. Returns how it went, in words."""
    name = f'Episode {number:03d}'
    if number in read_index(index_path):
        return f'{name} is already in the index.'
    questions = questions_of(chapters_of(info))
    if not questions:
        return f'{name} has no chapters on YouTube yet, so no questions were added. Run this again once it has.'
    add_to_index(index_path, number, info['id'], questions)
    return f'{name}: added {len(questions)} questions to {Path(index_path).name}.'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('number', nargs='?', type=int, help='Episode number of a chosen video')
    parser.add_argument('url', nargs='?', help='Its URL')
    args = parser.parse_args()
    if (args.number is None) != (args.url is None) or (args.number is not None and args.number < 1):
        parser.error('give both a positive NUMBER and a URL, or neither for the newest episode')
    try:
        if args.number:
            print(index_episode(args.number, download(args.number, args.url)))
            return
        print('Reading the playlist', flush=True)
        playlist = json.loads(yt_dlp('--flat-playlist', '--dump-single-json', PLAYLIST))
        found = new_episodes(playlist['entries'], read_index(INDEX))
        if not found:
            print(f'Nothing new: all {len(playlist["entries"])} videos of the playlist are in the index.')
        for number, video, title in found:
            print(f'New: episode {number}, "{title}"', flush=True)
            print(index_episode(number, download(number, f'https://www.youtube.com/watch?v={video}')))
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f'Error: yt-dlp failed ({exc.returncode}). If YouTube changed something, update it: bash scripts/01-setup/run.sh download\n')
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
