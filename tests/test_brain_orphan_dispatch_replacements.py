"""Living owners for the producer-less dispatch cases removed from modules/engine_intents.py.

test_brain_orphan_dispatch_guard.py proves the dispatcher no longer holds the case; every test
here proves the same user behaviour still runs through its canonical owner. Each owner is called
at its own seam with the device, browser, mail, transfer and task effects mocked, so nothing in
this file touches a real PC.
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

import engine_source
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
    'mail': ('modules.engine_tools', '_mail_handle'),
    'media': ('modules.media', 'handle'),
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
    'feedback': ('modules.learning_feedback', 'capture'),
}


def run_branch(marker, namespace, guard_variable='skip'):
    """Execute one real branch of engine_commands.handle, with its guard assignment when named."""
    handle = next(node for node in engine_source.tree().body
                  if isinstance(node, ast.FunctionDef) and node.name == 'handle')
    start = 0
    if guard_variable != 'skip':
        start = next(i for i, item in enumerate(handle.body) if isinstance(item, ast.Assign)
                     and any(getattr(target, 'id', '') == guard_variable for target in item.targets))
    end = next(i for i, item in enumerate(handle.body[start:], start)
               if isinstance(item, ast.If) and marker in ast.unparse(item))
    branch = [handle.body[end]] if guard_variable == 'skip' else handle.body[start:end + 1]
    body = branch + [ast.Return(value=ast.Constant(value=None))]
    fn = ast.FunctionDef(name='run_branch', args=ast.arguments(
        posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=body, decorator_list=[])
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[fn], type_ignores=[])), 'real-engine-branch', 'exec'), namespace)
    return namespace['run_branch']()


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
    def test_app_open_grammar_delegates_to_the_evidence_backed_launcher(self):
        opened = []

        def launch(_runtime, name):
            opened.append(name)
            return f"{name} açıldı."

        with patch('modules.command_execution.open_app', side_effect=launch):
            out = run_branch('open_app(', {'cmd_lower': 'not defterini aç', 're': re,
                                           'runtime': SimpleNamespace()}, guard_variable='om')
        self.assertEqual(opened, ['not defterini'])
        self.assertIn('açıldı', out)

    def test_app_open_grammar_leaves_a_media_word_request_to_its_owner(self):
        launch = Mock()
        with patch('modules.command_execution.open_app', launch):
            out = run_branch('open_app(', {'cmd_lower': 'sesi aç', 're': re,
                                           'runtime': SimpleNamespace()}, guard_variable='om')
        self.assertIsNone(out)
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

    def test_generic_mail_check_goes_to_the_gmail_owner(self):
        from modules import engine_tools, meeting_prep, outlook
        google = SimpleNamespace(handle=Mock(return_value='3 okunmamış e-postan var.'),
                                 _MAIL_CHECK=re.compile(r'mail'))
        with patch.object(meeting_prep, 'asked', return_value=False), \
             patch.object(outlook, 'draft_handle', return_value=None), \
             patch.object(outlook, 'handle', return_value=None), \
             patch.object(outlook, 'installed', return_value=False):
            out = engine_tools._mail_handle(self.runtime(google), 'maillerimi kontrol et')
        self.assertEqual(out, '3 okunmamış e-postan var.')
        google.handle.assert_called_once_with('maillerimi kontrol et')

    def test_business_mail_check_goes_to_the_outlook_owner(self):
        from modules import engine_tools, meeting_prep, outlook
        google = SimpleNamespace(handle=Mock(side_effect=AssertionError('gmail okunmaz')), _MAIL_CHECK=re.compile(r'mail'))
        with patch.object(meeting_prep, 'asked', return_value=False), \
             patch.object(outlook, 'draft_handle', return_value=None), \
             patch.object(outlook, 'handle', return_value='İş: 2 okunmamış e-postan var.'), \
             patch.object(outlook, 'installed', return_value=True):
            out = engine_tools._mail_handle(self.runtime(google), 'iş maillerimi kontrol et')
        self.assertEqual(out, 'İş: 2 okunmamış e-postan var.')

    def test_media_owner_presses_the_transport_keys(self):
        from modules import media
        for sentence, action in (('sonraki şarkıya geç', 'next'), ('önceki şarkıya dön', 'prev'),
                                 ('müziği durdur', 'play_pause')):
            control = Mock()
            with self.subTest(sentence=sentence), patch.object(media, 'system_control', control):
                out = media.handle(sentence)
            self.assertTrue(out)
            control.media_control.assert_called_once_with(action)

    def test_send_phone_owner_resolves_the_file_before_the_transport(self):
        from modules import filesend
        target = Path('rapor.pdf')
        pending = {'t': 0, 'files': []}
        with patch.object(filesend, '_pending', pending), \
             patch.object(filesend, 'find', return_value=[target]) as found, \
             patch.object(filesend, 'send', return_value='Telefona gönderdim: rapor.pdf') as sent:
            out = filesend.handle('rapor dosyasını telefonuma gönder')
        self.assertEqual(out, 'Telefona gönderdim: rapor.pdf')
        sent.assert_called_once_with(target)
        found.assert_called_once()

    def test_ambiguous_send_request_asks_instead_of_guessing_a_file(self):
        from modules import filesend
        send = Mock()
        with patch.object(filesend, '_pending', {'t': 0, 'files': []}), \
             patch.object(filesend, 'find', side_effect=AssertionError('belirsiz istekte dosya aranmaz')), \
             patch.object(filesend, 'send', send):
            out = filesend.handle('şu dosyayı telefonuma gönder')
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
        control = SimpleNamespace(is_muted=Mock(return_value=False), set_mute=Mock(return_value=True))
        out = run_branch('set_mute(True)', {'cmd_lower': 'sessize al', 're': re, '_numbers': lambda _t: [],
                                            'system_control': control})
        self.assertIn('sessizde', out)
        control.set_mute.assert_called_once_with(True)

    def test_mute_owner_does_not_reverse_a_device_refusal(self):
        control = SimpleNamespace(is_muted=Mock(return_value=False), set_mute=Mock(return_value=False))
        out = run_branch('set_mute(True)', {'cmd_lower': 'sessize al', 're': re, '_numbers': lambda _t: [],
                                            'system_control': control})
        self.assertEqual(out, 'Sesi kapatamadım.')

    def test_screenshot_fast_path_returns_the_desktop_owner_result(self):
        desktop = SimpleNamespace(screenshot=Mock(return_value='Kaydedildi: C:\\Users\\hamdi\\ekran.png'))
        out = run_branch('screenshot', {'cmd_lower': 'ekran görüntüsü al', 'desktop': desktop},
                         guard_variable='wants_analysis')
        self.assertEqual(out, 'Kaydedildi: C:\\Users\\hamdi\\ekran.png')
        desktop.screenshot.assert_called_once_with()

    def test_screen_reading_stays_with_the_analysis_owner(self):
        desktop = SimpleNamespace(screenshot=Mock())
        out = run_branch('screenshot', {'cmd_lower': 'ekran görüntüsündeki tabloyu oku', 'desktop': desktop},
                         guard_variable='wants_analysis')
        self.assertIsNone(out)
        desktop.screenshot.assert_not_called()

    def test_status_fast_path_asks_the_desktop_owner(self):
        desktop = SimpleNamespace(system_status=Mock(return_value='CPU %13.1, RAM %56.3, pil %100'))
        out = run_branch('system_status', {'cmd_lower': 'sistem durumu', 'desktop': desktop})
        self.assertEqual(out, 'CPU %13.1, RAM %56.3, pil %100')
        desktop.system_status.assert_called_once_with()

    def test_shutdown_grammar_proposes_confirmation_without_powering_off(self):
        session = SimpleNamespace(pending_confirm=None)
        out = run_branch("pending_confirm = 'shutdown'",
                         {'cmd_lower': 'bilgisayarı kapat', '_session': lambda: session})
        self.assertEqual(session.pending_confirm, 'shutdown')
        self.assertIn('onaylıyor musun', out)

    def test_shutdown_cancel_grammar_reaches_the_device_only(self):
        control = SimpleNamespace(cancel_shutdown=Mock(return_value=True))
        out = run_branch('cancel_shutdown', {'cmd_lower': 'kapatmayı iptal et', 'system_control': control})
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
    """The removed ``feedback`` case added nothing the canonical chat path does not already do.

    Its live behaviour - promoting a direct instruction about Jarvis' own response style into a
    durable rule - is owned by ``learning_feedback.capture``, which the default arm of dispatch
    already calls on every non-command sentence. The unreachable ``profile.feedback`` +/- counter
    is deliberately not resurrected: no new intent, classifier or compatibility mapper is created
    for it, and the profile schema, stored records and web presentation field stay as they are.
    """

    def test_a_feedback_sentence_is_routed_as_plain_chat(self):
        # No special intent is needed: the canonical single gate hands the sentence to chat.
        import test_brain_production_entry as fixtures
        _semantic, decision = fixtures.door(BEHAVIOUR_FEEDBACK)
        self.assertEqual(decision['intent'], 'chat')
        self.assertNotIn('feedback', str(decision))

    def test_the_chat_default_arm_captures_the_feedback_of_its_own_turn(self):
        from modules.engine_intents import dispatch
        captured = []
        runtime = ChatBackedRuntime(FakeFeedbackProfile())
        with patch('modules.learning_feedback.capture',
                   side_effect=lambda profile, text: captured.append((profile, text)) or []):
            out = dispatch(runtime, 'chat', {}, BEHAVIOUR_FEEDBACK, BEHAVIOUR_FEEDBACK.casefold())
        self.assertEqual([text for _profile, text in captured], [BEHAVIOUR_FEEDBACK])
        self.assertEqual(captured[0][0], runtime.profile)
        self.assertEqual(out, 'Anladım, öyle yaparım.')

    def test_the_feedback_becomes_a_durable_rule_with_no_dispatch_intent(self):
        from modules import learning
        from modules.engine_intents import dispatch
        runtime = ChatBackedRuntime(FakeFeedbackProfile())
        with patch('modules.advisory_router.finalize',
                   side_effect=lambda command, raw, settings=None: raw):
            # The real capture, not a mock: this is the user-visible behaviour being kept alive.
            out = dispatch(runtime, 'chat', {}, BEHAVIOUR_FEEDBACK, BEHAVIOUR_FEEDBACK.casefold())
        stored = learning.rules(runtime.profile)
        self.assertTrue(stored, 'davranış geri bildirimi kural olarak saklanmadı')
        self.assertIn('otomatik onaylama', ' '.join(stored))
        self.assertIn('yanlışsa açıkça söyle', ' '.join(stored))
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

    def test_capture_failure_is_recorded_instead_of_silently_swallowed(self):
        from modules.engine_intents import dispatch
        runtime = ChatBackedRuntime(FakeFeedbackProfile())
        with patch('modules.learning_feedback.capture', side_effect=RuntimeError('boom')):
            out = dispatch(runtime, 'chat', {}, BEHAVIOUR_FEEDBACK, BEHAVIOUR_FEEDBACK.casefold())
        self.assertIn('modules/engine_intents.py:learning_feedback', runtime.failures)
        self.assertEqual(out, 'Anladım, öyle yaparım.')


if __name__ == '__main__':
    unittest.main()
