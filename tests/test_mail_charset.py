"""Gmail gövdesi MIME charset'e göre çözülür; iç içe text/plain–HTML seçimi doğru yapılır.

Regresyon (14 Ekim 2026): "İyi çalışmalar" sohbete "Ä°yi Ã§alÄ±ÅŸmalar" olarak geliyordu. Baytlar UTF-8 iken
parça windows-1254 (ya da iso-8859-9/windows-1252) bildiriyordu ve gövde bildirilen charset ile çözülüyordu.
Düzeltme bayt düzeyindedir: tek baytlı ailede baytlar geçerli UTF-8 ise UTF-8 okunur. Karakter değiştirme yoktur.
"""
import base64
import unittest
from pathlib import Path

from modules import mail_content as content

TR = 'İyi çalışmalar, Şükrü Öğün. ĞÜŞİÖÇ ğüşıöç'
MOJIBAKE = 'Ä°yi Ã§alÄ±ÅŸmalar'


def part(raw, mime='text/plain', content_type=None, **extra):
    headers = [] if content_type is False else [{'name': 'Content-Type', 'value': content_type or mime}]
    return {'mimeType': mime, 'headers': headers,
            'body': {'data': base64.urlsafe_b64encode(raw).decode().rstrip('=')}, **extra}


def multi(kind, *parts):
    return {'mimeType': 'multipart/' + kind, 'headers': [{'name': 'Content-Type', 'value': 'multipart/' + kind + '; boundary=x'}],
            'parts': list(parts)}


class CharsetTests(unittest.TestCase):
    def test_non_text_codecs_fall_back_to_utf8(self):
        for charset in ('base64', 'hex', 'zlib_codec'):
            with self.subTest(charset=charset):
                self.assertEqual(self.body(part(TR.encode('utf-8'), content_type=f'text/plain; charset={charset}')), TR)

    def body(self, payload):
        return content.extract(payload)['body']

    def test_utf8_declared_in_nested_alternative(self):
        payload = multi('mixed', multi('alternative',
                                       part(TR.encode('utf-8'), content_type='text/plain; charset="UTF-8"'),
                                       part(f'<p>{TR}</p>'.encode('utf-8'), 'text/html', 'text/html; charset=utf-8')),
                        part(b'ek', content_type='text/plain; charset=utf-8', filename='not.txt'))
        self.assertEqual(content.extract(payload), {'body': TR, 'format': 'plain', 'truncated': False})

    def test_real_windows_1254_and_iso_8859_9_bytes(self):
        for charset in ('windows-1254', 'iso-8859-9', 'cp1254', 'latin5'):
            with self.subTest(charset=charset):
                self.assertEqual(self.body(part(TR.encode('cp1254'), content_type=f'text/plain; charset={charset}')), TR)

    def test_utf8_bytes_under_single_byte_label_are_not_mojibake(self):
        for charset in ('windows-1254', 'iso-8859-9', 'windows-1252', 'iso-8859-1', 'us-ascii'):
            with self.subTest(charset=charset):
                text = self.body(part('İyi çalışmalar'.encode('utf-8'), content_type=f'text/plain; charset="{charset}"'))
                self.assertEqual(text, 'İyi çalışmalar')
                self.assertNotIn(MOJIBAKE, text)

    def test_html_utf8_bytes_under_windows_1254_label(self):
        payload = multi('alternative', part(f'<div>{TR}</div>'.encode('utf-8'), 'text/html', 'text/html; charset=windows-1254'))
        self.assertEqual(content.extract(payload), {'body': TR, 'format': 'html_text', 'truncated': False})

    def test_html_meta_charset_used_when_header_has_none(self):
        html = f'<html><head><meta charset="windows-1254"></head><body><p>{TR}</p></body></html>'.encode('cp1254')
        self.assertEqual(self.body(part(html, 'text/html', 'text/html')), TR)
        html = f'<meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-9"><p>{TR}</p>'.encode('iso-8859-9')
        self.assertEqual(self.body(part(html, 'text/html', False)), TR)

    def test_missing_or_unknown_charset_never_raises(self):
        self.assertEqual(self.body(part(TR.encode('utf-8'), content_type=False)), TR)
        self.assertEqual(self.body(part(TR.encode('utf-8'), content_type='text/plain; charset=x-unknown-8bit')), TR)
        broken = self.body(part(b'Merhaba \xff\xfe d\xfcnya', content_type='text/plain; charset=x-unknown-8bit'))
        self.assertIn('Merhaba', broken)
        self.assertIn('�', broken)

    def test_no_blind_character_replacement(self):
        # Gerçekten "Ã§" yazan UTF-8 metin olduğu gibi kalır; çözüm bayt düzeyindedir.
        self.assertEqual(self.body(part('Ã§ ve Ä° yazısı'.encode('utf-8'), content_type='text/plain; charset=utf-8')), 'Ã§ ve Ä° yazısı')
        source = (Path(__file__).resolve().parents[1] / 'modules' / 'mail_content.py').read_text(encoding='utf-8')
        for token in ('Ã', 'Ä°', 'ÅŸ', '.replace('):
            self.assertNotIn(token, source)


class AlternativeSelectionTests(unittest.TestCase):
    def test_alternative_without_plain_uses_html_from_related(self):
        payload = multi('mixed', multi('alternative', multi('related',
                        part(f'<p>{TR}</p>'.encode('utf-8'), 'text/html', 'text/html; charset=utf-8'),
                        part(b'img', 'image/png', 'image/png'))))
        self.assertEqual(content.extract(payload), {'body': TR, 'format': 'html_text', 'truncated': False})

    def test_each_alternative_picked_once_and_mixed_parts_kept_in_order(self):
        first = multi('alternative', part('Birinci düz'.encode('utf-8'), content_type='text/plain; charset=utf-8'),
                      part('<p>Birinci HTML</p>'.encode('utf-8'), 'text/html', 'text/html; charset=utf-8'))
        second = multi('alternative', part('<p>İkinci yalnız HTML</p>'.encode('cp1254'), 'text/html', 'text/html; charset=windows-1254'))
        out = content.extract(multi('mixed', first, second))
        self.assertEqual(out['body'], 'Birinci düz\n\nİkinci yalnız HTML')
        self.assertEqual(out['format'], 'html_text')
        self.assertNotIn('Birinci HTML', out['body'])

    def test_plain_preferred_even_when_html_comes_first(self):
        payload = multi('alternative', part('<p>HTML</p>'.encode('utf-8'), 'text/html', 'text/html; charset=utf-8'),
                        part(TR.encode('cp1254'), content_type='text/plain; charset=windows-1254'))
        self.assertEqual(content.extract(payload), {'body': TR, 'format': 'plain', 'truncated': False})


if __name__ == '__main__':
    unittest.main()
