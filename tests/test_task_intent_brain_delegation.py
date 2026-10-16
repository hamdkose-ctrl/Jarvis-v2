from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from modules import brain_delegate, engine_intents, requests_state


class TaskIntentBrainDelegationTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(slug='alice'))

    def test_replay_safe_specialist_plan_is_allowed(self):
        tasks=[
            {'id':'a','specialist':'research','tool':'research','input':{'url':'https://example.com'},'depends':[]},
            {'id':'b','specialist':'production','tool':'writer','input':{'instruction':'Rapor yaz'},'depends':['a']},
        ]
        self.assertTrue(brain_delegate._safe(tasks))

    def test_effectful_specialist_plan_stays_on_durable_goal_loop(self):
        for tool,data in (
            ('publish',{'service':'gmail','destination':'a@example.com','text':'x'}),
            ('browser',{'url':'https://example.com','instruction':'Butona tıkla'}),
            ('coder',{'request':'Projeyi değiştir'}),
        ):
            self.assertFalse(brain_delegate._safe([{'id':'a','specialist':'x','tool':tool,'input':data,'depends':[]}]))

    def test_task_intent_returns_brain_result_without_starting_goal_executor(self):
        runtime=self.runtime()
        with patch('modules.brain_delegate.try_run',return_value='Uzman sonucu') as brain, \
             patch('modules.goal_executor.run',side_effect=AssertionError('durable fallback çalışmamalı')):
            self.assertEqual(engine_intents.dispatch(runtime,'task',{},'Finans CSV dosyasını analiz et','finans csv dosyasını analiz et'),'Uzman sonucu')
        brain.assert_called_once_with(runtime,'Finans CSV dosyasını analiz et')

    def test_task_intent_falls_back_before_effectful_execution(self):
        runtime=self.runtime()
        with patch('modules.brain_delegate.try_run',return_value=None) as brain, \
             patch('modules.goal_executor.run',return_value='Kalıcı hedef') as durable:
            self.assertEqual(engine_intents.dispatch(runtime,'task',{},'Instagram hesabına gönder','instagram hesabına gönder'),'Kalıcı hedef')
        brain.assert_called_once();durable.assert_called_once_with(runtime,'Instagram hesabına gönder')

    def test_task_intent_planning_error_falls_back_but_cancellation_does_not(self):
        runtime=self.runtime()
        with patch('modules.brain_delegate.try_run',side_effect=ValueError('bad plan')), \
             patch('modules.goal_executor.run',return_value='Kalıcı hedef') as durable:
            self.assertEqual(engine_intents.dispatch(runtime,'task',{},'Araştır','araştır'),'Kalıcı hedef')
            durable.assert_called_once()
        with patch('modules.brain_delegate.try_run',side_effect=requests_state.Cancelled()), \
             patch('modules.goal_executor.run') as durable:
            with self.assertRaises(requests_state.Cancelled):
                engine_intents.dispatch(runtime,'task',{},'Araştır','araştır')
            durable.assert_not_called()


if __name__=='__main__':
    unittest.main()
