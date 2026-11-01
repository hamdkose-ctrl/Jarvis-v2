"""Çeviri kaynak seçiminin TEK kuralı: `translation_request.pick_source`.

Oturum cache'i (`_sources`) ve ikinci kaynak-seçici emekli edildi; satırlar artık canonical
ActiveContext/Candidate kaynağından gelir, kural saf bir fonksiyondur."""
import unittest
from datetime import datetime

from modules import translation_request as tr


class ShortTranslationContextTests(unittest.TestCase):
    def rows(self, text):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        return [{'id': 'r1', 'role': 'user', 'text': 'Older long original paragraph.', 'ts': ts},
                {'id': 'r2', 'role': 'assistant', 'text': 'Eski çeviri', 'ts': ts},
                {'id': 'r3', 'role': 'user', 'text': text, 'ts': ts},
                {'id': 'r4', 'role': 'assistant', 'text': 'Merhaba, nasıl yardımcı olayım?', 'ts': ts}]

    def source(self, command, rows):
        request = tr.parse(command)
        self.assertIsNotNone(request, command)
        return tr.pick_source(request, command, rows)

    def test_latest_original_user_text_wins(self):
        self.assertEqual(self.source('önceki metni Türkçeye çevir', self.rows('hello'))[:2],
                         ('hello', tr.ORIGIN_USER))

    def test_single_character_is_valid_source(self):
        self.assertEqual(self.source('çevir', self.rows('a'))[0], 'a')

    def test_acknowledgement_does_not_replace_source(self):
        rows = self.rows('hello')
        rows.append({'id': 'r5', 'role': 'user', 'text': 'tamam', 'ts': rows[-1]['ts']})
        self.assertEqual(self.source('çevir', rows)[0], 'hello')

    def test_explicit_last_answer_still_selects_assistant(self):
        self.assertEqual(self.source('son cevabını Türkçeye çevir', self.rows('hello'))[:2],
                         ('Merhaba, nasıl yardımcı olayım?', tr.ORIGIN_ASSISTANT))

    def test_the_command_is_never_its_own_source(self):
        self.assertEqual(self.source('çevir', self.rows('çevir'))[0], 'Older long original paragraph.')

    def test_inline_text_beats_history(self):
        self.assertEqual(self.source('çevir: günaydın', self.rows('hello'))[:2], ('günaydın', tr.ORIGIN_INLINE))


if __name__ == "__main__":
    unittest.main()
