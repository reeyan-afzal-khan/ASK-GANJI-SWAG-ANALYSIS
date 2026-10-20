#!/usr/bin/env python3
"""Selective SRT hallucination repair, MP3 region re-ASR and Urdu -> Roman Urdu.

Only flagged intervals are re-decoded. Outputs are drafts pending listening-based QA.
No audio is deleted, only temporary extracted WAV clips.
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
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
SRT_TIME = re.compile(r"(?P<a>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<b>\d{2}:\d{2}:\d{2}[,.]\d{3})")
URDU = re.compile(r"[\u0600-\u06ff]")
TOK = re.compile(r"[A-Za-z0-9\u0600-\u06ff]+")
LATIN = re.compile(r"([A-Za-z][A-Za-z0-9'’-]*(?:\s+[A-Za-z][A-Za-z0-9'’-]*)*)")
EP_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
# Cues with several Urdu-script renderings of English terms merit code-switch review.
PHONETIC_ENGLISH = ('ویلکم','ایکسپیرینس','پرابلم','ویڈیو','یوٹیوب','چینل',
 'سبسکرائب','کمیونیکیشن','سکلز','ریلیشنشپ','اکچولی','ڈیفنیٹلی',
 'ہونسٹلی','انسٹاگرام','کانفیڈنس','لیٹرلی','پلیز','ڈسکس','سٹارٹ','لرننگ',
 'ڈین وانڈ','ایپیسوڈ','اپیسوڈ','آئی ایم','تھنک')

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


def write_srt_atomic(path: Path, cues: list[Cue]):
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = sorted((c for c in cues if c.end > c.start and c.text.strip()), key=lambda x: (x.start,x.end))
    lines=[]
    for i,c in enumerate(valid,1):
        lines.extend([str(i),f'{time_str(c.start)} --> {time_str(c.end)}',c.text.strip(),''])
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

# Common phonetically written English technical terms. Edit locally if needed.
ENGLISH_WORDS={
 'یوٹیوب':'YouTube','فیس بک':'Facebook','فیس بک':'Facebook','گوگل':'Google',
 'انسٹاگرام':'Instagram','ای میل':'email','ای میلز':'emails',
 'سبسکرائب':'subscribe','چینل':'channel','ویڈیو':'video','ویڈیوز':'videos',
 'پرابلم':'problem','پرابلمز':'problems','چیلنج':'challenge','چیلنجز':'challenges',
 'ایکسپیرینس':'experience','ایکسپوزر':'exposure','کانفیڈنس':'confidence',
 'کمیونیکیشن':'communication','سکلز':'skills','الگورتھم':'algorithm',
 'مشین لرننگ':'machine learning','ڈیٹا سائنس':'data science',
}

class Romanizer:
    """Offline transliteration; protects English text and batches neural inference."""
    def __init__(self,method:str):
        self.method=method
        import uroman
        self.simple=uroman.Uroman()
        self.full=None;self.cache={};self.warned=False
        if method=='adapter':
            import torch
            from transformers import M2M100ForConditionalGeneration,M2M100Tokenizer
            from peft import PeftModel
            self.torch=torch
            self.device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self.tokenizer=M2M100Tokenizer.from_pretrained('Mavkif/m2m100_rup_tokenizer_both')
            self.tokenizer.src_lang='ur'
            backbone=M2M100ForConditionalGeneration.from_pretrained('Mavkif/m2m100_rup_ur_to_rur')
            self.full=PeftModel.from_pretrained(backbone,'Maaz-x14/m2m100-ur-to-roman-urdu').to(self.device).eval()
            self.bos_id=self.tokenizer.convert_tokens_to_ids('__roman-ur__')
            if self.bos_id==self.tokenizer.unk_token_id or self.bos_id is None:
                raise RuntimeError('Roman Urdu adapter tokenizer is missing __roman-ur__')
        elif method!='uroman':raise ValueError(method)

    def _fallback(self,s:str)->str:
        return self.simple.romanize_string(s,lcode='urd')

    def _batch(self,words:list[str])->None:
        if not words:return
        if self.full is None:
            for s in words:self.cache[s]=self._fallback(s)
            return
        # Mild batches avoid per-phrase GPU launches while limiting CPU/GPU peak RAM.
        batch_size=12 if self.device.type=='cuda' else 4
        for i in range(0,len(words),batch_size):
            group=words[i:i+batch_size]
            try:
                inp=self.tokenizer(group,return_tensors='pt',padding=True,
                    max_length=128,truncation=True).to(self.device)
                with self.torch.inference_mode():
                    output=self.full.generate(**inp,forced_bos_token_id=self.bos_id,
                        max_new_tokens=128,num_beams=4,early_stopping=True)
                texts=self.tokenizer.batch_decode(output,skip_special_tokens=True)
            except Exception as e:
                if not self.warned:
                    print(f'WARNING: Roman Urdu adapter failed on batch; fallback to uroman: {e}',file=sys.stderr)
                    self.warned=True
                texts=['']*len(group)
            for orig,translated in zip(group,texts):
                val=translated.strip()
                if not val or URDU.search(val) or not (.22 <= len(val)/max(1,len(orig)) <= 3.5):
                    val=self._fallback(orig)
                self.cache[orig]=val

    def many(self,texts:list[str])->list[str]:
        parted=[];missing=[];seen=set()
        # Existing English words are excluded from any generative transliterator.
        for line in texts:
            for ur,en in sorted(ENGLISH_WORDS.items(),key=lambda kv:-len(kv[0])):
                line=line.replace(ur,en)
            fragments=LATIN.split(line)
            parted.append(fragments)
            for i,piece in enumerate(fragments):
                if i%2==0 and URDU.search(piece) and piece not in self.cache and piece not in seen:
                    missing.append(piece);seen.add(piece)
        self._batch(missing)
        converted=[]
        for fragments in parted:
            text=''.join((self.cache[p] if p in self.cache else (self._fallback(p) if URDU.search(p) else p))
                         if i%2==0 else p for i,p in enumerate(fragments))
            converted.append(re.sub(r'\s+',' ',text).strip())
        # Avoid unbounded retained caches across very large episode archives.
        if len(self.cache)>150000:self.cache.clear()
        return converted

    def __call__(self,text:str)->str:
        return self.many([text])[0]



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
    return [p for p in sorted(root.glob('episode_*.srt')) if wanted is None or episode_from_name(p) in wanted]


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


def run(files:list[Path],audio_dir:Path,output_dir:Path,engine:str,model:str,lang:str,
        device:str,romanizer_method:str,force:bool,romanize_only:bool,limit:int|None,max_window:float,repair_code_switch:bool,allow_incomplete:bool,no_cache:bool):
    if not files:raise RuntimeError('No source SRT files found')
    output_dir.mkdir(parents=True,exist_ok=True)
    roman=None
    asr=None
    completed=0;skipped=0
    review=output_dir/'review.csv'
    cache=RepairCache(output_dir/'repair_cache.sqlite3') if not romanize_only else None
    for src in files:
        ep=episode_from_name(src); dest=output_dir/f'episode_{ep:03d}.srt'
        if dest.exists() and not force:
            skipped+=1;print(f'[{ep:03d}] already exists; resume skip');continue
        old=read_srt(src)
        if not old:continue
        high,others=detect(old)
        if repair_code_switch:
            for ix,reasons in others.items():
                if 'phonetic_english_review' in reasons:
                    high.setdefault(ix,set()).add('phonetic_english_review')
        windows=make_windows(old,high,max_window=max_window)
        mp3=find_mp3(audio_dir,ep)
        if windows and not romanize_only and mp3 is None:
            append_review(review,dict(episode=f'{ep:03d}',status='MISSING_MP3',reason='audio',comment='No output written; source SRT preserved'))
            print(f'[{ep:03d}] missing MP3; skipping, not publishing un-repaired result');continue
        replacement=[]; removed=set();statuses=[]
        if windows and not romanize_only:
            with tempfile.TemporaryDirectory(prefix='ganji_repair_') as tdir:
                tmpdir=Path(tdir)
                for k,w in enumerate(windows,1):
                    cache_key=region_cache_key(src,mp3,ep,w,engine,model,lang)
                    cached=None if no_cache else cache.get(cache_key)
                    if cached is not None:
                        new,status=cached,'CACHED'
                        reason=''
                    else:
                        if asr is None:
                            print('Loading ASR model (first use downloads weights if not cached)...',flush=True)
                            asr=ASR(engine,model,lang,device)
                        try:
                            new,status=repair_one_window(mp3,w,tmpdir,asr)
                            reason=''
                            if status=='PATCHED':cache.put(cache_key,new)
                        except Exception as e:
                            new=[];status='REPAIR_ERROR';reason=str(e)[:250]
                            print(f'[{ep:03d} {k}/{len(windows)}] {reason}',file=sys.stderr)
                    statuses.append(status)
                    append_review(review,dict(episode=f'{ep:03d}',start=time_str(w.start),end=time_str(w.end),
                        status=status,reason='|'.join(sorted(w.reasons)),comment=reason))
                    if status in ('PATCHED','CACHED'):
                        replacement.extend(new)
                        removed.update(range(w.first,w.last+1))
        elif windows:
            append_review(review,dict(episode=f'{ep:03d}',status='ROMANIZED_ONLY',reason='no_audio_requested',
                                      comment=f'{len(windows)} high-risk repair windows left untouched'))
        if windows and not romanize_only and any(status not in ('PATCHED','CACHED') for status in statuses) and not allow_incomplete:
            append_review(review,dict(episode=f'{ep:03d}',status='INCOMPLETE_EPISODE',reason='patch_failed',
                         comment='No final SRT written. Successful patches are cached for retry.'))
            print(f'[{ep:03d}] INCOMPLETE: {len(windows)-sum(s in ("PATCHED","CACHED") for s in statuses)} windows need another attempt; no SRT published')
            continue
        # Everything outside patched windows keeps its original SRT timestamps.
        combined=[c for i,c in enumerate(old) if i not in removed]+replacement
        result=[];residual=0
        if roman is None:
            print('Loading local Roman Urdu transliterator...',flush=True)
            roman=Romanizer(romanizer_method)
        roman_texts=roman.many([c.text for c in combined])
        for c,text in zip(combined,roman_texts):
            if URDU.search(text):residual+=1
            if text:result.append(Cue(c.start,c.end,text))
        # Do not assert successful perfect output if transliteration fails to eliminate Urdu.
        write_srt_atomic(dest,result)
        if residual:append_review(review,dict(episode=f'{ep:03d}',status='RESIDUAL_SCRIPT',reason='romanization',comment=f'{residual} remaining Urdu-script cues'))
        if any('long_subtitle_cue' in v for v in others.values()):
            append_review(review,dict(episode=f'{ep:03d}',status='LONG_CUE_WARNING',reason='timing',
                comment=f'{sum("long_subtitle_cue" in v for v in others.values())} old cues >=20 sec; durations preserved'))
        print(f'[{ep:03d}] saved {len(result):,} cues; {sum(s in ("PATCHED","CACHED") for s in statuses)}/{len(windows)} windows patched/cached')
        completed+=1
        if limit and completed>=limit:break
    if cache is not None:cache.close()
    print(f'Done: {completed} newly written, {skipped} skipped. Originals/MP3s unchanged. Review: {review}')


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub=parser.add_subparsers(dest='action',required=True)
    def common(p):
        p.add_argument('--source',type=Path,default=HERE/'urdu_transcript_srt_raw_old')
        p.add_argument('--only',help='Comma-separated episodes e.g. 2,35,100,113')
        p.add_argument('--max-window',type=float,default=78,help='Maximum repair clip core length (seconds)')
    ap=sub.add_parser('audit',help='Scan old SRTs and emit repair queue (NO MP3s needed)');common(ap)
    ap.add_argument('--out',type=Path,default=HERE/'audit')
    rp=sub.add_parser('run',help='Repair high-risk audio regions then romanize all cues');common(rp)
    rp.add_argument('--audio',type=Path,default=HERE/'all_episodes')
    rp.add_argument('--out',type=Path,default=HERE/'subtitles')
    rp.add_argument('--engine',choices=['crisper','whisper'],default='crisper')
    rp.add_argument('--model',default='',help='For Crisper default large; Whisper default large-v3')
    rp.add_argument('--language',choices=['ur','en','auto'],default='ur')
    rp.add_argument('--device',choices=['auto','cuda','cpu'],default='auto',help='Whisper compute device; Crisper torch auto-detects')
    rp.add_argument('--romanizer',choices=['adapter','uroman'],default='adapter')
    rp.add_argument('--romanize-only',action='store_true',help='DO NOT run ASR: still-bad regions remain flagged; preview only')
    rp.add_argument('--repair-code-switch',action='store_true',help='Also re-ASR suspected phonetic-English cues (more audio work)')
    rp.add_argument('--allow-incomplete',action='store_true',help='Publish draft SRT even when some flagged windows failed (NOT recommended)')
    rp.add_argument('--no-cache',action='store_true',help='Bypass saved successful audio repairs')
    rp.add_argument('--force',action='store_true',help='Explicitly regenerate existing final SRTs')
    rp.add_argument('--limit',type=int,default=None,help='Stop after N newly produced episodes')
    args=parser.parse_args()
    files=select_srt_files(args.source,args.only)
    if not files:parser.error(f'No source episode_###.srt files in {args.source}')
    if args.action=='audit':
        summaries,windows=audit(files,args.out,args.max_window)
        print(f'Audited {len(files)} episodes; {len(windows)} targeted repair windows. Files: {args.out}')
        print('High-risk cue minutes:',round(sum(r['high_risk_minutes'] for r in summaries),1))
        return
    if not args.romanize_only and not shutil.which('ffmpeg'):
        parser.error('ffmpeg not found on PATH')
    run(files,args.audio,args.out,args.engine,args.model,args.language,args.device,
        args.romanizer,args.force,args.romanize_only,args.limit,args.max_window,args.repair_code_switch,args.allow_incomplete,args.no_cache)

if __name__=='__main__':main()
