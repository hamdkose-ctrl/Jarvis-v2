"""Desktop action evidence, interruption and approval ownership; native OS is simulated."""
import copy
import json
from itertools import chain, repeat
from pathlib import Path
import tempfile
import time
import sys
import types
import unittest
from unittest.mock import Mock, patch, MagicMock
if 'pyautogui' not in sys.modules:
    keyboard = types.ModuleType('pyautogui')
    keyboard.__getattr__ = lambda _: MagicMock()
    sys.modules['pyautogui'] = keyboard
from modules import desktop_agent as agent, desktop_uia as uia, requests_state


def screen(value='12', button='Topla'):
    return {'hwnd': 10, 'pid': 20, 'title': 'Hesap Makinesi', 'app': 'calculatorapp', 'controls': [
        {'id': 'display', 'name': 'Sonuç', 'value': value, 'type': 'ControlType.Text', 'selected': None,
         'patterns': [], 'enabled': True, 'password': False, 'automation_id': 'display'},
        {'id': 'button', 'name': button, 'value': '', 'type': 'ControlType.Button', 'selected': None,
         'patterns': ['invoke'], 'enabled': True, 'password': False, 'automation_id': 'sum'}]}


def action(value='19'):
    return {'op': 'invoke', 'control': 'button', 'expect': {'control': 'display', 'field': 'value', 'equals': value}}


class FakeUI:
    def __init__(self, before=None, changes=True):
        self.screen = before or screen()
        self.changes = changes
        self.calls = []

    def observe(self, *args):
        return copy.deepcopy(self.screen)

    def act(self, snapshot, step):
        self.calls.append(copy.deepcopy(step))
        if self.changes:
            self.screen['controls'][0]['value'] = step['expect']['equals']
        return {'ok': True, 'sent': True}


class DesktopTasksTests(unittest.TestCase):
    def test_operator_uses_new_visible_expression_while_result_stays_same(self):
        before = screen()
        before['controls'][0].update(name='Ekran değeri 12', value='')
        before['controls'].append({'id': 'expression', 'name': 'İfade değeri ', 'value': '',
            'offscreen': True, 'patterns': [], 'enabled': True, 'password': False,
            'type': 'ControlType.Text', 'automation_id': 'CalculatorExpression'})
        step = {'op': 'invoke', 'control': 'button',
                'expect': {'control': 'expression', 'field': 'name', 'equals': 'İfade değeri 12 +'}}
        self.assertEqual(agent.validate(before, step), step)
        after = copy.deepcopy(before)
        after['controls'][2].update(name='İfade değeri 12 +', offscreen=False)
        self.assertTrue(agent.expected(after, step['expect']))
        self.assertEqual(after['controls'][0], before['controls'][0])
        after['controls'][2]['offscreen'] = True
        self.assertFalse(agent.expected(after, step['expect']))
        self.assertFalse(agent.expected(after, {'text': 'İfade değeri 12 +'}))
        with self.assertRaises(ValueError):
            agent.validate(before, {'op': 'invoke', 'control': 'expression', 'expect': step['expect']})
        with self.assertRaises(ValueError):
            agent.validate(before, {'op': 'invoke', 'control': 'button',
                'expect': {'control': 'display', 'field': 'name', 'equals': 'Ekran değeri 12'}})
    def test_secret_labelled_value_is_not_sent_to_model(self):
        self.ui.screen['controls'][1].update(name='API key', value='unrecognizable-sensitive-value')
        self.plans({'op': 'ask', 'question': 'Alanı kendin gir'})
        self.run_job()
        self.assertNotIn('unrecognizable-sensitive-value', self.ask.call_args.args[0])
        self.assertIn('Gizli bilgi alanı', self.ask.call_args.args[0])
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(agent, 'STORE', Path(temporary.name)))
        self.enterContext(patch.object(agent.privacy, 'blocked', return_value=None))
        self.enterContext(patch.object(agent.time, 'sleep'))
        self.ask = self.enterContext(patch.object(agent.llm, 'ask'))
        self.ui = FakeUI()
        self.job = {'owner': 'alice', 'target': 'Hesap Makinesi', 'goal': '12 ile 7 topla',
                    'status': 'running', 'history': [], 'hwnd': None, 'approval': None, 'pending_effect': None}
        self.events = []

    def plans(self, *steps):
        self.ask.side_effect = [json.dumps(s) for s in steps]

    def run_job(self, **kwargs):
        return agent.run(self.job, ui=self.ui, emit=lambda *a: self.events.append(a), current=lambda: 'alice', **kwargs)

    def test_real_result_readback_required_before_job_is_done(self):
        self.plans(action(), {'op': 'finish', 'expect': action()['expect'], 'message': '19 elde edildi.'})
        self.run_job()
        self.assertEqual(self.job['status'], 'done')
        self.assertEqual(len(self.ui.calls), 1)
        self.assertTrue(self.job['history'][0]['verified'])
        self.assertEqual(agent._load('alice')['status'], 'done')
        self.assertIn('19', self.ask.call_args.args[0])

    def test_read_only_mode_observes_without_model_action_or_job_write(self):
        before = copy.deepcopy(self.job)
        result = self.run_job(read_only=True)
        self.assertEqual(result['state'], 'done')
        self.assertTrue(result['read_only'])
        self.assertEqual(result['observation']['window']['app'], 'calculatorapp')
        self.assertEqual(self.ui.calls, [])
        self.ask.assert_not_called()
        self.assertEqual(self.job, before)
        self.assertTrue(all('value' not in control for control in result['observation']['controls']))

    def test_missing_result_stops_and_resume_never_blindly_replays(self):
        self.ui.changes = False
        self.plans(action())
        self.run_job()
        self.assertEqual(self.job['status'], 'waiting')
        self.assertIsNotNone(self.job['pending_effect'])
        self.run_job()
        self.assertEqual(len(self.ui.calls), 1)
        self.assertEqual(self.ask.call_count, 1)
        self.assertFalse(any('done|' in e[-1] for e in self.events))
        self.ui.screen['controls'][0]['value'] = '19'
        self.plans({'op': 'finish', 'expect': action()['expect']})
        self.run_job()
        self.assertEqual(self.job['status'], 'done')
        self.assertEqual(len(self.ui.calls), 1)

    def test_restart_preserves_unknown_action_and_waits_for_evidence(self):
        self.job.update(hwnd=10, pid=20, status='checking', pending_effect={'action': action(), 'at': time.time()})
        agent._save(self.job)
        self.job = agent._load('alice')
        self.run_job()
        self.assertEqual(self.job['status'], 'waiting')
        self.assertEqual(self.ui.calls, [])
        self.ask.assert_not_called()

    def test_provably_unsent_action_is_replannable(self):
        self.ui.act = Mock(side_effect=uia.NotSent('Ekran değişti'))
        self.plans(action())
        self.run_job()
        self.assertEqual(self.job['status'], 'blocked')
        self.assertIsNone(self.job['pending_effect'])
        self.assertIn('Ekran değişti', self.job['last_error'])

    def test_sensitive_step_requires_matching_current_preview(self):
        self.ui.screen['controls'][1]['name'] = 'Sil'
        self.plans(action())
        self.run_job()
        self.assertEqual(self.ui.calls, [])
        token = self.job['approval']['id']
        self.run_job(approval='wrong')
        self.assertEqual(self.ui.calls, [])
        self.plans({'op': 'finish', 'expect': action()['expect']})
        self.run_job(approval=token)
        self.assertEqual(len(self.ui.calls), 1)
        self.assertEqual(self.job['status'], 'done')

    def test_changed_or_expired_preview_never_acts(self):
        for expired in (True, False):
            with self.subTest(expired=expired):
                self.job.update(status='running', history=[], approval=None, pending_effect=None)
                self.ui = FakeUI(screen(button='Sil'))
                self.plans(action()); self.run_job()
                token = self.job['approval']['id']
                if expired:
                    self.job['approval']['at'] -= 121
                else:
                    self.ui.screen['controls'][0]['value'] = 'değişti'
                self.run_job(approval=token)
                self.assertEqual(self.ui.calls, [])
                self.assertEqual(self.job['status'], 'paused')

    def test_finish_is_rechecked_after_model_response(self):
        self.ui.screen['controls'][0]['value'] = '19'
        def model(*_args, **_kwargs):
            self.ui.screen['controls'][0]['value'] = '20'
            return json.dumps({'op': 'finish', 'expect': action()['expect']})
        self.ask.side_effect = model
        self.run_job()
        self.assertEqual(self.job['status'], 'blocked')

    def test_invalid_plan_gets_bounded_feedback_without_interaction(self):
        self.ask.return_value = json.dumps({'op': 'shell', 'command': 'bad'})
        self.run_job()
        self.assertEqual(self.job['status'], 'blocked')
        self.assertEqual(self.ask.call_count, 3)
        self.assertIn('last_error', self.ask.call_args.args[0])
        self.assertEqual(self.ui.calls, [])

    def test_user_change_privacy_and_cancellation_stop_actions(self):
        self.plans(action())
        agent.run(self.job, ui=self.ui, current=lambda: 'bob')
        self.assertEqual(self.job['status'], 'blocked')
        self.assertEqual(self.ui.calls, [])
        with patch.object(agent.privacy, 'blocked', return_value='Ekran gizli modda kapalı'):
            self.run_job()
        self.assertIn('gizli', self.job['message'])
        with patch.object(requests_state, 'check', side_effect=requests_state.Cancelled('dur')):
            with self.assertRaises(requests_state.Cancelled):
                self.run_job()
        self.assertEqual(self.job['status'], 'cancelled')

    def test_phone_or_other_owner_cannot_start_or_approve(self):
        agent._save(self.job)
        with patch.object(agent, 'run') as run:
            self.assertIn('aktif kullanıcısı', agent.handle('alice', 'PC görevi: Calc | Topla', source='telefon'))
            self.assertIn('aktif kullanıcısı', agent.handle('bob', 'PC onayla token', current=lambda: 'alice'))
        run.assert_not_called()
        self.assertIsNone(agent._load('bob'))

    def test_reused_window_process_blocks_resume(self):
        self.job.update(hwnd=10, pid=999)
        self.run_job()
        self.assertEqual(self.ui.calls, [])
        self.ask.assert_not_called()

    def test_total_limit_cannot_be_reset_by_resume(self):
        self.job['history'] = [{'verified': True}] * 50
        self.run_job()
        self.assertEqual(self.job['status'], 'blocked')
        self.ask.assert_not_called()


    def test_name_expectation_ignores_invisible_and_spacing_differences_only(self):
        before = screen()
        before['controls'].append({'id': 'expression', 'name': 'İfade değeri 12 + ', 'value': '',
            'offscreen': False, 'patterns': [], 'enabled': True, 'password': False,
            'type': 'ControlType.Text', 'automation_id': 'CalculatorExpression'})
        expect = {'control': 'expression', 'field': 'name', 'equals': 'İfade değeri 12 +'}
        for actual in ('İfade değeri 12 + ', 'İfade değeri 12 +', ' İfade değeri 12 +\n', 'İfade değeri  12 +',
                       '‎İfade değeri 12 +‏', 'İfade değeri\t12 +'):
            with self.subTest(actual=actual):
                before['controls'][2]['name'] = actual
                self.assertTrue(agent.expected(before, expect))
        for actual in ('İfade değeri 12 -', 'İfade değeri 1 2 +', 'İfade değeri 12', '', None, 12):
            with self.subTest(actual=actual):
                before['controls'][2]['name'] = actual
                self.assertFalse(agent.expected(before, expect))
        before['controls'][2]['name'] = 'İfade değeri 12 + '
        self.assertTrue(agent.expected(before, {'text': 'İfade değeri 12 +'}))
        self.assertFalse(agent.expected(before, {'text': 'İfade değeri 12'}))
        self.assertFalse(agent.expected(before, {'control': 'expression', 'field': 'name', 'equals': ['İfade değeri 12 +']}))

    def test_typed_value_stays_exact_and_protected_controls_never_match(self):
        before = screen(value='merhaba  dünya')
        value_expect = {'control': 'display', 'field': 'value', 'equals': 'merhaba  dünya'}
        self.assertTrue(agent.expected(before, value_expect))
        for loose in ('merhaba dünya', 'merhaba  dünya ', ' merhaba  dünya'):
            with self.subTest(loose=loose):
                self.assertFalse(agent.expected(before, dict(value_expect, equals=loose)))
        self.assertFalse(agent.expected(before, {'text': 'merhaba dünya'}))
        locked = screen()
        locked['controls'][0].update(name='Parola 12', password=True)
        self.assertFalse(agent.expected(locked, {'control': 'display', 'field': 'name', 'equals': 'Parola 12'}))
        private = screen()
        private['controls'][0].update(name='API key 12')
        self.assertFalse(agent.expected(private, {'control': 'display', 'field': 'name', 'equals': 'API key 12'}))

    def goal_screen(self, shown='Ekran değeri 0', app='calculatorapp'):
        view = screen()
        view['app'] = app
        view['controls'][0].update(name=shown, value='')
        return view

    def goal_step(self, shown):
        return {'op': 'invoke', 'control': 'button',
                'expect': {'control': 'display', 'field': 'name', 'equals': shown}}

    def test_calculator_plan_numbers_must_follow_the_goal(self):
        view = self.goal_screen()
        goal = '15 ile 5 topla'
        for good in ('Ekran değeri 1', 'Ekran değeri 15', 'Ekran değeri 5', 'Ekran değeri 20', 'İfade değeri 15 + 5=',
                     'İfade değeri 15 +', 'Ekran değeri 10', 'Ekran değeri 75'):
            with self.subTest(good=good):
                self.assertEqual(agent.validate(view, self.goal_step(good), goal), self.goal_step(good))
        for bad in ('Ekran değeri 19', 'Ekran değeri 194', 'Ekran değeri 14', 'İfade değeri 15 + 7=', 'Ekran değeri 9'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'hedefle uyuşmuyor'):
                agent.validate(view, self.goal_step(bad), goal)
        with self.assertRaisesRegex(ValueError, 'hedefle uyuşmuyor'):
            agent.validate(view, {'op': 'invoke', 'control': 'button', 'expect': {'text': 'Ekran değeri 19'}}, goal)

    def test_goal_number_check_handles_decimals_thousands_and_long_division(self):
        view = self.goal_screen()
        for goal, good, bad in (('1,5 ile 2 topla', ('Ekran değeri 1,5', 'Ekran değeri 3,5'), 'Ekran değeri 4,5'),
                                ('1.234 ile 6 topla', ('Ekran değeri 1.240', 'Ekran değeri 1.234'), 'Ekran değeri 1.250'),
                                ('10 ile 3 böl', ('Ekran değeri 3,333333333333333',), 'Ekran değeri 3,5')):
            for shown in good:
                with self.subTest(goal=goal, shown=shown):
                    agent.validate(view, self.goal_step(shown), goal)
            with self.subTest(goal=goal, bad=bad), self.assertRaises(ValueError):
                agent.validate(view, self.goal_step(bad), goal)

    def test_goal_number_check_is_off_without_clear_numbers_or_outside_calculator(self):
        view = self.goal_screen()
        for goal in (None, 'iki ile üç topla', '15 ile beş topla', 'çıkan sonucu 3 ile çarp', 'ekrandaki sayıya 4 ekle',
                     'hesap makinesini aç'):
            with self.subTest(goal=goal):
                agent.validate(view, self.goal_step('Ekran değeri 19'), goal)
        notepad = self.goal_screen(app='notepad')
        notepad['title'] = 'Adsız - Not Defteri'
        notepad['controls'][1].update(type='ControlType.Document', patterns=['fill'])
        step = {'op': 'fill', 'control': 'button', 'value': '19', 'expect': {'control': 'button', 'field': 'value', 'equals': '19'}}
        self.assertEqual(agent.validate(notepad, step, '15 ile 5 topla'), step)

class CalculatorStartTests(unittest.TestCase):
    """Görev başlarken önceki işlemden kalan sayı temizlenir; yalnız hedef bunu gerektiriyorsa."""

    def calc_screen(self, shown='Ekran değeri 19'):
        return {'hwnd': 10, 'pid': 20, 'title': 'Hesap Makinesi', 'app': 'calculatorapp', 'controls': [
            {'id': 'results', 'name': shown, 'value': '', 'type': 'ControlType.Text', 'selected': None, 'patterns': [],
             'enabled': True, 'password': False, 'automation_id': 'CalculatorResults'},
            {'id': 'clear', 'name': 'Temizle', 'value': '', 'type': 'ControlType.Button', 'selected': None,
             'patterns': ['invoke'], 'enabled': True, 'password': False, 'automation_id': 'clearButton'}]}

    def make_ui(self, shown='Ekran değeri 19', clears=True):
        outer = self

        class CalcUI:
            def __init__(self):
                self.screen, self.calls = outer.calc_screen(shown), []

            def observe(self, *args):
                return copy.deepcopy(self.screen)

            def act(self, snapshot, step):
                self.calls.append(copy.deepcopy(step))
                if clears and step['control'] == 'clear':
                    self.screen['controls'][0]['name'] = step['expect']['equals']
                return {'ok': True, 'sent': True}
        return CalcUI()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(agent, 'STORE', Path(temporary.name)))
        self.enterContext(patch.object(agent.privacy, 'blocked', return_value=None))
        self.enterContext(patch.object(agent.time, 'sleep'))
        self.ask = self.enterContext(patch.object(agent.llm, 'ask'))

    def finish(self, shown):
        return json.dumps({'op': 'finish', 'message': 'tamam',
                           'expect': {'control': 'results', 'field': 'name', 'equals': shown}}, ensure_ascii=False)

    def job(self, goal):
        return {'owner': 'alice', 'target': 'Hesap Makinesi', 'goal': goal, 'status': 'running', 'history': [],
                'hwnd': None, 'approval': None, 'pending_effect': None}

    def run_job(self, job, ui):
        return agent.run(job, ui=ui, emit=lambda *a: None, current=lambda: 'alice')

    def test_stale_result_is_cleared_before_planning(self):
        self.ask.side_effect = [self.finish('Ekran değeri 0')]
        ui, job = self.make_ui(), self.job('15 ile 5 topla')
        self.run_job(job, ui)
        self.assertEqual([c['control'] for c in ui.calls], ['clear'])
        self.assertEqual(ui.calls[0]['expect'], {'control': 'results', 'field': 'name', 'equals': 'Ekran değeri 0'})
        self.assertTrue(job['history'][0]['verified'])
        self.assertIn('Ekran değeri 0', self.ask.call_args.args[0])
        self.assertNotIn('Ekran değeri 19', self.ask.call_args.args[0])
        self.assertEqual(job['status'], 'done')

    def test_clear_keeps_the_ui_language_of_the_display_name(self):
        step = agent._clear_step(self.calc_screen('Display is 1,234'), '15 ile 5 topla')
        self.assertEqual(step['expect']['equals'], 'Display is 0')

    def test_no_clear_when_goal_uses_the_screen_or_has_no_clear_numbers(self):
        for goal in ('çıkan sonucu 3 ile çarp', 'ekrandaki sayıya 4 ekle', 'iki ile üç topla', 'hesap makinesini aç'):
            with self.subTest(goal=goal):
                self.ask.side_effect = [self.finish('Ekran değeri 19')]
                ui = self.make_ui()
                job = self.job(goal)
                self.run_job(job, ui)
                self.assertEqual(ui.calls, [])
                self.assertEqual(job['status'], 'done')
                self.assertIn('Ekran değeri 19', self.ask.call_args.args[0])

    def test_no_clear_when_already_zero_or_controls_are_missing_or_other_app(self):
        self.assertIsNone(agent._clear_step(self.calc_screen('Ekran değeri 0'), '15 ile 5 topla'))
        missing = self.calc_screen(); del missing['controls'][1]
        self.assertIsNone(agent._clear_step(missing, '15 ile 5 topla'))
        twice = self.calc_screen(); twice['controls'].append(dict(twice['controls'][1], id='clear2'))
        self.assertIsNone(agent._clear_step(twice, '15 ile 5 topla'))
        notepad = self.calc_screen(); notepad['app'] = 'notepad'
        self.assertIsNone(agent._clear_step(notepad, '15 ile 5 topla'))
        self.assertIsNone(agent._clear_step(self.calc_screen('Ekran değeri yok'), '15 ile 5 topla'))

    def test_unverified_clear_stops_before_any_digit_is_pressed(self):
        ui, job = self.make_ui(clears=False), self.job('15 ile 5 topla')
        self.run_job(job, ui)
        self.assertEqual(job['status'], 'waiting')
        self.assertEqual([c['control'] for c in ui.calls], ['clear'])
        self.ask.assert_not_called()

    def digit_screen(self, shown, expression=None):
        view = self.calc_screen(shown)
        for number in range(10):
            view['controls'].append({'id': 'n%d' % number, 'name': 'Rakam %d' % number, 'value': '', 'type': 'ControlType.Button',
                'selected': None, 'patterns': ['invoke'], 'enabled': True, 'password': False,
                'automation_id': 'num%dButton' % number})
        if expression is not None:
            view['controls'].append({'id': 'expr', 'name': expression, 'value': '', 'type': 'ControlType.Text',
                'selected': None, 'patterns': [], 'enabled': True, 'password': False, 'automation_id': 'CalculatorExpression'})
        return view

    def press(self, view, digit, shown):
        return {'op': 'invoke', 'control': 'n%d' % digit, 'expect': {'control': 'results', 'field': 'name', 'equals': shown}}

    def test_digit_buttons_must_produce_the_screen_the_plan_expects(self):
        cases = (
            # (ekran, ifade satırı, basılan rakam, kabul edilen, reddedilen)
            ('Ekran değeri 1', None, 2, 'Ekran değeri 12', ('Ekran değeri 2', 'Ekran değeri 22')),
            ('Ekran değeri 1', None, 7, 'Ekran değeri 17', ('Ekran değeri 7', 'Ekran değeri 12')),
            ('Ekran değeri 0', None, 1, 'Ekran değeri 1', ('Ekran değeri 11', 'Ekran değeri 10')),
            ('Ekran değeri 12', 'İfade değeri 12 +', 7, 'Ekran değeri 7', ('Ekran değeri 127', 'Ekran değeri 19')),
            ('Ekran değeri 12', 'İfade değeri 12 ×', 3, 'Ekran değeri 3', ('Ekran değeri 123',)),
            ('Ekran değeri 19', 'İfade değeri 12 + 7=', 5, 'Ekran değeri 5', ('Ekran değeri 195',)),
            ('Ekran değeri 15', 'İfade değeri 15 Eksi (', 5, 'Ekran değeri 5', ('Ekran değeri 155',)),
            ('Ekran değeri 1.234', None, 5, 'Ekran değeri 12.345', ('Ekran değeri 5',)),
        )
        for shown, expression, digit, good, bad in cases:
            view = self.digit_screen(shown, expression)
            with self.subTest(shown=shown, expression=expression, digit=digit, good=good):
                step = self.press(view, digit, good)
                self.assertEqual(agent.validate(view, step), step)
            for wrong in bad:
                with self.subTest(shown=shown, expression=expression, digit=digit, wrong=wrong), \
                     self.assertRaisesRegex(ValueError, 'düğmeyle uyuşmuyor'):
                    agent.validate(view, self.press(view, digit, wrong))

    def test_digit_entry_check_leaves_other_buttons_apps_and_fields_alone(self):
        view = self.digit_screen('Ekran değeri 1')
        view['controls'].append({'id': 'plus', 'name': 'Artı', 'value': '', 'type': 'ControlType.Button', 'selected': None,
            'patterns': ['invoke'], 'enabled': True, 'password': False, 'automation_id': 'plusButton'})
        operator = {'op': 'invoke', 'control': 'plus', 'expect': {'control': 'results', 'field': 'name', 'equals': 'Ekran değeri 1 +'}}
        self.assertEqual(agent.validate(view, operator), operator)
        other = self.digit_screen('Ekran değeri 1'); other['app'] = 'notepad'
        other['title'] = 'Adsız - Not Defteri'
        self.assertIsNone(agent._check_digit_entry(other, self.press(other, 7, 'Ekran değeri 7')))
        on_expression = self.digit_screen('Ekran değeri 1', 'İfade değeri 1 +')
        step = {'op': 'invoke', 'control': 'n7', 'expect': {'control': 'expr', 'field': 'name', 'equals': 'İfade değeri 1 + 7'}}
        self.assertIsNone(agent._check_digit_entry(on_expression, step))

    def test_resumed_job_never_clears_again(self):
        ui, job = self.make_ui(), self.job('15 ile 5 topla')
        job['history'] = [{'op': 'invoke', 'control': 'clear', 'verified': True,
                           'expect': {'control': 'results', 'field': 'name', 'equals': 'Ekran değeri 0'}}]
        self.ask.side_effect = [self.finish('Ekran değeri 19')]
        self.run_job(job, ui)
        self.assertEqual(ui.calls, [])
        self.assertEqual(job['status'], 'done')


class CalcSim:
    """Windows Hesap Makinesi'nin ekran/ifade davranışını taklit eder (girdi, işlem, eşittir, temizle)."""
    GLYPHS = {'plusButton': ('+', lambda a, b: a + b), 'minusButton': ('−', lambda a, b: a - b),
              'multiplyButton': ('×', lambda a, b: a * b), 'divideButton': ('÷', lambda a, b: a // b)}

    def __init__(self, display='0', glyph_override=None):
        self.display, self.expression, self.left, self.operator, self.fresh = display, '', None, None, False
        self.calls, self.glyph_override = [], glyph_override or {}

    def observe(self, *args):
        controls = [{'id': 'results', 'name': 'Ekran değeri ' + self.display, 'value': '', 'type': 'ControlType.Text',
                     'selected': None, 'patterns': [], 'enabled': True, 'password': False, 'automation_id': 'CalculatorResults'}]
        controls.append({'id': 'expression', 'name': 'İfade değeri ' + (self.expression + ' ' if self.expression else ''),
                         'value': '', 'patterns': [], 'type': 'ControlType.Text', 'selected': None, 'enabled': True,
                         'password': False, 'automation_id': 'CalculatorExpression', 'offscreen': not self.expression})
        names = [('num%dButton' % n) for n in range(10)] + ['plusButton', 'minusButton', 'multiplyButton', 'divideButton',
                                                            'equalButton', 'clearButton']
        for automation_id in names:
            controls.append({'id': automation_id, 'name': automation_id, 'value': '', 'type': 'ControlType.Button',
                             'selected': None, 'patterns': ['invoke'], 'enabled': True, 'password': False,
                             'automation_id': automation_id})
        return {'hwnd': 10, 'pid': 20, 'title': 'Hesap Makinesi', 'app': 'calculatorapp', 'controls': controls}

    def act(self, snapshot, step):
        self.calls.append(step['control'])
        key = step['control']
        if key.startswith('num'):
            digit = key[3]
            self.display = digit if self.fresh or self.display == '0' else self.display + digit
            self.fresh = False
        elif key in self.GLYPHS:
            glyph = self.glyph_override.get(key, self.GLYPHS[key][0])
            self.left, self.operator, self.fresh = int(self.display), key, True
            self.expression = '%s %s' % (self.display, glyph)
        elif key == 'equalButton' and self.operator:
            glyph = self.glyph_override.get(self.operator, self.GLYPHS[self.operator][0])
            right = int(self.display)
            self.expression = '%d %s %d=' % (self.left, glyph, right)
            self.display, self.fresh = str(self.GLYPHS[self.operator][1](self.left, right)), True
        elif key == 'clearButton':
            self.display, self.expression, self.left, self.operator, self.fresh = '0', '', None, None, False
        return {'ok': True, 'sent': True}


class ArithmeticScriptTests(unittest.TestCase):
    """Basit aritmetik modele sorulmadan, adım adım ve her adımı ekran kanıtıyla yürütülür."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(agent, 'STORE', Path(temporary.name)))
        self.enterContext(patch.object(agent.privacy, 'blocked', return_value=None))
        self.enterContext(patch.object(agent.time, 'sleep'))
        self.ask = self.enterContext(patch.object(agent.llm, 'ask', side_effect=AssertionError('model çağrılmamalı')))

    def job(self, goal):
        return {'owner': 'alice', 'target': 'Hesap Makinesi', 'goal': goal, 'status': 'running', 'history': [],
                'hwnd': None, 'approval': None, 'pending_effect': None}

    def run_goal(self, goal, sim):
        job = self.job(goal)
        agent.run(job, ui=sim, emit=lambda *a: None, current=lambda: 'alice')
        return job

    def test_goals_are_parsed_only_when_they_are_simple_arithmetic(self):
        for goal, expected in (('12 ile 7 topla', (12, '+', 7)), ('15 ile 5 çıkar', (15, '-', 5)),
                               ("12 ile 7'yi topla", (12, '+', 7)), ("15'ten 5 çıkar", (15, '-', 5)),
                               ('6 ile 7 çarp', (6, '*', 7)), ('20 ile 4 böl', (20, '/', 4)),
                               ('6 x 7', (6, '*', 7)), ('9 − 4', (9, '-', 4)), ('12 + 7', (12, '+', 7)),
                               ('12 ile 7 topla.', (12, '+', 7))):
            with self.subTest(goal=goal):
                self.assertEqual(agent._parse_arithmetic(goal), expected)
        for goal in ('12 ile 7 topla ve sonucu not defterine yaz', 'üç ile dört topla', '1234 ile 5 topla',
                     'hesap makinesini aç', '12 ile 7', '', None, '12 ile 7 topla mısın acaba'):
            with self.subTest(goal=goal):
                self.assertIsNone(agent._parse_arithmetic(goal))

    def test_each_operation_runs_without_the_model_and_shows_the_real_result(self):
        for goal, result in (('12 ile 7 topla', '19'), ('15 ile 5 çıkar', '10'), ('6 ile 7 çarp', '42'),
                             ('20 ile 4 böl', '5'), ('125 ile 5 topla', '130'), ('15 ile 5 topla', '20'),
                             ('99 ile 9 çarp', '891'), ('5 ile 0 topla', '5')):
            with self.subTest(goal=goal):
                sim = CalcSim()
                job = self.run_goal(goal, sim)
                self.assertEqual(job['status'], 'done', job.get('message'))
                self.assertEqual(sim.display, result)
                self.assertTrue(all(h['verified'] for h in job['history']))
                self.assertIn('Ekran değeri ' + result, job['message'])
        self.ask.assert_not_called()

    def test_exact_button_sequence_for_the_failing_real_task(self):
        sim = CalcSim()
        self.run_goal('15 ile 5 topla', sim)
        self.assertEqual(sim.calls, ['num1Button', 'num5Button', 'plusButton', 'num5Button', 'equalButton'])

    def test_stale_screen_is_cleared_first_then_the_script_runs(self):
        sim = CalcSim(display='17')
        job = self.run_goal('15 ile 5 topla', sim)
        self.assertEqual(sim.calls[0], 'clearButton')
        self.assertEqual(sim.calls[1:], ['num1Button', 'num5Button', 'plusButton', 'num5Button', 'equalButton'])
        self.assertEqual((job['status'], sim.display), ('done', '20'))

    def test_operator_glyph_variants_are_accepted(self):
        for goal, result in (('15 ile 5 çıkar', '10'), ('6 ile 7 çarp', '42'), ('20 ile 4 böl', '5')):
            with self.subTest(goal=goal):
                sim = CalcSim(glyph_override={'minusButton': '-', 'multiplyButton': 'x', 'divideButton': '/'})
                self.assertEqual(self.run_goal(goal, sim)['status'], 'done')
                self.assertEqual(sim.display, result)
        for goal, result in (('15 ile 5 çıkar', '10'),):
            with self.subTest(goal=goal, glyph='Eksi ('):
                sim = CalcSim(glyph_override={'minusButton': 'Eksi ('})
                self.assertEqual(self.run_goal(goal, sim)['status'], 'done')
                self.assertEqual(sim.display, result)

    def test_script_is_declined_when_it_cannot_be_proven_and_the_model_takes_over(self):
        sim = CalcSim()
        view = sim.observe()
        for goal in ('7 ile 7 topla', '0 ile 5 topla', '999 ile 999 topla', '5 ile 8 çıkar', '10 ile 4 böl',
                     '5 ile 0 böl', '1 ile 12 topla'):
            with self.subTest(goal=goal):
                self.assertIsNone(agent._arithmetic_script(view, goal))
        dirty = CalcSim(display='17').observe()
        self.assertIsNone(agent._arithmetic_script(dirty, '15 ile 5 topla'))
        pending = CalcSim(); pending.expression = '12 +'
        self.assertIsNone(agent._arithmetic_script(pending.observe(), '15 ile 5 topla'))
        english = CalcSim().observe(); english['controls'][0]['name'] = 'Display is 0'
        self.assertIsNone(agent._arithmetic_script(english, '15 ile 5 topla'))
        missing = CalcSim().observe(); missing['controls'] = [c for c in missing['controls'] if c['id'] != 'equalButton']
        self.assertIsNone(agent._arithmetic_script(missing, '15 ile 5 topla'))
        notepad = CalcSim().observe(); notepad['app'] = 'notepad'
        self.assertIsNone(agent._arithmetic_script(notepad, '15 ile 5 topla'))
        self.assertIsNotNone(agent._arithmetic_script(view, '15 ile 5 topla'))

    def test_declined_script_hands_the_task_to_the_model(self):
        self.ask.side_effect = [json.dumps({'op': 'finish', 'message': 'x', 'expect': {
            'control': 'results', 'field': 'name', 'equals': 'Ekran değeri 0'}}, ensure_ascii=False)]
        sim = CalcSim()
        job = self.run_goal('7 ile 7 topla', sim)
        self.assertEqual(self.ask.call_count, 1)
        self.assertEqual(job['status'], 'done')

    def test_wrong_button_effect_stops_the_script_without_claiming_success(self):
        sim = CalcSim()
        original = sim.act

        def broken(snapshot, step):
            if step['control'] == 'plusButton':
                return {'ok': True, 'sent': True}   # tuş etkisiz: ifade satırı hiç görünmez
            return original(snapshot, step)
        sim.act = broken
        job = self.run_goal('12 ile 7 topla', sim)
        self.assertEqual(job['status'], 'waiting')
        self.assertNotEqual(sim.display, '19')
        self.assertNotIn('num7Button', sim.calls)
        self.assertNotIn('equalButton', sim.calls)
        self.ask.assert_not_called()

    def test_expectation_by_automation_id_is_safe(self):
        view = CalcSim(); view.expression = '12 +'
        screen_ = view.observe()
        expect = {'automation_id': 'CalculatorExpression', 'field': 'name', 'equals': ['İfade değeri 12 +', 'İfade değeri 12 -']}
        self.assertTrue(agent.expected(screen_, expect))
        for bad in ({'automation_id': 'CalculatorExpression', 'field': 'name', 'equals': ['İfade değeri 12 ×']},
                    {'automation_id': 'CalculatorExpression', 'field': 'value', 'equals': ['x']},
                    {'automation_id': 'CalculatorExpression', 'field': 'name', 'equals': []},
                    {'automation_id': 'CalculatorExpression', 'field': 'name', 'equals': [1]},
                    {'automation_id': 'CalculatorExpression', 'field': 'name', 'equals': 'İfade değeri 12 +'}):
            with self.subTest(bad=bad):
                try:
                    self.assertFalse(agent.expected(screen_, bad))
                except ValueError:
                    pass
        hidden = copy.deepcopy(screen_)
        for control in hidden['controls']:
            if control['automation_id'] == 'CalculatorExpression':
                control['offscreen'] = True
        self.assertFalse(agent.expected(hidden, expect))


class DesktopValidationTests(unittest.TestCase):
    def fake_worker(self, replies):
        worker = Mock(); worker.alive.return_value = True
        worker.lines = __import__('queue').Queue()
        for reply in replies:
            worker.lines.put(reply)
        return worker

    def test_native_bridge_keeps_model_text_in_json_stdin(self):
        payload = {'op': 'fill', 'value': '$(not-a-command); "ö"\nikinci satır', 'hwnd': 10}
        worker = self.fake_worker([b'{"ok":true,"sent":true}\n'])
        with patch.object(uia, 'os', types.SimpleNamespace(name='nt')), patch.object(uia, '_worker', None), patch.object(uia, '_Worker', return_value=worker):
            self.assertTrue(uia._call(payload)['ok'])
        sent = worker.process.stdin.write.call_args.args[0]
        self.assertEqual(sent.count(b'\n'), 1)   # tek satır: model metnindeki satır sonu kaçırılır
        self.assertTrue(sent.endswith(b'\n'))
        self.assertEqual(json.loads(sent), payload)

    def test_native_worker_is_reused_between_calls(self):
        worker = self.fake_worker([b'{"ok":true}\n', b'{"ok":true}\n'])
        with patch.object(uia, 'os', types.SimpleNamespace(name='nt')), patch.object(uia, '_worker', None), patch.object(uia, '_Worker', return_value=worker) as make:
            uia._call({'op': 'observe', 'hwnd': 10}); uia._call({'op': 'observe', 'hwnd': 10})
        make.assert_called_once()
        worker.kill.assert_not_called()

    def test_native_worker_is_restarted_after_it_died(self):
        dead = self.fake_worker([]); dead.alive.return_value = False
        fresh = self.fake_worker([b'{"ok":true}\n'])
        with patch.object(uia, 'os', types.SimpleNamespace(name='nt')), patch.object(uia, '_worker', dead), patch.object(uia, '_Worker', return_value=fresh) as make:
            uia._call({'op': 'observe', 'hwnd': 10})
        make.assert_called_once()

    def test_native_worker_is_terminated_when_cancelled(self):
        worker = self.fake_worker([])
        with patch.object(uia, 'os', types.SimpleNamespace(name='nt')), patch.object(uia, '_worker', None), patch.object(uia, '_Worker', return_value=worker),              patch.object(requests_state, 'check', side_effect=[None, requests_state.Cancelled('dur')]):
            with self.assertRaises(requests_state.Cancelled): uia._call({'op': 'observe', 'hwnd': 10})
        worker.kill.assert_called_once()

    def test_native_worker_with_unknown_result_is_not_reused_after_timeout(self):
        worker = self.fake_worker([])
        # A loaded runner may read the clock again: the fake is module-private and never exhausts.
        clock = chain((0, 0), repeat(25))
        with patch.object(uia, 'os', types.SimpleNamespace(name='nt')), \
                patch.object(uia, '_worker', None), \
                patch.object(uia, '_Worker', return_value=worker), \
                patch.object(uia, 'time', types.SimpleNamespace(monotonic=lambda: next(clock))):
            with self.assertRaisesRegex(ValueError, 'süre sınırını'): uia._call({'op': 'observe', 'hwnd': 10})
        worker.kill.assert_called_once()
        self.assertIsNone(uia._worker)

    def test_password_outbound_terminal_and_code_are_not_operated(self):
        for kind in ('password', 'send', 'terminal', 'source'):
            view = screen()
            if kind == 'password': view['controls'][1]['password'] = True
            if kind == 'send': view['controls'][1]['name'] = 'Gönder'
            if kind == 'terminal': view['app'] = 'powershell'
            if kind == 'source': view['title'] = 'main.py - Not Defteri'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                agent.validate(view, action())

    def test_fill_requires_exact_readback_of_same_field(self):
        view = screen(); view['controls'][1].update(patterns=['fill'], name='Metin')
        step = {'op': 'fill', 'control': 'button', 'value': 'merhaba',
                'expect': {'control': 'button', 'field': 'value', 'equals': 'merhaba'}}
        self.assertEqual(agent.validate(view, step), step)
        step['expect']['control'] = 'display'
        with self.assertRaises(ValueError): agent.validate(view, step)

    def test_only_supported_apps_and_plain_notepad_documents_are_operated(self):
        for app, title in [('notepad', 'main.ts - Not Defteri'), ('notepad', 'main.cpp - Notepad'),
                           ('notepad', 'Dockerfile - Notepad'), ('notepad', 'unknown - Notepad'),
                           ('chrome', 'Untitled'), ('mspaint', 'Untitled - Paint'), ('someeditor', 'notes.txt')]:
            view = screen(); view.update(app=app, title=title)
            with self.subTest(app=app, title=title), self.assertRaises(ValueError):
                agent.validate(view, action())
        for title in ('Untitled - Notepad', 'Adsız - Not Defteri', 'notes.txt - Notepad'):
            view = screen(); view.update(app='notepad', title=title)
            view['controls'][1].update(type='ControlType.Edit', automation_id='15', patterns=['fill'], name='Metin')
            step = {'op': 'fill', 'control': 'button', 'value': 'merhaba',
                    'expect': {'control': 'button', 'field': 'value', 'equals': 'merhaba'}}
            self.assertEqual(agent.validate(view, step), step)
            view['controls'][1].update(automation_id='filename', name='Dosya adı')
            with self.assertRaises(ValueError): agent.validate(view, step)
            view['controls'][1].update(patterns=['invoke'], name='Kaydet')
            with self.assertRaises(ValueError): agent.validate(view, action())

    def test_update_and_publish_include_only_the_bundled_native_script(self):
        import updater
        from modules import git_publish
        with tempfile.TemporaryDirectory() as folder, patch.object(git_publish, 'ROOT', Path(folder)):
            root = Path(folder); (root / 'modules').mkdir()
            (root / 'modules' / 'desktop_uia.ps1').write_text('bundled script')
            (root / 'other.ps1').write_text('unrelated script')
            self.assertEqual(set(git_publish._publishable_files()), {'modules/desktop_uia.ps1'})
        self.assertTrue(updater._publishable_path('modules/desktop_uia.ps1'))
        self.assertFalse(updater._publishable_path('other.ps1'))
        self.assertFalse(updater._publishable_path('.jarvis/modules/desktop_uia.ps1'))

    def test_preexisting_button_label_is_not_new_result_evidence(self):
        view = screen(button='19'); step = action(); step['expect'] = {'text': '19'}
        with self.assertRaises(ValueError): agent.validate(view, step)

    def test_sensitive_and_executable_address_values_are_blocked(self):
        view = screen(); view['controls'][1].update(patterns=['fill'], name='Metin')
        for value in ('javascript:alert(1)', 'file:///C:/secret', 'sk-'+'x'*40):
            step = {'op': 'fill', 'control': 'button', 'value': value,
                    'expect': {'control': 'button', 'field': 'value', 'equals': value}}
            with self.subTest(value=value), self.assertRaises(ValueError): agent.validate(view, step)

    def test_stale_native_snapshot_does_not_call_action_bridge(self):
        from modules import system_control as pc
        ui = uia.DesktopUI(); original = screen(); changed = screen('20')
        with patch.object(pc, 'window_action', return_value={'ok': True, 'hwnd': 10}), \
             patch.object(ui, 'observe', return_value=changed), patch.object(uia, '_call') as call:
            with self.assertRaises(uia.NotSent): ui.act(original, action())
        call.assert_not_called()

    def test_read_only_adapter_never_calls_native_action_bridge(self):
        ui = uia.DesktopUI()
        with patch.object(uia, '_call') as call:
            with self.assertRaisesRegex(uia.NotSent, 'Salt-okunur'):
                ui.act(screen(), action(), read_only=True)
        call.assert_not_called()

    def test_spoken_task_does_not_require_punctuation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)), \
             patch.object(agent, 'run', return_value='started') as run:
            self.assertEqual(agent.handle('alice', "PC görevi hesap makinesi 12 ile 7'yi topla", current=lambda: 'alice'), 'started')
        job = run.call_args.args[0]
        self.assertEqual(job['target'].casefold(), 'hesap makinesi')
        self.assertEqual(job['goal'], "12 ile 7'yi topla")

    def test_cancel_alias_closes_persisted_job_without_native_or_model_calls(self):
        for command in ('pc görev iptal', 'PC görevi iptal.', 'pc   görev   iptal!'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as folder, \
                 patch.object(agent, 'STORE', Path(folder)), patch.object(agent, 'run') as run:
                agent._save({'owner': 'alice', 'status': 'blocked', 'history': [], 'approval': {'token': 'old'}})
                self.assertIn('iptal ettim', agent.handle('alice', command, current=lambda: 'alice'))
                self.assertFalse(agent.awaiting('alice'))
                self.assertIsNone(agent._load('alice')['approval'])
                run.assert_not_called()

    def test_cancel_alias_cannot_close_other_pc_users_job(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)):
            agent._save({'owner': 'alice', 'status': 'blocked', 'history': []})
            for source, current in (('telefon', 'alice'), ('yazı', 'bob')):
                self.assertIn('aktif kullanıcısı', agent.handle('alice', 'pc görev iptal', source=source, current=lambda: current))
                self.assertTrue(agent.awaiting('alice'))

    def test_new_task_replaces_an_unfinished_one_without_manual_cancel(self):
        for status in ('blocked', 'waiting', 'paused', 'question', 'approval', 'running', 'done'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder, \
                 patch.object(agent, 'STORE', Path(folder)), patch.object(agent, 'run', return_value='started') as run:
                agent._save({'owner': 'alice', 'status': status, 'goal': 'eski', 'history': [], 'approval': {'id': 'x'}})
                self.assertEqual(agent.handle('alice', 'PC görevi: Hesap Makinesi | 12 ile 7 topla', current=lambda: 'alice'), 'started')
                self.assertEqual(run.call_args.args[0]['goal'], '12 ile 7 topla')
                self.assertIsNone(run.call_args.args[0]['approval'])
                self.assertEqual(agent._load('alice')['goal'], '12 ile 7 topla')

    def test_new_task_does_not_replace_a_job_that_is_really_running(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)), \
             patch.object(agent, 'run') as run:
            agent._save({'owner': 'alice', 'status': 'running', 'goal': 'eski', 'history': []})
            self.assertTrue(agent._BUSY.acquire(blocking=False))
            try:
                self.assertIn('çalışıyor', agent.handle('alice', 'PC görevi: Hesap Makinesi | 1 ile 2 topla', current=lambda: 'alice'))
            finally:
                agent._BUSY.release()
            run.assert_not_called()
            self.assertEqual(agent._load('alice')['goal'], 'eski')

    def test_spoken_reply_reports_the_real_status_not_always_ready(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)):
            for status, word in (('done', 'doğrulandı'), ('blocked', 'tamamlanmadı'), ('waiting', 'tamamlanmadı'),
                                 ('approval', 'onayını'), ('question', 'sorum'), ('cancelled', 'iptal')):
                agent._save({'owner': 'alice', 'status': status, 'history': []})
                with self.subTest(status=status):
                    self.assertIn(word, agent.spoken('alice'))
                    self.assertNotIn('hazır', agent.spoken('alice'))

    def test_reversible_tool_toggle_runs_without_asking_but_system_switches_still_ask(self):
        paint = screen(); paint.update(app='mspaint', title='Adsız - Paint')
        paint['controls'][1].update(name='Çizgi kalemi', patterns=['toggle'], value='Off')
        step = {'op': 'toggle', 'control': 'button', 'expect': {'control': 'button', 'field': 'value', 'equals': 'On'}}
        self.assertFalse(agent.needs_approval(paint, step))
        system = copy.deepcopy(paint); system.update(app='systemsettings', title='Ayarlar')
        self.assertTrue(agent.needs_approval(system, step))
        risky = copy.deepcopy(paint); risky['controls'][1]['name'] = 'Dosyayı sil'
        self.assertTrue(agent.needs_approval(risky, step))
        unnamed = copy.deepcopy(paint); unnamed['controls'][1]['name'] = ''
        self.assertTrue(agent.needs_approval(unnamed, step))

    def test_other_natural_desktop_request_reaches_router_without_action(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)), \
             patch.object(agent, 'run') as run:
            self.assertIsNone(agent.handle('alice', 'PC görevi başka uygulamada işi yap'))
        run.assert_not_called()

    def test_spoken_calculator_aliases_preserve_goal(self):
        for target in ('calc', 'calculator', 'calculatorapp', 'hesap makinesini', 'hesap makinesi uygulaması'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder, \
                 patch.object(agent, 'STORE', Path(folder)), patch.object(agent, 'run', return_value='started') as run:
                self.assertEqual(agent.handle('alice', f'PC görevi {target} 12 ile 7 topla', current=lambda: 'alice'), 'started')
                job = run.call_args.args[0]
                self.assertEqual(job['goal'], '12 ile 7 topla')
                from modules import system_control as pc
                self.assertEqual(pc._select_window(job['target'], [(10, 'Hesap Makinesi', 'applicationframehost')]),
                                 [(10, 'Hesap Makinesi', 'applicationframehost')])

    def test_duplicate_titles_use_foreground_then_act_on_exact_handle(self):
        from modules import system_control as pc
        windows = [(10, 'Hesap Makinesi', 'calculatorapp'), (11, 'Hesap Makinesi', 'calculatorapp')]
        api = Mock(); api.GetForegroundWindow.return_value = 11
        with patch.object(pc, '_app_windows', return_value=windows), patch.object(pc, '_window_api', return_value=api), \
             patch.object(uia, '_call', return_value={'pid': 20, 'controls': screen()['controls']}):
            view = uia.DesktopUI().observe('Hesap Makinesi')
        self.assertEqual(view['hwnd'], 11)
        with patch.object(pc, 'window_action', return_value={'ok': False}) as focus, \
             patch.object(uia.DesktopUI, 'observe', return_value=view), patch.object(uia, '_call') as call:
            uia.DesktopUI().act(view, action())
        focus.assert_not_called()
        self.assertEqual(call.call_args.args[0]['hwnd'], 11)
        self.assertEqual(call.call_args.args[0]['target']['id'], 'button')

    def test_two_real_windows_without_active_match_stay_ambiguous(self):
        from modules import system_control as pc
        api = Mock(); api.GetForegroundWindow.return_value = 99
        with patch.object(pc, '_app_windows', return_value=[(10, 'Calculator', 'calculatorapp'), (11, 'Calculator', 'calculatorapp')]), \
             patch.object(pc, '_window_api', return_value=api), patch.object(uia, '_call') as call:
            with self.assertRaisesRegex(ValueError, 'öne getir'):
                uia.DesktopUI().observe('Calculator')
        call.assert_not_called()

    def test_dwm_cloaked_window_is_recognized_but_failed_read_is_not_hidden(self):
        import ctypes
        from modules import system_control as pc
        fn = Mock()
        def cloaked(hwnd, attribute, ptr, size):
            self.assertEqual(attribute, 14); ptr._obj.value = 1; return 0
        fn.side_effect = cloaked
        api = Mock(); api.dwmapi.DwmGetWindowAttribute = fn
        with patch.object(ctypes, 'windll', api, create=True):
            self.assertTrue(pc._window_cloaked(10))
            fn.side_effect = lambda *args: -1
            self.assertFalse(pc._window_cloaked(10))

    def test_calculator_alias_allowed_but_generic_uwp_host_not_allowed(self):
        view = screen(); view['app'] = 'calculator'
        self.assertEqual(agent.validate(view, action()), action())
        view['app'] = 'applicationframehost'
        with self.assertRaisesRegex(ValueError, 'applicationframehost'):
            agent.validate(view, action())

    def test_native_control_process_must_match_verified_application(self):
        view = screen(); view.update(pid=100, app_pid=20)
        view['controls'][1]['process_id'] = 100
        with self.assertRaisesRegex(ValueError, 'işlemine ait değil'):
            agent.validate(view, action())
        view['controls'][1]['process_id'] = 20
        self.assertEqual(agent.validate(view, action()), action())

    def test_observe_uses_native_app_identity_instead_of_window_host(self):
        from modules import system_control as pc
        with patch.object(pc, '_app_windows', return_value=[(10, 'Hesap Makinesi', 'applicationframehost')]), \
             patch.object(uia, '_call', return_value={'pid': 100, 'app_pid': 20, 'app': 'calculatorapp', 'controls': screen()['controls']}):
            view = uia.DesktopUI().observe('Hesap Makinesi')
        self.assertEqual((view['app'], view['app_pid'], view['pid']), ('calculatorapp', 20, 100))

    def test_resumed_task_does_not_adopt_replaced_hosted_application(self):
        self.job = {'owner': 'alice', 'target': 'Calculator', 'goal': 'Topla', 'status': 'blocked',
                    'history': [], 'hwnd': 10, 'pid': 100, 'app_pid': 20}
        view = screen(); view.update(pid=100, app_pid=21)
        with tempfile.TemporaryDirectory() as folder, patch.object(agent, 'STORE', Path(folder)), \
             patch.object(agent, '_plan') as plan, patch.object(agent.llm, 'set_user_context'):
            result = agent.run(self.job, ui=FakeUI(view))
        self.assertIn('uygulamanın işlemi değişti', result)
        plan.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class AppPermissionTests(unittest.TestCase):
    """Ek uygulamalar yalnız kullanıcı bir kez izin verirse kullanılır; yasaklı uygulamalar hiçbir izinle açılmaz."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(agent, 'STORE', Path(temporary.name)))
        self.enterContext(patch.object(agent.privacy, 'blocked', return_value=None))
        self.enterContext(patch.object(agent.time, 'sleep'))
        self.ask = self.enterContext(patch.object(agent.llm, 'ask'))

    def paint(self, app='mspaint', title='Adsız - Paint'):
        view = screen(); view.update(app=app, title=title)
        view['controls'][1].update(name='Fırça')
        return FakeUI(before=view)

    def begin(self, ui, goal):
        job = {'owner': 'alice', 'target': 'Paint', 'goal': goal, 'status': 'running', 'history': [],
               'hwnd': None, 'approval': None, 'pending_effect': None}
        agent._save(job)
        agent.run(job, ui=ui, emit=lambda *a: None, current=lambda: 'alice')
        return job

    def test_unknown_app_asks_once_and_does_not_touch_the_screen_or_call_the_model(self):
        ui = self.paint()
        job = self.begin(ui, 'bir fırça seç')
        self.assertEqual((job['status'], job['pending_app']), ('consent', 'mspaint'))
        self.assertIn('PC izin ver', job['message'])
        self.assertEqual(ui.calls, [])
        self.ask.assert_not_called()
        self.assertTrue(agent.awaiting('alice'))
        self.assertIn('iznini', agent.spoken('alice'))

    def test_granting_permission_saves_it_per_user_and_continues_the_task(self):
        ui = self.paint()
        self.begin(ui, 'bir fırça seç')
        self.ask.side_effect = [json.dumps(action('19')), json.dumps({'op': 'finish', 'message': 'tamam', 'expect': action('19')['expect']})]
        with patch.object(agent.desktop_uia, 'DesktopUI', return_value=ui):
            reply = agent.handle('alice', 'PC izin ver', current=lambda: 'alice')
        self.assertIn('Tamamlandı', reply)
        self.assertEqual(agent._load('alice')['status'], 'done')
        self.assertEqual(agent.allowed_apps('alice'), ['mspaint'])
        self.assertEqual(agent.allowed_apps('bob'), [])
        self.assertTrue(agent.app_permitted('alice', 'mspaint'))
        self.assertFalse(agent.app_permitted('bob', 'mspaint'))

    def test_second_task_in_a_granted_app_does_not_ask_again(self):
        agent._save_apps('alice', ['mspaint'])
        ui = self.paint()
        self.ask.side_effect = [json.dumps({'op': 'ask', 'question': 'hangi fırça?'})]
        job = self.begin(ui, 'bir fırça seç')
        self.assertEqual(job['status'], 'question')

    def test_denying_permission_cancels_and_remembers_nothing(self):
        ui = self.paint()
        self.begin(ui, 'bir fırça seç')
        self.assertIn('yapmadım', agent.handle('alice', 'PC izin verme', current=lambda: 'alice'))
        self.assertEqual(agent.allowed_apps('alice'), [])
        self.assertFalse(agent.awaiting('alice'))
        self.assertEqual(ui.calls, [])

    def test_permission_can_be_listed_and_removed(self):
        agent._save_apps('alice', ['mspaint', 'systemsettings'])
        self.assertIn('mspaint', agent.handle('alice', 'PC izinleri', current=lambda: 'alice'))
        self.assertIn('kaldırdım', agent.handle('alice', 'PC izni kaldır mspaint', current=lambda: 'alice'))
        self.assertEqual(agent.allowed_apps('alice'), ['systemsettings'])
        self.assertIn('bulamadım', agent.handle('alice', 'PC izni kaldır mspaint', current=lambda: 'alice'))

    def test_never_apps_are_refused_even_if_the_permission_file_lists_them(self):
        for app in ('cmd', 'powershell', 'windowsterminal', 'code', 'chrome', 'keepass', 'regedit', 'applicationframehost'):
            with self.subTest(app=app):
                agent._save_apps('alice', [app])
                self.assertEqual(agent.allowed_apps('alice'), [])
                self.assertFalse(agent.app_permitted('alice', app))
                job = self.begin(self.paint(app=app, title='Pencere'), 'bir şey yap')
                self.assertEqual(job['status'], 'blocked')
                self.assertIn('desteklenmiyor', job['message'])
        self.ask.assert_not_called()

    def test_jarvis_window_and_source_titles_are_refused_without_asking(self):
        for title in ('Jarvis', 'main.py - Visual'):
            with self.subTest(title=title):
                job = self.begin(self.paint(title=title), 'bir şey yap')
                self.assertEqual(job['status'], 'blocked')

    def test_permission_commands_need_the_active_pc_user_and_a_pending_request(self):
        self.assertIn('aktif kullanıcısı', agent.handle('alice', 'PC izin ver', source='telefon', current=lambda: 'alice'))
        self.assertIn('aktif kullanıcısı', agent.handle('alice', 'PC izin ver', current=lambda: 'bob'))
        self.assertIn('bekleyen', agent.handle('alice', 'PC izin ver', current=lambda: 'alice'))
        self.assertEqual(agent.allowed_apps('alice'), [])

    def test_spoken_yes_and_no_map_to_permission_commands_only_while_waiting(self):
        self.assertIsNone(agent.consent_reply('alice', 'evet'))
        self.begin(self.paint(), 'bir fırça seç')
        self.assertEqual(agent.consent_reply('alice', 'evet'), 'PC izin ver')
        self.assertEqual(agent.consent_reply('alice', 'hayır.'), 'PC izin verme')
        self.assertIsNone(agent.consent_reply('alice', 'belki'))

    def test_builtin_calculator_and_notepad_need_no_permission(self):
        self.assertTrue(agent.app_permitted('alice', 'calculatorapp'))
        self.assertTrue(agent.app_permitted('alice', 'notepad'))
        self.assertFalse(agent.app_permitted(None, 'mspaint'))
