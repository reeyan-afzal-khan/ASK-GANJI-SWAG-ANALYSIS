import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'/'.shared'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build_data

TEST_TEMP=Path(__file__).resolve().parents[2]/'.cache/test-tmp'
TEST_TEMP.mkdir(parents=True,exist_ok=True)
CONFIG=json.loads(build_data.CONFIG.read_text(encoding='utf-8'))

INDEX='''# Index

<details open>
<summary><strong>Episode 001</strong></summary>

1. [Should I move to Canada for my masters?](https://youtu.be/abc123?list=PL&t=10)
2. [My wife and my mother fight](https://www.youtube.com/watch?v=abc123&t=1m5s)
3. [Untimed question]()

</details>
'''
ROMAN=('1\n00:00:00,000 --> 00:00:05,000\nWelcome [UH] to the show\n\n'
       '2\n00:00:10,000 --> 00:00:20,000\nCanada visa aur masters ka sawal [laughter] I am a twenty-two year old from Lahore\n\n'
       '3\n00:01:05,000 --> 00:01:30,000\nshaadi ke baad wife aur ammi\n\n')
SOURCE=('1\n00:00:00,000 --> 00:00:05,000\nWelcome [UH] to the show\n\n'
        '2\n00:00:10,000 --> 00:00:20,000\nCanada visa اور masters کا سوال [laughter] I am a twenty-two year old from Lahore\n\n'
        '3\n00:01:05,000 --> 00:01:30,000\nشادی کے بعد wife اور امی\n\n')

ENGLISH=('1\n00:00:00,500 --> 00:00:05,000\nWelcome to the show.\n\n'
         '2\n00:00:10,500 --> 00:00:20,000\nA question about a Canada visa and a masters.\n\n'
         '3\n00:01:06,000 --> 00:01:30,000\nAfter marriage my wife and my mother fight. I am 31 years old, living in Toronto.\n\n')

def build_fixture(root,labels=None,roman_text=ROMAN,alignment=None,english=None):
    roman=root/'roman';source=root/'source';out=root/'data'
    roman.mkdir();source.mkdir()
    (roman/'episode_001.srt').write_text(roman_text,encoding='utf-8')
    (source/'episode_001.srt').write_text(SOURCE,encoding='utf-8')
    (root/'index.md').write_text(INDEX,encoding='utf-8')
    labels_path=scripts=None
    if labels is not None:
        labels_path=root/'labels.json';labels_path.write_text(json.dumps(labels),encoding='utf-8')
    if english is not None:
        (root/'english').mkdir();(root/'english'/'episode_001.srt').write_text(english,encoding='utf-8')
        scripts={'english':root/'english'}
    with contextlib.redirect_stdout(io.StringIO()):
        return build_data.build(roman,source,root/'index.md',out,labels_path,alignment,scripts),out

class AppDataTests(unittest.TestCase):
    def test_index_links_and_timestamps(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            path=Path(d)/'index.md';path.write_text(INDEX,encoding='utf-8')
            items=build_data.read_index(path)[1]
        self.assertEqual([(video,start) for _,video,start in items],[('abc123',10),('abc123',65),(None,None)])

    def test_keyword_fallback_prefers_title_terms(self):
        rules=build_data.category_rules(CONFIG)
        self.assertEqual(build_data.classify(rules,'Should I move to Canada?')[0],'abroad')
        self.assertEqual(build_data.classify(rules,'My wife wants a divorce','visa canada dubai passport embassy')[0],'love')
        self.assertEqual(build_data.classify(rules,'Nostalgia','')[0],'other')

    def test_stated_ages(self):
        self.assertEqual(build_data.stated_age('16-year-old boy got beaten'),16)
        self.assertEqual(build_data.stated_age('I\N{RIGHT SINGLE QUOTATION MARK}m 22, making 100k a month'),22)
        self.assertEqual(build_data.stated_age('A title','Hi, I am a twenty-four year old female'),24)
        self.assertEqual(build_data.stated_age('25 yo girl from US'),25)
        self.assertEqual(build_data.stated_age('','I mean, I\'m thirty six and a housewife; thirteen year old boys are'),36)
        self.assertIsNone(build_data.stated_age('Married for twenty years','I am 100% sure, 40 job rejections'))

    def test_translated_ages_are_the_askers_own(self):
        self.assertEqual(build_data.own_age('Salam. I am 24 years old and my sister is 30.'),24)
        self.assertEqual(build_data.own_age('I\N{RIGHT SINGLE QUOTATION MARK}m a 24-year-old engineer'),24)
        self.assertEqual(build_data.own_age('Hope you are well, my age is twenty-one.'),21)
        self.assertEqual(build_data.own_age('I\'m only twenty one, born in Karachi'),21)
        # Someone else's age, a past one, or a number that is not an age.
        self.assertIsNone(build_data.own_age('My father is 56 years old and I have two girls, age 13 and 9.'))
        self.assertIsNone(build_data.own_age('I was 15 years old when it started'))
        self.assertIsNone(build_data.own_age('I am 30 minutes late and I am 100 percent sure'))

    def test_answer_words_are_what_sets_a_subject_apart(self):
        answers=([('love.rishta',build_data.collections.Counter({'marriage':3,'proposal':3,'family':1,'scams':1}))]*20
                 +[('career.jobs',build_data.collections.Counter({'jobs':2,'job':3,'family':1,'scam':2}))]*20
                 +[('other.misc',build_data.collections.Counter({'chicken':2,'family':1}))]*15)
        categories=[{'id':'love','subcategories':[{'id':'love.rishta'}]},{'id':'career','subcategories':[{'id':'career.jobs'}]},
                    {'id':'other','subcategories':[{'id':'other.misc'}]}]
        result=build_data.answer_words(answers,categories)
        groups=result['groups']
        self.assertEqual(result['answers'],55)
        # Other has no subject to describe; a word used everywhere (family) never stands out.
        self.assertEqual(sorted(groups),['career','career.jobs','love','love.rishta'])
        self.assertEqual([w[0] for w in groups['love']['words']][:2],['marriage','proposal'])
        self.assertNotIn('family',[w[0] for g in groups.values() for w in g['words']])
        # Plurals fold into the more used form, and the counts are [answers using it here, elsewhere, uses here].
        self.assertEqual(groups['career']['words'][0],['job',20,0,100])
        self.assertEqual((groups['love']['answers'],groups['love']['versus']),(20,35))

    def test_places_respect_case_for_short_names(self):
        rules=build_data.place_rules(CONFIG)
        names=lambda text:[CONFIG['places'][i]['name'] for i in build_data.mentioned_places(rules,text)]
        self.assertEqual(names('Moving to Dubai after living in New Zealand?'),['Dubai & UAE','New Zealand'])
        self.assertEqual(names('How to apply for US visa'),['USA'])
        self.assertEqual(names('Tell us about it'),[])

    def test_cities_are_named_apart_from_their_country(self):
        rules=build_data.place_rules(CONFIG,'cities')
        names=lambda text:[CONFIG['cities'][i]['name'] for i in build_data.mentioned_places(rules,text)]
        self.assertEqual(names('From Karachi, moving to Toronto in Canada'),['Karachi','Toronto'])
        self.assertEqual(names('Life in Bombay and Pindi'),['Rawalpindi','Mumbai'])
        self.assertEqual(names('Moving to Canada'),[])

    def test_build_with_keyword_fallback(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            data,out=build_fixture(Path(d))
            self.assertTrue((out/'summary.js').read_text(encoding='utf-8').startswith('window.GANJI_DATA = {'))
            transcript=(out/'transcripts'/'episode_001.js').read_text(encoding='utf-8')
        self.assertTrue(transcript.startswith('GANJI_TRANSCRIPT(1,[[0.0,"Welcome [UH] to the show"]'))
        episode=data['episodes'][0];questions=data['questions']
        self.assertEqual((episode['video'],episode['duration'],episode['words'],episode['english']),('abc123',90,25,17))
        self.assertEqual(episode['events'],{'laughter':1,'uh':1})
        self.assertEqual([q['length'] for q in questions],[55,25,None])
        self.assertEqual([q['sub'] for q in questions],['abroad.auto','love.auto','other.misc'])
        self.assertEqual((questions[0]['age'],[data['places'][i]['name'] for i in questions[0]['places']]),(22,['Lahore','Canada']))
        self.assertEqual([data['cities'][i]['name'] for i in questions[0]['cities']],['Lahore'])
        self.assertEqual(data['quality']['unlabelled'],[1])
        self.assertIn('abroad.auto',[s['id'] for c in data['categories'] for s in c['subcategories']])

    def test_build_reads_the_english_translation(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            data,out=build_fixture(Path(d),english=ENGLISH)
            transcript=(out/'transcripts-english'/'episode_001.js').read_text(encoding='utf-8')
        self.assertTrue(transcript.endswith(',"english");\n'))
        self.assertEqual(data['meta']['scripts'],['roman','english'])
        first,second,untimed=data['questions']
        self.assertEqual(first['excerptEn'],'A question about a Canada visa and a masters.')
        # The Roman opening gives the first age; the second is only said, in the first person, in the translation.
        self.assertEqual((first['age'],second['age']),(22,31))
        self.assertEqual([data['cities'][i]['name'] for i in second['cities']],['Toronto'])
        self.assertEqual((untimed['excerptEn'],untimed['age']),('',None))
        self.assertEqual(data['answerWords'],{'answers':2,'groups':{}})
        # Without the translation nothing of it is added.
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            data,_=build_fixture(Path(d))
        self.assertNotIn('excerptEn',data['questions'][0])
        self.assertIsNone(data['answerWords'])

    def test_english_share_survives_repaced_roman_cues(self):
        paced=ROMAN.replace('2\n00:00:10,000 --> 00:00:20,000\nCanada visa aur masters ka sawal [laughter] I am a twenty-two year old from Lahore\n\n3\n',
                            '2\n00:00:10,000 --> 00:00:14,000\nCanada visa aur masters ka sawal\n\n3\n00:00:14,080 --> 00:00:20,000\n[laughter] I am a twenty-two year old from Lahore\n\n4\n')
        self.assertNotEqual(paced,ROMAN)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            data,_=build_fixture(Path(d),roman_text=paced)
        episode=data['episodes'][0]
        self.assertEqual((episode['cues'],episode['words'],episode['english']),(4,25,17))
        self.assertEqual(data['quality']['unaligned'],[])

    def test_english_share_comes_from_the_cache_once_the_original_is_gone(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);roman=root/'roman';cache=root/'alignment'
            roman.mkdir();cache.mkdir()
            (roman/'episode_001.srt').write_text(ROMAN,encoding='utf-8')
            (root/'index.md').write_text(INDEX,encoding='utf-8')
            # The cache keeps the original cues as [start, end, text, Roman text, word times].
            originals=[[*build_data.span(c),c.text,'',[]] for c in build_data.parse(SOURCE)]
            (cache/'episode_001.json').write_text(json.dumps({'cues':originals}),encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                data=build_data.build(roman,root/'deleted',root/'index.md',root/'data',None,cache)
        self.assertEqual(data['episodes'][0]['english'],17)

    def test_added_passages_count_their_english(self):
        filled=ROMAN.replace('3\n00:01:05,000','3\n00:00:30,000 --> 00:00:40,000\nphir masters application submit ki\n\n4\n00:01:05,000')
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);cache=root/'alignment';cache.mkdir()
            (cache/'episode_001.json').write_text(json.dumps({'supplements':[{'source':'پھر masters application submit کی','applied':True}]}),encoding='utf-8')
            data,_=build_fixture(root,roman_text=filled,alignment=cache)
        episode=data['episodes'][0]
        self.assertEqual((episode['words'],episode['english']),(30,20))
        # A replaced loop's passage counts instead of the passage it covers.
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);cache=root/'alignment';cache.mkdir()
            (cache/'episode_001.json').write_text(json.dumps({
                'supplements':[{'source':'پھر masters ki baat','start':31.0,'end':33.0,'applied':True}],
                'loops':[{'source':'پھر masters application submit کی','span':[29.0,41.0],'phantom':True,'applied':True}]}),encoding='utf-8')
            data,_=build_fixture(root,roman_text=filled,alignment=cache)
        episode=data['episodes'][0]
        self.assertEqual((episode['words'],episode['english']),(30,20))

    def test_build_uses_curated_labels_and_rejects_unknown_codes(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            data,_=build_fixture(Path(d),{'1':['edu.abroad','family.inlaws love.marriage','other.misc']})
        self.assertEqual([(q['sub'],q['also']) for q in data['questions']],[('edu.abroad',[]),('family.inlaws',['love.marriage']),('other.misc',[])])
        self.assertEqual(data['quality']['unlabelled'],[])
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            with self.assertRaises(ValueError):build_fixture(Path(d),{'1':['edu.nonsense','love.rishta','other.misc']})

    def test_stale_transcripts_are_removed(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);(root/'data'/'transcripts').mkdir(parents=True)
            (root/'data'/'transcripts'/'episode_999.js').write_text('stale',encoding='utf-8')
            _,out=build_fixture(root)
            self.assertEqual([p.name for p in (out/'transcripts').iterdir()],['episode_001.js'])

    def test_theme_comes_from_skins(self):
        css=build_data.theme_css()
        self.assertEqual(css,build_data.THEME.read_text(encoding='utf-8'),'app/assets/theme.css is stale: run bash app/run.sh')
        self.assertIn('--acc: #FB4D3A;',css)
        self.assertIn('@media (prefers-color-scheme: dark)',css)
        self.assertIn(':root[data-theme="dark"] {',css)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            (Path(d)/'broken.json').write_text(json.dumps({'name':'Broken','dark':False,'tokens':{'acc':'#000000'}}),encoding='utf-8')
            with self.assertRaises(ValueError):build_data.theme_css(d)

    def test_preview_server_stays_inside_app(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),build_data.AppHandler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            def status(path):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                connection.request('GET',path);response=connection.getresponse();response.read();connection.close()
                return response.status
            self.assertEqual(status('/'),200)
            self.assertEqual(status('/assets/app.js'),200)
            self.assertEqual(status('/../scripts/.shared/paths.py'),404)
            self.assertEqual(status('/%2e%2e/.gitignore'),404)
        finally:
            server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
