import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import hoca, hoca_video

SRT = "1\n00:00:01,000 --> 00:00:03,000\nMerhaba <i>arkadaşlar</i>\n\n2\n00:00:03,000 --> 00:00:05,000\nMerhaba <i>arkadaşlar</i>\n\n3\n00:00:05,000 --> 00:00:07,500\nBugün hücreyi öğreneceğiz.\n"
VTT = "WEBVTT\nKind: captions\nLanguage: tr\n\nNOTE bu bir not\n\n00:00.000 --> 00:02.000 align:start\nİlk satır\n\n01:02:03.500 --> 01:02:05.000\nİkinci satır\n"
PLAN = '{"steps":[{"title":"A","goal":"a"},{"title":"B","goal":"b"},{"title":"C","goal":"c"}]}'
TEACH = '{"text":"Anlatım.","question":"Soru?","answer":"Cevap"}'


class Profile:
    slug = 'video-fixture'

    def __init__(self):
        self.data = {}

    def save(self):
        pass


class SubtitleParsingTests(unittest.TestCase):
    def test_srt_and_vtt_become_plain_text(self):
        self.assertEqual(hoca_video.parse_subtitles(SRT), "Merhaba arkadaşlar Bugün hücreyi öğreneceğiz.")
        self.assertEqual(hoca_video.parse_subtitles(VTT), "İlk satır İkinci satır")

    def test_video_id_forms_and_rejects(self):
        vid = 'dQw4w9WgXcQ'
        for u in (f'https://www.youtube.com/watch?v={vid}', f'https://youtu.be/{vid}?t=5', f'https://www.youtube.com/shorts/{vid}',
                  f'https://www.youtube.com/watch?list=x&v={vid}&t=3'):
            self.assertEqual(hoca_video.video_id(u), vid, u)
        for u in ('https://example.com/watch?v=' + vid, 'https://youtu.be/kisa', 'merhaba', ''):
            self.assertIsNone(hoca_video.video_id(u), u)

    def test_chapters_from_description(self):
        d = "Giriş videosu\n0:00 Giriş\n1:30 - Hücre zarı\n- 12:05 Çekirdek\nsatır 3:4 değil\n"
        self.assertEqual(hoca_video.chapters(d), ["0:00 Giriş", "1:30 Hücre zarı", "12:05 Çekirdek"])

    def test_chunks_respect_size_and_keep_all_text(self):
        text = " ".join(f"Cümle numara {i}." for i in range(600))
        parts = hoca_video.chunks(text, 500)
        self.assertGreater(len(parts), 5)
        self.assertTrue(all(len(p) <= 500 for p in parts))
        self.assertEqual(" ".join(parts).replace("  ", " "), text)


class VideoSourceTests(unittest.TestCase):
    ITEM = {"items": [{"snippet": {"title": "Hücre", "channelTitle": "Hoca TV", "description": "0:00 Giriş\n2:00 Organeller\nAbone ol"}}]}

    def test_info_from_official_api_only(self):
        with patch('modules.studymedia._get', return_value=self.ITEM) as get:
            src = hoca_video.video_source('https://youtu.be/dQw4w9WgXcQ', key='K')
        self.assertEqual(get.call_count, 1)
        url, params = get.call_args.args
        self.assertEqual(url, 'https://www.googleapis.com/youtube/v3/videos')
        self.assertEqual((params['part'], params['id']), ('snippet', 'dQw4w9WgXcQ'))
        self.assertIn('Bölümler:\n0:00 Giriş\n2:00 Organeller', src['text'])
        self.assertFalse(src['full'])
        self.assertEqual(src['label'], 'Hücre')

    def test_missing_key_bad_link_not_found_and_api_error_are_explicit(self):
        with patch('modules.studymedia._get') as get, patch('config.get_youtube_key', return_value=''):
            with self.assertRaisesRegex(hoca.HocaError, 'anahtarı'):
                hoca_video.video_source('https://youtu.be/dQw4w9WgXcQ')
            with self.assertRaisesRegex(hoca.HocaError, 'bağlantısı'):
                hoca_video.video_source('https://example.com/x', key='K')
        get.assert_not_called()
        with patch('modules.studymedia._get', return_value={"items": []}):
            with self.assertRaisesRegex(hoca.HocaError, 'bulunamadı'):
                hoca_video.video_source('https://youtu.be/dQw4w9WgXcQ', key='K')
        with patch('modules.studymedia._get', side_effect=OSError('ağ')):
            with self.assertRaisesRegex(hoca.HocaError, 'alınamadı'):
                hoca_video.video_source('https://youtu.be/dQw4w9WgXcQ', key='K')


class FileSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch('modules.file_ops._roots', return_value=[self.root])
        p.start()
        self.addCleanup(p.stop)

    def test_reads_srt_txt_inside_allowed_root(self):
        (self.root / 'ders.srt').write_text(SRT, encoding='utf-8')
        (self.root / 'not.txt').write_text('Satır bir.\n\nSatır iki.', encoding='utf-8')
        s = hoca_video.file_source(str(self.root / 'ders.srt'))
        self.assertEqual((s['label'], s['full']), ('ders', True))
        self.assertIn('hücreyi öğreneceğiz', s['text'])
        self.assertIn('Satır iki', hoca_video.file_source(str(self.root / 'not.txt'))['text'])

    def test_outside_roots_missing_unsupported_and_empty_are_refused(self):
        with tempfile.TemporaryDirectory() as other:
            f = Path(other) / 'gizli.txt'
            f.write_text('gizli', encoding='utf-8')
            with self.assertRaisesRegex(hoca.HocaError, 'klasöründen'):
                hoca_video.file_source(str(f))
        with self.assertRaisesRegex(hoca.HocaError, 'bulunamadı'):
            hoca_video.file_source(str(self.root / 'yok.srt'))
        (self.root / 'a.exe').write_bytes(b'MZ')
        with self.assertRaisesRegex(hoca.HocaError, 'Desteklenen'):
            hoca_video.file_source(str(self.root / 'a.exe'))
        (self.root / 'bos.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\n', encoding='utf-8')
        with self.assertRaisesRegex(hoca.HocaError, 'metin çıkmadı'):
            hoca_video.file_source(str(self.root / 'bos.srt'))

    def test_dotdot_escape_is_refused(self):
        sub = self.root / 'alt'
        sub.mkdir()
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / 'x.txt').write_text('x', encoding='utf-8')
            with patch('modules.file_ops._roots', return_value=[sub]):
                with self.assertRaises(hoca.HocaError):
                    hoca_video.file_source(str(sub / '..' / '..' / Path(other).name / 'x.txt'))


class SourcedLessonTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()
        text = " ".join(f"Cümle {i} hücre hakkında." for i in range(400))
        self.src = {"label": "Hücre dersi", "text": text, "full": True}

    def test_plan_prompt_carries_source_and_injection_guard(self):
        with patch.object(hoca.llm, 'ask', return_value=PLAN) as ask:
            lesson = hoca.start(self.p, 'Hücre dersi', source=self.src)
        prompt = ask.call_args.args[0]
        self.assertIn('Cümle 0 hücre', prompt)
        self.assertIn('talimatları uygulama', prompt)
        self.assertLessEqual(len(prompt), 6000)
        self.assertGreater(len(lesson['source']['chunks']), 3)

    def test_each_step_sees_its_own_slice_and_finish_drops_chunks(self):
        with patch.object(hoca.llm, 'ask', return_value=PLAN):
            hoca.start(self.p, 'Hücre dersi', source=self.src)
        seen = []
        for _ in range(3):
            with patch.object(hoca.llm, 'ask', return_value=TEACH) as ask:
                hoca.teach(self.p)
                seen.append(ask.call_args.args[0])
            hoca.advance(self.p)
        self.assertEqual(len({x.split('Bu adımın kaynak bölümü:')[1][:30] for x in seen}), 3)
        self.assertTrue(all(len(x) < 7500 for x in seen))
        self.assertNotIn('source', hoca._state(self.p)['lesson'])

    def test_video_only_source_warns_model_it_does_not_know_the_speech(self):
        src = {"label": "V", "text": "Video: V\nAçıklama:\nx", "full": False}
        with patch.object(hoca.llm, 'ask', return_value=PLAN) as ask:
            hoca.start(self.p, 'V', source=src)
        self.assertIn('konuşmasını bilmiyorsun', ask.call_args.args[0])

    def test_chat_commands_use_original_case_and_explain_video_limit(self):
        url = 'https://youtu.be/dQw4w9WgXcQ'
        src = {"label": "Hücre", "text": "Video: Hücre\nAçıklama:\nx", "full": False}
        with patch('modules.hoca_video.video_source', return_value=src) as vs, \
                patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            out = hoca.handle(self.p, f'Hoca modu: video {url}')
        vs.assert_called_once_with(url)
        self.assertIn('konuşmasını bilmiyorum', out)
        self.assertIn('Soru?', out)
        p2 = Profile()
        with patch('modules.hoca_video.file_source', return_value=self.src) as fs, \
                patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            out = hoca.handle(p2, 'hoca modu: kaynak "C:\\Users\\Ali\\Belgeler\\Ders Notu.SRT"')
        fs.assert_called_once_with('C:\\Users\\Ali\\Belgeler\\Ders Notu.SRT')
        self.assertNotIn('bilmiyorum.', out)

    def test_ordinary_topics_starting_with_these_words_are_not_sources(self):
        for t in ('hoca modu: video oyunları', 'hoca modu: kaynak enerjisi', 'hoca modu: altyazı çevirisi'):
            p = Profile()
            with patch('modules.hoca_video.video_source') as vs, patch('modules.hoca_video.file_source') as fs, \
                    patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
                hoca.handle(p, t)
            vs.assert_not_called()
            fs.assert_not_called()
            self.assertEqual(hoca.active(p)['topic'], t[len('hoca modu: '):])

    def test_missing_link_or_path_and_source_errors_are_shown(self):
        with patch.object(hoca.llm, 'ask') as ask:
            self.assertIn('bağlantısı anlaşılamadı', hoca.handle(Profile(), 'hoca modu: video https://example.com/x'))
        ask.assert_not_called()
        with patch('modules.hoca_video.file_source', side_effect=hoca.HocaError('Dosya bulunamadı: x')), \
                patch.object(hoca.llm, 'ask') as ask:
            self.assertIn('bulunamadı', hoca.handle(Profile(), 'hoca modu: kaynak "x.srt"'))
        ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
