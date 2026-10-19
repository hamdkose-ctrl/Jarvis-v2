import copy
import unittest
from unittest.mock import Mock, patch

from modules import news_policy


REQUEST = 'TÜBİTAK yapay zekâ haberini araştır ve raporla'
GOAL = {'text': 'Haberi araştır ve rapor yaz'}


def job(*, steps=None, outputs=None, state='running', partial_report=None):
    return {
        'request': REQUEST,
        'state': state,
        'steps': [] if steps is None else steps,
        'outputs': {} if outputs is None else outputs,
        'partial_report': partial_report,
    }


class NewsPolicyEdgeTests(unittest.TestCase):
    def setUp(self):
        self.news = self.enterContext(patch('modules.research_evidence.news_requested', return_value=True))
        self.enterContext(patch('modules.publisher_news.broad_research', return_value=False))
        self.enterContext(patch('modules.publisher_news.publisher_key', side_effect=lambda url: url.split('/')[2]))
        self.catalog = self.enterContext(patch('modules.publisher_news.require_catalog'))

    def test_empty_or_sourceless_evidence_never_completes_research(self):
        rows = [
            (job(), []),
            (job(steps=[{'id': 's1', 'tool': 'research', 'input': {}, 'depends': []}],
                 outputs={'s1': {'state': 'done', 'text': 'özet var ama kaynak yok'}}), ['s1']),
        ]
        for current, evidence in rows:
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, 'haber.*kanıt|kanıt.*haber'):
                news_policy.check_completion(current, GOAL, evidence, final=False)

    def test_valid_article_is_accepted_and_final_flag_only_adds_catalog_check(self):
        current = job(
            steps=[{'id': 's1', 'tool': 'research', 'input': {}, 'depends': []}],
            outputs={'s1': {'state': 'done', 'news_article': {'url': 'https://tubitak.example/haber'}}},
        )
        with patch('modules.research_evidence.news_receipt', return_value={
                'url': 'https://tubitak.example/haber', 'published': '2026-10-18'}), \
             patch('modules.research_evidence.news_date'):
            self.assertIsNone(news_policy.check_completion(current, GOAL, ['s1'], final=False))
            self.catalog.assert_not_called()
            self.assertIsNone(news_policy.check_completion(current, GOAL, ['s1'], final=True))
            self.catalog.assert_called_once_with(current)

    def test_goal_without_text_uses_request_safely_and_still_needs_source(self):
        current = job()
        before = copy.deepcopy(current)
        with self.assertRaises(ValueError) as caught:
            news_policy.check_completion(current, {}, [], final=False)
        self.assertNotIsInstance(caught.exception, KeyError)
        self.assertEqual(current, before)

    def test_repeated_completion_check_is_stable_and_does_not_mutate_job(self):
        current = job()
        before = copy.deepcopy(current)
        messages = []
        for _ in range(2):
            with self.assertRaises(ValueError) as caught:
                news_policy.check_completion(current, GOAL, [], final=False)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(current, before)

    def test_malformed_jobs_fail_closed_without_keyerror(self):
        rows = [
            {},
            {'request': REQUEST},
            {'request': REQUEST, 'steps': []},
            {'request': REQUEST, 'outputs': {}},
            {'request': REQUEST, 'steps': 'x', 'outputs': {}},
        ]
        for current in rows:
            with self.subTest(current=current):
                with self.assertRaisesRegex(ValueError, 'Geçersiz haber işi'):
                    news_policy.check_completion(current, GOAL, [], final=False)

    def test_resume_recovery_missing_or_incomplete_job_returns_false(self):
        save = Mock()
        rows = [
            {},
            {'request': REQUEST},
            {'request': REQUEST, 'steps': []},
            job(),
            job(steps=[{'id': 's1'}], outputs={}),
        ]
        for current in rows:
            with self.subTest(current=current):
                self.assertFalse(news_policy.resume_recovery(object(), current, 0, save))
        save.assert_not_called()

    def test_resume_recovery_no_progress_returns_same_decision_on_repeat(self):
        current = job(
            steps=[{'id': 's1', 'tool': 'research', 'input': {}, 'depends': [], 'started': True, 'state': 'done'}],
            outputs={'s1': {'state': 'done', 'news_article': {'url': 'https://tubitak.example/haber'}}},
            partial_report='report-step',
        )
        save = Mock()
        with patch('modules.news_recovery.deliver', return_value=None), \
             patch('modules.publisher_news.catalog_keys', return_value={'a'}), \
             patch('modules.publisher_news.catalog_attempted', return_value=set()):
            first = news_policy.resume_recovery(object(), current, 1, save)
            second = news_policy.resume_recovery(object(), current, 1, save)
        self.assertFalse(first)
        self.assertFalse(second)


class MixedGoalTests(unittest.TestCase):
    """Gerçek news_requested: haber istenen işte haber olmayan hedef (mail, hava) kaynak aramamalı."""

    @staticmethod
    def _job(request, tool):
        return {'request': request, 'state': 'running', 'partial_report': None,
                'steps': [{'id': 'x1', 'tool': tool, 'input': {}, 'depends': []}],
                'outputs': {'x1': {'state': 'done'}}}

    def test_non_news_goal_in_news_job_is_not_blocked(self):
        for request, goal, tool in [
            ('bugün mailleri özetle ve İstanbul haberlerini araştır', 'mailleri özetle', 'mail'),
            ('hava durumunu söyle ve son haberleri araştır', 'hava durumu raporunu yaz', 'weather'),
        ]:
            with self.subTest(goal=goal):
                self.assertIsNone(news_policy.check_completion(self._job(request, tool), {'text': goal}, ['x1']))

    def test_news_goal_without_article_is_still_blocked(self):
        current = self._job('bugün mailleri özetle ve İstanbul haberlerini araştır', 'mail')
        with self.assertRaises(ValueError):
            news_policy.check_completion(current, {'text': 'İstanbul haberlerini araştır'}, ['x1'])


if __name__ == '__main__':
    unittest.main()
