"""Haber tamamlanma/kurtarma politikası news_policy'de durur; goal_executor yalnız aynı adlı sarmalayıcıyı çağırır.

Taşıma davranış değiştirmemeli: iki giriş noktası aynı sonucu vermeli. Model ve ağ yoktur.
"""
import unittest
from unittest.mock import patch

from modules import goal_executor as goals, news_policy


def discovery_only_job(request):
    return {'request': request, 'state': 'running', 'goals': [], 'partial_report': None,
            'steps': [{'id': 's1', 'tool': 'data', 'input': {'operation': 'headlines'}, 'depends': []}],
            'outputs': {'s1': {'state': 'done', 'text': 'başlık listesi'}}}


class NewsPolicySplitTests(unittest.TestCase):
    GOAL = {'text': 'Haberleri araştır ve rapor yaz'}

    def test_headline_list_alone_never_completes_news_research(self):
        job = discovery_only_job('Son yapay zekâ haberlerini araştır ve rapor dosyası oluştur')
        with self.assertRaises(ValueError) as direct:
            news_policy.check_completion(job, self.GOAL, ['s1'])
        with self.assertRaises(ValueError) as wrapped:
            goals._check_news_completion(job, self.GOAL, ['s1'])
        self.assertEqual(str(direct.exception), str(wrapped.exception))
        self.assertIn('tekil haber gövdesi', str(direct.exception))

    def test_non_news_request_is_not_checked(self):
        job = discovery_only_job('Masaüstündeki dosyayı Word yap')
        self.assertIsNone(news_policy.check_completion(job, self.GOAL, ['s1']))
        self.assertIsNone(goals._check_news_completion(job, self.GOAL, ['s1']))

    def test_resume_wrapper_passes_the_executors_own_save(self):
        job = discovery_only_job('Masaüstündeki dosyayı Word yap')
        with patch.object(news_policy, 'resume_recovery', return_value=False) as call, patch.object(goals, '_save') as save:
            self.assertFalse(goals._resume_news_recovery(object(), job, 1))
        self.assertIs(call.call_args.args[3], save)       # çağrı anındaki _save (testler yamalar)


if __name__ == '__main__':
    unittest.main()
