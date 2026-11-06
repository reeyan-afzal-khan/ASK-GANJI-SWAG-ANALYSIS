import importlib.util
import json
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

if __name__=='__main__':unittest.main()
