import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import pc_deneme_kaydi as kayit


ITEMS = [
    {'id': 'A1', 'group': 'A', 'text': 'Birinci'},
    {'id': 'A2', 'group': 'A', 'text': 'İkinci'},
]


class FakeInput:
    def __init__(self, values):
        self.values = iter(values)
        self.prompts = []

    def __call__(self, prompt=''):
        self.prompts.append(prompt)
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value


class PcDenemeKaydiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'sonuc.json'

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_answers_are_saved_immediately(self):
        inputs = FakeInput(['c', 'b', 'gerçek hata'])
        kayit.run(ITEMS, inputs, lambda *_: None, self.path)
        self.assertEqual(self.read()['results'], {
            'A1': {'status': 'çalıştı', 'note': ''},
            'A2': {'status': 'bozuk', 'note': 'gerçek hata'},
        })

    def test_interrupted_session_resumes_and_skips_answered_items(self):
        first = FakeInput(['c', KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):
            kayit.run(ITEMS, first, lambda *_: None, self.path)
        self.assertEqual(set(self.read()['results']), {'A1'})

        printed = []
        second = FakeInput(['y', 'sonra düzeldi'])
        kayit.run(ITEMS, second, printed.append, self.path)
        self.assertFalse(any(line.startswith('A1 ') for line in printed))
        self.assertTrue(any(line.startswith('A2 ') for line in printed))
        self.assertEqual(self.read()['results']['A2']['status'], 'yarım')

    def test_bastan_flag_resets_existing_answers(self):
        kayit.run([ITEMS[0]], FakeInput(['c']), lambda *_: None, self.path)
        with patch.object(kayit, 'ITEMS', [ITEMS[1]]), patch('builtins.input', side_effect=['a']), patch('builtins.print'):
            self.assertEqual(kayit.main(['--bastan', str(self.path)]), 0)
        self.assertEqual(self.read()['results'], {'A2': {'status': 'atlandı', 'note': ''}})

    def test_invalid_answer_is_asked_again(self):
        printed = []
        inputs = FakeInput(['x', 'C'])
        kayit.run([ITEMS[0]], inputs, printed.append, self.path)
        self.assertEqual(self.read()['results']['A1']['status'], 'çalıştı')
        self.assertIn('Geçersiz cevap. c, y, b veya a gir.', printed)
        self.assertEqual(len(inputs.prompts), 2)

    def test_note_is_masked_then_capped_to_300_characters(self):
        note = ('mail alice@example.org telefon 0532 123 45 67 token sk-' + 'a' * 40 + ' ' + 'x' * 500)
        kayit.run([ITEMS[0]], FakeInput(['b', note]), lambda *_: None, self.path)
        saved = self.read()['results']['A1']['note']
        self.assertLessEqual(len(saved), 300)
        self.assertNotIn('alice@example.org', saved)
        self.assertNotIn('0532 123 45 67', saved)
        self.assertNotIn('sk-' + 'a' * 40, saved)
        self.assertGreaterEqual(saved.count('***'), 3)

    def test_summary_has_rows_notes_and_counter(self):
        data = {'results': {
            'A1': {'status': 'çalıştı', 'note': ''},
            'A2': {'status': 'bozuk', 'note': 'pencere açılmadı'},
        }}
        text = kayit.summary(data, ITEMS)
        self.assertIn('A1 çalıştı; A2 bozuk: pencere açılmadı', text)
        self.assertIn('1 çalıştı, 0 yarım, 1 bozuk, 0 atlandı', text)

    def test_corrupt_json_summary_reports_turkish_error_without_traceback(self):
        self.path.write_text('{bozuk', encoding='utf-8')
        output = []
        with patch('builtins.print', side_effect=lambda *args, **kwargs: output.append(' '.join(map(str, args)))):
            code = kayit.main(['--ozet', str(self.path)])
        self.assertEqual(code, 2)
        joined = '\n'.join(output)
        self.assertIn('Hata:', joined)
        self.assertIn('bozuk JSON', joined)
        self.assertNotIn('Traceback', joined)

    def test_empty_summary_file_reports_clear_error(self):
        self.path.write_text('', encoding='utf-8')
        output = []
        with patch('builtins.print', side_effect=lambda *args, **kwargs: output.append(' '.join(map(str, args)))):
            code = kayit.main(['--ozet', str(self.path)])
        self.assertEqual(code, 2)
        self.assertIn('Sonuç dosyası boş.', '\n'.join(output))

    def test_turkish_note_round_trips_as_utf8(self):
        note = 'Türkçe hata: pencere açılmadı, görev yarım kaldı.'
        kayit.run([ITEMS[0]], FakeInput(['y', note]), lambda *_: None, self.path)
        raw = self.path.read_bytes()
        self.assertIn('çalış'.encode('utf-8')[:2], 'çalıştı'.encode('utf-8'))
        self.assertIn(note.encode('utf-8'), raw)
        self.assertEqual(self.read()['results']['A1']['note'], note)


if __name__ == '__main__':
    unittest.main()
