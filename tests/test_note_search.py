"""Notu arama, düzeltme ve silme (18 Ekim 2026): modelsiz, gerçek profil JSON'u, gerçek EngineContext.

Arama/özetleme canonical hattan geçer: istek -> brain_entry.prepare -> Understanding -> Core ->
notes domain owner. Düzeltme/silmenin bounded biçimleri mevcut planner sahibinde kalır.

Gerçek sesli söyleyiş ve gerçek PC'de denenmedi.
"""
import unittest
import uuid
from dataclasses import replace
from unittest.mock import Mock
from datetime import datetime
from unittest.mock import patch

from modules import brain_entry, requests_state
from modules.brain_contracts import ContextReference, RequestKind
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


def typed_note_effect(rt, utterance, *, operation, index, new_text=None):
    """Mock ONLY a uniquely observed model note target, run real Core/effect.

    This verifies the current worker and snapshot fence, not Turkish intent
    recognition. The model's selected ID is a fixture grounded in a persisted
    note from this owner's profile, never an invented ID or parsed raw text.
    """
    note = rt.profile.data["items"][index]
    ident = str(note["id"])
    ref = ContextReference(
        id=ident, kind="note", source="candidate", owner=rt.profile.slug,
        provenance={"text": note["text"], "title": note.get("title"),
                    "ts": note.get("ts"), "photo": note.get("photo")})
    row = {"operation": operation, "id": ident}
    if operation == "update":
        row["text"] = new_text

    def selected(current, text, *, active_context=None):
        assert text == utterance
        return replace(current, request_kind=RequestKind.CAPABILITY,
                       capability_hint="notes.write", references=(ref,),
                       arguments={"original_text": text, "notes": row},
                       ambiguities=(), needs_input=False, actions=())

    owner = rt.profile.slug
    rid = "note-typed-" + uuid.uuid4().hex[:8]
    requests_state.register(owner, rid)
    forbidden = Mock(side_effect=AssertionError("typed note wrote via raw handler"))
    with requests_state.activate(owner, rid), \
         patch.object(brain_entry, "apply_model_understanding", side_effect=selected):
        entry = brain_entry.prepare(rt, owner=owner, request_id=rid, text=utterance,
                                    source="yazı", model_understanding=True)
        reply, feedback, _ = brain_entry.handoff(rt, entry, forbidden, utterance)
    assert feedback.result_status == "handled", (feedback, reply)
    forbidden.assert_not_called()
    return str(reply)


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
        reply = typed_note_effect(rt, 'o notu düzelt: market: süt, ekmek, peynir', operation='update', index=0, new_text='market: süt, ekmek, peynir')
        self.assertIn('Düzelttim', reply)
        self.assertEqual(self.texts()[0], 'market: süt, ekmek, peynir')
        self.assertEqual(len(self.texts()), 4)

    def test_edit_by_number_and_unique_keyword(self):
        rt = self.rt()
        self.assertIn('Düzelttim', typed_note_effect(rt, '2. notu düzelt: Ahmet ile toplantı salı', operation='update', index=1, new_text='Ahmet ile toplantı salı'))
        self.assertEqual(self.texts()[1], 'Ahmet ile toplantı salı')
        self.assertIn('Düzelttim', typed_note_effect(rt, 'kitap notunu değiştir: kitap: Suç ve Ceza', operation='update', index=3, new_text='kitap: Suç ve Ceza'))
        self.assertEqual(self.texts()[3], 'kitap: Suç ve Ceza')
        self.assertNotIn('Düzelttim', say(rt, '9. notu düzelt: x'))
        self.assertEqual(len(self.texts()), 4)

    def test_ambiguous_edit_and_delete_change_nothing_and_ask(self):
        before = self.texts()
        for text in ('market notunu düzelt: yeni metin', 'market notunu sil', 'o notu sil'):
            with self.subTest(text=text):
                reply = say(self.rt(), text)
                self.assertNotIn('Düzelttim', reply)
                self.assertEqual(self.texts(), before)

    def test_unique_keyword_delete(self):
        self.assertIn('Notu sildim: kitap: Sefiller', typed_note_effect(self.rt(), 'kitap notunu sil', operation='delete', index=3))
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
