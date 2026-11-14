"""Living owners for the producer-less dispatch cases removed from modules/engine_intents.py.

test_brain_orphan_dispatch_guard.py proves the dispatcher no longer holds the case; every test
here proves the same user behaviour still runs through its canonical owner. Each owner is called
at its own seam with the device, browser, mail, transfer and task effects mocked, so nothing in
this file touches a real PC.

PR3A: the raw-text branches these tests used to execute inside `engine_commands.handle` are
retired. The same sentences now reach the owner through the canonical plan
(`brain_core_map.CORE_INTENTS` / `FAST_INTENTS` -> `engine_intents.dispatch`), so the seam under
test is the validated intent, never the sentence.
"""
import ast
from pathlib import Path
import os
import importlib
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_brain_orphan_dispatch_guard import REMOVED_LEGACY_INTENTS

# A focused run can import config before any other test: keep that startup, including the
# config/privacy cycle, away from the real user directory.
_import_data = tempfile.TemporaryDirectory(prefix='orphan-replacement-tests-')
with patch.dict(os.environ, {'JARVIS_DATA_DIR': _import_data.name}):
    import config  # noqa: F401  (imported first so modules.privacy is not mid-cycle)
    from modules import browser, engine_tools, filesend, handoff, media, meeting_prep, outlook, worktrack

# Legacy dispatch case -> the module function that owns the behaviour today.
CAPABILITY_OWNERS = {
    'open_app': ('modules.command_execution', 'open_app'),
    'close_app': ('modules.system_control', 'close_application'),
    'open_url': ('modules.browser', 'handle'),
    'mail': ('modules.engine_tools', 'mail_read_typed'),
    'media': ('modules.media', 'youtube'),
    'note': ('modules.engine_tools', '_add_note'),
    'handoff': ('modules.handoff', 'handle'),
    'work': ('modules.worktrack', 'handle'),
    'pc_control': ('modules.system_control', 'shutdown_pc'),
    'screenshot': ('modules.desktop', 'screenshot'),
    'status': ('modules.desktop', 'system_status'),
    'volume': ('modules.engine_tools', '_volume_step'),
    'brightness': ('modules.system_control', 'set_brightness_verified'),
    'send_phone': ('modules.filesend', 'handle'),
    'desktop_task': ('modules.desktop_agent', 'handle'),
    'code': ('modules.goal_executor', 'run'),
    'feedback': ('modules.persona', 'request_scope'),
}


def canonical_intent(text: str) -> str:
    """The one intent this sentence's canonical turn hands to the dispatcher (no device runs)."""
    import test_brain_production_entry as fixtures
    _semantic, decision = fixtures.door(text)
    return str(decision.get("intent") or "")


def run_owner_intent(intent: str, args: dict, runtime, text: str) -> str:
    """Execute the validated Core intent with the real dispatcher, at its owner seam."""
    from modules.engine_intents import dispatch
    return dispatch(runtime, intent, dict(args), text, text.casefold())


class ReplacementOwnerInventoryTests(unittest.TestCase):
    def test_every_removed_case_names_a_living_owner(self):
        self.assertEqual(set(CAPABILITY_OWNERS), set(REMOVED_LEGACY_INTENTS))

    def test_each_owner_is_a_real_callable_outside_the_dispatcher(self):
        for intent, (module_name, attribute) in sorted(CAPABILITY_OWNERS.items()):
            with self.subTest(intent=intent):
                self.assertNotEqual(module_name, 'modules.engine_intents')
                module = importlib.import_module(module_name)
                self.assertTrue(callable(getattr(module, attribute)))


class AppAndWindowOwnerTests(unittest.TestCase):
    def test_validated_app_open_delegates_to_the_evidence_backed_launcher(self):
        opened = []

        def launch(_runtime, name):
            opened.append(name)
            return f"{name} açıldı."

        with patch('modules.command_execution.open_app', side_effect=launch):
            out = run_owner_intent('app_open', {'name': 'chrome'}, SimpleNamespace(),
                                   'chrome uygulamasını aç')
        self.assertEqual(canonical_intent('chrome uygulamasını aç'), 'app_open')
        self.assertEqual(opened, ['chrome'])
        self.assertIn('açıldı', out)

    def test_a_sound_sentence_never_reaches_the_app_open_owner(self):
        launch = Mock()
        with patch('modules.command_execution.open_app', launch):
            intent = canonical_intent('sesi aç')
        self.assertEqual(intent, 'audio_action')
        launch.assert_not_called()

    def test_url_owner_opens_the_site_and_audits_it(self):
        from modules import browser
        site = SimpleNamespace(open_url=Mock())
        audit = Mock()
        gate = SimpleNamespace(blocked=lambda _kind: None, audit=audit)
        with patch.object(browser, 'desktop', site), patch.object(browser, 'privacy', gate):
            out = browser.handle('google.com sitesini aç')
        self.assertEqual(out, 'google.com sitesini açtım.')
        site.open_url.assert_called_once_with('https://google.com')
        audit.assert_called_once_with('site açma', 'https://google.com')

    def test_url_owner_stops_when_the_privacy_gate_blocks_the_web(self):
        from modules import browser
        site = SimpleNamespace(open_url=Mock())
        with patch.object(browser, 'desktop', site), \
             patch.object(browser, 'privacy', SimpleNamespace(blocked=lambda _k: 'Web kapalı.', audit=Mock())):
            out = browser.handle('google.com sitesini aç')
        self.assertEqual(out, 'Web kapalı.')
        site.open_url.assert_not_called()


class MailMediaAndTransferOwnerTests(unittest.TestCase):
    def runtime(self, google):
        return SimpleNamespace(google_api=google, ask=None, profile=SimpleNamespace(slug='hamdi'))

    def test_generic_mail_read_goes_to_existing_gmail_worker(self):
        from modules import google_api
        runtime = self.runtime(SimpleNamespace())
        with patch("modules.requests_state.check"), \
             patch.object(google_api, "unread_mail",
                          return_value="3 okunmamış e-postan var.") as gmail:
            output = run_owner_intent("mail_read", {"source": "inbox"}, runtime,
                                      "maillerimi kontrol et")
        self.assertEqual(output, "3 okunmamış e-postan var.")
        gmail.assert_called_once_with()

    def test_business_mail_read_goes_to_existing_outlook_worker(self):
        from modules import outlook, google_api
        runtime = self.runtime(SimpleNamespace())
        with patch("modules.requests_state.check"), \
             patch.object(outlook, "unread_mail",
                          return_value="İş: 2 okunmamış e-postan var.") as work, \
             patch.object(google_api, "unread_mail",
                          side_effect=AssertionError("Gmail must not read")) as gmail:
            output = run_owner_intent("mail_read", {"source": "work"}, runtime,
                                      "iş maillerimi kontrol et")
        self.assertEqual(output, "İş: 2 okunmamış e-postan var.")
        work.assert_called_once_with()
        gmail.assert_not_called()

    def test_media_owner_presses_the_transport_keys(self):
        from modules import media
        for sentence, action in (('sonraki şarkıya geç', 'next'), ('önceki şarkıya dön', 'prev'),
                                 ('müziği durdur', 'play_pause')):
            control = Mock()
            with self.subTest(sentence=sentence):
                out = run_owner_intent('media_action', {'action': action}, SimpleNamespace(system_control=control), sentence)
            self.assertTrue(out)
            control.media_control.assert_called_once_with(action)

    def test_send_phone_owner_resolves_the_file_before_the_transport(self):
        from modules import filesend
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            target = folder / 'rapor.pdf'
            target.write_text('report', encoding='utf-8')
            with patch.object(filesend, '_folders', return_value=[folder]), \
                 patch.object(filesend, 'find', return_value=[target]) as found, \
                 patch.object(filesend, 'send', return_value='Telefona gönderdim: rapor.pdf') as sent:
                out = filesend.handle('rapor dosyasını telefonuma gönder', owner='test-owner')
            self.assertEqual(out, 'Telefona gönderdim: rapor.pdf')
            sent.assert_called_once_with(target)
            found.assert_called_once()

    def test_ambiguous_send_request_asks_instead_of_guessing_a_file(self):
        from modules import filesend
        send = Mock()
        with patch.object(filesend, 'find', side_effect=AssertionError('belirsiz istekte dosya aranmaz')), \
             patch.object(filesend, 'send', send):
            out = filesend.handle('şu dosyayı telefonuma gönder', owner='test-owner')
        self.assertEqual(out, filesend.ASK)
        send.assert_not_called()


class VolumeAndSystemOwnerTests(unittest.TestCase):
    def test_volume_step_reports_only_the_device_readback(self):
        from modules import engine_tools
        readback = {5: 45, 100: None}
        runtime = SimpleNamespace(system_control=SimpleNamespace(
            change_volume_by_delta=lambda delta: readback[delta]))
        self.assertEqual(engine_tools._volume_step(runtime, 5, 'artırdım'),
                         'Ses seviyesini artırdım. Yeni seviye yüzde 45.')
        self.assertEqual(engine_tools._volume_step(runtime, 100, 'artırdım'),
                         'Ses seviyesini değiştiremedim.')

    def test_mute_owner_reports_the_state_the_device_confirms(self):
        control = SimpleNamespace(is_muted=Mock(return_value=False), set_mute=Mock(return_value=True),
                                  current_volume=Mock(return_value=40))
        out = run_owner_intent('audio_action', {'action': 'mute'},
                               SimpleNamespace(system_control=control), 'sessize al')
        self.assertEqual(canonical_intent('sessize al'), 'audio_action')
        self.assertIn('sessizde', out)
        control.set_mute.assert_called_once_with(True)

    def test_mute_owner_does_not_reverse_a_device_refusal(self):
        control = SimpleNamespace(is_muted=Mock(return_value=False), set_mute=Mock(return_value=False))
        out = run_owner_intent('audio_action', {'action': 'mute'},
                               SimpleNamespace(system_control=control), 'sessize al')
        self.assertEqual(out, 'Sesi kapatamadım.')

    def test_screenshot_owner_returns_the_desktop_result(self):
        desktop = SimpleNamespace(screenshot=Mock(return_value='Kaydedildi: C:\\Users\\hamdi\\ekran.png'))
        out = run_owner_intent('screen_capture', {}, SimpleNamespace(desktop=desktop), 'ekran görüntüsü al')
        self.assertEqual(canonical_intent('ekran görüntüsü al'), 'screen_capture')
        self.assertEqual(out, 'Kaydedildi: C:\\Users\\hamdi\\ekran.png')
        desktop.screenshot.assert_called_once_with()

    def test_screen_reading_is_never_handed_to_the_capture_owner(self):
        desktop = SimpleNamespace(screenshot=Mock())
        intent = canonical_intent('ekran görüntüsündeki tabloyu oku')
        self.assertNotEqual(intent, 'screen_capture')
        desktop.screenshot.assert_not_called()

    def test_status_owner_asks_the_desktop(self):
        desktop = SimpleNamespace(system_status=Mock(return_value='CPU %13.1, RAM %56.3, pil %100'))
        out = run_owner_intent('fast_system_status', {}, SimpleNamespace(desktop=desktop), 'sistem durumu')
        self.assertEqual(out, 'CPU %13.1, RAM %56.3, pil %100')
        desktop.system_status.assert_called_once_with()

    def test_shutdown_proposes_confirmation_without_powering_off(self):
        session = SimpleNamespace(pending_confirm=None)
        control = SimpleNamespace(shutdown_pc=Mock(side_effect=AssertionError('kapatma çalışmaz')))
        out = run_owner_intent('shutdown_request', {},
                               SimpleNamespace(_session=lambda: session, system_control=control),
                               'bilgisayarı kapat')
        self.assertEqual(canonical_intent('bilgisayarı kapat'), 'shutdown_request')
        self.assertEqual(session.pending_confirm, 'shutdown')
        self.assertIn('onaylıyor musun', out)

    def test_shutdown_cancel_reaches_the_device_only(self):
        control = SimpleNamespace(cancel_shutdown=Mock(return_value=True))
        out = run_owner_intent('shutdown_cancel', {}, SimpleNamespace(system_control=control),
                               'kapatmayı iptal et')
        self.assertEqual(canonical_intent('kapatmayı iptal'), 'shutdown_cancel')
        self.assertIn('iptal ettim', out)
        control.cancel_shutdown.assert_called_once_with()

    def test_work_and_handoff_lists_keep_their_owners(self):
        from modules import worktrack
        with patch.object(worktrack, 'report', return_value='Son 7 günde 23 mail.') as report:
            out = worktrack.handle('haftalık iş özeti', None)
        report.assert_called_once_with('weekly')
        self.assertEqual(out, 'Son 7 günde 23 mail.')

        from modules import handoff
        added = []
        with patch.object(handoff, 'add', side_effect=lambda text, where, due=None: added.append((text, where))):
            out = handoff.handle('yarın işte sunuma bakayım', 'yarın işte sunuma bakayım')
        self.assertEqual([where for _text, where in added], ['is'])
        self.assertIn('sunum', added[0][0].lower())
        self.assertIn('listesine ekledim', out)


BEHAVIOUR_FEEDBACK = ('Hem bana sürekli haklısın deme, hep haklı olamam ben; '
                      'varsa yanlış onu da söyle yani.')


class ChatBackedRuntime:
    """The smallest runtime the real default arm of dispatch accepts: no vision, canned chat."""

    def __init__(self, profile):
        self.profile = profile
        self.vision = SimpleNamespace(mode=lambda: False)
        self.answers = []
        self.failures = []
        self.os = SimpleNamespace(remove=lambda path: None)

    def _sys_prompt(self, command):
        return 'sys'

    def _session(self):
        return SimpleNamespace()

    def _record_failure(self, where):
        self.failures.append(where)

    def chat(self, command, prompt, user=None):
        self.answers.append(command)
        return 'Anladım, öyle yaparım.'


class FakeFeedbackProfile:
    def __init__(self):
        self.slug = 'alice'
        self.name = 'Alice'
        self.data = {'rules': [], 'facts': [], 'items': [], 'prefs': {}}
        self.saved = 0

    def save(self):
        self.saved += 1


class FeedbackLearningOwnerTests(unittest.TestCase):
    """B09: durable style is owned by the single typed Brain/Core scope, never chat regexes."""

    def setUp(self):
        from modules.personalization import Profile
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.profile=Profile.__new__(Profile);self.profile.slug='alice';self.profile.name='Alice'
        self.profile.path=Path(folder.name)/'alice.json'
        self.profile.data={'name':'Alice','prefs':{},'rules':[],'facts':[],'items':[],'goals':[]}

    def scope(self,runtime):
        from dataclasses import replace
        import test_brain_primary_understanding as primary
        import test_brain_production_entry as fixtures
        from modules import brain_entry,persona
        semantic=primary.applied(BEHAVIOUR_FEEDBACK,primary.envelope(operation='chat',presentation=[{
            'key':'criticism','value':'doğrudan','scope':'explicit','evidence_quote':BEHAVIOUR_FEEDBACK}]))[1]
        semantic=replace(semantic,owner='alice')
        entry=replace(fixtures.entry(brain_entry,semantic=semantic),owner='alice',request_id=semantic.request_id,text=BEHAVIOUR_FEEDBACK,source='yazı')
        return persona.request_scope(runtime,entry,BEHAVIOUR_FEEDBACK)

    def test_a_feedback_sentence_is_routed_as_plain_chat(self):
        # No special intent is needed: the canonical single gate hands the sentence to chat.
        import test_brain_production_entry as fixtures
        _semantic, decision = fixtures.door(BEHAVIOUR_FEEDBACK)
        self.assertEqual(decision['intent'], 'chat')
        self.assertNotIn('feedback', str(decision))

    def test_chat_alone_cannot_capture_unvalidated_feedback(self):
        from modules.engine_intents import dispatch
        runtime = ChatBackedRuntime(self.profile)
        with patch('modules.advisory_router.finalize',side_effect=lambda command,raw,settings=None:raw):
            out = dispatch(runtime, 'chat', {}, BEHAVIOUR_FEEDBACK, BEHAVIOUR_FEEDBACK.casefold())
        self.assertNotIn('presentation_preferences',self.profile.data)
        self.assertEqual(self.profile.data['rules'],[])
        self.assertEqual(out, 'Anladım, öyle yaparım.')

    def test_the_feedback_becomes_a_durable_rule_with_no_dispatch_intent(self):
        from modules.engine_intents import dispatch
        runtime = ChatBackedRuntime(self.profile)
        with patch('modules.advisory_router.finalize',
                   side_effect=lambda command, raw, settings=None: raw),self.scope(runtime):
            out = dispatch(runtime, 'chat', {}, BEHAVIOUR_FEEDBACK, BEHAVIOUR_FEEDBACK.casefold())
        stored = self.profile.data['presentation_preferences']['explicit']['criticism']
        self.assertEqual(stored['value'],'doğrudan')
        self.assertEqual(stored['source'],'user.explicit')
        self.assertIn('otomatik onaylama',self.profile.system_prompt())
        self.assertEqual(out, 'Anladım, öyle yaparım.')
        self.assertEqual(runtime.answers, [BEHAVIOUR_FEEDBACK])

    def test_the_removed_case_was_the_only_writer_of_the_legacy_counter(self):
        from test_brain_orphan_dispatch_guard import INTENTS_FILE, dispatch_case_names
        source = INTENTS_FILE.read_text(encoding='utf-8')
        self.assertNotIn('feedback', dispatch_case_names(source))
        dispatcher = next(node for node in ast.parse(source).body
                          if isinstance(node, ast.FunctionDef) and node.name == 'dispatch')
        self.assertEqual([node.attr for node in ast.walk(dispatcher)
                          if isinstance(node, ast.Attribute) and node.attr == 'feedback'], [],
                         'unreachable profile.feedback +/- sayacı geri geldi')
        # The counter itself stays untouched product surface: schema and reader remain, only the
        # unreachable executor is gone.
        import inspect
        from modules import personalization
        self.assertIn('def feedback(', inspect.getsource(personalization.Profile))

    def test_preference_save_failure_propagates_and_does_not_claim_persistence(self):
        runtime = ChatBackedRuntime(self.profile)
        with patch.object(self.profile,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError),self.scope(runtime):
                self.fail('save failure cannot enter the reply')
        self.assertNotIn('presentation_preferences',self.profile.data)
        self.assertEqual(runtime.answers,[])


if __name__ == '__main__':
    unittest.main()
