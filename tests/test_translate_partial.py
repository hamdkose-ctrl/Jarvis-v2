"""Saved partial translations must still disclose untranslated work in the chat reply."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import translate


class TranslatePartialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'Türkçe belge.txt'
        self.saved = self.root / 'çeviri.docx'

    def run_translation(self, text, saved=True):
        self.source.write_text(text, encoding='utf-8')
        with patch.object(translate, 'ask', return_value='ÇEVİRİ: translated\nNOTLAR: yok') as model, \
                patch.object(translate.output, 'save_text_result',
                             return_value=str(self.saved) if saved else None) as save:
            reply = translate.translate_document(str(self.source), 'İngilizce')
        return reply, model.call_count, save.call_args.args[0]

    def test_saved_partial_translation_discloses_remaining_parts_and_size(self):
        # No whitespace: split boundaries and remaining source characters are exact.
        text = 'x' * (3500 * (translate.MAX_TEXT_PARTS + 2))
        reply, calls, saved_text = self.run_translation(text)
        self.assertEqual(calls, translate.MAX_TEXT_PARTS)
        self.assertIn(str(self.saved), reply)
        self.assertIn('kısmi', reply.lower())
        self.assertIn('2 parça', reply)
        self.assertIn('7.000 karakter', reply)
        self.assertIn('çevrilmedi', reply)
        self.assertIn('2 parça', saved_text)

    def test_complete_translation_has_no_partial_warning(self):
        reply, calls, saved_text = self.run_translation('Kısa metin.')
        self.assertEqual(calls, 1)
        self.assertEqual(reply, f'Çeviriyi kaydettim: {self.saved}')
        self.assertEqual(saved_text, 'translated')

    def test_cancelled_save_keeps_partial_warning_in_returned_text(self):
        reply, calls, _ = self.run_translation('x' * (3500 * (translate.MAX_TEXT_PARTS + 1)), saved=False)
        self.assertEqual(calls, translate.MAX_TEXT_PARTS)
        self.assertIn('1 parça', reply)
        self.assertIn('3.500 karakter', reply)
        self.assertIn('çevrilmedi', reply)
        self.assertNotIn('kaydettim', reply)

    def test_plain_text_api_stays_string_compatible(self):
        self.source.write_text('x' * (3500 * (translate.MAX_TEXT_PARTS + 1)), encoding='utf-8')
        with patch.object(translate, 'ask', return_value='ÇEVİRİ: translated\nNOTLAR: yok'):
            result = translate.translate_text_document(str(self.source), 'İngilizce')
        self.assertIsInstance(result, str)
        self.assertIn('karakter çevrilmedi', result)


if __name__ == '__main__':
    unittest.main()
