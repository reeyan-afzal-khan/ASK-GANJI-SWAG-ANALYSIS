import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.shared'))
from subtitles import parse, render, select_files, span
import manage_subtitles as manage
import pacing

TEST_TEMP=Path(__file__).resolve().parents[2]/'.cache/test-tmp'
TEST_TEMP.mkdir(parents=True,exist_ok=True)

SAMPLE='1\n00:00:00,000 --> 00:00:02,000\nHello\nworld\n\n2\n00:00:02,000 --> 00:00:03,000\nI am here.\n\n'

def setUpModule():
    # Validation also checks transcripts-english/; keep the tests away from the real one.
    english=patch.object(manage,'ENGLISH',TEST_TEMP/'no-english')
    english.start()
    unittest.addModuleCleanup(english.stop)

class SubtitleTests(unittest.TestCase):
    def test_single_line_preserves_ids_timing_and_words(self):
        before=parse(SAMPLE)
        after=parse(render(before))
        self.assertEqual([(c.number,c.timing,c.text) for c in before],[(c.number,c.timing,c.text) for c in after])
        self.assertTrue(all(len(c.lines)==1 for c in after))

    def test_format_is_idempotent(self):
        once=render(parse(SAMPLE))
        self.assertEqual(once,render(parse(once)))

    def test_bom_crlf_and_numeric_text(self):
        text='\ufeff1\r\n00:00:00,000 --> 00:00:01,000\r\n123\r\n\r\n'
        self.assertEqual(parse(text)[0].text,'123')

    def test_rejects_empty_or_invalid_input(self):
        for text in ['', '1\nwrong timing\ntext', '1\n00:00:00,000 --> 00:00:01,000\n']:
            with self.assertRaises(ValueError):parse(text)

    def test_missing_episode_fails(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            with self.assertRaises(ValueError):select_files(d,'999')

    def test_validator_catches_changed_english_and_timing(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);source=root/'source';out=root/'out'
            source.mkdir();out.mkdir()
            (source/'episode_001.srt').write_text(SAMPLE)
            p=out/'episode_001.srt';p.write_text(render(parse(SAMPLE)))
            with patch.object(manage,'REPORTS',root/'reports'),patch.object(manage,'ALIGNMENT',root/'alignment'):
                self.assertFalse(manage.validate(out,source))
                p.write_text(render(parse(SAMPLE)).replace('Hello','Goodbye'))
                self.assertTrue(manage.validate(out,source))
                # Timings may differ from the source once paced, but cues must never overlap.
                p.write_text(render(parse(SAMPLE)).replace('00:00:02,000 --> 00:00:03,000','00:00:01,500 --> 00:00:03,000'))
                self.assertTrue(manage.validate(out,source))

# One cue of the original Crisper SRT, its Roman conversion, and a cached word alignment of it.
SOURCE_CUES='1\n00:00:00,000 --> 00:00:04,000\nCanada visa اور masters کا سوال ہے اور میں ابھی lahore میں ہوں\n\n2\n00:00:05,500 --> 00:00:06,000\nشکریہ\n\n'
ROMAN_CUES='1\n00:00:00,000 --> 00:00:04,000\nCanada visa aur masters ka sawal hai aur mein abhi lahore mein hoon\n\n2\n00:00:05,500 --> 00:00:06,000\nshukriya\n\n'

def alignment(source_path,roman_text=ROMAN_CUES):
    cues=[]
    for src,rom in zip(parse(source_path.read_text(encoding='utf-8')),parse(roman_text)):
        start,end=span(src);n=len(src.text.split());step=(end-start)/n
        cues.append([start,end,src.text,rom.text,[[start+k*step,start+(k+1)*step-0.05,-0.1] for k in range(n)]])
    return {'version':1,'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),'duration':7.0,'cues':cues}

def timed_words(text,step=0.3):
    return [(w,k*step,k*step+step-0.05) for k,w in enumerate(text.split())]

def load_align():
    spec=importlib.util.spec_from_file_location('align',Path(__file__).resolve().parents[1]/'06-format'/'align.py')
    align=importlib.util.module_from_spec(spec)
    here=os.getcwd()
    try:spec.loader.exec_module(align)
    finally:os.chdir(here)
    return align

# A decoding loop between two real sentences: 48 words of one phrase in four cues, with a gap inside.
LOOP_SOURCE=('1\n00:00:00,000 --> 00:00:04,000\nhum ne pehle baat ki thi woh kehte hain\n\n'
             +''.join(f'{n}\n00:00:{a:02},000 --> 00:00:{b:02},000\n'+"I'm asking you. I don't know. "*2+'\n\n'
                      for n,(a,b) in enumerate(((4,9),(9,14),(22,26),(26,30)),2))
             +'6\n00:00:31,000 --> 00:00:34,000\nphir woh chala gaya apne ghar wapas\n\n')

class PacingTests(unittest.TestCase):
    def test_cues_fit_one_line_and_keep_every_word(self):
        words=timed_words('aap ne bilkul theek kaha hai lekin mein yeh samajhta hoon ke hamein pehle apni padhai poori karni chahiye aur phir naukri ke baare mein sochna chahiye.')
        cues=pacing.timed(words,pacing.segment(words))
        self.assertEqual(' '.join(t for *_,t in cues).split(),[w for w,*_ in words])
        self.assertTrue(all(len(t)<=pacing.MAX_CHARS and len(t.split())>2 for *_,t in cues))
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(cues,cues[1:])))

    def test_long_pause_breaks_and_short_cue_is_held(self):
        words=[('pehli',0.0,0.4),('baat.',0.5,0.9),('doosri',3.0,3.4),('baat',3.5,3.9)]
        cues=pacing.timed(words,pacing.segment(words))
        self.assertEqual([t for *_,t in cues],['pehli baat.','doosri baat'])
        self.assertGreaterEqual(cues[0][1]-cues[0][0],pacing.MIN_SECONDS)

    def test_compound_postpositions_stay_together(self):
        words=timed_words('humne apne bachon ke liye ek naya ghar khareed liya hai')
        cues=[t for *_,t in pacing.timed(words,pacing.segment(words))]
        self.assertEqual(len(cues),2)
        self.assertTrue(cues[0].endswith('ke liye'))

    def test_multiword_romanisation_shares_the_urdu_word_time(self):
        out=pacing.roman_words('I کیونکہ go','I kyun ke go',[[0.0,0.5,-0.1],[0.5,1.5,-0.2],[1.5,2.0,-0.1]])
        self.assertEqual([w for w,*_ in out],['I','kyun','ke','go'])
        self.assertEqual((out[0][1:],out[3][1:]),((0.0,0.5),(1.5,2.0)))
        self.assertAlmostEqual(out[1][1],0.5);self.assertAlmostEqual(out[2][2],1.5)
        self.assertLess(out[1][2],out[2][2])

    def test_format_paces_from_alignment_backs_up_once_and_validates(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);source=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (source,roman,cache):folder.mkdir()
            (source/'episode_001.srt').write_text(SOURCE_CUES,encoding='utf-8')
            # A hand correction made before pacing ('abhi' -> 'abhee') must survive it.
            p=roman/'episode_001.srt';p.write_text(ROMAN_CUES.replace('abhi','abhee'),encoding='utf-8')
            (cache/'episode_001.json').write_text(json.dumps(alignment(source/'episode_001.srt')),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,source))
                paced=p.read_text(encoding='utf-8')
                self.assertIn('abhee',paced);self.assertNotIn('abhi ',paced)
                self.assertFalse(manage.pace(roman,source))
                self.assertEqual(p.read_text(encoding='utf-8'),paced)
                self.assertEqual(len(list((root/'.cache/backups').glob('*.zip'))),1)
                cues=parse(paced)
                self.assertGreater(len(cues),2)
                self.assertTrue(all(len(c.text)<=pacing.MAX_CHARS for c in cues))
                self.assertFalse(manage.validate(roman,source))
                p.write_text(paced.replace('masters','master'),encoding='utf-8')
                self.assertTrue(manage.validate(roman,source))
                # Correcting Roman Urdu after pacing is allowed, and re-pacing keeps it.
                p.write_text(paced.replace('sawal','sawaal'),encoding='utf-8')
                self.assertFalse(manage.validate(roman,source))
                self.assertFalse(manage.pace(roman,source))
                self.assertIn('sawaal',p.read_text(encoding='utf-8'))

    def test_validation_reads_the_original_from_the_cache_once_its_folder_is_gone(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);source=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (source,roman,cache):folder.mkdir()
            (source/'episode_001.srt').write_text(SOURCE_CUES,encoding='utf-8')
            p=roman/'episode_001.srt';p.write_text(ROMAN_CUES,encoding='utf-8')
            (cache/'episode_001.json').write_text(json.dumps(alignment(source/'episode_001.srt')),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,source))
                paced=p.read_text(encoding='utf-8')
                gone=root/'deleted'
                self.assertFalse(manage.validate(roman,gone))
                p.write_text(paced.replace('masters','master'),encoding='utf-8')
                self.assertTrue(manage.validate(roman,gone))
                # Every cached episode still needs its Roman file.
                p.write_text(paced,encoding='utf-8')
                (cache/'episode_002.json').write_text(json.dumps(alignment(source/'episode_001.srt')),encoding='utf-8')
                self.assertTrue(manage.validate(roman,gone))

    def test_stitching_duplicates_are_left_out_and_still_validate(self):
        source=('1\n00:00:00,000 --> 00:00:03,000\nwe went to the market today\n\n'
                '2\n00:00:03,000 --> 00:00:03,100\nto the market today\n\n'
                '3\n00:00:03,200 --> 00:00:05,000\nand bought some fruit\n\n')
        cues=[(*span(c),c.text) for c in parse(source)]
        self.assertEqual(pacing.duplicates(cues),{1})
        # Squeezed but saying something new: kept.
        self.assertEqual(pacing.duplicates([cues[0],(3.0,3.1,'and then we came home'),cues[2]]),set())
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);src=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (src,roman,cache):folder.mkdir()
            (src/'episode_001.srt').write_text(source,encoding='utf-8')
            (roman/'episode_001.srt').write_text(source,encoding='utf-8')
            (cache/'episode_001.json').write_text(json.dumps(alignment(src/'episode_001.srt',source)),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,src))
                paced=parse((roman/'episode_001.srt').read_text(encoding='utf-8'))
                self.assertEqual(' '.join(c.text for c in paced),'we went to the market today and bought some fruit')
                self.assertFalse(manage.validate(roman,src))
                report=json.loads((root/'reports'/'pacing.json').read_text(encoding='utf-8'))
                self.assertEqual(report['duplicates_removed']['words'],4)

    def test_repacing_never_drops_words_that_a_duplicate_repeats(self):
        # The duplicate plus the next cue form a longer match than the real copy plus the cue before,
        # which once let re-pacing pair the real words with the duplicate and drop them.
        source=('1\n00:00:00,000 --> 00:00:03,000\nyeh baat to bilkul sahi hai\n\n'
                '2\n00:00:03,000 --> 00:00:03,100\nbaat to bilkul sahi hai\n\n'
                '3\n00:00:03,200 --> 00:00:06,000\nlekin hum kya kar sakte hain ab\n\n')
        expected='yeh baat to bilkul sahi hai lekin hum kya kar sakte hain ab'
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);src=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (src,roman,cache):folder.mkdir()
            (src/'episode_001.srt').write_text(source,encoding='utf-8')
            p=roman/'episode_001.srt';p.write_text(source,encoding='utf-8')
            (cache/'episode_001.json').write_text(json.dumps(alignment(src/'episode_001.srt',source)),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                for _ in range(3):
                    self.assertFalse(manage.pace(roman,src))
                    self.assertEqual(' '.join(c.text for c in parse(p.read_text(encoding='utf-8'))),expected)

    def test_missed_speech_is_inserted_once_and_edits_are_kept(self):
        source=('1\n00:00:00,000 --> 00:00:02,000\nhum ne pehle baat ki thi\n\n'
                '2\n00:00:10,000 --> 00:00:12,000\naur phir yeh hua\n\n')
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);src=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (src,roman,cache):folder.mkdir()
            (src/'episode_001.srt').write_text(source,encoding='utf-8')
            p=roman/'episode_001.srt';p.write_text(source,encoding='utf-8')
            data=alignment(src/'episode_001.srt',source)
            # Speech in the eight-second gap, transcribed later and already romanised.
            data['supplements']=[{'gap':[2.0,10.0],'start':4.0,'end':6.0,'source':'beech mein bhi kuch kaha',
                                  'roman':'beech mein bhi kuch kaha','words':[[4.0+0.4*k,4.35+0.4*k,None] for k in range(5)],'applied':False}]
            (cache/'episode_001.json').write_text(json.dumps(data),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,src))
                words=' '.join(c.text for c in parse(p.read_text(encoding='utf-8')))
                self.assertEqual(words,'hum ne pehle baat ki thi beech mein bhi kuch kaha aur phir yeh hua')
                self.assertTrue(json.loads((cache/'episode_001.json').read_text(encoding='utf-8'))['supplements'][0]['applied'])
                paced=p.read_text(encoding='utf-8')
                self.assertFalse(manage.pace(roman,src))
                self.assertEqual(p.read_text(encoding='utf-8'),paced)
                self.assertFalse(manage.validate(roman,src))
                # Deleting the added passage's cue by hand is respected by later pacing.
                p.write_text(render([c for c in parse(paced) if 'beech' not in c.text]),encoding='utf-8')
                self.assertFalse(manage.pace(roman,src))
                self.assertNotIn('beech',p.read_text(encoding='utf-8'))

    def test_passages_before_the_first_or_after_the_last_cue_validate(self):
        # An intro or outro the original transcription skipped lies outside the source's time.
        source=('1\n00:00:10,000 --> 00:00:12,000\nhum ne pehle baat ki thi\n\n'
                '2\n00:00:12,500 --> 00:00:14,000\naur phir yeh hua\n\n')
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);src=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (src,roman,cache):folder.mkdir()
            (src/'episode_001.srt').write_text(source,encoding='utf-8')
            p=roman/'episode_001.srt';p.write_text(source,encoding='utf-8')
            data=alignment(src/'episode_001.srt',source)
            data['supplements']=[{'gap':gap,'start':start,'end':start+2.0,'source':text,'roman':text,
                                  'words':[[start+0.4*k,start+0.35+0.4*k,None] for k in range(5)],'applied':False}
                                 for gap,start,text in (([0.0,10.0],2.0,'salaam aur khush aamdeed sab'),
                                                        ([14.0,30.0],20.0,'milte hain agli dafa phir'))]
            (cache/'episode_001.json').write_text(json.dumps(data),encoding='utf-8')
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,src))
                cues=parse(p.read_text(encoding='utf-8'))
                self.assertEqual((span(cues[0])[0],cues[-1].text.split()[-1]),(2.0,'phir'))
                self.assertFalse(manage.validate(roman,src))

    def test_decoding_loops_cover_long_phrase_loops_only(self):
        cues=[(*span(c),c.text) for c in parse(LOOP_SOURCE)]
        # The window may take in two neighbouring words on each side ("kehte hain", "phir woh").
        self.assertEqual(pacing.decoding_loops(cues),[(7,59)])
        varied=lambda first:' '.join(f'lafz{k}' for k in range(first,first+10))
        self.assertEqual(pacing.decoding_loops([(0,1,varied(0)),(1,2,'ke woh ja rahe '*8),(2,3,varied(10))]),[(10,42)])
        self.assertEqual(pacing.decoding_loops([(0,1,varied(0)+' '+varied(10)+' '+varied(20))]),[])
        self.assertEqual(pacing.decoding_loops([(0,1,'[lipsmack] '*60)]),[])

    def test_origins_follow_letters_inside_romanised_runs(self):
        self.assertEqual(pacing.origins('کہ وہ جارہے ہیں','ke woh ja rahe hain'),[0,1,2,2,3])
        self.assertEqual(pacing.origins('Canada visa اور جارہے','Canada visa aur ja rahe'),[0,1,2,3,3])
        self.assertEqual(pacing.roman_range([[0,1,'کہ وہ جارہے ہیں','ke woh ja rahe hain',[]]],2,3),'ja rahe')

    def test_fresh_transcription_must_differ_to_confirm_a_loop(self):
        align=load_align()
        loop=("I'm asking you. I don't know. "*8).split()
        self.assertTrue(align.confirms(loop,'beta asal mein mujhe khud nahi pata ke woh kya chahti hai'.split())[0])
        self.assertTrue(align.confirms(loop,"woh keh rahi thi I'm asking you. I don't know. phir hum ne socha".split())[0])
        self.assertFalse(align.confirms(loop,("I'm asking you. I don't know. "*5).split())[0])
        self.assertFalse(align.confirms(loop,("I'm asking you. I don't know. aur "*3).split())[0])
        self.assertFalse(align.confirms(loop,'[UH] [lipsmack]'.split())[0])
        # Shorter, but circling the loop's own words (episode 79 came back like this).
        stuck=('to bhaiyon ko yeh hota hai ke '*9).split()
        self.assertFalse(align.confirms(stuck,'to bhaiyon ko yeh hota hai umeman ke bhaiyon ne ke bhaiyon ne ke bhaiyon'.split())[0])

    def test_confirmed_loop_is_replaced_once_with_passages_inside_it(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);src=root/'source';roman=root/'roman';cache=root/'alignment'
            for folder in (src,roman,cache):folder.mkdir()
            (src/'episode_001.srt').write_text(LOOP_SOURCE,encoding='utf-8')
            p=roman/'episode_001.srt';p.write_text(LOOP_SOURCE,encoding='utf-8')
            data=alignment(src/'episode_001.srt',LOOP_SOURCE);data['gaps']=[]
            # Speech --fill already added in the gap inside the loop's stretch.
            data['supplements']=[{'gap':[14.0,22.0],'start':15.0,'end':20.0,'source':'beech mein kuch aur bhi kaha',
                                  'roman':'beech mein kuch aur bhi kaha','words':[[15+0.8*k,15.6+0.8*k,None] for k in range(6)],'applied':False}]
            save=lambda:(cache/'episode_001.json').write_text(json.dumps(data),encoding='utf-8')
            words=lambda:' '.join(c.text for c in parse(p.read_text(encoding='utf-8')))
            save()
            with patch.object(manage,'ROOT',root),patch.object(manage,'ALIGNMENT',cache),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.pace(roman,src))
                data=json.loads((cache/'episode_001.json').read_text(encoding='utf-8'))
                self.assertIn('beech mein',words())
                flat=[t for c in data['cues'] for t in c[4]]
                heard='kehte hain ke asal mein usay nahi pata tha phir woh'
                record={'replaces':[7,59],'span':[flat[6][1],flat[59][0]],'phantom':False,'reason':'kept','roman':heard,'applied':False,
                        'start':3.2,'end':30.7,'source':heard,'words':[[3.2+2.5*k,5.2+2.5*k,None] for k in range(11)]}
                # A loop the fresh transcription did not confirm stays as it is.
                data['loops']=[record];save()
                before=p.read_text(encoding='utf-8')
                self.assertFalse(manage.pace(roman,src))
                self.assertEqual(p.read_text(encoding='utf-8'),before)
                record['phantom']=True;save()
                self.assertFalse(manage.pace(roman,src))
                expected='hum ne pehle baat ki thi woh '+heard+' chala gaya apne ghar wapas'
                self.assertEqual(words(),expected)
                self.assertTrue(json.loads((cache/'episode_001.json').read_text(encoding='utf-8'))['loops'][0]['applied'])
                report=json.loads((root/'reports'/'pacing.json').read_text(encoding='utf-8'))
                self.assertEqual((report['loops_replaced']['loops'],report['missed_speech_added']['passages']),(1,0))
                paced=p.read_text(encoding='utf-8')
                self.assertFalse(manage.pace(roman,src))
                self.assertEqual(p.read_text(encoding='utf-8'),paced)
                self.assertFalse(manage.validate(roman,src))
                manage.review(roman,src)
                audio=json.loads((root/'reports'/'audio_check.json').read_text(encoding='utf-8'))
                self.assertEqual([i['status'] for i in audio['decoding_loops']['items']],['replaced'])
                # Correcting the new passage by hand is kept by later pacing.
                p.write_text(paced.replace('asal','asl'),encoding='utf-8')
                self.assertFalse(manage.pace(roman,src))
                self.assertEqual(words(),expected.replace('asal','asl'))
            # Without the cache, validation still knows the loop's words may be gone.
            with patch.object(manage,'ALIGNMENT',root/'missing'),patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.validate(roman,src))

    def test_fill_collapses_loops_and_trims_repeated_edges(self):
        align=load_align()
        timed=lambda text:[(w,float(k),k+0.5) for k,w in enumerate(text.split())]
        words=lambda items:' '.join(w for w,*_ in items)
        self.assertEqual(words(align.collapse_loops(timed('haan [UH] [UH] [UH] [UH] theek'))),'haan [UH] theek')
        self.assertEqual(words(align.collapse_loops(timed('nahi nahi nahi nahi'))),'nahi nahi nahi nahi')
        self.assertEqual(words(align.collapse_loops(timed('w- w- w- w- w- w- ok'))),'w- w- ok')
        self.assertEqual(words(align.trim_edges(timed('ki thi phir naya jumla aur'),'hum ne baat ki thi'.split(),'aur phir'.split())),'phir naya jumla')

    def test_translation_windows_and_cues(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'06-format'))
        spec=importlib.util.spec_from_file_location('translate',Path(__file__).resolve().parents[1]/'06-format'/'translate.py')
        translate=importlib.util.module_from_spec(spec)
        here=os.getcwd()
        try:spec.loader.exec_module(translate)
        finally:os.chdir(here)
        # Whole cues, at most 28 s, never across a pause of two seconds or more.
        self.assertEqual(translate.windows_for([(0,5),(5.5,10),(13,20),(20,45)]),[(0,10.2),(12.8,20.2),(19.8,45.2)])
        # A window under four seconds joins the one before it, or else the one after; short=0 keeps it apart.
        self.assertEqual(translate.windows_for([(0,5),(8,9),(12,20)]),[(0,9.2),(11.8,20.2)])
        self.assertEqual(translate.windows_for([(0,1),(4,10)]),[(0,10.2)])
        self.assertEqual(translate.windows_for([(0,5),(8,9),(12,20)],short=0),[(0,5.2),(7.8,9.2),(11.8,20.2)])
        # A second try's pieces: about ten seconds of whole cues each.
        self.assertEqual(translate.windows_for([(0,4),(4.5,8),(8.5,12),(12.5,14)],longest=10),[(0,8.2),(8.3,14.2)])
        self.assertEqual(translate.spoken('[UH] haan [breath] bhai.'),['haan','bhai.'])
        decode=lambda ids:' '.join(f'w{i}' for i in ids)
        stamp=1000  # Whisper's <|0.00|>; stamps count 0.02 s each
        self.assertEqual(translate.segments_of([stamp,5,6,stamp+100,stamp+100,7,stamp+150],(10.0,14.0),stamp,decode),
                         [(10.0,12.0,'w5 w6'),(12.0,13.0,'w7')])
        # The prompt, end of text and the model's own tags after <|30.00|> are not text.
        self.assertEqual(translate.segments_of([900,stamp,5,stamp+50,950,stamp+1501],(0.0,5.0),stamp,decode,900),[(0.0,1.0,'w5')])
        cues=translate.cues_of([(0.0,2.0,'Hello there.'),(1.5,3.0,'Hello there.'),(1.8,4.0,'How are you?')])
        self.assertEqual([(c.timing,c.text) for c in cues],[('00:00:00,000 --> 00:00:01,720','Hello there.'),('00:00:01,800 --> 00:00:04,000','How are you?')])
        # Two pieces that both heard one sentence: it is kept once, whatever its capitals and punctuation.
        self.assertEqual([c.text for c in translate.cues_of([(0.0,2.0,'Because it is not.'),(2.5,4.0,'because it is not')])],['Because it is not.'])
        # A fragment of the cue next to it goes; it keeps the earlier start. Short phrases may repeat, as people do.
        cues=translate.cues_of([(0.0,2.0,'few upsets in recent years.'),(2.0,6.0,'Few upsets in recent years against USA, Afghanistan.'),
                                (6.5,7.0,'I quit.'),(7.5,9.0,'I quit is very easy.')])
        self.assertEqual([(c.timing[:12],c.text) for c in cues],[('00:00:00,000','Few upsets in recent years against USA, Afghanistan.'),
                                                                  ('00:00:06,500','I quit.'),('00:00:07,500','I quit is very easy.')])
        # A long segment splits between sentences, which share its speech by length and skip its silences.
        self.assertEqual(translate.sentences([(0.0,10.0,'Aaaa. Bbbb.')],[(0.0,2.0),(8.0,10.0)]),[(0.0,2.0,'Aaaa.'),(8.0,10.0,'Bbbb.')])
        self.assertEqual(translate.sentences([(0.0,10.0,'Mr. Zaidi asked.')],[]),[(0.0,10.0,'Mr. Zaidi asked.')])
        self.assertEqual(translate.sentences([(0.0,5.0,'Short. Ones stay.')],[]),[(0.0,5.0,'Short. Ones stay.')])
        # A long sentence is cut at commas into parts of about 90 characters; a number's comma is not a cut.
        self.assertEqual(translate.pieces('So if she leaves you, even though she knows that she is very important to you, '
                                          'even knowing this she is listening to her friends who are taunting her, so clearly '
                                          'you are not in their priority. She owes 1,000 rupees.'),
                         ['So if she leaves you, even though she knows that she is very important to you,',
                          'even knowing this she is listening to her friends who are taunting her,',
                          'so clearly you are not in their priority.','She owes 1,000 rupees.'])
        # A runaway echo of a stutter is caught; ordinary English, and empty windows without speech, are not.
        self.assertEqual(translate.doubts('if you get so '+'over-'*40,10),['repeats'])
        self.assertEqual(translate.doubts('I love being alone. That is the best company you will ever have.',12),[])
        self.assertEqual((translate.doubts('',20),translate.doubts('',3)),(['empty'],[]))
        # English under a third of the spoken Roman words has lost speech, as when the model stops early.
        self.assertEqual(translate.doubts('Zimbabwe does not say that.',40),['thin'])
        self.assertLess(translate.score([(0,9,'We are not that kind of people at all.')],20),translate.score([(0,9,'We are')],20))
        # A thin try beats an invented loop, however many words the loop has.
        self.assertLess(translate.score([(0,9,'We are fine.')],30),translate.score([(0,9,' '.join(['Good bye.']*40))],30))
        # Stock phrases go where nothing like them was said nearby; a sentence looping four times or more is kept once.
        roman=[((0,3),'aap ka bohat shukriya'),((20,23),'phir woh chala gaya'),((40,45),'allah hafiz')]
        self.assertEqual(translate.clean([(0,3,'Thank you very much.'),(20,23,'He left. Thank you.'),(30,32,'Peace be upon you.'),
                                          (40,45,' '.join(['Good bye.']*6)),(50,55,"It's okay. It's okay. It's okay."),
                                          (60,65,'see you do not send remittances to the country,')],roman),
                         [(0,3,'Thank you very much.'),(20,23,'He left.'),(40,45,'Good bye.'),(50,55,"It's okay. It's okay. It's okay."),
                          (60,65,'see you do not send remittances to the country,')])
        # Run-together stock phrases go too, and "like" as a filler word is no reason to keep "Please like…".
        roman=[((0,6),'phir like obviously she will miss her family'),((20,26),'video ko like kariye aur subscribe kariye')]
        self.assertEqual(translate.clean([(0,6,'Please like and subscribe..Thankyou. Obviously she will miss her family.'),
                                          (20,26,'Please like and subscribe.'),(30,32,'The U.S.A. is far.')],roman),
                         [(0,6,'Obviously she will miss her family.'),(20,26,'Please like and subscribe.'),(30,32,'The U.S.A. is far.')])
        # Repair keeps the English of windows the file was made with, by start; joined windows go again.
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path=Path(d)/'episode_001.srt'
            path.write_text('1\n00:00:00,000 --> 00:00:04,000\nHello.\n\n2\n00:00:07,800 --> 00:00:09,000\nThank you very much.\n\n'
                            '3\n00:00:11,800 --> 00:00:19,000\nNext part.\n\n',encoding='utf-8')
            spans=[(0,5),(8,9),(12,20)]
            self.assertEqual(translate.existing(path,translate.windows_for(spans),spans),{1:[(11.8,19.0,'Next part.')]})

    def test_review_finds_repetition_loops(self):
        self.assertEqual(manage.loops('a b b b b c'.split()),[(1,4,'b')])
        self.assertEqual(manage.loops('x y x y x y x y z'.split()),[(0,4,'x y')])
        self.assertEqual(manage.loops('nahi nahi nahi theek'.split()),[])

    def test_format_refuses_without_current_alignment(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);source=root/'source';roman=root/'roman'
            source.mkdir();roman.mkdir()
            (source/'episode_001.srt').write_text(SOURCE_CUES,encoding='utf-8')
            (roman/'episode_001.srt').write_text(ROMAN_CUES,encoding='utf-8')
            with patch.object(manage,'ALIGNMENT',root/'alignment'),patch.object(manage,'REPORTS',root/'reports'):
                with self.assertRaises(ValueError):manage.pace(roman,source)
                self.assertTrue(manage.pace(roman,source,check=True))

if __name__=='__main__':unittest.main()
