"""Direct tests for the three EngineContext-bound sequence handlers; no real timer or device."""
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def drive(self, steps, replies=None):
        """_run_steps'i canonical adım envelope'ı üzerinden ölçer; gerçek motor/etki yok."""
        from modules import brain_entry
        replies = replies or {}
        calls = []

        def fake_run_step(runtime, text):
            calls.append(text)
            reply = replies.get(text, (f'{text} bitti', SimpleNamespace(result_status='handled')))
            return reply
        with patch.object(brain_entry, 'run_step', side_effect=fake_run_step):
            return calls, sequence._run_steps(self.runtime, steps)

    def test_run_steps_never_reinterprets_a_step_through_the_engine(self):
        self.runtime.handle.side_effect = AssertionError('adım metni ikinci kez yorumlanamaz')
        calls, out = self.drive(['oku', 'yaz'])
        self.assertIsInstance(out, str)
        self.assertEqual(calls, ['oku', 'yaz'])
        self.runtime.handle.assert_not_called()

    def test_run_steps_runs_every_step_in_order_and_reports_each_reply(self):
        calls, out = self.drive(['maili oku', 'raporu yaz', 'notu aç'])
        self.assertEqual(calls, ['maili oku', 'raporu yaz', 'notu aç'])
        self.assertEqual(out.splitlines(), ['1. maili oku bitti', '2. raporu yaz bitti', '3. notu aç bitti'])
        self.runtime.privacy.audit.assert_called_once_with('çok adımlı komut', '3 adım')
        self.runtime.emit.assert_not_called()

    def test_run_steps_uses_the_canonical_step_envelope_for_every_step(self):
        with patch('modules.brain_entry.run_step', return_value=('tamam', SimpleNamespace(result_status='handled'))) as step:
            sequence._run_steps(self.runtime, ['oku', 'yaz'])
        self.assertEqual([row.args[1] for row in step.call_args_list], ['oku', 'yaz'])
        self.assertEqual([row.args[0] for row in step.call_args_list], [self.runtime, self.runtime])

    def test_run_steps_invents_no_step_result(self):
        _calls, out = self.drive(['raporu özetle', 'pdf çevir'],
                               {'raporu özetle': ('ÖZETLENDİ', SimpleNamespace(result_status='handled')),
                                'pdf çevir': ('ÇEVRİLDİ', SimpleNamespace(result_status='handled'))})
        self.assertEqual(out.splitlines(), ['1. ÖZETLENDİ', '2. ÇEVRİLDİ'])
        self.assertNotIn('Tamam', out)
        self.assertNotIn('CEVAP', out)

    def test_run_steps_empty_list_is_noop_with_zero_step_audit(self):
        calls, out = self.drive([])
        self.assertEqual(calls, [])
        self.assertEqual(out, '')
        self.runtime.privacy.audit.assert_called_once_with('çok adımlı komut', '0 adım')

    def test_run_steps_long_single_step_is_passed_intact(self):
        command = 'oku ' + 'ş' * 100000
        self.assertIn(command, self.drive([command])[1])

    def test_run_steps_clears_the_step_speech_and_the_multi_marker(self):
        from modules import brain_entry
        def step(runtime, text):
            self.session.speech_override = 'yalnız bu adım'
            return ('cevap', SimpleNamespace(result_status='handled'))
        with patch.object(brain_entry, 'run_step', side_effect=step):
            sequence._run_steps(self.runtime, ['oku', 'yaz'])
        self.assertIs(self.session._in_multi, False)
        self.assertIsNone(self.session.speech_override)

    def test_run_steps_invalid_container_raises_without_auditing(self):
        for steps in (None, 123, True):
            with self.subTest(steps=steps), patch('modules.brain_entry.run_step',
                                                  side_effect=AssertionError('adım çalışmamalı')):
                with self.assertRaises(TypeError):
                    sequence._run_steps(self.runtime, steps)
        self.runtime.handle.assert_not_called()
        self.runtime.privacy.audit.assert_not_called()
        self.assertIs(self.session._in_multi, False)

    def test_closing_runtime_stops_before_the_first_step(self):
        self.runtime.flags['closing'] = True
        calls, out = self.drive(['ilk', 'ikinci'])
        self.assertEqual(calls, [])
        self.assertIn('kalan adımları', out)

    def test_owner_change_after_a_step_stops_the_chain(self):
        from modules import brain_entry
        def switch(runtime, text):
            self.runtime.profile.slug = 'bob'
            return ('ilk bitti', SimpleNamespace(result_status='handled'))
        with patch.object(brain_entry, 'run_step', side_effect=switch):
            out = sequence._run_steps(self.runtime, ['ilk', 'ikinci'])
        self.assertIn('Kullanıcı değişti', out)
        self.assertNotIn('ikinci', out)

    def test_pending_answer_opened_by_a_step_stops_the_chain_and_is_not_consumed(self):
        self.session.pending_confirm = {'request': 'waiting'}
        calls, out = self.drive(['ilk', 'ikinci'])
        self.assertEqual(calls, ['ilk'])
        self.assertIn('yanıt veya onay bekliyor', out)
        self.assertEqual(self.session.pending_confirm, {'request': 'waiting'})
        self.runtime.handle.assert_not_called()

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
