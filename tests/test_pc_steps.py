"""Visible PC-control steps and the separate whole-PC mute bridge."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import engine_output
from modules.pc_steps import ReportedControl


class ReportedControlTests(unittest.TestCase):
    def test_nonempty_failure_message_is_not_success(self):
        control, sent = self.control(open_application=Mock(return_value='Uygulamayı açamadım.'))
        control.open_application('paint')
        self.assertEqual(sent[-1][1], 'error')

    def test_only_explicit_verified_application_evidence_is_done(self):
        class Evidence(str):
            ok = True
        control, sent = self.control(open_application=Mock(return_value=Evidence('Pencere açık.')))
        control.open_application('paint')
        self.assertEqual(sent[-1][1], 'done')
    def control(self, **functions):
        sent = []
        module = SimpleNamespace(installed_apps=lambda: {'paint': ()}, **functions)
        return ReportedControl(module, lambda *a: sent.append(a)), sent

    def test_action_reports_working_then_done_with_same_step(self):
        control, sent = self.control(set_volume=Mock(return_value=True))
        self.assertTrue(control.set_volume(30))
        control._module.set_volume.assert_called_once_with(30)
        self.assertEqual([s[1] for s in sent], ['working', 'done'])
        self.assertEqual(sent[0][0], 'Ses yüzde 30 yapılıyor')
        self.assertEqual(sent[0][2], sent[1][2])

    def test_failed_and_raising_actions_are_reported_as_errors(self):
        control, sent = self.control(set_mute=Mock(return_value=False), close_application=Mock(return_value=None),
                                     open_application=Mock(side_effect=OSError('x')))
        self.assertFalse(control.set_mute(True))
        self.assertIsNone(control.close_application('paint'))
        with self.assertRaises(OSError):
            control.open_application('paint')
        self.assertEqual([s[1] for s in sent if s[1] != 'working'], ['error', 'error', 'error'])
        self.assertEqual(sent[0][0], 'Bilgisayarın sesi kapatılıyor')

    def test_unlisted_attributes_pass_through_and_reporting_never_blocks(self):
        module = SimpleNamespace(installed_apps=Mock(return_value={}), shutdown_pc=Mock(return_value=None))
        control = ReportedControl(module, Mock(side_effect=RuntimeError('screen gone')))
        self.assertIs(control.installed_apps, module.installed_apps)
        self.assertIsNone(control.shutdown_pc())
        module.shutdown_pc.assert_called_once_with()

    def test_step_event_carries_request_and_owner(self):
        ui = Mock()
        ui.event_metadata = True
        profile = SimpleNamespace(slug='hamdi', name='Hamdi')
        runtime = SimpleNamespace(pc_profile=lambda: profile, profile=profile, _cur_rid='r1', _guest=None, _ui=ui,
                                  _record_failure=Mock())
        engine_output.emit(runtime, 'step', 'Ses kısılıyor', 'done|s1|')
        ui.assert_called_once_with('step', 'Ses kısılıyor', 'done|s1|', metadata={'user': 'hamdi', 'rid': 'r1'})

    def test_model_route_becomes_step_lines(self):
        runtime = SimpleNamespace(_llm=SimpleNamespace(take_route=lambda: [('Gemini kotası dolu', False), ('Cevap: Groq', True)]),
                                  emit=Mock(), _record_failure=Mock())
        engine_output._emit_route(runtime)
        self.assertEqual([c.args for c in runtime.emit.call_args_list],
                         [('step', 'Gemini kotası dolu', 'error|m1|'), ('step', 'Cevap: Groq', 'done|m2|')])

    def test_phone_guest_steps_stay_off_the_pc_screen(self):
        ui = Mock()
        ui.event_metadata = True
        pc, phone = SimpleNamespace(slug='hamdi', name='Hamdi'), SimpleNamespace(slug='ebru', name='Ebru')
        runtime = SimpleNamespace(pc_profile=lambda: pc, profile=phone, _cur_rid='r2', _guest='ebru', _ui=ui,
                                  _record_failure=Mock())
        engine_output.emit(runtime, 'step', 'Ses kısılıyor', 'done|s1|')
        ui.assert_not_called()


class PcMuteBridgeTests(unittest.TestCase):
    def bridge(self, **functions):
        """Real WebVoice with a fake Windows audio module (no pycaw/pyautogui needed)."""
        import sys
        import modules
        from web_voice import WebVoice
        fake = SimpleNamespace(**functions)
        self.enterContext(patch.dict(sys.modules, {'modules.system_control': fake}))
        self.enterContext(patch.object(modules, 'system_control', fake, create=True))
        return WebVoice(), fake

    def test_mute_sets_whole_pc_and_reports_state(self):
        bridge, fake = self.bridge(set_mute=Mock(return_value=True), is_muted=Mock(return_value=True))
        self.assertEqual(bridge.pc_mute(True), {'muted': True})
        fake.set_mute.assert_called_once_with(True)

    def test_mute_failure_is_a_clear_error(self):
        bridge, _ = self.bridge(set_mute=Mock(return_value=False), is_muted=Mock())
        with self.assertRaisesRegex(ValueError, 'Bilgisayarın sesi'):
            bridge.pc_mute(False)

    def test_state_reads_without_changing(self):
        bridge, fake = self.bridge(set_mute=Mock(), is_muted=Mock(return_value=None))
        self.assertEqual(bridge.pc_mute_state(), {'muted': None})
        fake.set_mute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
