"""Bayat hedef işi ve kota beklemesi: eski iş yeni cümleleri yutmaz, kotası dolu modele yeni iş açılmaz.

Model çağrılmaz (llm.ask taklit); gerçek PC, Gemini veya ağ denemesinin yerini tutmaz.
"""
from contextlib import nullcontext
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import goal_executor as goals, llm, nxapi, smart_router

HOUR = 3600


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); root = Path(self.tmp.name)
        for obj, name, value in [(goals, 'STORE', root / 'goals'), (goals, '_ACTIVE', set()), (nxapi, 'FILES_DIR', root / 'files')]:
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice', data={'items': []}), _cur_source='yazı',
                                       pc_profile=lambda: self.runtime.profile, emit=Mock())
        p = patch.object(llm, 'ask'); self.ask = p.start(); self.addCleanup(p.stop)
        p = patch.object(llm, 'quota_wait_seconds', return_value=0); self.quota = p.start(); self.addCleanup(p.stop)

    def job(self, state, age_hours, **extra):
        stamp = time.time() - age_hours * HOUR
        job = {'id': '0123456789abcdef', 'owner': 'alice', 'request': 'bugünün haberleri', 'created': stamp, 'updated': stamp,
               'state': state, 'goals': [], 'steps': [], 'outputs': {}, **extra}
        # _save damgayı yenilediği için dosyayı doğrudan yazarız.
        root = goals._root('alice')
        (root / (job['id'] + '.json')).write_text(json.dumps(job), encoding='utf-8')
        (root / 'latest.json').write_text(json.dumps({'id': job['id']}), encoding='utf-8')
        return job


class StaleGoalTests(_Base):
    def test_stale_paused_job_is_not_resumed_by_bare_devam(self):
        self.job('paused', 7)
        text = goals.handle(self.runtime, 'devam')
        self.ask.assert_not_called()
        self.assertIn('hedef devam', text); self.assertIn('hedef iptal', text)
        self.assertEqual(goals.latest('alice')['state'], 'paused')

    def test_explicit_hedef_devam_still_resumes_a_stale_job(self):
        self.job('paused', 7)
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.handle(self.runtime, 'hedef devam')
        self.assertTrue(self.ask.called)

    def test_fresh_paused_job_is_resumed_by_bare_devam(self):
        self.job('paused', 1)
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.handle(self.runtime, 'devam')
        self.assertTrue(self.ask.called)

    def test_bare_devam_after_done_job_does_not_replay_it(self):
        self.job('done', 0.1)
        text = goals.handle(self.runtime, 'devam')
        self.ask.assert_not_called()
        self.assertIn('Açık hedef yok', text); self.assertIn('tamamlandı', text)

    def test_bare_devam_after_cancelled_job_says_cancelled(self):
        self.job('cancelled', 0.1)
        text = goals.handle(self.runtime, 'devam')
        self.assertIn('Açık hedef yok', text); self.assertIn('iptal', text)

    def test_bare_iptal_ignores_stale_job_but_cancels_fresh_one(self):
        self.job('paused', 7)
        self.assertIsNone(goals.handle(self.runtime, 'iptal'))
        self.assertEqual(goals.latest('alice')['state'], 'paused')
        self.job('paused', 1)
        goals.handle(self.runtime, 'iptal')
        self.assertEqual(goals.latest('alice')['state'], 'cancelled')

    def test_old_question_does_not_swallow_unrelated_sentences(self):
        self.job('question', 0.5, question='Hangi kurum?')
        self.assertIsNone(goals.handle(self.runtime, 'dolar ne kadar'))
        self.ask.assert_not_called()

    def test_fresh_question_still_takes_the_answer(self):
        self.job('question', 0.02, question='Hangi kurum?')
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.handle(self.runtime, 'Boğaziçi Üniversitesi')
        self.assertTrue(self.ask.called)

    def test_fresh_review_job_blocks_new_goal_with_clear_message(self):
        self.job('review', 1)
        text = goals.run(self.runtime, 'yeni bir iş yap')
        self.ask.assert_not_called()
        self.assertIn('hedef iptal', text)

    def test_stale_review_job_does_not_block_new_goal(self):
        old = self.job('review', 7)
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.run(self.runtime, 'yeni bir iş yap')
        self.assertTrue(self.ask.called)
        self.assertNotEqual(goals.latest('alice')['id'], old['id'])

    def test_unstamped_job_keeps_old_behaviour(self):
        job = self.job('paused', 0); job.pop('created'); job.pop('updated')
        self.assertTrue(goals.is_open(job))


class QuotaGateTests(_Base):
    def test_new_goal_is_not_started_while_every_model_waits(self):
        self.quota.return_value = 90
        text = goals.run(self.runtime, 'bugünün haberleri neler')
        self.ask.assert_not_called()
        self.assertIsNone(goals.latest('alice'))
        self.assertIn('kota', text.lower()); self.assertIn('90', text)

    def test_resume_is_not_blocked_by_quota_gate(self):
        self.job('paused', 1); self.quota.return_value = 90
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.handle(self.runtime, 'devam')
        self.assertTrue(self.ask.called)

    def test_gate_failure_never_blocks_a_goal(self):
        self.quota.side_effect = RuntimeError('beklenmeyen')
        self.ask.side_effect = RuntimeError('models unavailable')
        goals.run(self.runtime, 'bir iş yap')
        self.assertTrue(self.ask.called)


class WaitSecondsTests(unittest.TestCase):
    def test_auto_provider_waits_only_when_no_candidate_is_left(self):
        rows = {'candidates': [], 'skipped': [{'provider': 'gemini', 'seconds': 293, 'reason': 'x'},
                                               {'provider': 'groq', 'seconds': 40, 'reason': 'x'}]}
        with patch.object(smart_router, 'selection', return_value=rows):
            self.assertEqual(smart_router.wait_seconds('alice'), 40)
        rows['candidates'] = ['ollama']
        with patch.object(smart_router, 'selection', return_value=rows):
            self.assertEqual(smart_router.wait_seconds('alice'), 0)

    def test_missing_key_without_any_wait_is_not_a_quota_wait(self):
        rows = {'candidates': [], 'skipped': [{'provider': 'gemini', 'seconds': 0, 'reason': 'anahtar yok'}]}
        with patch.object(smart_router, 'selection', return_value=rows):
            self.assertEqual(smart_router.wait_seconds('alice'), 0)

    def test_llm_helper_uses_router_in_auto_mode(self):
        with patch.object(llm, 'provider', return_value='auto'), patch.object(smart_router, 'wait_seconds', return_value=12):
            self.assertEqual(llm.quota_wait_seconds('alice'), 12)

    def test_llm_helper_reads_gemini_rate_limit_marks(self):
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        with patch.object(llm, 'provider', return_value='gemini'), patch.object(llm, 'user_groq_key', return_value=''), \
                patch.object(llm, 'model_names', return_value=['m1', 'm2']), patch.dict(llm._rate_limited, clear=True):
            self.assertEqual(llm.quota_wait_seconds('alice'), 0)
            llm._mark_limited('gemini', 'm1', RuntimeError('429'), 60)
            self.assertEqual(llm.quota_wait_seconds('alice'), 0)      # ikinci model hâlâ açık
            llm._mark_limited('gemini', 'm2', RuntimeError('429'), 30)
            self.assertTrue(0 < llm.quota_wait_seconds('alice') <= 30)


if __name__ == '__main__':
    unittest.main()
