import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve()
sys.path.insert(0,str(HERE.parents[1]/'.shared'))
import manage_subtitles as manage

TEST_TEMP=HERE.parents[2]/'.cache/test-tmp'
TEST_TEMP.mkdir(parents=True,exist_ok=True)

def load(folder,name):
    """A numbered step's Python file, which a plain import cannot reach."""
    spec=importlib.util.spec_from_file_location(name,HERE.parents[1]/folder/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

download=load('03-download-audio','download')
romanize=load('05-romanize','romanize')

CHAPTERS=[{'title':'Intro','start_time':0,'end_time':190},{'title':'Comments','start_time':190,'end_time':1145},
          {'title':'Pyaar ya Pressure','start_time':1145,'end_time':2233},{'title':'Outro','start_time':2233,'end_time':2300}]
INDEX='''# Index

<details open>
<summary><strong>Episode 001</strong></summary>

1. [Should I move?](https://youtu.be/old?list=PL&t=10)

</details>



'''

class NewEpisodeTests(unittest.TestCase):
    def test_number_comes_from_the_title(self):
        self.assertEqual(download.episode_number('Pyaar Ya Pressure? | Ask Ganjiswag #243'),243)
        self.assertEqual(download.episode_number('Ask Ganjiswag #2 | Junaid Akram'),2)
        self.assertEqual(download.episode_number('8 years | Ask Ganjiswag Special Episode #225'),225)
        self.assertEqual(download.episode_number('India | Ask Ganjiswag Indian Special #110'),110)
        self.assertIsNone(download.episode_number('#1 mistake | Ask Ganjiswag'))
        self.assertIsNone(download.episode_number('Curious Case | Ask Ganjiswag'))
        self.assertIsNone(download.episode_number(None))

    def test_only_videos_the_index_does_not_list_are_new(self):
        index={1:[('A','a',0)],2:[('B','b',0)]}
        entries=[{'id':'a','title':'x | Ask Ganjiswag #1'},{'id':'b','title':'y | Ask Ganjiswag #2'},
                 {'id':'d','title':'w | Ask Ganjiswag #4'},{'id':'c','title':'z | Ask Ganjiswag #3'}]
        self.assertEqual([n for n,_,_ in download.new_episodes(entries,index)],[3,4])
        self.assertEqual(download.new_episodes(entries[:2],index),[])

    def test_title_without_a_number_takes_the_next_one(self):
        # The playlist lost a video, so places would say 2 and 3 here.
        index={1:[('A','a',0)],5:[('E','e',0)]}
        entries=[{'id':'a','title':'x'},{'id':'e','title':'y'},{'id':'f','title':'A special | Ask Ganjiswag'},{'id':'g','title':None}]
        self.assertEqual(download.new_episodes(entries,index),[(6,'f','A special | Ask Ganjiswag'),(7,'g','')])

    def test_chapters_become_questions(self):
        questions=download.questions_of(download.chapters_of({'chapters':CHAPTERS}))
        self.assertEqual(questions,[('Youtube Comments',190),('Pyaar ya Pressure',1145)])

    def test_a_chapter_that_only_starts_like_intro_stays(self):
        self.assertEqual(download.questions_of([('Introvert and alone',5),('End of my marriage',9)]),[('Introvert and alone',5),('End of my marriage',9)])

    def test_description_times_stand_in_for_chapters(self):
        description='Links below\n0:00 - Intro\n3:10 - Comments\n1:03:52 - Sapney Vs Indian Father \n4:44:21 - Outro\nThanks'
        self.assertEqual(download.questions_of(download.chapters_of({'chapters':None,'description':description})),
                         [('Youtube Comments',190),('Sapney Vs Indian Father',3832)])

    def test_a_lone_time_in_the_description_is_not_a_chapter_list(self):
        self.assertEqual(download.chapters_of({'description':'Live at 7:30 in Lahore\nTickets soon'}),[])
        self.assertEqual(download.chapters_of({}),[])

    def test_index_gains_one_block_and_reads_back(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path=Path(d)/'index.md';path.write_text(INDEX,encoding='utf-8')
            info={'id':'new-video','chapters':CHAPTERS}
            self.assertIn('added 2 questions',download.index_episode(2,info,path))
            text=path.read_text(encoding='utf-8')
            self.assertTrue(text.startswith(INDEX.rstrip('\n')))
            self.assertTrue(text.endswith('</details>\n\n\n\n'))
            read=download.read_index(path)
            self.assertEqual(read[1],[('Should I move?','old',10)])
            self.assertEqual(read[2],[('Youtube Comments','new-video',190),('Pyaar ya Pressure','new-video',1145)])
            self.assertIn('<summary><strong>Episode 002</strong></summary>',text)
            self.assertIn('already in the index',download.index_episode(2,info,path))
            self.assertEqual(path.read_text(encoding='utf-8'),text)

    def test_video_without_chapters_adds_nothing_yet(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path=Path(d)/'index.md';path.write_text(INDEX,encoding='utf-8')
            self.assertIn('no chapters',download.index_episode(2,{'id':'new-video'},path))
            self.assertEqual(path.read_text(encoding='utf-8'),INDEX)

class DownloadTests(unittest.TestCase):
    """A new episode's audio waits in the root folder only until the episode has both subtitles."""
    def fetch(self,root,audio=False,roman=False,english=False):
        """download() of episode 244 into a made-up root folder, with yt-dlp stood in for; returns its calls."""
        folders={'AUDIO':root,'DOWNLOADS':root/'.cache'/'downloads','ROMAN':root/'roman','ENGLISH':root/'english'}
        for key,wanted in (('ROMAN',roman),('ENGLISH',english)):
            folders[key].mkdir()
            if wanted:(folders[key]/'episode_244.srt').write_text(ROMAN,encoding='utf-8')
        if audio:(root/'episode_244.mp3').write_bytes(b'put here by hand')
        calls=[]
        def yt_dlp(arguments,check):
            calls.append(arguments)
            work=Path(arguments[arguments.index('-P')+1])
            (work/'episode_244.info.json').write_text(json.dumps({'id':'v244','chapters':CHAPTERS}),encoding='utf-8')
            if '--skip-download' not in arguments:(work/'episode_244.mp3').write_bytes(b'downloaded')
        with patch.multiple(download,**folders),patch.object(download.subprocess,'run',yt_dlp):
            self.assertEqual(download.download(244,'https://youtu.be/v244')['id'],'v244')
        return calls

    def test_new_audio_alone_reaches_the_root_folder(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d)
            self.assertNotIn('--skip-download',self.fetch(root)[0])
            self.assertEqual([p.name for p in root.iterdir() if p.is_file()],['episode_244.mp3'])
            self.assertEqual((root/'episode_244.mp3').read_bytes(),b'downloaded')
            self.assertEqual([p.name for p in (root/'.cache'/'downloads').iterdir()],['episode_244.info.json'])

    def test_audio_put_in_the_root_folder_is_used(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d)
            self.assertIn('--skip-download',self.fetch(root,audio=True)[0])
            self.assertEqual((root/'episode_244.mp3').read_bytes(),b'put here by hand')

    def test_an_episode_with_both_subtitles_is_not_downloaded_again(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d)
            self.assertIn('--skip-download',self.fetch(root,roman=True,english=True)[0])
            self.assertFalse((root/'episode_244.mp3').exists())

    def test_roman_urdu_alone_still_needs_the_audio(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            self.assertNotIn('--skip-download',self.fetch(Path(d),roman=True)[0])


ROMAN='1\n00:00:00,000 --> 00:00:02,000\nCanada visa aur masters\n\n'
SOURCE=ROMAN.replace('aur','اور')

class WithoutTheOriginalSrtTests(unittest.TestCase):
    """Most episodes' original SRTs are gone; their words live on in the alignment cache."""
    def folders(self,root):
        source,roman,cache=root/'source',root/'roman',root/'alignment'
        for folder in (source,roman,cache):folder.mkdir()
        (roman/'episode_001.srt').write_text(ROMAN,encoding='utf-8')
        (cache/'episode_001.json').write_text(json.dumps({'version':1,'source_sha256':'made from a file now gone','duration':3.0,'gaps':[],
            'cues':[[0.0,2.0,SOURCE.split('\n')[2],'Canada visa aur masters',[[0.0,0.4,-.1],[0.5,0.9,-.1],[1.0,1.4,-.1],[1.5,1.9,-.1]]]]}),encoding='utf-8')
        return source,roman,cache

    def test_cache_is_the_record_once_the_srt_is_gone(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            source,roman,cache=self.folders(Path(d))
            with patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',Path(d)/'reports'),patch.object(manage,'ROOT',Path(d)):
                self.assertIsNotNone(manage.alignment_for(roman/'episode_001.srt',source))
                self.assertFalse(manage.pace(roman,source))

    def test_an_srt_that_differs_from_the_cache_still_wins(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            source,roman,cache=self.folders(Path(d))
            (source/'episode_001.srt').write_text(SOURCE,encoding='utf-8')
            with patch.object(manage,'ALIGNMENT',cache):
                self.assertIsNone(manage.alignment_for(roman/'episode_001.srt',source))

    def test_validation_counts_both_kinds_of_episode(self):
        # Episode 1 has only its cache and episode 2 only its SRT; neither may lack a Roman file.
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            source,roman,cache=self.folders(Path(d))
            (source/'episode_002.srt').write_text(ROMAN,encoding='utf-8')
            with patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',Path(d)/'reports'),patch.object(manage,'ENGLISH',Path(d)/'none'):
                self.assertTrue(manage.validate(roman,source))
                (roman/'episode_002.srt').write_text(ROMAN,encoding='utf-8')
                self.assertFalse(manage.validate(roman,source))
                (roman/'episode_001.srt').unlink()
                (roman/'episode_003.srt').write_text(ROMAN,encoding='utf-8')
                self.assertTrue(manage.validate(roman,source))

class RomanizeTests(unittest.TestCase):
    def test_arabic_ligatures_become_ordinary_words(self):
        text=romanize.expanded('ہمارا رسول ﷺ سب')
        self.assertEqual(romanize.WORD.sub('',text).split(),[])
        self.assertEqual(len(romanize.WORD.findall(text)),7)
        self.assertEqual(romanize.expanded('Hello اور [UH]'),'Hello اور [UH]')

    def test_finished_episode_needs_no_source(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            source,output=Path(d)/'source',Path(d)/'roman'
            source.mkdir();output.mkdir()
            (output/'episode_001.srt').write_text(ROMAN,encoding='utf-8')
            (source/'episode_002.srt').write_text(SOURCE,encoding='utf-8')
            self.assertEqual(romanize.pending(source,output,'1',False),([],1))
            self.assertEqual(romanize.pending(source,output,'1,2',False),([source/'episode_002.srt'],1))
            self.assertEqual(romanize.pending(source,output,None,False),([source/'episode_002.srt'],0))
            with self.assertRaises(ValueError):romanize.pending(source,output,'1',True)
            with self.assertRaises(ValueError):romanize.pending(source,output,'3',False)
            self.assertEqual(romanize.pending(Path(d)/'gone',output,None,False),([],0))

# Stands in for each step of scripts/add-episode.sh: notes how it was called and makes the subtitles the real step would.
STUB='''#!/usr/bin/env bash
set -euo pipefail
step="$(basename "$(dirname "$0")")";args="$*";episodes=''
echo "$step $args" >> "$LOG"
while (($#));do [[ "$1" == --episodes ]] && episodes="$2";shift;done
make(){ local n;for n in ${episodes//,/ };do echo made > "$1/episode_$(printf '%03d' "$n").srt";done; }
case "$step" in
    05-romanize) [[ "$args" == *--alignment* ]] || make transcripts-urdu-roman ;;
    06-format) [[ "$args" != *--translate* ]] || make transcripts-english ;;
    07-validate) exit "${VALIDATE:-0}" ;;
esac
'''

@unittest.skipUnless(os.name=='posix' and shutil.which('bash'),'needs Bash')
class AddEpisodeTests(unittest.TestCase):
    """scripts/add-episode.sh in a made-up repository whose episode 243 is finished, each step stood in for by STUB."""
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=TEST_TEMP);self.addCleanup(temp.cleanup)
        self.root=root=Path(temp.name)
        for path in ('scripts/add-episode.sh','scripts/.shared/common.sh'):
            (root/path).parent.mkdir(parents=True,exist_ok=True);shutil.copy(HERE.parents[2]/path,root/path)
        for step in ('scripts/03-download-audio','scripts/04-transcribe','scripts/05-romanize','scripts/06-format','scripts/07-validate','ganji-model','app'):
            (root/step).mkdir(parents=True,exist_ok=True);(root/step/'run.sh').write_text(STUB,encoding='utf-8')
        for folder in ('transcripts-urdu-roman','transcripts-english'):
            (root/folder).mkdir();(root/folder/'episode_243.srt').write_text('made',encoding='utf-8')

    def add_episode(self,*arguments,validate='0'):
        """Runs it; returns how it went and the steps it ran."""
        log=self.root/'steps.log';log.unlink(missing_ok=True)
        done=subprocess.run(['bash','scripts/add-episode.sh',*arguments],cwd=self.root,capture_output=True,text=True,
                            env=dict(os.environ,LOG=str(log),VALIDATE=validate))
        return done,[line.strip() for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []

    def test_new_audio_becomes_subtitles_then_goes(self):
        (self.root/'episode_244.mp3').write_bytes(b'audio')
        done,steps=self.add_episode()
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(steps,['03-download-audio','04-transcribe --episodes 244','05-romanize --episodes 244',
            '06-format --episodes 244 --fill --loops --no-pace','05-romanize --alignment --episodes 244',
            '06-format --episodes 244 --skip-align','06-format --translate --episodes 244','07-validate --episodes 244',
            'ganji-model label','app'])
        self.assertFalse((self.root/'episode_244.mp3').exists())
        self.assertTrue((self.root/'transcripts-english'/'episode_244.srt').is_file())

    def test_audio_stays_until_the_subtitles_pass_the_check(self):
        (self.root/'episode_244.mp3').write_bytes(b'audio')
        done,_=self.add_episode(validate='1')
        self.assertNotEqual(done.returncode,0)
        self.assertTrue((self.root/'episode_244.mp3').exists())
        # Run again: the subtitles are made, so they are only checked before the audio goes.
        done,steps=self.add_episode()
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(steps,['03-download-audio','07-validate --episodes 244','ganji-model label','app'])
        self.assertFalse((self.root/'episode_244.mp3').exists())

    def test_an_episode_with_both_subtitles_is_never_made_again(self):
        (self.root/'episode_243.mp3').write_bytes(b'audio put back by hand')
        done,steps=self.add_episode()
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(steps,['03-download-audio','07-validate --episodes 243','ganji-model label','app'])
        self.assertFalse((self.root/'episode_243.mp3').exists())

    def test_nothing_new(self):
        done,steps=self.add_episode()
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(steps,['03-download-audio','ganji-model label','app'])
        self.assertIn('No new episode',done.stdout)

    def test_chosen_episodes_need_their_audio_in_the_root_folder(self):
        done,steps=self.add_episode('--episodes','244')
        self.assertEqual(done.returncode,1)
        self.assertIn('episode_244.mp3',done.stderr)
        self.assertEqual(steps,[])
        (self.root/'episode_244.mp3').write_bytes(b'audio')
        done,steps=self.add_episode('--episodes','244')
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(steps[0],'04-transcribe --episodes 244')
        self.assertFalse((self.root/'episode_244.mp3').exists())

if __name__=='__main__':unittest.main()
