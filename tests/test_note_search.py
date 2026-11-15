"""Notu arama, düzeltme ve silme (18 Ekim 2026): modelsiz, gerçek profil JSON'u, gerçek EngineContext.

Arama/özetleme canonical hattan geçer: istek -> brain_entry.prepare -> Understanding -> Core ->
notes domain owner. Düzeltme/silme testleri açık model önerisiyle aynı Core sahibine gider; dil başarısı iddiası değildir.

Gerçek sesli söyleyiş ve gerçek PC'de denenmedi.
"""
from modules import core_brain_adapter
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

from modules import brain_entry, requests_state
from brain_turn_fixture import note_change, reminder_change, turn
from test_mail_calendar_fixes import ProfileCase, _runtime


def say(rt, text):
    """Canonical giriş: aynı cümle Brain -> Core -> notes domain hattından geçer."""
    owner = rt.profile.slug
    rid = "note-search-" + uuid.uuid4().hex[:8]
    requests_state.register(owner, rid)
    with requests_state.activate(owner, rid):
        entry = brain_entry.prepare(rt, owner=owner, request_id=rid, text=text, source="yazı")
        out, _feedback, _job = core_brain_adapter.handoff(rt, entry, rt.handle, text)
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
        reply = note_change(rt, 'o notu düzelt: market: süt, ekmek, peynir', self.profile.data['items'][0], 'update', 'market: süt, ekmek, peynir')
        self.assertIn('Düzelttim', reply)
        self.assertEqual(self.texts()[0], 'market: süt, ekmek, peynir')
        self.assertEqual(len(self.texts()), 4)

    def test_edit_by_number_and_unique_keyword(self):
        rt = self.rt()
        self.assertIn('Düzelttim', note_change(rt, '2. notu düzelt: Ahmet ile toplantı salı', self.profile.data['items'][1], 'update', 'Ahmet ile toplantı salı'))
        self.assertEqual(self.texts()[1], 'Ahmet ile toplantı salı')
        self.assertIn('Düzelttim', note_change(rt, 'kitap notunu değiştir: kitap: Suç ve Ceza', self.profile.data['items'][3], 'update', 'kitap: Suç ve Ceza'))
        self.assertEqual(self.texts()[3], 'kitap: Suç ve Ceza')
        self.assertIn('doğrula', turn(rt, '9. notu düzelt: x', 'notes.write', {'notes': {'id': 'missing', 'operation': 'update', 'text': 'x'}}).lower())
        self.assertEqual(len(self.texts()), 4)

    def test_ambiguous_edit_and_delete_change_nothing_and_ask(self):
        before = self.texts()
        for text in ('market notunu düzelt: yeni metin', 'market notunu sil', 'o notu sil'):
            with self.subTest(text=text):
                reply = say(self.rt(), text)
                self.assertIn('Hangisini', reply) if 'market' in text else self.assertTrue(reply)
                self.assertEqual(self.texts(), before)

    def test_unique_keyword_delete(self):
        self.assertIn('Notu sildim: kitap: Sefiller', note_change(self.rt(), 'kitap notunu sil', self.profile.data['items'][3], 'delete'))
        self.assertEqual(len(self.texts()), 3)

    def test_existing_note_commands_not_hijacked(self):
        rt = self.rt()
        self.assertIn('Not aldım', turn(rt, 'not market sütü al', 'notes.add', {'text': 'market sütü al'}))
        self.assertEqual(len(self.texts()), 5)
        self.assertIn('Notu sildim', note_change(rt, '1 numaralı notu sil', self.profile.data['items'][0], 'delete'))
        self.assertIn('Notu sildim', note_change(rt, 'son notu sil', self.profile.data['items'][-1], 'delete'))
        self.assertIn('Notların', turn(rt, 'notlarım', 'notes.read', {'notes': {'which': 'all'}}))
        self.profile.add_event('Market', '2026-10-18T10:00')
        self.assertIn('Sildim: Market', reminder_change(self.rt(), 'market hatırlatmasını sil', {'operation': 'delete', 'title': 'Market'}))


if __name__ == '__main__':
    unittest.main()
