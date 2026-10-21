#!/usr/bin/env python3
"""Fully offline 241-episode MP3 + SRT anomaly audit (no retranscription).

Inspects every second of audio using streamed FFmpeg decoding and Silero voice
activity detection. Flags are *candidates for review*, not verified ASR errors.
No audio is uploaded and no language model is downloaded by this script.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.metadata
import json
import logging
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# All SRT handling is included here; no other local Python modules are needed.
EP_RE = re.compile(r"episode_(\d{3})\.srt$", re.I)
TIME_RE = re.compile(r"(?P<start>\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2,}:\d{2}:\d{2}[,.]\d{3})")
URDU_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f]")
LATIN_RE = re.compile(r"[A-Za-z]")
NONSPEECH_RE = re.compile(r"^(\[?\(?\s*(?:music|موسیقی|applause|clapping|silence|laughter|laughs|intro|outro)\s*\)?\]?\s*[.,!؟۔]*)$", re.I)


def clock(value):
    value = max(float(value), 0.0)
    ms = int(round(value * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    sec, milli = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{sec:02}.{milli:03}"


def parse_srt(text):
    cues, invalid = [], []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if not lines:
            continue
        idx = next((i for i, line in enumerate(lines[:3]) if "-->" in line), None)
        match = TIME_RE.search(lines[idx]) if idx is not None else None
        if match is None:
            invalid.append(" ".join(lines)[:180])
            continue
        def seconds(stamp):
            hh, mm, ss = stamp.replace(".", ",").split(":")
            whole, milliseconds = ss.split(",")
            return int(hh) * 3600 + int(mm) * 60 + int(whole) + int(milliseconds) / 1000
        cues.append({
            "idx": int(lines[0]) if lines[0].isdigit() else len(cues) + 1,
            "start": seconds(match["start"]),
            "end": seconds(match["end"]),
            "text": " ".join(lines[idx + 1:]).strip(),
        })
    return cues, invalid

VERSION = '3.0.0'
SR = 16000
ISSUE_FIELDS = ['episode','start','end','subtitle_number','severity','issue','details','text']
SUMMARY_FIELDS = [
    'episode','status','priority','subtitles','timeline_minutes','audio_status',
    'audio_minutes','duration_delta_seconds','speech_minutes','speech_covered_pct',
    'caption_over_silence_cues','uncovered_speech_spans','uncovered_speech_seconds',
    'subtitle_coverage_pct','under_0_2s','under_0_2_pct','over_40_chars_s',
    'longest_identical_run','runs_of_4_plus','recurrent_phrase_warnings',
    'replacement_char_cues','unparsed_blocks','timestamp_overlaps',
    'largest_subtitle_gap_seconds','urdu_script_character_fraction',
    'audio_codec','audio_channels','audio_sample_rate','audio_bitrate_kbps',
    'decoded_audio_minutes','audio_decode_seconds','peak_signal','audio_rms_dbfs','clipped_sample_pct','approx_silent_audio_pct',
    'flag_high','flag_medium','flag_low','flag_total','duration_seconds','error']


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def dump_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(payload,f,ensure_ascii=False,indent=2,default=str)
        f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def safe_command(cmd, timeout=10):
    try:
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,check=False,stdin=subprocess.DEVNULL)
        return {'returncode':proc.returncode,'stdout':proc.stdout.strip()[:3000], 'stderr':proc.stderr.strip()[:700]}
    except Exception as exc:
        return {'error':f'{type(exc).__name__}: {exc}'}


def machine_inventory(output_dir:Path):
    info={
        'collected_utc':now(),'audit_version':VERSION,'hostname':socket.gethostname(),
        'os':platform.platform(),'system':platform.system(),'release':platform.release(),
        'machine_architecture':platform.machine(),'processor':platform.processor(),
        'python_version':sys.version,'python_executable':sys.executable,
        'logical_cpu_count':os.cpu_count(),
        'ffmpeg':safe_command(['ffmpeg','-version']),
        'ffprobe':safe_command(['ffprobe','-version']),
        'nvidia_gpus':safe_command(['nvidia-smi','--query-gpu=index,name,memory.total,memory.free,driver_version,compute_cap','--format=csv,noheader,nounits']),
        'environment_non_secret':{k:os.environ.get(k) for k in ['CUDA_VISIBLE_DEVICES','OMP_NUM_THREADS'] if k in os.environ},
        'installed_packages':{},'disks':{},
    }
    for pkg in ['numpy','faster-whisper','ctranslate2','onnxruntime','psutil','torch','scipy','soundfile']:
        try:info['installed_packages'][pkg]=importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:info['installed_packages'][pkg]=None
    try:
        import psutil
        info['physical_cpu_count']=psutil.cpu_count(logical=False)
        ram=psutil.virtual_memory()
        info['ram_total_gb']=round(ram.total/1e9,2)
        info['ram_available_gb_at_start']=round(ram.available/1e9,2)
        info['swap_total_gb']=round(psutil.swap_memory().total/1e9,2)
        try: info['cpu_model']=platform.processor() or (Path('/proc/cpuinfo').read_text().split('model name\t: ')[1].split('\n')[0])
        except Exception: pass
    except ImportError:
        info['ram_total_gb']=None
    try:
        disk=shutil.disk_usage(str(output_dir))
        info['disks']['results_location']={'total_gb':round(disk.total/1e9,2),'free_gb':round(disk.free/1e9,2)}
    except Exception:pass
    if sys.platform == 'darwin':
        info['mac_hardware']=safe_command(['system_profiler','SPHardwareDataType','SPDisplaysDataType'],timeout=20)
    if platform.system()=='Windows':
        info['windows_version']=platform.win32_ver()
    return info


def resource_snapshot():
    try:
        import psutil
        vm=psutil.virtual_memory();proc=psutil.Process()
        return {'system_ram_available_gb':round(vm.available/1e9,3),
                'process_rss_mb':round(proc.memory_info().rss/1e6,1),
                'process_cpu_seconds':round(sum(proc.cpu_times()[:2]),2)}
    except ImportError:return {}


def build_logger(name: str, log_path: Path, console=False):
    log=logging.getLogger(name)
    log.handlers.clear();log.setLevel(logging.DEBUG);log.propagate=False
    formatter=logging.Formatter('%(asctime)s UTC | %(levelname)-7s | %(message)s')
    txt=logging.FileHandler(log_path,mode='a',encoding='utf-8')
    txt.setFormatter(formatter);log.addHandler(txt)
    if console:
        s=logging.StreamHandler(sys.stdout);s.setLevel(logging.INFO);s.setFormatter(formatter);log.addHandler(s)
    return log


def close_logger(log):
    for h in list(log.handlers):
        log.removeHandler(h);h.flush();h.close()


def input_source(source:Path):
    """Load SRT contents, bounded to 241 small text files; ZIP supported."""
    found={};duplicates=[]
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            for member in sorted(z.infolist(),key=lambda x:x.filename):
                match=EP_RE.fullmatch(Path(member.filename).name)
                if not match or member.is_dir():continue
                ep=int(match.group(1))
                if ep in found:duplicates.append((ep,member.filename));continue
                raw=z.read(member)
                found[ep]={'text':raw.decode('utf-8-sig',errors='replace'),
                           'signature':hashlib.sha256(raw).hexdigest(),
                           'where':f'{source}!/{member.filename}'}
    elif source.is_dir():
        for p in sorted(source.rglob('episode_*.srt')):
            match=EP_RE.fullmatch(p.name)
            if not match:continue
            ep=int(match.group(1))
            if ep in found:duplicates.append((ep,str(p)));continue
            raw=p.read_bytes()
            found[ep]={'text':raw.decode('utf-8-sig',errors='replace'),
                       'signature':hashlib.sha256(raw).hexdigest(),'where':str(p)}
    else:raise FileNotFoundError('SRT source must be an existing .zip file or folder')
    return found,duplicates


def sound_signature(path:Path | None):
    if path is None:return None
    if not path.exists():return 'MISSING'
    stat=path.stat();h=hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(65536))
        if stat.st_size>65536:
            f.seek(max(0,stat.st_size-65536));h.update(f.read(65536))
    return f'{stat.st_size}:{stat.st_mtime_ns}:{h.hexdigest()}'


def video_probe(audio_file:Path):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries',
        'format=duration,bit_rate,size:stream=codec_name,sample_rate,channels,bit_rate','-of','json',str(audio_file)],
        capture_output=True,text=True,timeout=60,check=True)
    data=json.loads(p.stdout)
    stream=(data.get('streams') or [{}])[0];fmt=data.get('format',{})
    if not data.get('streams'):raise RuntimeError('No audio stream detected')
    def as_number(val):
        try:return float(val)
        except (ValueError,TypeError):return None
    return {'duration_seconds':as_number(fmt.get('duration')),
            'codec':stream.get('codec_name'), 'sample_rate':stream.get('sample_rate'),
            'channels':stream.get('channels'), 'bitrate_kbps':round((as_number(stream.get('bit_rate')) or as_number(fmt.get('bit_rate')) or 0)/1000,1),
            'file_bytes':audio_file.stat().st_size}


def merge_intervals(intervals, join_gap=0.0):
    merged=[]
    for s,e in sorted(intervals):
        if e<=s:continue
        if merged and s <= merged[-1][1]+join_gap:
            merged[-1]=(merged[-1][0],max(e,merged[-1][1]))
        else:merged.append((s,e))
    return merged


def interval_seconds(regions):
    return sum(e-s for s,e in regions)


class Coverage:
    """O(log N) overlap length for sorted, disjoint intervals."""
    def __init__(self, intervals):
        self.intervals=merge_intervals(intervals)
        self.starts=[v[0] for v in self.intervals]
        self.ends=[v[1] for v in self.intervals]
        self.prefix=[0.]
        for s,e in self.intervals:self.prefix.append(self.prefix[-1]+e-s)
    def seconds(self,s,e):
        if e<=s or not self.intervals:return 0.
        # Regions with end > s through regions with start < e.
        i=bisect_right(self.ends,s)
        j=bisect_left(self.starts,e)
        if i>=j:return 0.
        total=self.prefix[j]-self.prefix[i]
        total-=max(0.,s-self.starts[i])
        total-=max(0.,self.ends[j-1]-e)
        return max(0.,min(total,e-s))


def subtract_intervals(a,b):
    """Yield exact intervals in union(a) that are outside union(b), O(N+M)."""
    a=merge_intervals(a);b=merge_intervals(b)
    out=[];j=0
    for s,e in a:
        pos=s
        while j<len(b) and b[j][1]<=s:j+=1
        k=j
        while k<len(b) and b[k][0]<e:
            bs,be=b[k]
            if bs>pos:out.append((pos,min(e,bs)))
            pos=max(pos,be)
            if pos>=e:break
            k+=1
        if pos<e:out.append((pos,e))
    return out


def vad_stream(audio_file:Path, log:logging.Logger, logs_dir:Path, ep:int, chunk_seconds:int=120, threshold:float=.50):
    """Stream decoded 16kHz mono PCM, with 2s left context for VAD chunk seams.
    Memory bounded to ~chunk_seconds of audio, not entire episode.
    Speech intervals near chunk seams are approximate; analysis is triage only.
    """
    import numpy as np
    from faster_whisper.vad import VadOptions,get_speech_timestamps
    opts=VadOptions(threshold=threshold,min_silence_duration_ms=550,
                    min_speech_duration_ms=200,speech_pad_ms=200)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(audio_file),
         '-map','0:a:0','-vn','-ac','1','-ar',str(SR),'-f','s16le','pipe:1']
    stderr_path=logs_dir/f'episode_{ep:03}_ffmpeg.stderr.log'
    spans=[];count=0;silent=0;peak=0.;chunks=0;sum_squared=0.;clipped=0
    carry=b'';start=time.monotonic()
    def read_bytes(stream,n):
        parts=[];done=0
        while done<n:
            b=stream.read(n-done)
            if not b:break
            parts.append(b);done+=len(b)
        return b''.join(parts)
    with stderr_path.open('wb') as errors:
        process=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors)
        try:
            while True:
                payload=read_bytes(process.stdout,SR*2*chunk_seconds)
                if not payload:break
                if len(payload)%2:payload=payload[:-1]
                incoming=np.frombuffer(payload,dtype='<i2')
                if not len(incoming):break
                incoming_floats=incoming.astype(np.float32)/32768.0
                peak=max(peak,float(np.max(np.abs(incoming_floats))))
                sum_squared+=float(np.sum(np.square(incoming_floats.astype(np.float64))))
                clipped+=int(np.count_nonzero(np.abs(incoming.astype(np.int32))>=32760))
                # audio near silence by 0.5-s blocks; not a voice detector.
                for block in np.array_split(incoming,max(1,int(len(incoming)/8000))):
                    val=np.mean(np.square(block.astype(np.float64)/32768.0))
                    if val<1e-6:silent+=len(block)
                chunk=np.frombuffer(carry+payload,dtype='<i2').astype(np.float32)/32768.0
                start_sample=count-len(carry)//2
                regions=get_speech_timestamps(chunk,opts,sampling_rate=SR)
                for item in regions:
                    s=max(count,(start_sample+int(item['start'])))
                    e=min(count+len(incoming),start_sample+int(item['end']))
                    if e>s:spans.append((s/SR,e/SR))
                count+=len(incoming);chunks+=1
                # Overlap ensures the next pass has context from just before seam.
                carry=payload[-SR*2*2:]
                log.info('audio decoded: %.1f minutes (%d chunks); resources=%s',
                         count/SR/60, chunks, resource_snapshot())
            status=process.wait(timeout=40)
            if status!=0:
                raise RuntimeError(f'ffmpeg decode returned {status}; see {stderr_path.name}')
        finally:
            if process.poll() is None:
                process.kill();process.wait()
            if process.stdout:process.stdout.close()
    if stderr_path.exists() and stderr_path.stat().st_size == 0:
        stderr_path.unlink()  # No FFmpeg issues; keep Logs uncluttered.
    out=merge_intervals(spans,join_gap=.25)
    rms=math.sqrt(sum_squared/max(count,1))
    return {'regions':out,'decoded_duration_seconds':count/SR,
            'speech_seconds':interval_seconds(out),'peak_signal':round(peak,4),
            'audio_rms_dbfs':round(20*math.log10(max(1e-10,rms)),2),
            'clipped_sample_pct':round(100*clipped/max(count,1),4),
            'approx_silent_audio_pct':round(100*silent/max(count,1),2),
            'audio_decode_seconds':round(time.monotonic()-start,2), 'audio_chunks_processed':chunks}


def make_flag(ep,issue,severity,start='',end='',subtitle_number='',details='',text=''):
    return {'episode':ep,'start':clock(start) if isinstance(start,(int,float)) else start,
            'end':clock(end) if isinstance(end,(int,float)) else end,
            'subtitle_number':subtitle_number,'severity':severity,'issue':issue,
            'details':str(details)[:350],'text':str(text)[:400]}


def inspect_text(ep:int, text:str, log:logging.Logger):
    cues,invalid=parse_srt(text)
    flags=[]
    counts=collections.Counter()
    def flag(x,issue,severity,details):
        flags.append(make_flag(ep,issue,severity,x['start'],x['end'],x['idx'],details,x['text']))
    longest=0; run_count=0;largest_gap=0.
    normalized=[]
    for x in cues:
        norm=re.sub(r'[\W_]+','',x['text'].casefold(),flags=re.UNICODE)
        normalized.append(norm)
        d=x['end']-x['start'];q=x['text']
        if d<0:flag(x,'negative_duration','high',f'{d:.3f} seconds')
        elif d==0:flag(x,'zero_duration','high','Zero seconds')
        elif d<.10:flag(x,'cue_under_100ms','medium',f'{d:.3f}s')
        if 0<=d<.2:counts['tiny']+=1
        if d>0 and len(q)>=4 and len(q)/d>40:
            counts['fast']+=1;flag(x,'implausible_character_rate','medium',f'{len(q)/d:.1f} chars/s')
        if d>35 and len(q)>=20:flag(x,'long_text_caption','medium',f'{d:.1f} seconds')
        if not q:flag(x,'empty_caption','medium','Empty subtitle text')
        if '\ufffd' in q:counts['replacement']+=1;flag(x,'encoding_replacement_character','high','Unicode replacement character U+FFFD')
    for i,x in enumerate(cues):
        if i==0:continue
        prev=cues[i-1];gap=x['start']-prev['end']
        if x['start']<prev['start']-.01:flag(x,'out_of_order_timestamp','high','Start earlier than previous cue')
        elif gap<-.08:counts['overlap']+=1;flag(x,'overlapping_timestamps','low',f'{abs(gap):.2f}s overlap')
        elif gap>60:largest_gap=max(largest_gap,gap);flag(x,'large_caption_gap','low',f'{gap:.1f}s without captions')
        largest_gap=max(largest_gap,max(0,gap))
    i=0
    while i<len(cues):
        j=i+1
        while j<len(cues) and normalized[i] and normalized[j]==normalized[i]:j+=1
        run=j-i;longest=max(run,longest)
        if run>=4:
            run_count+=1
            flag(cues[i],'near_identical_cue_run','high',f'{run} successive repeated captions; through {clock(cues[j-1]["end"])}')
        i=j
    # Non-adjacent repeats within 3 minutes, useful for Whisper's looping silence.
    recent=collections.defaultdict(collections.deque)
    recurrent=0
    for idx,x in enumerate(cues):
        norm=normalized[idx]
        if len(norm)<18:continue
        dq=recent[norm]
        while dq and x['start']-dq[0]>180:dq.popleft()
        dq.append(x['start'])
        if len(dq)==5:
            recurrent+=1
            flag(x,'frequent_phrase_recurrence','medium','At least 5 occurrences of same long text within 3 minutes')
    for block in invalid:
        flags.append(make_flag(ep,'unparseable_srt_block','high',details=block[:150]))
    urn=sum(len(URDU_RE.findall(x['text'])) for x in cues)
    lat=sum(len(LATIN_RE.findall(x['text'])) for x in cues)
    values={'subtitles':len(cues),'timeline_minutes':round(max((v['end'] for v in cues),default=0)/60,3),
            'under_0_2s':counts['tiny'],'under_0_2_pct':round(100*counts['tiny']/max(len(cues),1),2),
            'over_40_chars_s':counts['fast'],'longest_identical_run':longest,
            'runs_of_4_plus':run_count,'recurrent_phrase_warnings':recurrent,
            'replacement_char_cues':counts['replacement'],'unparsed_blocks':len(invalid),
            'timestamp_overlaps':counts['overlap'],'largest_subtitle_gap_seconds':round(largest_gap,2),
            'urdu_script_character_fraction':round(urn/(urn+lat),4) if (urn+lat) else 0.}
    log.info('SRT parsed: cues=%s malformed=%s repeats=%s fast=%s tiny=%s',len(cues),len(invalid),longest,counts['fast'],counts['tiny'])
    return cues,values,flags


def inspect_audio(ep:int,cues:list[dict],audio:dict,probe:dict,flags:list[dict],text_stats:dict,log):
    spans=audio['regions'];vad=Coverage(spans)
    sound_duration=audio['decoded_duration_seconds']
    transcript_intervals=merge_intervals([(max(0,c['start']),min(sound_duration,c['end']))
                for c in cues if c['end']>c['start'] and c['start']<sound_duration])
    transcript_cov=Coverage(transcript_intervals)
    padded_caption_intervals=merge_intervals([(max(0,c['start']-.35),min(sound_duration,c['end']+.35))
                for c in cues if c['end']>c['start'] and c['start']<sound_duration])
    uncovered=subtract_intervals(spans,padded_caption_intervals)
    significant=[(s,e) for s,e in uncovered if e-s>=3.]
    voice_covered=interval_seconds(spans)-interval_seconds(uncovered)
    warn_no_voice=0
    for x in cues:
        d=x['end']-x['start'];q=x['text'].strip()
        if d<.7 or len(q)<7 or NONSPEECH_RE.fullmatch(q):continue
        overlap=vad.seconds(max(0,x['start']-.15),min(sound_duration,x['end']+.15))
        if overlap<max(.15,min(d*.08,.5)):
            warn_no_voice+=1
            flags.append(make_flag(ep,'caption_without_detected_voice','high' if d>=5 else 'medium',
                        x['start'],x['end'],x['idx'],f'Only {overlap:.2f}s detected voice in {d:.2f}s caption; VAD may be wrong',q))
    for s,e in significant:
        flags.append(make_flag(ep,'detected_speech_without_caption','medium',s,e,'',
                     f'{e-s:.1f}s of speech-like activity without caption (VAD may include noise or music)'))
    if cues and cues[-1]['end']>sound_duration+3:
        flags.append(make_flag(ep,'caption_after_audio_end','high',cues[-1]['start'],cues[-1]['end'],cues[-1]['idx'],
                               f'Audio decoded to {clock(sound_duration)}',cues[-1]['text']))
    if sound_duration>0 and text_stats['timeline_minutes']*60<sound_duration-60:
        flags.append(make_flag(ep,'audio_extends_past_subtitles','medium',text_stats['timeline_minutes']*60,sound_duration,'',
                               f'{round(sound_duration-text_stats["timeline_minutes"]*60,1)}s audio after last caption'))
    if audio['clipped_sample_pct']>1:
        flags.append(make_flag(ep,'possible_clipped_audio','medium',0,sound_duration,'',
                               f'{audio["clipped_sample_pct"]}% of decoded samples are at digital full-scale'))
    if sound_duration>30 and audio['audio_rms_dbfs'] < -48:
        flags.append(make_flag(ep,'very_quiet_audio','medium',0,sound_duration,'',
                               f'Overall decoded RMS {audio["audio_rms_dbfs"]} dBFS; volume and VAD may be unreliable'))
    if probe.get('duration_seconds') and abs(probe['duration_seconds']-sound_duration)>3:
        flags.append(make_flag(ep,'probe_decode_duration_mismatch','medium',0,sound_duration,'',
                               f'ffprobe {probe["duration_seconds"]:.1f}s vs decoded {sound_duration:.1f}s'))
    if sound_duration<=0:
        flags.append(make_flag(ep,'zero_decoded_audio','high',details='Decoder produced no audio samples'))
    if not spans and sound_duration>30:
        flags.append(make_flag(ep,'no_voice_detected_in_audio','high',0,sound_duration,'',
                               'Silero VAD found no speech; could be music, extremely low audio, or wrong file'))
    audio_stats={
        'audio_status':'full_vad_completed','audio_minutes':round(sound_duration/60,3),
        'duration_delta_seconds':round(text_stats['timeline_minutes']*60-sound_duration,1),
        'speech_minutes':round(interval_seconds(spans)/60,3),
        'speech_covered_pct':round(100*voice_covered/max(interval_seconds(spans),.01),2),
        'caption_over_silence_cues':warn_no_voice,
        'uncovered_speech_spans':len(significant),
        'uncovered_speech_seconds':round(interval_seconds(significant),2),
        'subtitle_coverage_pct':round(100*interval_seconds(transcript_intervals)/max(sound_duration,.01),2),
        'decoded_audio_minutes':round(sound_duration/60,3),
        'audio_decode_seconds':audio['audio_decode_seconds'],
        'peak_signal':audio['peak_signal'],
        'audio_rms_dbfs':audio['audio_rms_dbfs'],
        'clipped_sample_pct':audio['clipped_sample_pct'],
        'approx_silent_audio_pct':audio['approx_silent_audio_pct']}
    log.info('VAD done: speech=%.1fm covered=%.1f%% text_in_silence=%d uncovered_spans=%d decoded=%.1fm',
              audio_stats['speech_minutes'],audio_stats['speech_covered_pct'],warn_no_voice,len(significant),audio_stats['audio_minutes'])
    return audio_stats


def rank_priority(metrics,flags):
    # Flag priority is a triage instruction; NOT an estimated WER or accuracy percentage.
    issues=collections.Counter(f['issue'] for f in flags)
    if (metrics.get('status')!='completed'):
        return 'INCOMPLETE'
    if (metrics['longest_identical_run']>=10 or metrics['replacement_char_cues']>0
       or metrics['unparsed_blocks']>0 or issues['caption_after_audio_end']>0
       or issues['empty_or_invalid_transcript']>0 or issues['no_voice_detected_in_audio']>0
       or issues['zero_decoded_audio']>0
       or metrics['caption_over_silence_cues']>=10
       or (metrics['subtitles']>0 and metrics['under_0_2_pct']>=20)):
        return 'HIGH'
    if (metrics['longest_identical_run']>=4 or metrics['recurrent_phrase_warnings']>=2
        or metrics['uncovered_speech_spans']>2 or metrics['caption_over_silence_cues']>0
        or issues['audio_extends_past_subtitles']>0 or issues['possible_clipped_audio']>0
        or metrics['under_0_2_pct']>7 or metrics['over_40_chars_s']>30):return 'REVIEW'
    return 'ROUTINE'


def default_stats(ep):
    d={field:'' for field in SUMMARY_FIELDS}
    d.update({'episode':ep,'status':'pending','priority':'INCOMPLETE','audio_status':'not_checked',
              'caption_over_silence_cues':0,'uncovered_speech_spans':0,
              'uncovered_speech_seconds':0, 'speech_covered_pct':'',
              'flag_high':0,'flag_medium':0,'flag_low':0,'flag_total':0,'error':''})
    return d


def audit_one(ep,source_info,mp3_path,opts,logger,logs_dir):
    begin=time.monotonic(); stats=default_stats(ep);flags=[]
    if source_info is None:
        stats.update({'status':'missing_srt','audio_status':'not_checked','error':'SRT missing'})
        flags.append(make_flag(ep,'missing_srt','high',details='Expected episode SRT is absent'))
        return finalize(stats,flags,begin)
    logger.info('START ep=%03d SRT=%s MP3=%s resources=%s',ep,source_info['where'],mp3_path,resource_snapshot())
    logger.info('SRT integrity signature sha256=%s',source_info['signature'])
    cues,metrics,flags=inspect_text(ep,source_info['text'],logger)
    stats.update(metrics)
    if not cues:
        flags.append(make_flag(ep,'empty_or_invalid_transcript','high',details='No valid SRT captions'))
    if mp3_path is None or not mp3_path.exists():
        stats['audio_status']='missing_mp3';stats['status']='missing_mp3'
        stats['error']=f'MP3 missing: {mp3_path}'
        flags.append(make_flag(ep,'missing_mp3','high',details=str(mp3_path)))
        logger.error(stats['error'])
        return finalize(stats,flags,begin)
    try:
        logger.info('audio probe begin: %s', mp3_path)
        probe = video_probe(mp3_path)
        logger.info('audio probed: %s', probe)
        stats.update({'audio_codec': probe['codec'], 'audio_channels': probe['channels'],
                      'audio_sample_rate': probe['sample_rate'], 'audio_bitrate_kbps': probe['bitrate_kbps'],
                      'audio_minutes': round((probe['duration_seconds'] or 0) / 60, 3)})
        logger.info('full Silero VAD begin; chunk_seconds=%d threshold=%.2f',
                    opts.chunk_seconds, opts.vad_threshold)
        audio = vad_stream(mp3_path, logger, logs_dir, ep, opts.chunk_seconds, opts.vad_threshold)
        stats.update(inspect_audio(ep, cues, audio, probe, flags, stats, logger))
        stats['status'] = 'completed'
    except Exception as exc:
        # Keep SRT findings even when the MP3 is corrupt or VAD cannot decode it.
        logger.exception('Audio audit failed, text findings are preserved')
        stats.update({'status': 'error', 'audio_status': 'error', 'error': str(exc)[:250]})
        flags.append(make_flag(ep, 'audio_processing_error', 'high', details=exc))
    logger.info('resource snapshot at end: %s', resource_snapshot())
    return finalize(stats, flags, begin)


def finalize(stats,flags,begin):
    ct=collections.Counter(f['severity'] for f in flags)
    stats['flag_high']=ct['high'];stats['flag_medium']=ct['medium'];stats['flag_low']=ct['low']
    stats['flag_total']=len(flags);stats['duration_seconds']=round(time.monotonic()-begin,2)
    stats['priority']=rank_priority(stats,flags)
    return {'summary':stats,'flags':flags}


def aggregate(out,selected,run_logger):
    report_dir=out/'Reports';report_dir.mkdir(exist_ok=True)
    summary=[];flags=[]
    for ep in selected:
        doc=out/'Episodes'/f'episode_{ep:03}.json'
        if doc.exists():
            try:
                obj=json.loads(doc.read_text(encoding='utf-8'))
                summary.append(obj['summary']);flags.extend(obj.get('flags',[]))
            except Exception as exc:
                record=default_stats(ep);record.update({'status':'result_corrupt','error':str(exc)})
                summary.append(record)
        else:summary.append(default_stats(ep))
    def to_csv(fname,headers,rows):
        with (report_dir/fname).open('w',newline='',encoding='utf-8-sig') as f:
            wr=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');wr.writeheader();wr.writerows(rows)
    to_csv('episode_summary.csv',SUMMARY_FIELDS,summary)
    to_csv('review_flags.csv',ISSUE_FIELDS,flags)
    totals=collections.Counter(r['status'] for r in summary)
    priorities=collections.Counter(r['priority'] for r in summary)
    insight={'created_utc':now(),'episodes_expected':len(selected),'status_counts':dict(totals),
          'priority_counts':dict(priorities),'flags_total':len(flags),
          'flags_by_issue':dict(collections.Counter(x['issue'] for x in flags)),
          'audio_vad_completed':totals.get('completed',0) if all(r['audio_status']=='full_vad_completed' for r in summary) else sum(r['audio_status']=='full_vad_completed' for r in summary),
          'IMPORTANT':'Heuristics only. No automatic decision that speech was correctly or incorrectly transcribed.'}
    dump_json(report_dir/'audit_overview.json',insight)
    run_logger.info('AGGREGATED episodes=%d statuses=%s flags=%d',len(summary),dict(totals),len(flags))
    return insight



def package_results(out: Path, log):
    """One ready-to-share artifact, without copies of the MP3s or SRTs."""
    archive = out / 'Review_Package.zip'
    files = sorted((out / 'Reports').glob('*'))
    files += sorted((out / 'Episodes').glob('episode_*.json'))
    files += sorted((out / 'Logs').glob('*.log'))
    files += [p for p in [out / 'Logs' / 'machine_info.json',
                          out / 'Logs' / 'run_config.json', out / 'Logs' / 'run_outcome.json'] if p.exists()]
    with zipfile.ZipFile(archive.with_suffix('.zip.tmp'), 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            z.write(path, arcname=path.relative_to(out).as_posix())
    os.replace(archive.with_suffix('.zip.tmp'), archive)
    log.info('SHAREABLE REPORT READY %s size=%.1f MB', archive,
             archive.stat().st_size / 1e6)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Audit ALL 241 episodes: SRT issues, MP3 signal, and speech/caption alignment.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--srt-source', required=True, type=Path,
                        help='Original ASK-GANJI-SWAG-ANALYSIS.zip or folder containing episode_###.srt')
    parser.add_argument('--audio-dir', required=True, type=Path,
                        help='Folder containing episode_001.mp3 through episode_241.mp3')
    parser.add_argument('--out', type=Path, default=Path('Audit_Results'),
                        help='Directory for logs, episode JSONs, CSVs and final shareable ZIP')
    parser.add_argument('--force', action='store_true',
                        help='Reprocess all files instead of resuming unchanged completed results')
    parser.add_argument('--chunk-seconds', type=int, default=120,
                        help='Streaming decode chunk length, in seconds')
    parser.add_argument('--vad-threshold', type=float, default=0.5,
                        help='Silero speech detector threshold (0.05..0.99)')
    args = parser.parse_args(argv)
    if not args.srt_source.exists():
        parser.error('SRT input not found')
    if not args.audio_dir.is_dir():
        parser.error('Audio folder not found')
    if not 15 <= args.chunk_seconds <= 900:
        parser.error('--chunk-seconds must be between 15 and 900')
    if not 0.05 <= args.vad_threshold <= 0.99:
        parser.error('--vad-threshold must be between 0.05 and 0.99')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('Install FFmpeg and ensure both ffmpeg and ffprobe are on PATH')
    try:
        import numpy  # noqa: F401
        import faster_whisper.vad  # noqa: F401
    except ImportError as exc:
        parser.error(f'Missing Python dependency: {exc}. Run: python -m pip install -r requirements.txt')

    source, duplicates = input_source(args.srt_source)
    out = args.out.resolve()
    logs = out / 'Logs'
    episodes = out / 'Episodes'
    reports = out / 'Reports'
    for directory in (logs, episodes, reports):
        directory.mkdir(parents=True, exist_ok=True)
    log = build_logger('audit_main', logs / 'run.log', console=True)
    selected = list(range(1, 242))
    configuration = {
        'version': VERSION,
        'run_started_utc': now(),
        'srt_source': str(args.srt_source.resolve()),
        'audio_dir': str(args.audio_dir.resolve()),
        'output_dir': str(out),
        'episode_range': '001-241',
        'chunk_seconds': args.chunk_seconds,
        'vad_threshold': args.vad_threshold,
        'force': args.force,
        'duplicates': duplicates,
        'unexpected_srt_ids': sorted(set(source) - set(selected)),
    }
    # Resume validity depends only on settings that change episode output.
    key = {k: configuration[k] for k in (
        'version', 'srt_source', 'audio_dir', 'episode_range', 'chunk_seconds', 'vad_threshold')}
    config_digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    configuration['analysis_signature'] = config_digest
    dump_json(logs / 'machine_info.json', machine_inventory(out))
    dump_json(logs / 'run_config.json', configuration)
    log.info('FULL AUDIT START: 241 episodes; SRT files found=%d; audio_dir=%s', len(source), args.audio_dir)
    log.info('MACHINE INVENTORY stored at %s', logs / 'machine_info.json')
    if duplicates:
        log.warning('Duplicate SRT episode IDs (first used): %s', duplicates)
    if configuration['unexpected_srt_ids']:
        log.warning('Unexpected SRT episode IDs: %s', configuration['unexpected_srt_ids'])

    completed = 0
    resumed = 0
    failures = 0
    interrupted = False
    try:
        for count, ep in enumerate(selected, 1):
            info = source.get(ep)
            sound = args.audio_dir / f'episode_{ep:03}.mp3'
            signature = {
                'srt': info['signature'] if info else 'MISSING',
                'mp3': sound_signature(sound),
                'config_digest': config_digest,
            }
            result_path = episodes / f'episode_{ep:03}.json'
            if result_path.exists() and not args.force:
                try:
                    saved = json.loads(result_path.read_text(encoding='utf-8'))
                    if (saved.get('input_signatures') == signature and
                            saved['summary'].get('status') == 'completed' and
                            saved['summary'].get('audio_status') == 'full_vad_completed'):
                        resumed += 1
                        log.info('[%03d/241] Episode %03d SKIPPED (unchanged, already completed)', count, ep)
                        continue
                except (ValueError, KeyError, OSError, TypeError):
                    pass
            episode_log = build_logger(f'audit_episode_{ep:03}', logs / f'episode_{ep:03}.log')
            try:
                episode_log.info('EPISODE %03d START', ep)
                result = audit_one(ep, info, sound, args, episode_log, logs)
                result.update({'input_signatures': signature, 'completed_utc': now(),
                               'audit_version': VERSION})
                dump_json(result_path, result)
                episode_log.info('EPISODE %03d FINISHED: status=%s, priority=%s, flags=%d, walltime=%.1fs',
                                 ep, result['summary']['status'], result['summary']['priority'],
                                 len(result['flags']), result['summary']['duration_seconds'])
                completed += 1
                if result['summary']['status'] == 'error':
                    failures += 1
                log.info('[%03d/241] Episode %03d: %s, priority=%s, flags=%d',
                         count, ep, result['summary']['status'], result['summary']['priority'],
                         len(result['flags']))
            except Exception as exc:
                failures += 1
                episode_log.exception('EPISODE %03d ERROR', ep)
                log.error('[%03d/241] Episode %03d ERROR: %s', count, ep, exc)
                stats = default_stats(ep)
                stats.update({'status': 'error', 'audio_status': 'error', 'error': str(exc)[:250]})
                result = finalize(stats, [make_flag(ep, 'processing_error', 'high', details=exc)], time.monotonic())
                result.update({'input_signatures': signature, 'completed_utc': now(),
                               'audit_version': VERSION})
                dump_json(result_path, result)
            finally:
                close_logger(episode_log)
    except KeyboardInterrupt:
        interrupted = True
        log.warning('INTERRUPTED; all previously finished episodes were saved. Run the same command to resume.')

    overview = aggregate(out, selected, log)
    dump_json(logs / 'run_outcome.json', {
        'ended_utc': now(), 'completed_in_this_run': completed, 'reused_results': resumed,
        'failures_in_this_run': failures, 'interrupted': interrupted, 'overview': overview,
    })
    try:
        package_results(out, log)
    except Exception:
        log.exception('Could not package results; all raw results remain under %s', out)
    log.info('END: new=%d, cached=%d, failures=%d, interrupted=%s',
             completed, resumed, failures, interrupted)
    close_logger(log)
    if interrupted:
        return 130
    if failures or overview['status_counts'].get('error') or overview['status_counts'].get('missing_mp3') or overview['status_counts'].get('missing_srt'):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
