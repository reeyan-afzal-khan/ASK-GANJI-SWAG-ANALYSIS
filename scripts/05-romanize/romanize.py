"""Reversible, cached Urdu word transliteration. English and SRT timing are immutable.

Model: Mavkif/m2m100_rup_ur_to_rur (local safetensors, no remote code).
Candidate reranking rejects consonant changes; a reviewed glossary takes priority.
"""
import argparse, collections, hashlib, json, re, sys, time, unicodedata
from pathlib import Path
from zipfile import ZipFile
# Allow this entry point to run directly as well as through run.sh.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.shared'))
from paths import ROOT, SOURCE, ROMAN, CACHE as CACHE_DIR, MODELS, REPORTS, GLOSSARY
from subtitles import Cue, parse, render, atomic_write, select_files
import os
from datetime import datetime, timezone
if os.name == 'nt':
    sys.path.insert(0,str(ROOT/'.cache/windows-roman-dependencies'))
WORD=re.compile(r'[\u0620-\u065f\u066e-\u06d3\u06fa-\u06fc]+')
CACHE=CACHE_DIR/'roman_candidates.jsonl'
FILES=[]


def normalized(s):
    s=unicodedata.normalize('NFKC',s).translate(str.maketrans({'ي':'ی','ك':'ک','ى':'ی','ۀ':'ہ','ة':'ہ'}))
    return ''.join(c for c in s if not unicodedata.combining(c) and c!='ـ')

def vocabulary():
    counter=collections.Counter()
    for path in FILES:
        counter.update(normalized(w) for w in WORD.findall(path.read_text(encoding='utf-8-sig')))
    counter.pop('',None)
    return counter

def generate(retry=False):
    import torch
    from transformers import M2M100ForConditionalGeneration,M2M100Tokenizer
    from transformers.utils import logging
    logging.set_verbosity_error(); logging.disable_progress_bar()
    torch.set_num_threads(4)
    counts=vocabulary(); cache=read_cache()
    if retry:
        overrides=json.loads(GLOSSARY.read_text(encoding='utf-8'))
        todo=[w for w in counts if w not in overrides and choose(w,cache[w])[1]>0 and len(cache[w])<16]
    else:
        overrides=json.loads(GLOSSARY.read_text(encoding='utf-8'))
        todo=[w for w in counts if w not in cache and w not in overrides]
    todo=sorted(todo,key=lambda w:(len(w),w))
    beams=16 if retry else 4
    batch_size=32 if retry else 64
    print('Vocabulary',len(counts),'cached',len(cache),'remaining',len(todo),flush=True)
    if not todo:return
    if not torch.cuda.is_available():raise ValueError('CUDA GPU required to generate new Roman candidates; use --cached-only for existing vocabulary.')
    tok=M2M100Tokenizer.from_pretrained(MODELS/'tokenizer',local_files_only=True,src_lang='ur')
    model=M2M100ForConditionalGeneration.from_pretrained(MODELS/'model',local_files_only=True,torch_dtype=torch.float16).to('cuda').eval()
    started=time.time()
    with CACHE.open('a',encoding='utf-8') as f,torch.inference_mode():
        for pos in range(0,len(todo),batch_size):
            batch=todo[pos:pos+batch_size]
            inputs=tok(batch,return_tensors='pt',padding=True).to('cuda')
            ids=model.generate(**inputs,forced_bos_token_id=128105,max_new_tokens=max(24,min(100,max(map(len,batch))*3)),num_beams=beams,num_return_sequences=beams)
            texts=tok.batch_decode(ids,skip_special_tokens=True)
            for i,w in enumerate(batch): f.write(json.dumps({'source':w,'candidates':texts[i*beams:i*beams+beams]},ensure_ascii=False)+'\n')
            f.flush()
            if pos%640==0:print(f'{pos+len(batch)}/{len(todo)} words; {time.time()-started:.1f}s',flush=True)
    print('Generation complete',flush=True)

def read_cache():
    if not CACHE.exists():return {}
    return {j['source']:j['candidates'] for line in CACHE.read_text(encoding='utf-8').splitlines() if line.strip() for j in [json.loads(line)]}

CONSONANTS={'ب':'b','پ':'p','ت':'t','ٹ':'t','ث':'s','ج':'j','چ':'ch','ح':'h','خ':'kh','د':'d','ڈ':'d','ذ':'z','ر':'r','ڑ':'r','ز':'z','ژ':'zh','س':'s','ش':'sh','ص':'s','ض':'z','ط':'t','ظ':'z','ع':'','غ':'gh','ف':'f','ق':'q','ک':'k','گ':'g','ل':'l','م':'m','ن':'n','ں':'n','ہ':'h','ھ':'h','ء':'','ا':'','آ':'','و':'','ی':'','ے':'','ۓ':''}
def skeleton(s,urdu=False):
    if urdu:s=''.join(CONSONANTS.get(c,'') for c in normalized(s))
    else:
        s=s.lower().replace('tion','shn').replace('sion','zhn').replace('dge','j').replace('ck','k').replace('x','ks')
        s=re.sub('c(?=[eiy])','s',s)
        s=re.sub('c(?!h)','k',s)
        s=re.sub(r'[aeiouvwy\W_0-9]','',s)
    s=s.replace('q','k').replace('ph','f')
    return re.sub(r'(.)\1+',r'\1',s)

def distance(a,b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=row
    return prev[-1]

def choose(w,candidates):
    clean=[re.sub(r'[^A-Za-z \-\x27]','',s).strip().lower() for s in candidates]
    clean=[s for s in clean if s]
    if not clean:return '',99
    target=skeleton(w,True)
    targets=[target]
    if w.endswith(('ہ','ه')) and target.endswith('h'):targets.append(target[:-1])
    scored=[(min(distance(t,skeleton(s)) for t in targets),i,s) for i,s in enumerate(clean)]
    score,_,s=min(scored)
    return s,score

def review():
    counts=vocabulary(); cache=read_cache(); rows=[]
    import uroman
    fallback=uroman.Uroman()
    overrides=json.loads(GLOSSARY.read_text(encoding='utf-8')) if GLOSSARY.exists() else {}
    for w,n in counts.most_common():
        if w not in cache and w not in overrides:raise ValueError(f'Missing model candidates for {w!r}; rerun without --cached-only.')
        out,score=choose(w,cache.get(w,[])) if w not in overrides else (overrides[w],0)
        method='glossary' if w in overrides else 'model'
        if w not in overrides and score>0:
            # Conservative fallback preserves the source spelling rather than
            # publishing a model's unrelated word; these need pronunciation QA.
            out=fallback.romanize_string(w,lcode='urd')
            out=unicodedata.normalize('NFKD',out)
            out=''.join(c for c in out if not unicodedata.combining(c))
            out=re.sub(r'[^A-Za-z \-\x27]','',out).strip()
            method='phonetic_fallback'
        rows.append({'urdu':w,'count':n,'roman':overrides.get(w,out),'distance':score,'reviewed':w in overrides,'method':method,'candidates':cache.get(w,[])})
    (REPORTS/'roman_word_review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Reviewed glossary',len(overrides),'unreviewed mismatches',sum(r['distance']>0 and not r['reviewed'] for r in rows),flush=True)
    return rows

def convert(output, overwrite=False):
    import uroman
    other=uroman.Uroman()
    rows=review()
    lex={r['urdu']:r['roman'] for r in rows}
    if not all(lex.values()):raise ValueError('Empty conversions require glossary review')
    uncertain={r['urdu'] for r in rows if r['method']=='phonetic_fallback'}
    punctuation=str.maketrans({'،':',','۔':'.','؟':'?','؛':';','٪':'%','٫':'.','٬':',','ؑ':' (AS)','\u200c':'','\u200d':'','\u200e':'','\u200f':'','\u061c':''})
    for a,b in zip('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'):punctuation[ord(a)]=b
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run_dir=REPORTS/'romanization'/stamp
    run_dir.mkdir(parents=True)
    output.mkdir(parents=True,exist_ok=True)
    manifest=[]; queue=[]
    backup=None
    try:
        for path in FILES:
            raw=path.read_bytes(); before=parse(raw.decode('utf-8-sig')); after=[]
            for cue in before:
                def replace_word(m):
                    key=normalized(m[0])
                    return lex[key] if key else ''
                text=WORD.sub(replace_word,cue.text).translate(punctuation)
                def replace_other(m):
                    chunk=m[0]
                    if any(c.isalpha() and 'LATIN' not in unicodedata.name(c,'') for c in chunk):
                        return other.romanize_string(chunk)
                    return chunk
                text=re.sub(r'[^\x00-\x7f]+',replace_other,text)
                if any(c.isalpha() and 'LATIN' not in unicodedata.name(c,'') for c in text):
                    raise ValueError(f'Unconverted script: {path.name}, cue {cue.number}')
                cursor=0
                for token in re.findall('[A-Za-z]+',cue.text):
                    pos=text.find(token,cursor)
                    if pos<0:raise ValueError(f'English changed: {path.name}, cue {cue.number}')
                    cursor=pos+len(token)
                if cue.text.isascii() and text!=cue.text:raise ValueError('ASCII text changed')
                flagged=sorted({normalized(w) for w in WORD.findall(cue.text)} & uncertain)
                if flagged:queue.append({'file':path.name,'cue':cue.number,'timing':cue.timing,'words':flagged,'source':cue.text,'roman':text})
                after.append(Cue(cue.number,cue.timing,(text,)))
            result=render(after)
            dest=output/path.name
            if path.read_bytes()!=raw:raise ValueError(f'Source changed during conversion: {path}')
            if dest.exists() and dest.stat().st_size:
                if not overwrite:raise ValueError(f'Output appeared during conversion: {dest}')
                if backup is None:
                    backup_path=ROOT/'.cache/backups'/f'before-romanization-{stamp}.zip'
                    backup_path.parent.mkdir(parents=True,exist_ok=True)
                    backup=ZipFile(backup_path,'x')
                backup.writestr(dest.name,dest.read_bytes())
            atomic_write(dest,result)
            manifest.append({'file':path.name,'source_sha256':hashlib.sha256(raw).hexdigest(),'output_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'cues':len(after)})
            # Persist each completed episode so interruption retains provenance.
            atomic_write(run_dir/'manifest.json',json.dumps(manifest,indent=2))
            atomic_write(run_dir/'review_queue.json',json.dumps(queue,ensure_ascii=False,indent=2))
            print(f'[DONE] {dest.name}: {len(after)} single-line cues',flush=True)
    finally:
        if backup is not None:backup.close()
    print(f'Report: {run_dir}')


def romanize_alignment(cached_only=False):
    """Romanise what step 06's audio check heard in uncovered stretches, by the subtitles' own rules.

    The heard passages go through the unchanged SRT conversion as cues of a temporary file, so new
    words get model candidates (GPU) or the reviewed glossary exactly like subtitle words, and the
    Roman text is stored next to them in .cache/alignment/ for the audio-check report.
    """
    import tempfile
    caches=[(p,json.loads(p.read_text(encoding='utf-8'))) for p in sorted((CACHE_DIR/'alignment').glob('episode_*.json'))]
    heard=[(g[2],lambda roman,g=g:g.__setitem__(slice(3,None),[roman])) for _,data in caches for g in data.get('gaps',[]) if g[2].strip()]
    # Passages transcribed by align.py --fill that are not romanised yet (applied ones stay as they are).
    added=[(s['source'],lambda roman,s=s:s.__setitem__('roman',roman)) for _,data in caches for s in data.get('supplements',[]) if s.get('roman') is None]
    # Fresh transcriptions of decoding loops (align.py --loops), for pacing and the report.
    added+=[(p['source'],lambda roman,p=p:p.__setitem__('roman',roman)) for _,data in caches for p in data.get('loops',[]) if p.get('source') and p.get('roman') is None]
    jobs=heard+added
    print(f'{len(heard)} heard passages and {len(added)} new transcribed passages in {len(caches)} alignment caches',flush=True)
    if not jobs:return
    with tempfile.TemporaryDirectory(dir=CACHE_DIR) as tmp:
        source=Path(tmp)/'source';output=Path(tmp)/'roman'
        source.mkdir();output.mkdir()
        stamp=lambda n:f'{n//3600:02}:{n%3600//60:02}:{n%60:02},000'
        atomic_write(source/'episode_001.srt',render([Cue(str(n),f'{stamp(n)} --> {stamp(n)}',(text,)) for n,(text,_) in enumerate(jobs,1)]))
        FILES[:]=[source/'episode_001.srt']
        if not cached_only:
            generate()
            generate(retry=True)
        convert(output)
        romans=[c.text for c in parse((output/'episode_001.srt').read_text(encoding='utf-8'))]
    for (_,store),roman in zip(jobs,romans):
        store(roman)
    for path,data in caches:
        atomic_write(path,json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print(f'Stored Roman Urdu for {len(heard)} heard and {len(added)} new passages.',flush=True)


def main():
    global FILES
    parser=argparse.ArgumentParser(description='Convert live Crisper subtitles to single-line Roman Urdu; preserve English and timing.')
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=ROMAN)
    parser.add_argument('--episodes',help='Comma-separated episode numbers')
    parser.add_argument('--overwrite',action='store_true',help='Back up and replace existing outputs')
    parser.add_argument('--cached-only',action='store_true',help='Use existing glossary and candidates without GPU generation')
    parser.add_argument('--alignment',action='store_true',help="Romanise what step 06's audio check heard (stored in .cache/alignment/) instead of SRT files")
    args=parser.parse_args()
    if args.source.resolve()==args.output.resolve():parser.error('Source and output must be different folders')
    if args.alignment:
        try:
            CACHE_DIR.mkdir(exist_ok=True);REPORTS.mkdir(parents=True,exist_ok=True)
            romanize_alignment(args.cached_only)
        except (ValueError,OSError,ImportError) as exc:parser.exit(1,f'Error: {exc}\n')
        return
    try:
        files=select_files(args.source,args.episodes)
        FILES=[p for p in files if args.overwrite or not (args.output/p.name).is_file() or not (args.output/p.name).stat().st_size]
        print(f'{len(FILES)} pending; {len(files)-len(FILES)} existing outputs skipped.')
        if not FILES:return
        CACHE_DIR.mkdir(exist_ok=True);REPORTS.mkdir(parents=True,exist_ok=True)
        if not args.cached_only:
            generate()
            generate(retry=True)
        convert(args.output,args.overwrite)
    except (ValueError,OSError,ImportError) as exc:parser.exit(1,f'Error: {exc}\n')

if __name__=='__main__':main()
