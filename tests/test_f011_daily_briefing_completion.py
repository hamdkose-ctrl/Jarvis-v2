import queue
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class F011DailyBriefingCompletionTests(unittest.TestCase):
    def owner(self):
        owner = SimpleNamespace(
            name='Hamdi', slug='hamdi', path=None,
            data={
                'prefs': {},
                'tasks': [
                    {'id': 1, 'text': 'Geciken rapor', 'done': False, 'when': '2026-10-26'},
                    {'id': 2, 'text': 'Bugünkü sunum', 'done': False, 'when': '2026-10-27T18:00'},
                    {'id': 3, 'text': 'Açık araştırma', 'done': False, 'when': ''},
                    {'id': 4, 'text': 'Biten iş', 'done': True, 'when': '2026-10-27'},
                ],
                'goals': [],
            },
        )
        owner.set_pref = lambda k, v: owner.data['prefs'].__setitem__(k, v)
        owner.events_on = lambda _day: []
        return owner

    def runtime(self, owner=None):
        owner = owner or self.owner()
        now = datetime(2026, 10, 27, 9, 0)
        return SimpleNamespace(
            profile=owner,
            pc_profile=Mock(return_value=owner),
            datetime=SimpleNamespace(now=lambda: now),
            timedelta=__import__('datetime').timedelta,
            stop_event=SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)),
            flags={'sleep': False},
            _llm=Mock(), _emit_for=Mock(), events=queue.Queue(),
            weather=SimpleNamespace(report=Mock(return_value='')), _DAYS=('Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'),
            google_api=SimpleNamespace(connected=Mock(return_value=False)),
            ask=Mock(return_value='Kısa özet'), ASSISTANT_NAME='Jarvis',
        )

    def test_scheduler_entrypoint_reuses_day_guard_without_startup_delay(self):
        from modules import engine_background, main_planner
        owner = self.owner(); runtime = self.runtime(owner)
        with patch.object(main_planner, '_daily_briefing', return_value='Günlük özet') as briefing:
            engine_background._scheduled_brief(runtime)
            engine_background._scheduled_brief(runtime)
        briefing.assert_called_once()
        runtime.stop_event.wait.assert_not_called()
        runtime._emit_for.assert_called_once_with(owner, 'assistant', 'Günlük özet')
        self.assertEqual(owner.data['prefs']['last_brief'], '2026-10-27')

    def test_brief_facts_reuse_day_plan_and_read_only_work_state(self):
        from modules import engine_background
        runtime = self.runtime()
        snapshot = {
            'owner': 'hamdi',
            'goal': {'id': 'goal-1', 'state': 'approval', 'open': True},
            'task': {'id': 'job-1', 'state': 'done', 'updated': 1},
            'authority': 'core', 'permission_granted': False,
        }
        with patch('modules.main_planner._day_plan', return_value='Görevler: 1 gecikmiş (Geciken rapor), bugün 1 (Bugünkü sunum), ayrıca 1 açık görev.'), \
             patch('modules.continuity.snapshot', return_value=snapshot), \
             patch('modules.outlook.installed', return_value=False):
            facts = engine_background._scheduled_brief_facts(runtime)
        text = '\n'.join(facts)
        self.assertIn('1 gecikmiş (Geciken rapor)', text)
        self.assertIn('bugün 1 (Bugünkü sunum)', text)
        self.assertIn('ayrıca 1 açık görev', text)
        self.assertIn('Bekleyen onay', text)
        self.assertIn('Tamamlanan iş', text)

    def test_blocked_or_failed_work_is_visible_as_blocker_fact(self):
        from modules import engine_background
        runtime = self.runtime()
        snapshot = {
            'owner': 'hamdi',
            'goal': {'id': 'goal-1', 'state': 'blocked', 'open': True},
            'task': {'id': 'job-1', 'state': 'failed', 'updated': 1},
            'authority': 'core', 'permission_granted': False,
        }
        with patch('modules.main_planner._day_plan', return_value='Bugünün planı.'), \
             patch('modules.continuity.snapshot', return_value=snapshot), \
             patch('modules.outlook.installed', return_value=False):
            text = '\n'.join(engine_background._scheduled_brief_facts(runtime))
        self.assertIn('Engel', text)
        self.assertIn('blocked', text)
        self.assertIn('failed', text)

    def test_google_reconnect_failure_from_day_plan_stays_visible_fact(self):
        from modules import engine_background
        runtime = self.runtime()
        with patch('modules.main_planner._day_plan', return_value='Google Takvim\'e bakamadım ve Gmail\'e bakamadım. Google izni çalışmıyor; “Bağlan” düğmesine basıp izni yenile.'), \
             patch('modules.continuity.snapshot', return_value={'owner':'hamdi','goal':None,'task':None,'authority':'core','permission_granted':False}), \
             patch('modules.outlook.installed', return_value=False):
            text = '\n'.join(engine_background._scheduled_brief_facts(runtime))
        self.assertIn('Google izni çalışmıyor', text)

    def test_engine_uses_existing_task_queue_scheduler_for_daily_brief(self):
        source = Path(__file__).resolve().parents[1] / 'main.py'
        text = source.read_text(encoding='utf-8')
        self.assertIn('task_queue.set_daily_notify', text)
        self.assertIn('engine_background._scheduled_brief', text)


if __name__ == '__main__':
    unittest.main()
