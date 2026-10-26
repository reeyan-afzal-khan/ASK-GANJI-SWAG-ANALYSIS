"""Pace or validate live SRT folders without models or old backups."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
import unicodedata
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path
from paths import ROOT, ROMAN, SOURCE, REPORTS, CACHE
from subtitles import Cue, parse, render, atomic_write, select_files, span
import pacing

ALIGNMENT = CACHE / 'alignment'

def non_latin(text):
    return [c for c in text if c.isalpha() and 'LATIN' not in unicodedata.name(c, '')]

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def alignment_for(path, source):
    """The cached word alignment of an episode, if it was made from the current source SRT."""
    cache = ALIGNMENT / f'{Path(path).stem}.json'
    original = Path(source) / Path(path).name
    if not cache.is_file() or not original.is_file():
        return None
    data = json.loads(cache.read_text(encoding='utf-8'))
    return data if data.get('source_sha256') == sha256(original) else None

def aligned_words(data):
    return ' '.join(cue[3] for cue in data['cues']).split()

def check_paced(path, source, cues, before):
    """A paced file keeps every source word in order, inside the source's time, without overlaps.

    Passages added from the audio may widen that time (a skipped intro or outro).
    Returns warnings: Roman words that differ from the alignment cache are hand corrections, kept.
    """
    if [c.number for c in cues] != [str(n) for n in range(1, len(cues) + 1)]:
        raise ValueError('Cue numbers are not consecutive')
    spans = [span(c) for c in cues]
    for cue, (start, end) in zip(cues, spans):
        if end <= start:
            raise ValueError(f'Cue {cue.number} ends before it starts')
    for k in range(1, len(spans)):
        if spans[k][0] < spans[k - 1][1]:
            raise ValueError(f'Cue {cues[k].number} overlaps the cue before it')
    data = alignment_for(path, source)
    applied = [s for s in data.get('supplements', []) if s.get('applied')] if data else []
    timing = [span(c) for c in before] + [(s['start'], s['end']) for s in applied]
    if spans[0][0] < min(start for start, _ in timing) - 0.5 or spans[-1][1] > max(end for _, end in timing) + 2.0:
        raise ValueError('Cues fall outside the timing of the source')
    text = ' '.join(c.text for c in cues)
    words = text.split()
    # Stitching duplicates are left out on purpose, and decoding loops may have been replaced by a
    # fresh transcription (the same rules pacing uses, applied to the source alone).
    originals = [(*span(c), c.text) for c in before]
    repeated = pacing.duplicates(originals)
    looped = {i for first, end in pacing.decoding_loops(originals) for i in range(first, end)}
    kept, i = [], 0
    for k, c in enumerate(before):
        for word in c.text.split():
            if k not in repeated and i not in looped:
                kept.append(word)
            i += 1
    kept_source = ' '.join(kept)
    # Like the per-cue check, search Latin runs as text: a source word that mixes scripts
    # (an Urdu letter fused to "ermany") becomes one Roman word ("jermany") that contains the run.
    cursor = 0
    for token in re.findall(r'[A-Za-z]+', kept_source):
        pos = text.find(token, cursor)
        if pos < 0:
            raise ValueError(f'Latin text changed or reordered near "{token}"')
        cursor = pos + len(token)
    if data is None:
        return []
    swapped = [p for p in data.get('loops', []) if p.get('applied')]
    expected = [w for w, *_ in pacing.words_for(data['cues'], None, applied, swapped)[0]]
    if expected == words:
        return []
    changed = sum(max(i1 - i0, j1 - j0) for tag, i0, i1, j0, j1 in
                  difflib.SequenceMatcher(None, expected, words, autojunk=False).get_opcodes() if tag != 'equal')
    return [f'{path.name}: {changed} words differ from the alignment cache (hand corrections, kept)']

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
            paced = [(c.number,c.timing) for c in cues] != [(c.number,c.timing) for c in before]
            if paced:
                warnings.extend(check_paced(path, source, cues, before))
                long = sum(len(c.text) > pacing.MAX_CHARS and len(c.text.split()) > 1 for c in cues)
                if long: warnings.append(f'{path.name}: {long} cues longer than {pacing.MAX_CHARS} characters')
            else:
                for old, new in zip(before, cues):
                    if old.text.isascii() and old.text != new.text:
                        raise ValueError(f'ASCII content changed in cue {old.number}')
                    cursor = 0
                    for token in re.findall(r'[A-Za-z]+', old.text):
                        pos = new.text.find(token, cursor)
                        if pos < 0:
                            raise ValueError(f'Latin text changed in cue {old.number}')
                        cursor = pos + len(token)
            corrupt = sum(c.text.count('�') for c in cues)
            if corrupt: warnings.append(f'{path.name}: {corrupt} pre-existing replacement characters need audio review')
            results.append({'file':path.name,'cues':len(cues),'paced':paced,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        except ValueError as exc:
            errors.append(f'{path.name}: {exc}')
    report={'files':len(files),'validated':len(results),'cues':sum(r['cues'] for r in results),'paced':sum(r['paced'] for r in results),'errors':errors,'warnings':warnings,'results':results}
    REPORTS.mkdir(parents=True,exist_ok=True)
    atomic_write(REPORTS/'validation.json', json.dumps(report,indent=2))
    print(f'Validated {len(results)}/{len(files)} files ({report["paced"]} paced); {report["cues"]:,} cues; {len(errors)} errors; {len(warnings)} warnings.')
    for error in errors: print(error)
    if warnings: print('Warnings recorded in .cache/reports/validation.json.')
    return bool(errors)

LOW_CONFIDENCE = -3.0   # mean log-probability of a cue's words under teacher forcing
TAGGED = re.compile(r'^\[[A-Za-z]+\][.,?!]*$')

def clock(seconds):
    seconds = int(seconds)
    return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'

def loops(words, minimum=4):
    """(index, repeats, phrase) for every word or phrase of up to four words repeated minimum+ times in a row."""
    found, i = [], 0
    while i < len(words):
        reps, size = 1, 1
        for n in range(1, 5):
            gram, r = words[i:i + n], 1
            while words[i + r * n:i + (r + 1) * n] == gram:
                r += 1
            if r >= minimum and r * n > reps * size:
                reps, size = r, n
        if reps >= minimum:
            found.append((i, reps, ' '.join(words[i:i + size])))
            i += reps * size
        else:
            i += 1
    return found

def review(folder, source, episodes=None):
    """What the audio check found, from the cached alignment: speech no cue covers, cues whose words the
    model doubts, and repetition loops. Nothing is changed; the findings are for listening to."""
    missed=[]; doubtful=[]; repeated=[]; looping=[]; checked=0
    for path in select_files(folder,episodes):
        data=alignment_for(path,source)
        if data is None:continue
        checked+=1
        filled={tuple(s['gap']) for s in data.get('supplements',[]) if s.get('applied')}
        # Decoding loops, and what a fresh transcription of each stretch decided (align.py --loops).
        records={tuple(p['replaces']):p for p in data.get('loops',[])}
        starts=[t[0] for c in data['cues'] for t in c[4]]
        for first,end in pacing.decoding_loops([(c[0],c[1],c[2]) for c in data['cues']]):
            p=records.get((first,end))
            if p is None:status='not transcribed again yet (bash scripts/06-format/run.sh --loops)'
            elif not p.get('phantom'):status=f'kept: {p.get("reason")}'
            elif p.get('roman') is None:status='confirmed as a phantom; waiting for Roman Urdu'
            else:status='replaced' if p.get('applied') else 'confirmed as a phantom; pace again to replace it'
            looping.append({'episode':path.stem,'at':clock(starts[first]),'words':end-first,'status':status,
                            'loop':pacing.roman_range(data['cues'],first,end),'heard':p.get('roman') if p else None})
        gone=[p['span'] for p in pacing.replacements(data['cues'],data.get('loops',[])) if p.get('applied')]
        replaced=lambda t:any(a<=t<=b for a,b in gone)
        for gap in data['gaps']:
            lo,hi,heard=gap[:3]
            spoken=[w for w in heard.split() if not TAGGED.match(w)]
            if len(spoken)>=3:
                # Only the Roman Urdu is reported (romanize.py --alignment adds it to the cache).
                missed.append({'episode':path.stem,'at':clock(lo),'seconds':round(hi-lo,1),'words':len(spoken),
                               'filled':(lo,hi) in filled,'heard':gap[3] if len(gap)>3 else None})
        # Words of replaced loops are no longer in the file, so they are not reported.
        times=[];words=[]
        for start,end,source_text,roman,cue_words in data['cues']:
            scores=[w[2] for w in cue_words if w[2] is not None]
            if scores and sum(scores)/len(scores)<LOW_CONFIDENCE and not replaced((start+end)/2):
                doubtful.append({'episode':path.stem,'at':clock(start),'score':round(sum(scores)/len(scores),2),'text':roman})
            for word,s,_ in pacing.roman_words(source_text,roman,cue_words):
                if not replaced(s):
                    words.append(word);times.append(s)
        for i,reps,phrase in loops(words):
            repeated.append({'episode':path.stem,'at':clock(times[i]),'kind':'repeated words','repeats':reps,'phrase':phrase})
        # Sounds stretched into one long token (wahahaha..., w-w-w-...) are loops too.
        for i,word in enumerate(words):
            if len(word)>=20 and len(set(word.lower()))<=5:
                repeated.append({'episode':path.stem,'at':clock(times[i]),'kind':'stretched word','repeats':len(word),'phrase':word[:40]+('...' if len(word)>40 else '')})
    report={'episodes_checked':checked,
            'missed_speech':{'stretches':len(missed),'seconds':round(sum(m['seconds'] for m in missed)),
                             'filled':sum(m['filled'] for m in missed),'items':missed},
            'low_confidence':{'threshold':LOW_CONFIDENCE,'cues':len(doubtful),'items':sorted(doubtful,key=lambda d:d['score'])},
            'loops':{'count':len(repeated),'items':sorted(repeated,key=lambda r:-r['repeats'])},
            'decoding_loops':{'count':len(looping),'replaced':sum(d['status']=='replaced' for d in looping),'items':looping}}
    REPORTS.mkdir(parents=True,exist_ok=True)
    atomic_write(REPORTS/'audio_check.json',json.dumps(report,ensure_ascii=False,indent=2))
    print(f'Audio check of {checked} episodes: {len(missed)} uncovered stretches with speech ({report["missed_speech"]["seconds"]:,} s, '
          f'{report["missed_speech"]["filled"]} now filled), {len(doubtful)} low-confidence cues, {len(repeated)} repetition loops, '
          f'{len(looping)} decoding loops ({report["decoding_loops"]["replaced"]} replaced). Details: .cache/reports/audio_check.json')
    pending=sum(m['heard'] is None for m in missed)
    if pending:
        print(f'{pending} heard passages are not in Roman Urdu yet; run scripts/05-romanize/romanize.py --alignment, then review again.')
    return False

def pace(folder, source, episodes=None, check=False):
    """Rewrite Roman SRTs as evenly paced single-line cues from the cached word alignment."""
    pending=[]; stale=[]; before_all=[]; after_all=[]; repeats=[]; filled=[]; swapped=[]; marks=[]; unromanised=0
    for path in select_files(folder,episodes):
        data=alignment_for(path,source)
        if data is None:
            stale.append(path.stem); continue
        raw=path.read_bytes()
        now=parse(raw.decode('utf-8-sig'))
        before_all+=[(*span(c),c.text) for c in now]
        # The words come from the file as it is now, so hand corrections are never reverted.
        current=' '.join(c.text for c in now).split()
        # Missed speech transcribed by align.py --fill joins once it is in Roman Urdu, and so does a
        # fresh transcription (align.py --loops) that confirms a decoding loop as a phantom.
        supplements=data.get('supplements',[]); relistened=data.get('loops',[])
        unromanised+=sum(s.get('roman') is None for s in supplements)+sum(bool(p.get('phantom')) and p.get('roman') is None for p in relistened)
        kept,dropped,inserted=pacing.words_for(data['cues'],current,supplements,relistened)
        paced=pacing.pace_words(kept,data.get('duration'))
        if [w for *_,t in paced for w in t.split()]!=[w for w,*_ in kept]:
            raise ValueError(f'Pacing changed the words of {path.name}')
        repeats+=[{'episode':path.stem,'at':clock(start),'text':text} for _,start,text in dropped]
        replacing=pacing.replacements(data['cues'],relistened)
        live=lambda p:p.get('applied') or any(p is q for q in inserted)
        filled+=[{'episode':path.stem,'at':clock(s['start']),'seconds':round(s['end']-s['start'],1),'text':s['roman']}
                 for s in supplements if live(s) and not any(pacing.covers(p,s) for p in replacing)]
        swapped+=[{'episode':path.stem,'at':clock(p['span'][0]),'seconds':round(p['span'][1]-p['span'][0],1),
                   'loop':pacing.roman_range(data['cues'],*p['replaces']),'text':p['roman']} for p in replacing if live(p)]
        if inserted:marks.append((path,data,inserted))
        after_all+=paced
        text=render([Cue(str(n),f'{pacing.stamp(s)} --> {pacing.stamp(e)}',(t,)) for n,(s,e,t) in enumerate(paced,1)])
        if text.encode('utf-8')!=raw: pending.append((path,raw,text))
    report={'changed':len(pending),'not_aligned':stale,'before':pacing.describe(before_all),'after':pacing.describe(after_all),
            'duplicates_removed':{'cues':len(repeats),'words':sum(len(r['text'].split()) for r in repeats),'items':repeats},
            'missed_speech_added':{'passages':len(filled),'words':sum(len(f['text'].split()) for f in filled),'items':filled},
            'loops_replaced':{'loops':len(swapped),'words_removed':sum(len(s['loop'].split()) for s in swapped),
                              'words_added':sum(len(s['text'].split()) for s in swapped),'items':swapped}}
    if check:
        print(f'{len(pending)} files need pacing; {len(stale)} have no current word alignment (run bash scripts/06-format/run.sh).')
        if after_all: print(f'Cues {report["before"]["cues"]:,} -> {report["after"]["cues"]:,}; median characters {report["before"]["chars"]["median"]} -> {report["after"]["chars"]["median"]}.')
        return bool(pending or stale)
    if stale:
        raise ValueError(f'No current word alignment for {len(stale)} episodes ({", ".join(stale[:6])}{", ..." if len(stale) > 6 else ""}); run bash scripts/06-format/run.sh')
    if pending:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=ROOT/'.cache/backups'/f'before-pacing-{stamp}.zip'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with ZipFile(backup,'x',ZIP_DEFLATED) as archive:
            for path,raw,_ in pending:archive.writestr(path.name,raw)
        with ZipFile(backup) as archive:
            for path,raw,_ in pending:
                if archive.read(path.name)!=raw:raise ValueError('Backup verification failed')
        for path,raw,text in pending:
            if path.read_bytes()!=raw:raise ValueError(f'File changed during pacing: {path}')
            atomic_write(path,text)
        print(f'Backup: {backup}')
    # Inserted passages are now part of the files: from here on they are matched like any words,
    # so later edits to them are kept and they are never inserted twice.
    for path,data,inserted in marks:
        for p in inserted:p['applied']=True
        atomic_write(ALIGNMENT/f'{path.stem}.json',json.dumps(data,ensure_ascii=False,separators=(',',':')))
    REPORTS.mkdir(parents=True,exist_ok=True)
    atomic_write(REPORTS/'pacing.json',json.dumps(report,indent=2))
    print(f'Paced {len(pending)} files.' + (f' Cues {report["before"]["cues"]:,} -> {report["after"]["cues"]:,}; median characters per cue {report["before"]["chars"]["median"]} -> {report["after"]["chars"]["median"]}.' if after_all else ''))
    if repeats:
        print(f'Left out {len(repeats):,} stitching duplicates ({report["duplicates_removed"]["words"]:,} words); listed in .cache/reports/pacing.json.')
    if filled:
        print(f'Includes {len(filled):,} passages of speech the original transcription skipped ({report["missed_speech_added"]["words"]:,} words).')
    if swapped:
        print(f'Replaced {len(swapped)} decoding loops ({report["loops_replaced"]["words_removed"]:,} words) with what a fresh transcription '
              f'heard ({report["loops_replaced"]["words_added"]:,} words).')
    if unromanised:
        print(f'{unromanised} transcribed passages wait for Roman Urdu; run scripts/05-romanize/romanize.py --alignment, then pace again.')
    return False

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['format','validate','review'])
    parser.add_argument('--directory',type=Path,default=ROMAN)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--episodes',help='Comma-separated episode numbers')
    parser.add_argument('--check',action='store_true',help='Report pacing changes without writing')
    args=parser.parse_args()
    try:
        if args.action=='format':
            failed=pace(args.directory,args.source,args.episodes,args.check)
            if not args.check:review(args.directory,args.source,args.episodes)
        elif args.action=='review':failed=review(args.directory,args.source,args.episodes)
        else:failed=validate(args.directory,args.source,args.episodes)
    except (ValueError,OSError) as exc:parser.exit(1,f'Error: {exc}\n')
    raise SystemExit(int(failed))

if __name__=='__main__':main()
