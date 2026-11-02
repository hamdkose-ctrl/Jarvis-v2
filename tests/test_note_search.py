"""Notu arama, düzeltme ve silme (18 Ekim 2026): modelsiz, gerçek profil JSON'u, gerçek EngineContext.

Arama/özetleme canonical hattan geçer: istek -> brain_entry.prepare -> Understanding -> Core ->
notes domain owner. Düzeltme/silmenin bounded biçimleri mevcut planner sahibinde kalır.

Gerçek sesli söyleyiş ve gerçek PC'de denenmedi.
"""
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

from modules import brain_entry, requests_state
from test_mail_calendar_fixes import ProfileCase, _runtime


def say(rt, text):
    """Canonical giriş: aynı cümle Brain -> Core -> notes domain hattından geçer."""
    owner = rt.profile.slug
    rid = "note-search-" + uuid.uuid4().hex[:8]
    requests_state.register(owner, rid)
    with patch.object(brain_entry, "_install_core_guards", lambda runtime: None), \
            requests_state.activate(owner, rid):
        entry = brain_entry.prepare(rt, owner=owner, request_id=rid, text=text, source="yazı")
        out, _feedback, _job = brain_entry.handoff(rt, entry, rt.handle, text)
    return out


class NoteSearchTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)           # cumartesi; bu hafta 12-18 Ekim, geçen hafta 5-11 Ekim

    def setUp(self):
        super().setUp()
        for text, ts in (('market: süt, ekmek, yumurta', '2026-10-08 18:30'),
                         ('Ahmet ile toplantı pazartesi', '2026-10-16 09:10'),
                         ('market bayram için hurma al', '2026-10-17 09:00'),
                         ('kitap: Sefiller', '2026-09-20 21:00')):
            self.profile.add_note_item(text)
            self.profile.data['items'][-1]['ts'] = ts
        self.profile.save()

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def texts(self):
        return [n['text'] for n in self.reload().data['items']]

    def test_keyword_lists_every_match_with_its_number(self):
        reply = say(self.rt(), 'market notum')
        self.assertIn('1) market: süt', reply)
        self.assertIn('3) market bayram', reply)
        self.assertNotIn('Sefiller', reply)

    def test_last_week_market_note_finds_only_that_one(self):
        for text in ('geçen hafta aldığım market notu', 'gecen hafta aldigim market notu', 'Geçen haftaki market notum'):
            with self.subTest(text=text):
                reply = say(self.rt(), text)
                self.assertIn('market: süt, ekmek', reply)
                self.assertNotIn('hurma', reply)

    def test_search_phrasings(self):
        rt = self.rt()
        for text in ('notlarımda kitap ara', 'notlarimda kitap bul', 'Sefiller ile ilgili notum var mı',
                     'sefiller hakkında notlarım', 'kitap notumu göster', 'marketteki notum', 'marekt notum'):
            with self.subTest(text=text):
                reply = say(rt, text)
                self.assertTrue('Sefiller' in reply or 'market' in reply, reply)
        self.assertNotIn('hurma', say(rt, 'notlarımda kitap ara'))

    def test_date_windows(self):
        rt = self.rt()
        today = say(rt, 'bugünkü notlarım')
        self.assertIn('hurma', today)
        self.assertNotIn('Ahmet', today)
        week = say(rt, 'bu haftaki notlarım')
        self.assertIn('Ahmet', week)
        self.assertIn('hurma', week)
        self.assertNotIn('süt', week)
        self.assertIn('süt', say(rt, 'geçen haftaki notlarım'))
        self.assertIn('Ahmet', say(rt, 'dünkü notlarım'))
        self.assertIn('Sefiller', say(rt, 'geçen ayki notlarım'))
        self.assertIn('bulamadım', say(rt, 'dünkü market notum'))

    def test_no_match_says_so_and_shows_note_count(self):
        reply = say(self.rt(), 'faturalar notum')
        self.assertIn('bulamadım', reply)
        self.assertIn('4 notun var', reply)

    def test_edit_found_note_with_that_note(self):
        rt = self.rt()
        say(rt, 'geçen hafta aldığım market notu')
        reply = say(rt, 'o notu düzelt: market: süt, ekmek, peynir')
        self.assertIn('Düzelttim', reply)
        self.assertEqual(self.texts()[0], 'market: süt, ekmek, peynir')
        self.assertEqual(len(self.texts()), 4)

    def test_edit_by_number_and_unique_keyword(self):
        rt = self.rt()
        self.assertIn('Düzelttim', say(rt, '2. notu düzelt: Ahmet ile toplantı salı'))
        self.assertEqual(self.texts()[1], 'Ahmet ile toplantı salı')
        self.assertIn('Düzelttim', say(rt, 'kitap notunu değiştir: kitap: Suç ve Ceza'))
        self.assertEqual(self.texts()[3], 'kitap: Suç ve Ceza')
        self.assertIn('Böyle bir numaralı not yok', say(rt, '9. notu düzelt: x'))
        self.assertEqual(len(self.texts()), 4)

    def test_ambiguous_edit_and_delete_change_nothing_and_ask(self):
        before = self.texts()
        for text in ('market notunu düzelt: yeni metin', 'market notunu sil', 'o notu sil'):
            with self.subTest(text=text):
                reply = say(self.rt(), text)
                self.assertIn('Hangisini', reply) if 'market' in text else self.assertTrue(reply)
                self.assertEqual(self.texts(), before)

    def test_unique_keyword_delete(self):
        self.assertIn('Notu sildim: kitap: Sefiller', say(self.rt(), 'kitap notunu sil'))
        self.assertEqual(len(self.texts()), 3)

    def test_existing_note_commands_not_hijacked(self):
        rt = self.rt()
        self.assertIn('Not aldım', say(rt, 'not market sütü al'))
        self.assertEqual(len(self.texts()), 5)
        self.assertIn('Notu sildim', say(rt, '1 numaralı notu sil'))
        self.assertIn('Son notu sildim', say(rt, 'son notu sil'))
        self.assertIn('Notların', say(rt, 'notlarım'))
        self.profile.add_event('Market', '2026-10-18T10:00')
        self.assertIn('Sildim: Market', say(self.rt(), 'market hatırlatmasını sil'))


if __name__ == '__main__':
    unittest.main()
