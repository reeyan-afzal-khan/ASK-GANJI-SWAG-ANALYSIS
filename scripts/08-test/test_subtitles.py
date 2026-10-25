import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.shared'))
from subtitles import parse, render, select_files
import manage_subtitles as manage

TEST_TEMP=Path(__file__).resolve().parents[2]/'.cache/test-tmp'
TEST_TEMP.mkdir(parents=True,exist_ok=True)

SAMPLE='1\n00:00:00,000 --> 00:00:02,000\nHello\nworld\n\n2\n00:00:02,000 --> 00:00:03,000\nI am here.\n\n'

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

    def test_formatter_backs_up_exact_original(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);folder=root/'roman';folder.mkdir()
            p=folder/'episode_001.srt';p.write_text(SAMPLE)
            with patch.object(manage,'ROOT',root):
                manage.single_line(folder)
                manage.single_line(folder)
            self.assertEqual(len(list((root/'.cache/backups').glob('*.zip'))),1)
            self.assertEqual(p.read_text(),render(parse(SAMPLE)))

    def test_validator_catches_changed_english_and_timing(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as d:
            root=Path(d);source=root/'source';out=root/'out'
            source.mkdir();out.mkdir()
            (source/'episode_001.srt').write_text(SAMPLE)
            p=out/'episode_001.srt';p.write_text(render(parse(SAMPLE)))
            with patch.object(manage,'REPORTS',root/'reports'):
                self.assertFalse(manage.validate(out,source))
                p.write_text(render(parse(SAMPLE)).replace('Hello','Goodbye'))
                self.assertTrue(manage.validate(out,source))
                p.write_text(render(parse(SAMPLE)).replace('00:00:02,000','00:00:02,100'))
                self.assertTrue(manage.validate(out,source))

if __name__=='__main__':unittest.main()
