#!/usr/bin/env python3
"""Full second-pass CrisperWhisper verification + conservative Urdu/English SRT repairs.

Every MP3 is transcribed chunk-by-chunk and compared to its original SRT.
Only clearly suspicious regions are automatically replaced; unresolved conflicts
are logged rather than rewritten blindly. No Romanization. Originals preserved.
"""
from __future__ import annotations
import argparse
import csv
import json
import sqlite3
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
SRT_TIME = re.compile(r"(?P<a>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<b>\d{2}:\d{2}:\d{2}[,.]\d{3})")
URDU = re.compile(r"[\u0600-\u06ff]")
TOK = re.compile(r"[A-Za-z0-9\u0600-\u06ff]+")
EP_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
# Cues with several Urdu-script renderings of English terms merit code-switch review.
PHONETIC_ENGLISH = ('ویلکم','ایکسپیرینس','پرابلم','ویڈیو','یوٹیوب','چینل',
 'سبسکرائب','کمیونیکیشن','سکلز','ریلیشنشپ','اکچولی','ڈیفنیٹلی',
 'ہونسٹلی','انسٹاگرام','کانفیڈنس','لیٹرلی','پلیز','ڈسکس','سٹارٹ','لرننگ',
 'ڈین وانڈ','ایپیسوڈ','اپیسوڈ','آئی ایم','تھنک','سوئمنگ')

@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    source: int = -1

@dataclass
class Window:
    start: float
    end: float
    first: int
    last: int           # inclusive source-cue indices
    reasons: set[str]


def parse_time(s: str) -> float:
    h, m, sec, ms = map(int, re.split('[:,.]', s))
    return h * 3600 + m * 60 + sec + ms / 1000.


def time_str(x: float) -> str:
    ms = max(0, round(x * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{milli:03d}'


def read_srt(path: Path) -> list[Cue]:
    txt = path.read_text(encoding='utf-8-sig', errors='replace').replace('\r\n','\n')
    out = []
    for block in re.split(r'\n\s*\n',txt):
        lines = block.strip().splitlines()
        index = next((i for i, line in enumerate(lines) if SRT_TIME.search(line)), None)
        if index is None:
            continue
        m = SRT_TIME.search(lines[index])
        a, b = parse_time(m['a']), parse_time(m['b'])
        text = ' '.join(line.strip() for line in lines[index+1:]).strip()
        if b > a and text:
            out.append(Cue(a,b,text,len(out)))
    return out


def clean_text(text: str) -> str:
    """Only normalize typography/whitespace; NEVER translate, Romanize, or guess words."""
    text = unicodedata.normalize('NFC', text)
    text = text.replace('\ufeff', '').replace('\u200b', '')
    text = re.sub(r'[\t\r\n ]+', ' ', text).strip()
    text = re.sub(r'\s+([,.!?;:،۔؟])', r'\1', text)
    text = re.sub(r'([\(\[\{])\s+', r'\1', text)
    text = re.sub(r'\s+([\)\]\}])', r'\1', text)
    return text


def write_srt_atomic(path: Path, cues: list[Cue]):
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = sorted((c for c in cues if c.end > c.start and c.text.strip()), key=lambda x: (x.start,x.end))
    lines=[]
    for i,c in enumerate(valid,1):
        lines.extend([str(i),f'{time_str(c.start)} --> {time_str(c.end)}',clean_text(c.text),''])
    # A completed episode is only visible after the entire file is successfully written.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,prefix='.partial_',suffix='.srt',delete=False) as f:
            tmp=Path(f.name);f.write('\n'.join(lines))
        os.replace(tmp,path)
    finally:
        if tmp and tmp.exists(): tmp.unlink()


def tokens(text:str)->list[str]:
    return TOK.findall(text.casefold())


def normalized(text:str)->str:
    return ' '.join(tokens(text))


def is_internal_loop(text: str) -> bool:
    tt=tokens(text)
    if len(tt)<12:return False
    for n in (4,5,6):
        ct=Counter(tuple(tt[i:i+n]) for i in range(len(tt)-n+1))
        if any(k>=3 for k in ct.values()):
            return True
    # Very long repeated 3-token sequences, with at least 4 occurrences
    ct=Counter(tuple(tt[i:i+3]) for i in range(len(tt)-2))
    return any(v>=4 for v in ct.values())


def detect(cues: list[Cue]) -> tuple[dict[int,set[str]], dict[int,set[str]]]:
    """Conservative high-priority repeat patterns; broad secondary warnings."""
    strong:dict[int,set[str]]={};other:dict[int,set[str]]={}
    for i,c in enumerate(cues):
        d=c.end-c.start
        if is_internal_loop(c.text) and (d>=6 or len(tokens(c.text))>50):
            strong.setdefault(i,set()).add('internal_phrase_loop')
        if sum(needle in c.text for needle in PHONETIC_ENGLISH)>=3 or any(phrase in c.text for phrase in ('ویلکم ٹو','ہاو ایک آلے','آئی ایم')):
            other.setdefault(i,set()).add('phonetic_english_review')
        if d>=18 and len(tokens(c.text))<=3:
            other.setdefault(i,set()).add('long_near_empty')
        if d>=20:
            other.setdefault(i,set()).add('long_subtitle_cue')
        if d>=15 and len(tokens(c.text))/d>4.8:
            other.setdefault(i,set()).add('high_text_density')
    i=0
    while i <len(cues):
        j=i+1
        same=normalized(cues[i].text)
        while j<len(cues) and same and normalized(cues[j].text)==same and cues[j].start-cues[j-1].end<=2.0:
            j+=1
        if j-i>=2 and ((cues[j-1].end-cues[i].start)>=10 or j-i>=4):
            for k in range(i,j): strong.setdefault(k,set()).add('identical_cue_loop')
        i=j
    return strong,other


def make_windows(cues: list[Cue], flagged: dict[int,set[str]], max_window=78, max_gap=5) -> list[Window]:
    if not flagged:return []
    ordered=sorted(flagged)
    blocks=[]
    left=right=ordered[0];reasons=set(flagged[left])
    for i in ordered[1:]:
        if cues[i].start-cues[right].end <= max_gap and cues[i].end-cues[left].start <= max_window:
            right=i;reasons |= flagged[i]
        else:
            blocks.append(Window(cues[left].start,cues[right].end,left,right,reasons))
            left=right=i;reasons=set(flagged[i])
    blocks.append(Window(cues[left].start,cues[right].end,left,right,reasons))
    return blocks


def ffmpeg_clip(mp3: Path, wav: Path, start: float, end: float) -> None:
    command=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
             '-ss',f'{start:.3f}','-t',f'{max(.1,end-start):.3f}','-i',str(mp3),
             '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)]
    result=subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not wav.exists() or wav.stat().st_size <= 44:
        raise RuntimeError('FFmpeg extraction failed: '+result.stderr[-500:])



# Audio-aware scanning: decode MP3 -> raw mono PCM through a pipe, never write a full WAV.
# WebRTC VAD catches likely speech missing from the old SRT timeline. It is not
# an ASR comparison and is not a calibrated accuracy/confidence estimate.
def merge_spans(spans: list[tuple[float,float]], gap:float=0.0)->list[tuple[float,float]]:
    merged=[]
    for a,b in sorted((max(0.0,a),b) for a,b in spans if b>a):
        if merged and a <= merged[-1][1]+gap:
            merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    return merged


def speech_intervals(mp3:Path, mode:int=1)->list[tuple[float,float]]:
    """Stream-decode entire audio; use 30-ms WebRTC VAD frames, O(seconds of speech) memory."""
    try: import webrtcvad
    except ImportError as e:
        raise RuntimeError('Deep scan requires webrtcvad-wheels. Run: pip install webrtcvad-wheels') from e
    sample_rate=16000
    frame_ms=30
    frame_bytes=sample_rate*frame_ms//1000*2
    proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-nostdin',
        '-i',str(mp3),'-vn','-ac','1','-ar','16000','-f','s16le','pipe:1'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    vad=webrtcvad.Vad(mode)
    intervals=[]; open_at=None; last_speech=None; total_frames=0
    try:
        while True:
            block=proc.stdout.read(frame_bytes)
            if len(block)<frame_bytes: break
            t=total_frames*frame_ms/1000
            total_frames+=1
            spoken=vad.is_speech(block,sample_rate)
            if spoken:
                if open_at is None: open_at=t
                last_speech=t+frame_ms/1000
            elif open_at is not None and t-last_speech>0.18:
                intervals.append((open_at,last_speech));open_at=None;last_speech=None
        if open_at is not None: intervals.append((open_at,last_speech))
        proc.stdout.close()
        err=proc.stderr.read().decode('utf-8','replace')[-1000:]
        if proc.wait()!=0: raise RuntimeError('Full MP3 audio scan failed: '+err)
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        if proc.stdout and not proc.stdout.closed:proc.stdout.close()
        if proc.stderr:proc.stderr.close()
    return [(a,b) for a,b in merge_spans(intervals,gap=0.38) if b-a>=0.45]


def subtract_spans(source:list[tuple[float,float]],cover:list[tuple[float,float]])->list[tuple[float,float]]:
    """Intervals in source without overlap with the union of cover."""
    output=[]
    union=merge_spans(cover)
    k=0
    for start,end in merge_spans(source):
        cursor=start
        while k<len(union) and union[k][1]<=start:k+=1
        j=k
        while j<len(union) and union[j][0]<end:
            a,b=union[j]
            if a>cursor:output.append((cursor,min(a,end)))
            cursor=max(cursor,b)
            if cursor>=end:break
            j+=1
        if cursor<end:output.append((cursor,end))
    return [(a,b) for a,b in output if b>a]


def find_uncaptioned_speech(cues:list[Cue],speech:list[tuple[float,float]],
        minimum:float=5.0,margin:float=0.75)->list[tuple[float,float]]:
    """Find prolonged likely voiced intervals not covered by any subtitle cue."""
    coverage=merge_spans([(max(0,c.start-margin),c.end+margin) for c in cues])
    # WebRTC VAD can mistake music for voice: requiring sustained uncovered
    # intervals intentionally sacrifices recall to avoid needless ASR.
    missing=subtract_spans(speech,coverage)
    return [(a,b) for a,b in missing if b-a>=minimum]


def find_silence_warnings(cues:list[Cue],speech:list[tuple[float,float]],
        min_len:float=7.5,max_voiced_frac:float=0.04)->list[Cue]:
    """Potential text in silence; DO NOT delete solely because VAD said silence."""
    voiced=merge_spans(speech)
    out=[]; k=0
    for cue in sorted(cues,key=lambda c:c.start):
        duration=cue.end-cue.start
        if duration<min_len:continue
        while k<len(voiced) and voiced[k][1]<cue.start:k+=1
        j=k;occupied=0.0
        while j<len(voiced) and voiced[j][0]<cue.end:
            a,b=voiced[j]
            occupied+=max(0,min(b,cue.end)-max(a,cue.start))
            j+=1
        if occupied/max(duration,0.001)<max_voiced_frac:out.append(cue)
    return out


def add_gap_windows(existing:list[Window],missing:list[tuple[float,float]],
                    max_window:float=78)->list[Window]:
    """Add true insert-only windows: leave all old cues untouched in those gaps."""
    uncovered=subtract_spans(missing,[(w.start,w.end) for w in existing])
    gaps=[]
    for a,b in uncovered:
        if b-a<2.5:continue
        cur=a
        while cur<b:
            stop=min(b,cur+max_window)
            if stop-cur>=2.5:
                gaps.append(Window(cur,stop,-1,-1,{'unsubtitled_speech_vad'}))
            cur=stop
    return sorted(existing+gaps,key=lambda w:(w.start,w.end))


def audio_scan_cache_key(mp3:Path,mode:int)->str:
    stat=mp3.stat()
    return hashlib.sha256(repr((str(mp3.resolve()),stat.st_size,stat.st_mtime_ns,mode)).encode()).hexdigest()

def find_mp3(folder: Path, ep: int) -> Path|None:
    for name in [f'episode_{ep:03d}.mp3',f'episode_{ep}.mp3',f'{ep:03d}.mp3',f'{ep}.mp3']:
        p=folder/name
        if p.is_file():return p
    # A tolerant fallback for descriptive filenames, without confusing ep 1 and 101.
    matches=[p for p in folder.glob('*.mp3') if any(int(m)==ep for m in map(int,EP_RE.findall(p.stem)))]
    return matches[0] if len(matches)==1 else None


def capture_words(segments, offset: float) -> list[Cue]:
    out=[]
    for seg in segments:
        words=getattr(seg,'words',None)
        if words:
            for w in words:
                val=str(getattr(w,'word','')).strip()
                a=offset+float(getattr(w,'start',0) or 0)
                b=offset+float(getattr(w,'end',0) or 0)
                if val and b>a:out.append(Cue(a,b,val))
        else:
            txt=str(getattr(seg,'text','')).strip()
            a=offset+float(getattr(seg,'start',0) or 0)
            b=offset+float(getattr(seg,'end',0) or 0)
            if txt and b>a:out.append(Cue(a,b,txt))
    return out

class ASR:
    def __init__(self,engine:str,model:str,language:str,device:str):
        self.engine=engine;self.language=None if language=='auto' else language
        if engine=='whisper':
            from faster_whisper import WhisperModel
            chosen='cuda' if device=='auto' and cuda_available() else ('cpu' if device=='auto' else device)
            compute_type='float16' if chosen=='cuda' else 'int8'
            self.model=WhisperModel(model or 'large-v3',device=chosen,compute_type=compute_type)
        elif engine=='crisper':
            from crisperwhisper import CrisperWhisperModel
            # PyTorch backend avoids incompatibilities with faster-whisper's ctranslate2.
            self.model=CrisperWhisperModel(model or 'large',backend='transformers')
        else:raise ValueError(engine)

    def transcribe(self,wav:Path, offset:float)->list[Cue]:
        if self.engine=='whisper':
            segs,_=self.model.transcribe(str(wav), task='transcribe',
                language=self.language, beam_size=5, best_of=5,
                condition_on_previous_text=False, vad_filter=True,
                word_timestamps=True, repetition_penalty=1.1,
                hallucination_silence_threshold=1.0,
                compression_ratio_threshold=2.4, log_prob_threshold=-1.0)
            return capture_words(list(segs),offset)
        # Crisper requires an explicit language, does not offer auto in same sense.
        if self.language is None:
            raise ValueError('Crisper requires --language ur or en')
        result=self.model.transcribe(str(wav),language=self.language,
             mode='verbatim',word_timestamps=True,hallucination_mitigation=True)
        words=getattr(result,'words',None) or []
        if words:
            return capture_words([result],offset)
        txt=getattr(result,'text','')
        # For a model with no word times, do not invent precise per-word timings.
        if txt:
            import wave
            with wave.open(str(wav),'rb') as wf:duration=wf.getnframes()/wf.getframerate()
            return [Cue(offset,offset+duration,str(txt).strip())]
        return []


def cuda_available()->bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return bool(shutil.which('nvidia-smi'))


def chunk_words(words:list[Cue], core_start:float, core_end:float, max_words:int=12,max_seconds:float=5.5)->list[Cue]:
    chosen=[]
    for w in sorted(words,key=lambda x:x.start):
        if core_start <= (w.start+w.end)/2 <= core_end:
            a=max(core_start,w.start);b=min(core_end,w.end)
            if b>a:chosen.append(Cue(a,b,w.text))
    chunks=[]; current=[]
    for w in chosen:
        if current and (len(current)>=max_words or w.end-current[0].start>max_seconds or w.start-current[-1].end>1.25):
            chunks.append(current);current=[]
        current.append(w)
    if current:chunks.append(current)
    result=[]
    for group in chunks:
        # Do not inject fake words or text; only normalize spacing and punctuation.
        text=' '.join(w.text.strip() for w in group)
        text=re.sub(r'\s+([,.!?;:،۔])',r'\1',text)
        result.append(Cue(group[0].start,group[-1].end,text))
    return result

# --- Dependency checks: no Roman Urdu model is needed ---
def check_runtime(*, engine: str='crisper', deep_scan: bool=False,
                  clean_only: bool=False, verbose: bool=True) -> bool:
    import importlib.util
    need=[] if clean_only else (['crisperwhisper'] if engine=='crisper' else ['faster_whisper'])
    if deep_scan and not clean_only:
        need.append('webrtcvad')
    missing=[name for name in need if importlib.util.find_spec(name) is None]
    if not clean_only and not shutil.which('ffmpeg'):
        missing.append('ffmpeg')
    if not clean_only and not shutil.which('ffprobe'):
        missing.append('ffprobe')
    if verbose:
        for name in need:
            print(f'  {name}: {"MISSING" if name in missing else "OK"}', flush=True)
        print(f'  ffmpeg: {"OK" if shutil.which("ffmpeg") else "MISSING"}', flush=True)
        print(f'  ffprobe: {"OK" if shutil.which("ffprobe") else "MISSING"}', flush=True)
        print('  Romanizer: NONE (Urdu script and English preserved)', flush=True)
    if missing:
        print('Missing: '+', '.join(missing),file=sys.stderr)
        print('Install required packages from requirements.txt WITHOUT replacing Jetson PyTorch.',file=sys.stderr)
        return False
    return True


def doctor() -> int:
    print('Urdu + English SRT cleaner — preflight',flush=True)
    print('  Spacing normalization:',clean_text('  کیا حال ہے  machine learning  کے بارے میں ؟ '),flush=True)
    try:
        import torch
        print(f'  torch: {torch.__version__}, CUDA: {torch.cuda.is_available()}',flush=True)
    except ImportError:
        print('  torch not installed (only needed for Crisper audio repair)',flush=True)
    return 0 if check_runtime(engine='crisper',deep_scan=True) else 2


class RepairCache:
    """A single resumable SQLite file; cached successful regions avoid repeated ASR."""
    def __init__(self,path:Path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS patches (key TEXT PRIMARY KEY, result TEXT NOT NULL)')
    def get(self,key:str)->list[Cue]|None:
        row=self.db.execute('SELECT result FROM patches WHERE key=?',(key,)).fetchone()
        if row is None:return None
        return [Cue(float(a),float(b),str(t)) for a,b,t in json.loads(row[0])]
    def put(self,key:str,words:list[Cue]):
        value=json.dumps([[c.start,c.end,c.text] for c in words],ensure_ascii=False)
        self.db.execute('INSERT OR REPLACE INTO patches(key,result) VALUES (?,?)',(key,value))
        self.db.commit()
    def get_speech(self,key:str)->list[tuple[float,float]]|None:
        self.db.execute('CREATE TABLE IF NOT EXISTS audio_scans (key TEXT PRIMARY KEY, result TEXT NOT NULL)')
        row=self.db.execute('SELECT result FROM audio_scans WHERE key=?',(key,)).fetchone()
        return [(float(a),float(b)) for a,b in json.loads(row[0])] if row else None
    def put_speech(self,key:str,spans:list[tuple[float,float]]):
        self.db.execute('CREATE TABLE IF NOT EXISTS audio_scans (key TEXT PRIMARY KEY, result TEXT NOT NULL)')
        self.db.execute('INSERT OR REPLACE INTO audio_scans(key,result) VALUES(?,?)',
                        (key,json.dumps(spans)))
        self.db.commit()
    def close(self):self.db.close()

def region_cache_key(src:Path,mp3:Path,ep:int,w:Window,engine:str,model:str,language:str)->str:
    meta=(ep,w.start,w.end,engine,model or ('large' if engine=='crisper' else 'large-v3'),
          language,src.stat().st_size,src.stat().st_mtime_ns,mp3.stat().st_size,mp3.stat().st_mtime_ns)
    return hashlib.sha256(repr(meta).encode()).hexdigest()

def repair_one_window(mp3:Path,w:Window,work:Path,asr:ASR,padding:float=2.5)->tuple[list[Cue],str]:
    audio_start=max(0,w.start-padding)
    audio_end=w.end+padding
    wav=work/'clip.wav'
    try:
        ffmpeg_clip(mp3,wav,audio_start,audio_end)
        units=asr.transcribe(wav,audio_start)
        out=chunk_words(units,w.start,w.end)
        if not out or not any(len(tokens(x.text))>=1 for x in out):
            return [],'NO_SPEECH_OR_NO_WORD_TIMINGS'
        all_text=' '.join(x.text for x in out)
        if is_internal_loop(all_text) and (w.end-w.start)>=10:
            return [],'STILL_REPETITIVE'
        return out,'PATCHED'
    finally:
        # Both success and failure paths discard the temporary WAV.
        wav.unlink(missing_ok=True)


def episode_from_name(path:Path)->int:
    m=re.search(r'episode_(\d{1,3})\.srt$',path.name,re.I)
    if m:return int(m.group(1))
    raise ValueError(f'Unexpected filename: {path}')


def select_srt_files(root:Path, only:str|None):
    wanted=None
    if only:
        wanted={int(item) for item in only.split(',') if item.strip()}
    return [p for p in sorted(root.glob('episode_*.srt'), key=episode_from_name) if wanted is None or episode_from_name(p) in wanted]


def write_csv(path:Path,rows:list[dict],headers:list[str]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def audit(files:list[Path],destination:Path,max_window:float=78) ->tuple[list[dict],list[dict]]:
    summaries=[];windows=[]
    for path in files:
        ep=episode_from_name(path);cues=read_srt(path);high,other=detect(cues)
        win=make_windows(cues,high,max_window=max_window)
        high_sec=sum(cues[i].end-cues[i].start for i in high)
        for w in win:
            windows.append(dict(episode=f'{ep:03d}',start=time_str(w.start),end=time_str(w.end),
                seconds=round(w.end-w.start,1),reasons='|'.join(sorted(w.reasons)),
                excerpt=cues[w.first].text[:110]))
        summaries.append(dict(episode=f'{ep:03d}',cues=len(cues),
            timeline_minutes=round(cues[-1].end/60,1) if cues else 0,
            high_risk_cues=len(high),high_risk_minutes=round(high_sec/60,2),
            repair_windows=len(win),long_timing_cues=sum('long_subtitle_cue' in x for x in other.values()),
            near_empty_cues=sum('long_near_empty' in x for x in other.values()),
            phonetic_english_cues=sum('phonetic_english_review' in x for x in other.values())))
    write_csv(destination/'repair_windows.csv',windows,['episode','start','end','seconds','reasons','excerpt'])
    write_csv(destination/'episode_audit.csv',summaries,['episode','cues','timeline_minutes','high_risk_cues','high_risk_minutes','repair_windows','long_timing_cues','near_empty_cues','phonetic_english_cues'])
    return summaries,windows


def append_review(path:Path,row:dict):
    fields=['episode','start','end','status','reason','comment']
    first=not path.exists()
    with path.open('a',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        if first:writer.writeheader()
        writer.writerow(row)



# -- v9: full-episode second-pass comparison with conservative selective correction --
import difflib

CACHE_VERSION = 'full_second_pass_v9_word_timestamps'
RESULTS = HERE/'audit'/'results'
DEFAULT_SRT_OUT = HERE/'urdu_transcript_srt_crisper'


def audio_duration(mp3:Path)->float:
    """Get actual media duration, not the (possibly inaccurate) SRT end time."""
    p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                      '-of','default=noprint_wrappers=1:nokey=1',str(mp3)],
                     capture_output=True,text=True,timeout=90)
    if p.returncode!=0: raise RuntimeError('ffprobe failed: '+p.stderr[-300:])
    try:d=float(p.stdout.strip())
    except ValueError: raise RuntimeError('ffprobe returned no numeric duration')
    if not math.isfinite(d) or d<=0:raise RuntimeError('Invalid MP3 duration')
    return d


def episode_chunks(duration:float,cues:list[Cue],seconds:float=55.0)->list[tuple[float,float]]:
    """Cover the ENTIRE MP3; try to place boundaries at existing cue ends."""
    if duration<=0:return []
    cuts=[];left=0.0
    ends=sorted(set(c.end for c in cues if c.end>0 and c.end<duration))
    import bisect
    while left<duration-0.02:
        target=min(duration,left+seconds)
        if target<duration:
            at=bisect.bisect_left(ends,target)
            candidates=ends[max(0,at-4):at+5]
            eligible=[v for v in candidates if left+15<=v<=min(duration,target+3) and abs(v-target)<=4]
            if eligible:target=min(eligible,key=lambda t:abs(target-t))
        if target<=left+0.02:target=min(duration,left+seconds)
        cuts.append((round(left,3),round(target,3)))
        left=target
    return cuts


def compare_text(original:str,candidate:str)->float:
    """Similarity is a triage signal, NEVER calibrated confidence."""
    a=normalized(clean_text(original));b=normalized(clean_text(candidate))
    if not a and not b:return 1.0
    if not a or not b:return 0.0
    return difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()


def voice_seconds(span:tuple[float,float],speech:list[tuple[float,float]])->float:
    a,b=span
    return sum(max(0.0,min(b,e)-max(a,s)) for s,e in speech)


def cached_second_pass_key(mp3:Path,ep:int,start:float,end:float,engine:str,model:str,language:str)->str:
    st=mp3.stat()
    data=[CACHE_VERSION,ep,str(mp3.resolve()),st.st_size,st.st_mtime_ns,
          round(start,3),round(end,3),engine,model or ('large' if engine=='crisper' else 'large-v3'),language]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False).encode()).hexdigest()


def episode_signature(src:Path,mp3:Path,engine:str,model:str,language:str,
                      seconds:float,deep_scan:bool,code_switch:bool)->str:
    data=[CACHE_VERSION,*( (str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns) for p in [src,mp3]),
          engine,model,language,seconds,deep_scan,code_switch]
    return hashlib.sha256(repr(data).encode()).hexdigest()


def initialize_result_cache(results:Path)->Path:
    """Copy existing v8 cache once; new writes belong only in audit/results."""
    results.mkdir(parents=True,exist_ok=True)
    dest=results/'repair_cache.sqlite3'
    if dest.exists():return dest
    candidates=[HERE/'subtitles_cleaned'/'repair_cache.sqlite3',
                HERE/'subtitles'/'repair_cache.sqlite3',
                HERE/'audit'/'repair_cache.sqlite3']
    for c in candidates:
        if c.is_file():
            shutil.move(str(c),str(dest))
            print(f'Migrated previous repair cache: {c} -> {dest}',flush=True)
            break
    return dest


def migrate_review(results:Path):
    """Keep prior review data without leaving new logs in subtitle output."""
    dest=results/'review.csv'
    if dest.exists():return
    for c in [HERE/'subtitles_cleaned'/'review.csv',HERE/'subtitles'/'review.csv']:
        if c.is_file():
            shutil.move(str(c),str(dest))
            print(f'Migrated previous review CSV: {c} -> {dest}',flush=True)
            break


def store_review_episode(path:Path,ep:int,rows:list[dict]):
    """Replace this episode's audit rows atomically to avoid duplicates with --force."""
    fields=['episode','start','end','status','reason','comment']
    epstr=f'{ep:03d}'
    previous=[]
    if path.exists():
        with path.open('r',newline='',encoding='utf-8-sig') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames and all(k in reader.fieldnames for k in fields):
                previous=[dict(row) for row in reader if row.get('episode','')!=epstr]
    write_csv(path,previous+[{**{'episode':epstr},**row} for row in rows],fields)


def ensure_pass_tables(cache:RepairCache):
    cache.db.execute('CREATE TABLE IF NOT EXISTS full_second_pass (key TEXT PRIMARY KEY, result TEXT NOT NULL)')
    cache.db.execute('CREATE TABLE IF NOT EXISTS completed_episodes (episode INTEGER PRIMARY KEY, signature TEXT NOT NULL, cues INTEGER NOT NULL, completed_at TEXT NOT NULL)')
    cache.db.commit()


def get_pass(cache:RepairCache,key:str)->list[Cue]|None:
    row=cache.db.execute('SELECT result FROM full_second_pass WHERE key=?',(key,)).fetchone()
    if row is None:return None
    return [Cue(float(a),float(b),str(t)) for a,b,t in json.loads(row[0])]


def save_pass(cache:RepairCache,key:str,units:list[Cue]):
    data=json.dumps([[c.start,c.end,c.text] for c in units],ensure_ascii=False)
    cache.db.execute('INSERT OR REPLACE INTO full_second_pass (key,result) VALUES (?,?)',(key,data))
    cache.db.commit()


def is_completed(cache:RepairCache,ep:int,signature:str)->bool:
    row=cache.db.execute('SELECT signature FROM completed_episodes WHERE episode=?',(ep,)).fetchone()
    return bool(row and row[0]==signature)


def mark_completed(cache:RepairCache,ep:int,signature:str,num:int):
    from datetime import datetime,timezone
    cache.db.execute('INSERT OR REPLACE INTO completed_episodes(episode,signature,cues,completed_at) VALUES(?,?,?,?)',
                     (ep,signature,num,datetime.now(timezone.utc).isoformat()))
    cache.db.commit()


def segment_is_good(words:list[Cue],start:float,end:float)->bool:
    """Require timed, nonempty ASR before ANY automatic replacement."""
    if not words:return False
    if not all((w.end>w.start and w.text.strip()) for w in words):return False
    # A single untimed transcript masquerading as the whole long chunk is unsafe for splice.
    if len(words)==1 and (words[0].end-words[0].start)>12 and len(tokens(words[0].text))>8:return False
    text=' '.join(w.text for w in words)
    if is_internal_loop(text):return False
    return True


def choose_repairs(old:list[Cue],words:list[Cue],speech:list[tuple[float,float]],
                   high:dict[int,set[str]],code_switch:bool,max_window:float,
                   reviews:list[dict])->list[Cue]:
    """Replace obvious loops, optionally some phonetic-English regions, insert strong gaps.

    Every audio chunk receives independent ASR separately (above). Plausible differences
    are logged, not auto-applied because two ASRs can both be wrong.
    """
    other=detect(old)[1]
    flagged={i:set(reasons) for i,reasons in high.items()}
    if code_switch:
        for i,reasons in other.items():
            if 'phonetic_english_review' in reasons:
                flagged.setdefault(i,set()).add('phonetic_english_review')
    windows=make_windows(old,flagged,max_window=max_window)
    missing=find_uncaptioned_speech(old,speech,minimum=5) if speech else []
    windows=add_gap_windows(windows,missing,max_window=max_window)
    gone=set();patches=[]
    for window in windows:
        chosen=[x for x in words if window.start-0.001 <= (x.start+x.end)/2 < window.end+0.001]
        reason='|'.join(sorted(window.reasons))
        if not segment_is_good(chosen,window.start,window.end):
            reviews.append(dict(start=time_str(window.start),end=time_str(window.end),status='NEEDS_REVIEW',reason=reason,
                                comment='ASR returned missing/repeated/unaligned text; original retained'))
            continue
        if window.first>=0 and window.reasons=={'phonetic_english_review'}:
            # Do not claim to have fixed code-switching if the second model still
            # writes everything in Urdu script. This is especially important with --language ur.
            if not re.search(r'[A-Za-z]{3,}', ' '.join(x.text for x in chosen)):
                reviews.append(dict(start=time_str(window.start),end=time_str(window.end),
                                    status='CODE_SWITCH_UNRESOLVED',reason='phonetic_english_review',
                                    comment='Second ASR did not provide English-script words; original retained'))
                continue
        if window.first<0:
            # Music and applause can fool VAD. Require sustained VAD speech and timed ASR.
            voiced=voice_seconds((window.start,window.end),speech)
            if voiced<3 or voiced/max(window.end-window.start,.01)<.35:
                reviews.append(dict(start=time_str(window.start),end=time_str(window.end),status='GAP_REVIEW',reason='vad',
                                    comment='Possible missing speech; insufficient VAD support to insert automatically'))
                continue
        new=chunk_words(chosen,window.start,window.end)
        if not new:
            reviews.append(dict(start=time_str(window.start),end=time_str(window.end),status='NEEDS_REVIEW',reason=reason,
                                comment='Unable to build timestamped replacement cues'))
            continue
        if window.first>=0:
            # Only remove original cues whose CENTER is inside successfully replaced span;
            # do not remove distant neighboring captions.
            for i,c in enumerate(old):
                if window.start <= (c.start+c.end)/2 <= window.end and window.first<=i<=window.last:gone.add(i)
        patches.extend(new)
        reviews.append(dict(start=time_str(window.start),end=time_str(window.end),status='REPAIRED',reason=reason,
                            comment=f'Replaced with {len(new)} ASR cue(s) from full second pass'))
    combined=[c for i,c in enumerate(old) if i not in gone]+patches
    return [Cue(c.start,c.end,clean_text(c.text)) for c in sorted(combined,key=lambda x:(x.start,x.end)) if clean_text(c.text)]


def run(files:list[Path],audio_dir:Path,output_dir:Path,engine:str='crisper',model:str='',
        lang:str='ur',device:str='auto',force:bool=False,clean_only:bool=False,
        limit:int|None=None,max_window:float=78,repair_code_switch:bool=False,
        allow_incomplete:bool=False,no_cache:bool=False,deep_scan:bool=True,
        cache_path:Path|None=None,chunk_seconds:float=55.0,results_dir:Path|None=None):
    """Generate output for EVERY raw SRT; full audio ASR comparison by default."""
    if not files:raise RuntimeError('No raw SRT files found')
    output_dir.mkdir(parents=True,exist_ok=True)
    results=results_dir or (HERE/'audit'/'results')
    results.mkdir(parents=True,exist_ok=True)
    migrate_review(results)
    review=results/'review.csv'
    if cache_path is None:cache_path=initialize_result_cache(results)
    else:
        cache_path.parent.mkdir(parents=True,exist_ok=True)
        if cache_path.resolve()!=(results/'repair_cache.sqlite3').resolve():
            raise ValueError('Cache must be stored at audit/results/repair_cache.sqlite3')
    cache=None if clean_only else RepairCache(cache_path)
    if cache is not None:ensure_pass_tables(cache)
    asr=None;completed=skipped=errors=0
    try:
        for src in files:
            ep=episode_from_name(src)
            dest=output_dir/f'episode_{ep:03d}.srt'
            reviews=[]
            try:
                old=read_srt(src)
                if not old:raise RuntimeError('SRT contains no readable captions')
                high,other=detect(old)
                if any('long_subtitle_cue' in x for x in other.values()):
                    reviews.append(dict(status='LONG_CUE_WARNING',reason='timing',
                                        comment=f'{sum("long_subtitle_cue" in x for x in other.values())} original cues >=20 seconds'))
                if any('phonetic_english_review' in x for x in other.values()):
                    reviews.append(dict(status='CODE_SWITCH_WARNING',reason='urdu_phonetic_english',
                                        comment=f'{sum("phonetic_english_review" in x for x in other.values())} cues merit English spelling review'))
                if clean_only:
                    # Formatting-only output must NEVER inherit an earlier 'full pass done' marker.
                    if cache_path.exists():
                        with sqlite3.connect(cache_path) as marker_db:
                            t={r[0] for r in marker_db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
                            if 'completed_episodes' in t:
                                marker_db.execute('DELETE FROM completed_episodes WHERE episode=?',(ep,))
                                marker_db.commit()
                    result=[Cue(x.start,x.end,clean_text(x.text)) for x in old]
                    write_srt_atomic(dest,result)
                    reviews.append(dict(status='FORMATTING_ONLY',reason='no_audio',comment='NOT a second audio pass'))
                    store_review_episode(review,ep,reviews)
                    completed+=1
                    print(f'[{ep:03d}] formatted {len(result)} cues (no ASR)',flush=True)
                    if limit and completed>=limit:break
                    continue
                mp3=find_mp3(audio_dir,ep)
                if mp3 is None:raise RuntimeError('No corresponding MP3; full second pass NOT performed')
                signature=episode_signature(src,mp3,engine,model,lang,chunk_seconds,deep_scan,repair_code_switch)
                if dest.exists() and is_completed(cache,ep,signature) and not force and not no_cache:
                    skipped+=1
                    print(f'[{ep:03d}] verified prior full second pass; resume skip',flush=True)
                    continue
                duration=audio_duration(mp3)
                if max(c.end for c in old)>duration+10:
                    reviews.append(dict(status='TIMING_WARNING',reason='duration',
                        comment=f'Last SRT ends at {old[-1].end:.1f}s, MP3 at {duration:.1f}s'))
                print(f'[{ep:03d}] full second ASR pass: {duration/60:.1f} minutes, {len(old):,} old cues',flush=True)
                # VAD scans all audio to recognize missing-speech windows, not speech accuracy.
                speech=[]
                if deep_scan:
                    vadkey=audio_scan_cache_key(mp3,1)
                    speech=None if no_cache else cache.get_speech(vadkey)
                    if speech is None:
                        speech=speech_intervals(mp3,mode=1)
                        cache.put_speech(vadkey,speech)
                    missing=find_uncaptioned_speech(old,speech)
                    silent=find_silence_warnings(old,speech)
                    for cue in silent[:100]:
                        reviews.append(dict(start=time_str(cue.start),end=time_str(cue.end),
                                            status='POSSIBLE_SILENT_TEXT',reason='vad_only',
                                            comment='Long caption but little detected speech; not deleted automatically'))
                    print(f'[{ep:03d}] VAD: {len(missing)} possible uncaptioned spans, {len(silent)} silence warnings',flush=True)
                spans=episode_chunks(duration,old,seconds=chunk_seconds)
                all_words=[];failures=0;disagreements=0;chunk_summary=[]
                with tempfile.TemporaryDirectory(prefix='ganji_pass_') as tmp:
                    tmpdir=Path(tmp)
                    for j,(a,b) in enumerate(spans,1):
                        key=cached_second_pass_key(mp3,ep,a,b,engine,model,lang)
                        units=None if no_cache else get_pass(cache,key)
                        if units is not None:
                            how='cached'
                        else:
                            try:
                                if asr is None:
                                    print('Loading CrisperWhisper 2.0 Large for full pass...',flush=True)
                                    asr=ASR(engine,model,lang,device)
                                wav=tmpdir/'current_chunk.wav'
                                begin=max(0,a-2.5);ending=min(duration,b+2.5)
                                try:
                                    ffmpeg_clip(mp3,wav,begin,ending)
                                    units=asr.transcribe(wav,begin)
                                finally:
                                    wav.unlink(missing_ok=True)
                                if units is None:units=[]
                                if not segment_is_good(units,begin,ending) and units:
                                    raise RuntimeError('Unreliable ASR words (loop or missing alignment)')
                                save_pass(cache,key,units)
                                how='ASR'
                            except Exception as e:
                                failures+=1
                                reviews.append(dict(start=time_str(a),end=time_str(b),status='SECOND_PASS_ERROR',
                                                    reason='asr',comment=str(e)[:320]))
                                print(f'[{ep:03d}] chunk {j}/{len(spans)} ERROR: {e}',flush=True)
                                continue
                        # crop padding: each spoken word belongs to exactly one core window
                        selected=[x for x in units if a<=((x.start+x.end)/2)<b]
                        all_words.extend(selected)
                        if speech and not selected and voice_seconds((a,b),speech)>=4:
                            reviews.append(dict(start=time_str(a),end=time_str(b),
                                                status='VOICE_WITHOUT_ASR',reason='asr_vad',
                                                comment='VAD detected speech but independent ASR gave no words; inspect audio'))
                        candidate=' '.join(x.text for x in selected)
                        baseline=' '.join(x.text for x in old if a<=((x.start+x.end)/2)<b)
                        score=compare_text(baseline,candidate)
                        if baseline.strip() and candidate.strip() and score<0.54 and len(tokens(baseline))>=5:
                            disagreements+=1
                            if disagreements<=500:
                                reviews.append(dict(start=time_str(a),end=time_str(b),status='DISAGREEMENT_REVIEW',
                                                    reason='asr_comparison',
                                                    comment=f'similarity={score:.2f}; old/new differ; not automatically overwritten'))
                        if j==1 or j==len(spans) or j%10==0:
                            print(f'[{ep:03d}] second pass {j}/{len(spans)} ({how}), {disagreements} disagreements',flush=True)
                if failures and not allow_incomplete:
                    reviews.append(dict(status='INCOMPLETE_SECOND_PASS',reason='asr',
                                        comment=f'{failures} chunks failed. No finalized SRT written. Successful ASR chunks are cached.'))
                    store_review_episode(review,ep,reviews)
                    print(f'[{ep:03d}] incomplete: {failures} failed chunks; no published SRT',flush=True)
                    errors+=1
                    continue
                result=choose_repairs(old,all_words,speech,high,repair_code_switch,max_window,reviews)
                leftover,_=detect(result)
                if leftover:
                    reviews.append(dict(status='RESIDUAL_REPETITION',reason='text_heuristic',
                                        comment=f'{len(leftover)} cues still flagged after second pass'))
                if disagreements>500:
                    reviews.append(dict(status='DISAGREEMENTS_TRUNCATED',reason='review_limit',
                                        comment=f'{disagreements} discrepant windows; first 500 logged'))
                summary_status='SECOND_PASS_PARTIAL' if failures else 'SECOND_PASS_COMPLETE'
                reviews.append(dict(status=summary_status,reason='full_audio',
                                    comment=f'{len(spans)} checked chunks; {len(old)} input cues; {len(result)} output cues; '
                                            f'{disagreements} disagreements; {failures} failed chunks; {len(high)} high-risk original cues'))
                write_srt_atomic(dest,result)
                store_review_episode(review,ep,reviews)
                if not failures:mark_completed(cache,ep,signature,len(result))
                completed+=1
                print(f'[{ep:03d}] saved {len(result):,} cues -> {dest.name} | review: {len(reviews)} entries',flush=True)
                if limit and completed>=limit:break
            except KeyboardInterrupt:raise
            except Exception as e:
                errors+=1
                reviews.append(dict(status='EPISODE_ERROR',reason='processing',comment=str(e)[:350]))
                store_review_episode(review,ep,reviews)
                print(f'[{ep:03d}] FAILED: {e}',file=sys.stderr,flush=True)
                continue
    finally:
        if cache is not None:cache.close()
    print(f'Done: {completed} written, {skipped} previously completed, {errors} failed. '
          f'Output: {output_dir} | Audit: {results}',flush=True)


def main():
    parser=argparse.ArgumentParser(description='Full second-pass CrisperWhisper SRT verification and conservative cleanup',
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub=parser.add_subparsers(dest='action',required=True)
    def common(p):
        p.add_argument('--source',type=Path,default=HERE/'urdu_transcript_srt_raw_old')
        p.add_argument('--only',help='Comma-separated episodes e.g. 1,2,35,113')
        p.add_argument('--max-window',type=float,default=78)
    ap=sub.add_parser('audit',help='Quick text-only structural audit; does NOT run second ASR pass');common(ap)
    ap.add_argument('--out',type=Path,default=HERE/'audit')
    rp=sub.add_parser('run',help='Full audio second pass of EVERY MP3, preserve and clean original SRTs');common(rp)
    rp.add_argument('--audio',type=Path,default=HERE/'all_episodes')
    rp.add_argument('--out',type=Path,default=DEFAULT_SRT_OUT)
    rp.add_argument('--engine',choices=['crisper','whisper'],default='crisper')
    rp.add_argument('--model',default='',help='Crisper model Large; alternative Whisper Large-v3')
    rp.add_argument('--language',choices=['ur','en','auto'],default='ur')
    rp.add_argument('--device',choices=['auto','cuda','cpu'],default='auto')
    rp.add_argument('--deep-scan',action=argparse.BooleanOptionalAction,default=True,
                    help='VAD scan for missing speech, on by default')
    rp.add_argument('--repair-code-switch',action='store_true',help='Repair obvious phonetic-English regions from second ASR pass')
    rp.add_argument('--chunk-seconds',type=float,default=55.0,help='Full-episode audio chunk duration (25–75)')
    rp.add_argument('--clean-only',action='store_true',help='ONLY formatting. Does not fulfill full second pass!')
    rp.add_argument('--offline',action='store_true',help='Require previously cached Hugging Face model weights')
    rp.add_argument('--force',action='store_true',help='Rebuild output even when a completed marker is present')
    rp.add_argument('--no-cache',action='store_true',help='Rerun audio ASR rather than reuse successful chunks')
    rp.add_argument('--allow-incomplete',action='store_true',help='Publish a clearly flagged partial draft after ASR failure')
    rp.add_argument('--limit',type=int,help='Stop after N newly written episodes')
    dp=sub.add_parser('doctor',help='Check dependencies, FFmpeg and CUDA')
    sp=sub.add_parser('status',help='Show verified completion counts')
    args=parser.parse_args()
    if args.action=='doctor':sys.exit(doctor())
    if args.action=='status':
        path=RESULTS/'repair_cache.sqlite3'
        if not path.exists():
            print('No completed full passes recorded yet.');return
        with sqlite3.connect(path) as db:
            tables={r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            if 'completed_episodes' not in tables:print('Cache exists, but no full-pass completions yet.');return
            count=db.execute('SELECT count(*) FROM completed_episodes').fetchone()[0]
            print(f'{count} episode(s) recorded with a completed second pass; '
                  f'{len(list(DEFAULT_SRT_OUT.glob("episode_*.srt")))} SRT files currently in output.')
        return
    files=select_srt_files(args.source,args.only)
    if not files:parser.error(f'No episode_###.srt files found in {args.source}')
    if args.action=='audit':
        summaries,windows=audit(files,args.out,args.max_window)
        print(f'Audited {len(files)} episodes; {len(windows)} repeat-related candidate windows. Reports: {args.out}')
        return
    if args.offline:
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    if args.clean_only and args.deep_scan:args.deep_scan=False
    if not 25<=args.chunk_seconds<=75:parser.error('--chunk-seconds must be between 25 and 75')
    if not check_runtime(engine=args.engine,deep_scan=args.deep_scan,clean_only=args.clean_only):
        parser.exit(2,'Fix missing dependencies; source files were not modified.\n')
    run(files,args.audio,args.out,args.engine,args.model,args.language,args.device,
        args.force,args.clean_only,args.limit,args.max_window,args.repair_code_switch,
        args.allow_incomplete,args.no_cache,args.deep_scan,None,args.chunk_seconds)

if __name__=='__main__':main()
