"""Format or validate live SRT folders without models or old backups."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path
from paths import ROOT, ROMAN, SOURCE, REPORTS
from subtitles import parse, render, atomic_write, select_files

def non_latin(text):
    return [c for c in text if c.isalpha() and 'LATIN' not in unicodedata.name(c, '')]

def validate(folder, source, episodes=None):
    results = []; errors = []; warnings = []
    files = select_files(folder, episodes)
    if not episodes and Path(source).is_dir():
        missing = {p.name for p in Path(source).glob('episode_*.srt')} - {p.name for p in files}
        errors.extend(f'Missing output: {name}' for name in sorted(missing))
    for path in files:
        try:
            cues = parse(path.read_text(encoding='utf-8-sig'))
            if any(len(c.lines) != 1 for c in cues):
                raise ValueError('Subtitle text spans multiple lines')
            if any(non_latin(c.text) for c in cues):
                raise ValueError('Non-Latin letters remain')
            original = Path(source) / path.name
            if not original.is_file():
                raise ValueError(f'Source not found: {original}')
            before = parse(original.read_text(encoding='utf-8-sig'))
            if [(c.number,c.timing) for c in cues] != [(c.number,c.timing) for c in before]:
                raise ValueError('Cue numbers or timestamps differ from source')
            for old, new in zip(before, cues):
                if old.text.isascii() and old.text != new.text:
                    raise ValueError(f'ASCII content changed in cue {old.number}')
                cursor = 0
                for token in re.findall(r'[A-Za-z]+', old.text):
                    pos = new.text.find(token, cursor)
                    if pos < 0:
                        raise ValueError(f'Latin text changed in cue {old.number}')
                    cursor = pos + len(token)
            corrupt = sum(c.text.count('\ufffd') for c in cues)
            if corrupt: warnings.append(f'{path.name}: {corrupt} pre-existing replacement characters need audio review')
            results.append({'file':path.name,'cues':len(cues),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        except ValueError as exc:
            errors.append(f'{path.name}: {exc}')
    report={'files':len(files),'validated':len(results),'cues':sum(r['cues'] for r in results),'errors':errors,'warnings':warnings,'results':results}
    REPORTS.mkdir(parents=True,exist_ok=True)
    atomic_write(REPORTS/'validation.json', json.dumps(report,indent=2))
    print(f'Validated {len(results)}/{len(files)} files; {report["cues"]:,} cues; {len(errors)} errors; {len(warnings)} warnings.')
    for error in errors: print(error)
    if warnings: print('Source-text warnings recorded in .cache/reports/validation.json.')
    return bool(errors)

def single_line(folder, episodes=None, check=False):
    pending=[]; joined=0
    for path in select_files(folder,episodes):
        raw=path.read_bytes(); cues=parse(raw.decode('utf-8-sig'))
        count=sum(len(c.lines)>1 for c in cues)
        if count:
            pending.append((path,raw,render(cues)));joined+=count
    if check:
        print(f'{len(pending)} files need formatting ({joined:,} cues).')
        return bool(pending)
    if pending:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=ROOT/'.cache/backups'/f'before-single-line-{stamp}.zip'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with ZipFile(backup,'x',ZIP_DEFLATED) as archive:
            for path,raw,_ in pending:archive.writestr(path.name,raw)
        with ZipFile(backup) as archive:
            for path,raw,_ in pending:
                if archive.read(path.name)!=raw:raise ValueError('Backup verification failed')
        for path,raw,text in pending:
            if path.read_bytes()!=raw:raise ValueError(f'File changed during formatting: {path}')
            atomic_write(path,text)
        print(f'Backup: {backup}')
    print(f'Joined {joined:,} cues in {len(pending)} files.')
    return False

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['format','validate'])
    parser.add_argument('--directory',type=Path,default=ROMAN)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--episodes',help='Comma-separated episode numbers')
    parser.add_argument('--check',action='store_true',help='Report formatting changes without writing')
    args=parser.parse_args()
    try:
        failed=single_line(args.directory,args.episodes,args.check) if args.action=='format' else validate(args.directory,args.source,args.episodes)
    except (ValueError,OSError) as exc:parser.exit(1,f'Error: {exc}\n')
    raise SystemExit(int(failed))

if __name__=='__main__':main()
