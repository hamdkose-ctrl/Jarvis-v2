"""Historical reminder behavior, now exercised through typed Brain/Core and State approval.

The old direct raw-language reminder handler is retired. The mapping below is
explicit TEST MODEL OUTPUT for fixed historical utterances: it is not a
production phrase parser and does not prove live Turkish recognition. Every
positive mutation runs the same existing worker and a separate "evet" turn.
Canonical no-mutation-before-consent tests live in test_brain03_reminder_canonical.
"""
import uuid
import unittest
from dataclasses import replace
from datetime import datetime
from unittest.mock import Mock, patch

from test_mail_calendar_fixes import (ProfileCase, _runtime, say as raw_say,
    bounded_reminder_answer, typed_reminder_create)
from modules import brain_entry, requests_state
from modules.brain_contracts import ConversationRelation, RequestKind

# Semantic fixtures only. These strings are NOT runtime grammar.
_MODEL_REMINDER_CASES = {
    "ilaç hatırlatmasını sil": ("delete", "İlaç", None, None),
    "dişçi randevusunu kaldır": ("delete", "Dişçi", None, None),
    "dişçi hatırlatmasını iptal et": ("delete", "Dişçi", None, None),
    "disci hatirlatmasini sil": ("delete", "Dişçi", None, None),
    "kitap hatırlatmasını sil": ("delete", "Kitap", None, None),
    "sunum hatırlatmasını 10 dakika ertele": ("postpone", "Sunum", "10 dakika", None),
    "sunumu 2 saat ertele": ("postpone", "Sunum", "2 saat", None),
    "sunum randevusunu yarına ertele": ("postpone", "Sunum", "yarına", None),
    "sunum hatırlatmasını yarım saat ertele": ("postpone", "Sunum", "yarım saat", None),
    "hediye hatırlatmasını 10 dakika ertele": ("postpone", "Hediye", "10 dakika", None),
    "hediye hatırlatmasını 2 gün ertele": ("postpone", "Hediye", "2 gün", None),
    "yarınki ilaç hatırlatmasını 1 saat ertele": ("postpone", "İlaç", "1 saat", None),
    "yarinki ilac hatirlatmasini 1 saat otele": ("postpone", "İlaç", "1 saat", None),
    "yarınki ilacı 1 saat ertele": ("postpone", "İlaç", "1 saat", None),
    "YARINKİ İlaç hatırlatmasını bir saat ertele": ("postpone", "İlaç", "bir saat", None),
    "bu haftaki toplantı hatırlatmasını cumaya kaydır": ("move", "Toplantı", None, "cuma"),
    "toplantıyı pazartesiye kaydir": ("move", "Toplantı", None, "pazartesi"),
    "ilaç hatırlatmasını cumaya kaydır": ("move", "İlaç", None, "cuma"),
    "sunumu cumaya kaydır": ("move", "Sunum", None, "cuma"),
    "toplantıyı cumaya kaydır": ("move", "Toplantı", None, "cuma"),
    "toplantı hatırlatmasını atla": ("skip", "Toplantı", None, None),
    "ilaç hatırlatmasını atla": ("skip", "İlaç", None, None),
    "yarınki ilacı atla": ("skip", "İlaç", None, None),
    "bugünkünü atla": ("skip", None, None, None),
    "bugunku hatirlatmayi atla": ("skip", None, None, None),
    "dişçi hatırlatmasını atla": ("skip", "Dişçi", None, None),
    "ertele": ("snooze", None, None, None),
    "ilaç hatırlatmasını yarım saat ertele": ("snooze", "İlaç", "yarım saat", None),
    "ilaci 1 saat otele": ("snooze", "İlaç", "1 saat", None),
    "10 dk sonra tekrar çal": ("snooze", None, "10 dk", None),
    "5 dakika sonra yine hatırlat": ("snooze", None, "5 dakika", None),
    "10 dakika sonra bir daha çal": ("snooze", None, "10 dakika", None),
    "1 saat sonra tekrar çal": ("snooze", None, "1 saat", None),
    "beni 10 dakika sonra tekrar uyar": ("snooze", None, "10 dakika", None),
    "ilaç hatırlatmasını 10 dk sonra tekrar çal": ("snooze", "İlaç", "10 dk", None),
    "daha sonra hatırlat": ("snooze", None, None, None),
    "sonra tekrar hatırlat": ("snooze", None, None, None),
    "10 dakika sonra tekrar hatırlat": ("snooze", None, "10 dakika", None),
    "ilaç hatırlatmasını 10 dakika ertele": ("postpone", "İlaç", "10 dakika", None),
    "ilaç hatırlatmasını 30 dakika ertele": ("postpone", "İlaç", "30 dakika", None),
    "ilaç hatırlatmasını 1 gün ertele": ("postpone", "İlaç", "1 gün", None),
}

_MODEL_CREATION_CASES = {
    "yarın 10da dişçi hatırlat": ("Dişçi", "2026-10-18T10:00", None),
    "toplantıyı 10 dakika sonra hatırlat": ("toplantı", "2026-10-17T10:10", None),
    "ilacı yarın sabah hatırlat": ("ilaç", "2026-10-18T09:00", None),
    "2 saat sonra su iç hatırlat": ("su iç", "2026-10-17T12:00", None),
}

def say(rt, text):
    if text in _MODEL_CREATION_CASES:
        title, when, repeat = _MODEL_CREATION_CASES[text]
        return typed_reminder_create(rt, text, title=title, when=when, repeat=repeat)
    params = _MODEL_REMINDER_CASES.get(text)
    if params is None:
        return raw_say(rt, text)
    operation, title, duration, weekday = params
    arguments = {"operation": operation}
    if title is not None:
        arguments["title"] = title
    if duration is not None:
        arguments["duration"] = duration
    if weekday is not None:
        arguments["weekday"] = weekday
    if text in {"bugünkünü atla", "bugunku hatirlatmayi atla"}:
        arguments["period"] = "today"
    if text == "yarınki ilacı atla":
        arguments["period"] = "tomorrow"
    owner = rt.profile.slug
    request = "historical-reminder-" + uuid.uuid4().hex[:12]
    assert requests_state.register(owner, request)
    def model(current, utterance, *, active_context=None):
        assert utterance == text
        return replace(
            current, request_kind=RequestKind.CAPABILITY,
            conversation_relation=ConversationRelation.NEW_REQUEST,
            capability_hint="reminders.manage",
            arguments={"original_text": text, **arguments},
            ambiguities=(), needs_input=False, actions=(),
            reason_codes=current.reason_codes + ("MODEL_DECIDED",),
        )
    forbidden = Mock(side_effect=AssertionError("historical reminder called retired NLP"))
    with requests_state.activate(owner, request), \
         patch.object(brain_entry, "apply_model_understanding", side_effect=model):
        entry = brain_entry.prepare(rt, owner=owner, request_id=request,
                                    text=text, source="yazı", model_understanding=True)
        reply, feedback, _ = brain_entry.handoff(rt, entry, forbidden, text)
    forbidden.assert_not_called()
    if feedback.result_status == "needs_input" and rt._session().pending_confirm is not None:
        return bounded_reminder_answer(rt, "evet")
    return str(reply)


class ReminderEditTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def titles(self):
        return sorted(e['title'] for e in self.reload().data['events'])

    def test_delete_by_title_and_persists(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00')
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        reply = say(self.rt(), 'ilaç hatırlatmasını sil')
        self.assertIn('Sildim: İlaç', reply)
        self.assertIn("Google Takvim'e dokunmadım", reply)
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_delete_variants_and_ascii(self):
        for text in ('dişçi randevusunu kaldır', 'dişçi hatırlatmasını iptal et', 'disci hatirlatmasini sil'):
            with self.subTest(text=text):
                self.profile.add_event('Dişçi', '2026-10-19T15:00')
                self.profile.add_event('Başka', '2026-10-20T15:00')
                self.assertIn('Sildim: Dişçi', say(self.rt(), text))
                self.assertEqual(self.titles(), ['Başka'])
                self.profile.data['events'].clear()
                self.profile.save()

    def test_ambiguous_delete_asks_and_deletes_nothing(self):
        self.profile.add_event('Toplantı A', '2026-10-18T09:00')
        self.profile.add_event('Toplantı B', '2026-10-19T09:00')
        reply = say(self.rt(), 'hatırlatmayı sil')
        self.assertIn('Hangisini kastettin', reply)
        self.assertEqual(len(self.reload().data['events']), 2)

    def test_unknown_title_and_empty(self):
        self.assertIn('Kayıtlı bir hatırlatman yok', say(self.rt(), 'ilaç hatırlatmasını sil'))
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn('bulamadım', say(self.rt(), 'kitap hatırlatmasını sil'))
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_notes_and_adding_are_not_hijacked(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        say(self.rt(), 'yarın 10da dişçi hatırlat')
        self.assertEqual(len(self.reload().data['events']), 2)
        self.assertNotIn('Sildim', say(self.rt(), '1 numaralı notu sil'))

    def test_repeating_delete_says_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarları', say(self.rt(), 'ilaç hatırlatmasını sil'))
        self.assertEqual(self.titles(), [])

    def test_postpone_future_by_minutes_hours_days(self):
        self.profile.add_event('Sunum', '2026-10-17T14:00')
        self.assertIn('erteledim', say(self.rt(), 'sunum hatırlatmasını 10 dakika ertele'))
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-17T14:10')
        say(self.rt(), 'sunumu 2 saat ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-17T16:10')
        say(self.rt(), 'sunum randevusunu yarına ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-18T16:10')
        say(self.rt(), 'sunum hatırlatmasını yarım saat ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-18T16:40')

    def test_bare_postpone_snoozes_last_fired_reminder_from_now(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.profile.add_event('Başka', '2026-10-20T09:30')
        self.profile.data['events'][0]['notified'] = True
        self.profile.save()
        reply = say(self.rt(), 'ertele')
        self.assertIn('İlaç hatırlatmasını 10 dakika sonra', reply)
        ev = [e for e in self.reload().data['events'] if e['title'] == 'İlaç'][0]
        self.assertEqual((ev['when'], ev['notified']), ('2026-10-17T10:10', False))     # şimdiden itibaren, tekrar çalar

    def test_postpone_allday_minutes_refused_days_ok(self):
        self.profile.add_event('Hediye', '2026-10-20')
        self.assertIn('Tüm gün', say(self.rt(), 'hediye hatırlatmasını 10 dakika ertele'))
        self.assertIn('erteledim', say(self.rt(), 'hediye hatırlatmasını 2 gün ertele'))
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-22')

    def test_postponed_reminder_fires_again(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)
        say(self.rt(), 'ilaç hatırlatmasını 30 dakika ertele')
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 17, 10, 29))), 0)
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 17, 10, 31))), 1)


class RepeatingEditTests(ProfileCase):
    """Tekrarlayan hatırlatmayı yalnız sıradaki oluşum için ertele / başka güne kaydır / atla (18 Ekim 2026)."""
    now = datetime(2026, 10, 17, 10, 0)       # cumartesi

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def ev(self, title='İlaç'):
        return [e for e in self.reload().data['events'] if e['title'] == title][0]

    def test_postpone_next_occurrence_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        reply = say(self.rt(), 'yarınki ilaç hatırlatmasını 1 saat ertele')
        self.assertIn('yarın 10:00', reply)
        self.assertIn('09:00', reply)                                   # sonrakilerin eski saatte kaldığı söylenir
        e = self.ev()
        self.assertEqual((e['when'], e['base'], e['repeat']), ('2026-10-18T10:00', '09:00', 'daily'))
        self.assertEqual(self.reload().events_on('2026-10-19')[0]['when'], '2026-10-19T09:00')
        self.assertEqual(self.reload().events_on('2026-10-18')[0]['when'], '2026-10-18T10:00')

    def test_shifted_occurrence_fires_then_rule_returns_to_base_time(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        say(self.rt(), 'yarınki ilaç hatırlatmasını 1 saat ertele')
        p = self.reload()
        self.assertEqual(p.due_events(datetime(2026, 10, 18, 9, 30)), [])
        self.assertEqual(len(p.due_events(datetime(2026, 10, 18, 10, 1))), 1)
        e = p.data['events'][0]
        self.assertEqual(e['when'], '2026-10-19T09:00')                  # kural eski saatine döndü
        self.assertNotIn('base', e)

    def test_ascii_and_typo_variants(self):
        for text in ('yarinki ilac hatirlatmasini 1 saat otele', 'yarınki ilacı 1 saat ertele', 'YARINKİ İlaç hatırlatmasını bir saat ertele'):
            with self.subTest(text=text):
                self.profile.data['events'].clear()
                self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
                say(self.rt(), text)
                self.assertEqual(self.ev()['when'], '2026-10-18T10:00')

    def test_move_to_weekday(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')      # pazartesi
        reply = say(self.rt(), 'bu haftaki toplantı hatırlatmasını cumaya kaydır')
        self.assertIn('23 Ekim 10:00', reply)
        e = self.ev('Toplantı')
        self.assertEqual(e['when'], '2026-10-23T10:00')
        self.assertNotIn('base', e)                                      # saat değişmedi, kaydırılan yalnız gün
        say(self.rt(), 'toplantıyı pazartesiye kaydir')
        self.assertEqual(self.ev('Toplantı')['when'], '2026-10-19T10:00')

    def test_move_past_regular_occurrences_says_so(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        reply = say(self.rt(), 'ilaç hatırlatmasını cumaya kaydır')
        self.assertEqual(self.ev()['when'], '2026-10-23T09:00')
        self.assertIn('Aradaki', reply)

    def test_move_one_off_event_and_not_hijacking(self):
        self.profile.add_event('Sunum', '2026-10-19T14:00')
        self.assertIn('Sunum', say(self.rt(), 'sunumu cumaya kaydır'))
        self.assertEqual(self.ev('Sunum')['when'], '2026-10-23T14:00')
        from modules import main_planner
        from modules import brain_core_map
        self.assertFalse(hasattr(main_planner, "_edit_reminder"),
                         "Retired free-text edit parser must remain absent.")
        for text in ('sayfayı aşağı kaydır', 'ekranı yukarı kaydır',
                     'oyunu atla', 'reklamı atla', 'bugünkü reklamı atla'):
            with self.subTest(text=text):
                self.assertIsNone(brain_core_map.core_plan(
                    "reminders.manage", {"operation": "move",
                                         "title": "Sunum", "weekday": text}))

    def test_skip_today_and_ascii(self):
        self.profile.add_event('İlaç', '2026-10-17T18:00', repeat='daily')
        reply = say(self.rt(), 'bugünkünü atla')
        self.assertIn('atladım', reply)
        self.assertEqual(self.ev()['when'], '2026-10-18T18:00')
        self.profile.data['events'].clear()
        self.profile.add_event('İlaç', '2026-10-17T18:00', repeat='daily')
        say(self.rt(), 'bugunku hatirlatmayi atla')
        self.assertEqual(self.ev()['when'], '2026-10-18T18:00')

    def test_skip_clears_shift_and_uses_rule(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')
        say(self.rt(), 'toplantıyı cumaya kaydır')
        say(self.rt(), 'toplantı hatırlatmasını atla')
        e = self.ev('Toplantı')
        self.assertEqual(e['when'], '2026-10-26T10:00')                  # sıradaki pazartesi
        self.assertNotIn('base', e)

    def test_day_qualifier_mismatch_changes_nothing(self):
        self.profile.add_event('İlaç', '2026-10-19T09:00', repeat='weekly:0')
        reply = say(self.rt(), 'yarınki ilacı atla')
        self.assertIn('Yarın', reply)
        self.assertEqual(self.ev()['when'], '2026-10-19T09:00')

    def test_skip_one_off_is_refused(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn('tek seferlik', say(self.rt(), 'dişçi hatırlatmasını atla'))
        self.assertEqual(self.ev('Dişçi')['when'], '2026-10-19T15:00')

    def test_bare_postpone_does_not_touch_repeating_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('Yakın zamanda', say(self.rt(), 'ertele'))
        self.assertEqual(self.ev()['when'], '2026-10-18T09:00')

    def test_delete_still_removes_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarları', say(self.rt(), 'ilaç hatırlatmasını sil'))


class RepeatSnoozeTests(ProfileCase):
    """Az önce çalan tekrarlayan hatırlatmayı "10 dakika sonra tekrar çal" (snooze); sıradaki tekrar değişmez."""
    now = datetime(2026, 10, 17, 10, 0)

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def fire(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30', repeat='daily')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)         # çaldı, sıradaki 18 Ekim'e kuruldu

    def ev(self):
        return self.reload().data['events'][0]

    def test_bare_postpone_snoozes_without_moving_next_occurrence(self):
        self.fire()
        reply = say(self.rt(), 'ertele')
        self.assertIn('10 dakika sonra yeniden', reply)
        e = self.ev()
        self.assertEqual((e['snooze'], e['when']), ('2026-10-17T10:10', '2026-10-18T09:30'))
        p = self.reload()
        self.assertEqual(p.due_events(datetime(2026, 10, 17, 10, 9)), [])
        self.assertEqual(len(p.due_events(datetime(2026, 10, 17, 10, 11))), 1)
        self.assertEqual(p.due_events(datetime(2026, 10, 17, 10, 12)), [])          # bir kez çalar
        self.assertEqual(p.data['events'][0]['when'], '2026-10-18T09:30')
        self.assertNotIn('snooze', p.data['events'][0])

    def test_named_and_ascii_snooze(self):
        for text, want in (('ilaç hatırlatmasını yarım saat ertele', '2026-10-17T10:30'),
                           ('ilaci 1 saat otele', '2026-10-17T11:00')):
            with self.subTest(text=text):
                self.profile.data['events'].clear()
                self.fire()
                say(self.rt(), text)
                self.assertEqual(self.ev()['snooze'], want)

    def test_tomorrow_qualifier_days_and_stale_fire_move_next_occurrence_instead(self):
        self.fire()
        say(self.rt(), 'yarınki ilaç hatırlatmasını 1 saat ertele')
        e = self.ev()
        self.assertEqual((e['when'], e.get('snooze')), ('2026-10-18T10:30', None))
        self.profile.data['events'].clear()
        self.fire()
        say(self.rt(), 'ilaç hatırlatmasını 1 gün ertele')
        self.assertEqual(self.ev()['when'], '2026-10-19T09:30')
        self.profile.data['events'].clear()
        self.profile.add_event('İlaç', '2026-10-18T09:30', repeat='daily')          # hiç çalmadı: sıradaki kayar
        say(self.rt(), 'ilaç hatırlatmasını 10 dakika ertele')
        e = self.ev()
        self.assertEqual((e['when'], e.get('snooze')), ('2026-10-18T09:40', None))

    def test_bare_postpone_picks_latest_fired_among_one_off_and_repeating(self):
        self.profile.add_event('Eski', '2026-10-17T08:00')
        self.profile.data['events'][0]['notified'] = True
        self.profile.save()
        self.profile.add_event('İlaç', '2026-10-17T09:30', repeat='daily')
        self.profile.due_events(self.now)
        self.assertIn('İlaç', say(self.rt(), 'ertele'))
        self.assertNotIn('snooze', [e for e in self.reload().data['events'] if e['title'] == 'Eski'][0])

    def test_failed_save_leaves_no_snooze(self):
        self.fire()
        p = self.reload()
        eid = p.data['events'][0]['id']
        with patch.object(p, 'save', side_effect=OSError('disk dolu')):
            with self.assertRaises(OSError):
                p.snooze_event(eid, '2026-10-17T10:10')
        self.assertNotIn('snooze', p.data['events'][0])
        self.assertTrue(p.snooze_event(eid, '2026-10-17T10:10'))
        self.assertEqual(self.reload().data['events'][0]['snooze'], '2026-10-17T10:10')


if __name__ == '__main__':
    unittest.main()


class SnoozeWordingTests(ProfileCase):
    """"10 dk sonra tekrar çal", "daha sonra hatırlat", "yarın sabah hatırlat": ertele demeden söylenen erteleme; yeni kayıt eklemez."""
    now = datetime(2026, 10, 17, 10, 0)

    def setUp(self):
        super().setUp()
        self.profile.add_event('İlaç', '2026-10-17T09:30', repeat='daily')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)          # çaldı, sıradaki 18 Ekim'e kuruldu

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def ev(self):
        evs = self.reload().data['events']
        self.assertEqual(len(evs), 1, 'yeni kayıt eklenmemeli')
        return evs[0]

    def test_after_n_minutes_again_variants_snooze(self):
        for text, want in (('10 dk sonra tekrar çal', '2026-10-17T10:10'), ('5 dakika sonra yine hatırlat', '2026-10-17T10:05'),
                           ('10 dakika sonra bir daha çal', '2026-10-17T10:10'), ('1 saat sonra tekrar çal', '2026-10-17T11:00'),
                           ('beni 10 dakika sonra tekrar uyar', '2026-10-17T10:10'), ('ilaç hatırlatmasını 10 dk sonra tekrar çal', '2026-10-17T10:10'),
                           ('daha sonra hatırlat', '2026-10-17T10:10'), ('sonra tekrar hatırlat', '2026-10-17T10:10'),
                           ('10 dakika sonra tekrar hatırlat', '2026-10-17T10:10')):
            with self.subTest(text=text):
                self.profile.data['events'][0].pop('snooze', None)
                self.profile.save()
                say(self.rt(), text)
                e = self.ev()
                self.assertEqual((e['snooze'], e['when']), (want, '2026-10-18T09:30'))

    def test_day_part_snooze_and_next_occurrence_shift(self):
        say(self.rt(), 'akşama ertele')
        e = self.ev()
        self.assertEqual((e['snooze'], e['when']), ('2026-10-17T18:00', '2026-10-18T09:30'))
        for text in ('yarın sabah hatırlat', 'yarın sabaha ertele', 'ilaç hatırlatmasını yarın sabah tekrar hatırlat'):
            with self.subTest(text=text):
                self.profile.data['events'][0]['when'] = '2026-10-18T09:30'
                self.profile.save()
                reply = say(self.rt(), text)
                self.assertIn('yarın 09:00', reply)
                self.assertEqual(self.ev()['when'], '2026-10-18T09:00')

    def test_adding_a_new_reminder_is_not_hijacked(self):
        for text in ('toplantıyı 10 dakika sonra hatırlat', 'ilacı yarın sabah hatırlat', '2 saat sonra su iç hatırlat'):
            with self.subTest(text=text):
                before = len(self.reload().data['events'])
                say(self.rt(), text)
                self.assertEqual(len(self.reload().data['events']), before + 1)
                self.profile.data['events'] = self.profile.data['events'][:1]
                self.profile.save()
