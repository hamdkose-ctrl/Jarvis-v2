"""Kota sayacı: her gerçek sağlayıcı denemesi kaydedilir, metin yazılmaz, komut modele gitmez.

Model ve ağ taklittir; sayılan çağrılar gerçek Gemini/Groq kotası değildir.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import llm, usage_meter


class _Chat:
    def __init__(self, model, fail):
        self.model, self.fail = model, fail

    def send_message(self, prompt):
        if self.model in self.fail:
            raise llm.errors.ClientError(429, {'error': {'message': 'Quota exceeded PerMinute', 'status': 'RESOURCE_EXHAUSTED'}})
        return SimpleNamespace(text='cevap metni')


def ask_from_router():
    # Kaynak tespiti: çağrıyı başlatan Jarvis fonksiyonu kaydedilmeli.
    return llm._send_provider('gemini', 'gizli soru metni', 'sistem metni', 2000, None)


class UsageMeterTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        p = patch.object(usage_meter, '_dir', return_value=self.dir); p.start(); self.addCleanup(p.stop)
        self.user = 'alice'
        self.fail = {'lite'}
        cli = SimpleNamespace(chats=SimpleNamespace(create=lambda model, config, history: _Chat(model, self.fail)))
        for target, name, kwargs in [
            (llm, '_cli', {'return_value': cli}), (llm, 'provider', {'return_value': 'gemini'}),
            (llm, 'model_names', {'return_value': ['lite', 'flash']}), (llm, 'user_groq_key', {'return_value': ''}),
            (llm, 'current_user', {'side_effect': lambda: self.user}),
            (llm, '_rate_limited', {'new': {}}), (llm, '_fallback_states', {'new': {}}),
            (llm.time, 'sleep', {'return_value': None}),
        ]:
            p = patch.object(target, name, **kwargs); p.start(); self.addCleanup(p.stop)
        p = patch.object(llm, 'privacy', SimpleNamespace(mode=lambda: 'normal', redact=lambda t, **_: t))
        p.start(); self.addCleanup(p.stop)
        llm.take_route(); self.addCleanup(llm.take_route)

    def lines(self, user='alice'):
        path = self.dir / (user + '.jsonl')
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_every_attempt_is_recorded_with_source_and_no_text(self):
        self.assertEqual(ask_from_router(), 'cevap metni')
        rows = self.lines()
        self.assertEqual([(r['p'], r['m'], r['r']) for r in rows], [('gemini', 'lite', '429'), ('gemini', 'flash', 'ok')])
        self.assertTrue(all(r['s'] == 'test_usage_meter.ask_from_router' for r in rows), rows)
        self.assertEqual(rows[0]['i'], len('gizli soru metni') + len('sistem metni'))
        self.assertEqual(rows[1]['o'], len('cevap metni'))
        raw = (self.dir / 'alice.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('gizli soru', raw)
        self.assertNotIn('cevap metni', raw)

    def test_users_are_counted_separately(self):
        ask_from_router()
        self.user = 'bob'
        self.fail = set()
        ask_from_router()
        self.assertEqual(len(self.lines('alice')), 2)
        self.assertEqual([r['m'] for r in self.lines('bob')], ['lite'])

    def test_groq_and_ollama_attempts_are_recorded(self):
        ok = Mock(status_code=200, json=lambda: {'choices': [{'message': {'content': 'tamam'}}]})
        limited = Mock(status_code=429, headers={}, text='Rate limit reached')
        with patch.object(llm, 'user_groq_key', return_value='k'), patch.object(llm, 'groq_model', return_value='g1'), \
                patch.object(llm, 'GROQ_MODELS', ['g2']), \
                patch('modules.smart_router.settings', return_value={'cloud_free_confirmed': True}), \
                patch.object(llm.requests, 'post', side_effect=[limited, ok]):
            self.assertEqual(llm._groq([{'role': 'user', 'content': 'soru'}], 'sistem', 50), 'tamam')
        with patch.object(llm, 'ollama_models', return_value=['meter-local']), \
                patch.object(llm.requests, 'post', side_effect=llm.requests.ConnectionError('yok')):
            with self.assertRaises(llm.LocalModelError):
                llm._ollama([{'role': 'user', 'content': 'soru'}], '', 50)
        self.assertEqual([(r['p'], r['m'], r['r']) for r in self.lines()],
                         [('groq', 'g1', '429'), ('groq', 'g2', 'ok'), ('ollama', 'meter-local', 'baglanti')])

    def test_ollama_success_is_recorded_after_reply_is_decoded(self):
        def bad_json():
            raise ValueError('geçersiz JSON')
        good = Mock(status_code=200, content=b'x', json=lambda: {'message': {'content': 'merhaba'}})
        broken = Mock(status_code=200, content=b'x', json=bad_json)
        msgs = [{'role': 'user', 'content': 'soru'}]
        with patch.object(llm, 'ollama_models', return_value=['meter-local']), \
             patch.object(llm.requests, 'post', side_effect=[good, broken]):
            self.assertEqual(llm._ollama(msgs, '', 50), 'merhaba')
            with self.assertRaises(llm.LocalModelError):
                llm._ollama(msgs, '', 50)     # eskiden bozuk 200 yanıtı "ok" yazılıp ValueError fırlıyordu
        rows = [(r['r'], r['o']) for r in self.lines()]
        self.assertEqual(rows, [('ok', len('merhaba')), ('bozuk', 0)])

    def test_summary_command_answers_without_model(self):
        ask_from_router()
        with patch.object(llm, 'ask', side_effect=AssertionError('model called')):
            for command in ('kota durumu', 'Kota Durumu.', 'Jarvis, kota raporu', 'kota sayacı', 'bugün ne kadar kota harcadım?'):
                with self.subTest(command=command):
                    text = usage_meter.handle('alice', command)
                    self.assertIn('toplam 2 çağrı', text)
                    self.assertIn('1 kez 429', text)
                    self.assertIn('test_usage_meter.ask_from_router: 2 çağrı', text)
        self.assertIsNone(usage_meter.handle('alice', 'kota nedir'))
        self.assertIn('kayıtlı model çağrısı yok', usage_meter.handle('carol', 'kota durumu'))

    def test_meter_failure_never_breaks_the_call(self):
        with patch.object(usage_meter, '_dir', side_effect=OSError('disk dolu')):
            self.assertEqual(ask_from_router(), 'cevap metni')

    def test_old_day_rows_are_not_counted_today(self):
        (self.dir / 'alice.jsonl').write_text(json.dumps({'t': '2020-01-01T10:00:00+03:00', 'p': 'gemini', 'm': 'x',
                                                          's': 'a.b', 'i': 1, 'o': 1, 'r': 'ok'}) + '\nbozuk satır\n',
                                              encoding='utf-8')
        self.assertIn('kayıtlı model çağrısı yok', usage_meter.summary('alice'))
        self.assertIn('toplam 1 çağrı', usage_meter.summary('alice', '2020-01-01'))


if __name__ == '__main__':
    unittest.main()
