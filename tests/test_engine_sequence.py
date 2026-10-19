"""Direct tests for the three EngineContext-bound sequence handlers; no real timer or device."""
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from modules import engine_sequence as sequence
from modules.command_manager import PENDING_INPUT_FIELDS


class EngineSequenceTests(unittest.TestCase):
    def setUp(self):
        # Only the dependencies used by these handlers; no EngineContext startup,
        # background workers, disk, network, or physical desktop is required.
        self.session = SimpleNamespace(**{name: None for name in PENDING_INPUT_FIELDS},
                                       _in_multi=False, speech_override='old step speech')
        self.timer = Mock()
        self.runtime = SimpleNamespace(
            re=re,
            # Same command grammar supplied by engine_runtime._initialize.
            _STEP_SPLIT=re.compile(r'\s*(?:,\s*)?(?:ve\s+)?(?:daha\s+)?(?:sonra|ardından|akabinde)\s*,?\s+', re.I),
            _session=Mock(return_value=self.session), profile=SimpleNamespace(slug='alice'),
            flags={}, stop_event=Mock(), handle=Mock(return_value='Tamam'),
            privacy=SimpleNamespace(audit=Mock()), emit=Mock(),
            threading=SimpleNamespace(Timer=Mock(return_value=self.timer)))
        self.runtime.stop_event.is_set.return_value = False

    def assert_clean(self):
        self.assertIs(self.session._in_multi, False)
        self.assertIsNone(self.session.speech_override)

    def test_split_steps_understands_documented_sequence_forms_and_preserves_order(self):
        for command in ('önce maili oku, sonra raporu yaz', 'maili oku ardından raporu yaz',
                        'maili oku akabinde raporu yaz', 'ÖNCE maili oku SONRA raporu yaz',
                        ' önce maili oku, ve daha sonra, raporu yaz. '):
            with self.subTest(command=command):
                self.assertEqual(sequence._split_steps(self.runtime, command), ['maili oku', 'raporu yaz'])

    def test_split_steps_returns_none_for_single_empty_or_unmarked_commands(self):
        for command in ('', '   ', 'maili oku', 'önce maili oku', 'önce', 'sonra raporu yaz',
                        'maili oku ve raporu yaz', 'aç ardından x', 'önce abc sonra xy'):
            with self.subTest(command=command):
                self.assertIsNone(sequence._split_steps(self.runtime, command))

    def test_split_steps_filters_short_parts_and_keeps_three_character_boundary(self):
        self.assertEqual(sequence._split_steps(self.runtime, 'önce ab sonra abc ardından def'), ['abc', 'def'])
        self.assertEqual(sequence._split_steps(self.runtime, 'önce abc sonra def'), ['abc', 'def'])

    def test_split_steps_caps_six_or_more_steps_at_five(self):
        for count in (2, 5, 6, 100):
            with self.subTest(count=count):
                steps = [f'adım {index}' for index in range(count)]
                command = 'önce ' + ' sonra '.join(steps)
                self.assertEqual(sequence._split_steps(self.runtime, command), steps[:5])

    def test_split_steps_keeps_long_valid_text_without_truncating_each_step(self):
        long_step = 'ğ' * 100000
        self.assertEqual(sequence._split_steps(self.runtime, 'önce ' + long_step + ' sonra bitir'),
                         [long_step, 'bitir'])

    def test_split_steps_invalid_types_raise_without_executing_anything(self):
        for command in (None, True, 12, b'abc', [], {}):
            with self.subTest(command=command), self.assertRaises(TypeError):
                sequence._split_steps(self.runtime, command)
        self.runtime.handle.assert_not_called()
        self.runtime.emit.assert_not_called()
        self.runtime.threading.Timer.assert_not_called()

    def test_run_steps_uses_runtime_and_session_sequentially_and_clears_single_step_speech(self):
        def handle(command):
            self.assertTrue(self.session._in_multi)
            self.session.speech_override = command
            return 'cevap ' + command
        self.runtime.handle.side_effect = handle
        self.assertEqual(sequence._run_steps(self.runtime, ['oku', 'yaz']), '1. cevap oku\n2. cevap yaz')
        self.assertEqual(self.runtime.handle.call_args_list, [call('oku'), call('yaz')])
        self.runtime.privacy.audit.assert_called_once_with('çok adımlı komut', '2 adım')
        self.assert_clean()

    def test_run_steps_empty_list_is_noop_with_cleanup_and_zero_step_audit(self):
        self.assertEqual(sequence._run_steps(self.runtime, []), '')
        self.runtime.handle.assert_not_called()
        self.runtime.privacy.audit.assert_called_once_with('çok adımlı komut', '0 adım')
        self.assert_clean()

    def test_run_steps_long_single_step_is_passed_intact(self):
        command = 'oku ' + 'ş' * 100000
        self.assertEqual(sequence._run_steps(self.runtime, [command]), '1. Tamam')
        self.runtime.handle.assert_called_once_with(command)
        self.assert_clean()

    def test_run_steps_invalid_container_raises_but_finally_resets_mutable_session(self):
        for steps in (None, 123, True):
            with self.subTest(steps=steps):
                self.session.speech_override = 'stale'
                with self.assertRaises(TypeError):
                    sequence._run_steps(self.runtime, steps)
                self.assert_clean()
        self.runtime.handle.assert_not_called()
        self.runtime.privacy.audit.assert_not_called()

    def test_run_steps_handler_error_does_not_run_remaining_and_always_cleans_up(self):
        for error in (TypeError('invalid command'), RuntimeError('failed'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.runtime.handle.reset_mock()
                self.runtime.handle.side_effect = error
                self.session.speech_override = 'stale'
                with self.assertRaises(type(error)):
                    sequence._run_steps(self.runtime, [None, 'never execute'])
                self.runtime.handle.assert_called_once_with(None)
                self.assert_clean()
        self.runtime.privacy.audit.assert_not_called()

    def test_run_steps_unverified_application_result_stops_dependent_steps(self):
        class Reply(str):
            ok = False
        self.runtime.handle.return_value = Reply('Pencere doğrulanmadı')
        result = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
        self.assertIn('1. Pencere doğrulanmadı', result)
        self.assertIn('Bu adım doğrulanamadı', result)
        self.assertIn('kalan adımları çalıştırmadım', result)
        self.runtime.handle.assert_called_once_with('ilk')
        self.assert_clean()

    def test_run_steps_verified_and_plain_text_results_can_continue(self):
        class Reply(str):
            ok = True
        self.runtime.handle.side_effect = [Reply('Doğrulandı'), 'Yerel sonuç']
        self.assertEqual(sequence._run_steps(self.runtime, ['ilk', 'ikinci']), '1. Doğrulandı\n2. Yerel sonuç')
        self.assertEqual(self.runtime.handle.call_count, 2)
        self.assert_clean()

    def test_run_steps_closing_or_stopped_before_start_does_not_execute(self):
        for closing, stopped in ((True, False), (False, True)):
            with self.subTest(closing=closing, stopped=stopped):
                self.runtime.flags['closing'] = closing
                self.runtime.stop_event.is_set.return_value = stopped
                result = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
                self.assertIn('Jarvis kapanıyor', result)
                self.runtime.handle.assert_not_called()
                self.assert_clean()

    def test_run_steps_closing_or_stopped_during_step_does_not_execute_next(self):
        for condition in ('closing', 'stop'):
            with self.subTest(condition=condition):
                self.runtime.flags.clear()
                self.runtime.stop_event.is_set.return_value = False
                self.runtime.handle.reset_mock()
                def handle(command):
                    if condition == 'closing':
                        self.runtime.flags['closing'] = True
                    else:
                        self.runtime.stop_event.is_set.return_value = True
                    return 'ilk sonuç'
                self.runtime.handle.side_effect = handle
                result = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
                self.assertIn('1. ilk sonuç', result)
                self.assertIn('Jarvis kapanıyor', result)
                self.runtime.handle.assert_called_once_with('ilk')
                self.assert_clean()

    def test_run_steps_owner_change_stops_cross_user_execution(self):
        def change_owner(command):
            self.runtime.profile.slug = 'bob'
            return 'ilk sonuç'
        self.runtime.handle.side_effect = change_owner
        result = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
        self.assertIn('Kullanıcı değişti', result)
        self.runtime.handle.assert_called_once_with('ilk')
        self.assert_clean()

    def test_run_steps_all_pending_input_fields_stop_without_consuming_answer_or_approval(self):
        for field in PENDING_INPUT_FIELDS:
            with self.subTest(field=field):
                self.runtime.handle.reset_mock()
                def wait(command):
                    setattr(self.session, field, {'request': 'waiting'})
                    return 'Onay gerekli'
                self.runtime.handle.side_effect = wait
                try:
                    result = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
                    self.assertIn('yanıt veya onay bekliyor', result)
                    self.runtime.handle.assert_called_once_with('ilk')
                    self.assertEqual(getattr(self.session, field), {'request': 'waiting'})
                    self.assert_clean()
                finally:
                    setattr(self.session, field, None)

    def test_close_jarvis_marks_closing_emits_notice_and_schedules_only_supplied_stop_callback(self):
        self.runtime.flags['unrelated'] = 'preserve'
        result = sequence._close_jarvis(self.runtime)
        self.assertIs(self.runtime.flags['closing'], True)
        self.assertEqual(self.runtime.flags['unrelated'], 'preserve')
        self.assertEqual(result, "Jarvis'i kapatıyorum. Bilgisayar açık kalacak.")
        self.runtime.emit.assert_called_once_with('activity', 'Jarvis kapatma istendi',
            'working|Jarvis|Yalnızca Jarvis uygulaması kapanacak; bilgisayar açık kalacak.')
        self.runtime.threading.Timer.assert_called_once_with(1.8, self.runtime.stop_event.set)
        self.timer.start.assert_called_once_with()
        self.runtime.stop_event.set.assert_not_called()
        self.runtime.handle.assert_not_called()

    def test_close_jarvis_invalid_runtime_or_flags_fails_without_scheduling_timer(self):
        with self.assertRaises(AttributeError):
            sequence._close_jarvis(None)
        self.runtime.flags = None
        with self.assertRaises(TypeError):
            sequence._close_jarvis(self.runtime)
        self.runtime.threading.Timer.assert_not_called()
        self.runtime.emit.assert_not_called()

    def test_close_jarvis_timer_start_error_is_not_reported_as_success(self):
        self.timer.start.side_effect = RuntimeError('timer unavailable')
        with self.assertRaisesRegex(RuntimeError, 'timer unavailable'):
            sequence._close_jarvis(self.runtime)
        self.assertIs(self.runtime.flags['closing'], True)
        self.runtime.stop_event.set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
