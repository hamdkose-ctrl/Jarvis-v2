"""Faz 1 #352: model yokken doğrulanmış teslim haber/finans dışına da yayılır.

Ölçülen boşluk (22 Kasım 2026, 18:10): model kapalıyken "güncel akademik makaleleri
listele" hedefi hiç adım üretmedi → `paused`, `model_free.evidence` boş, kullanıcıya
yalnız "model yok" dendi. Oysa listenin kendisi modelsiz üretilebiliyor
(`task_workers.academic_listing`, arXiv Atom API; model çağrısı yok). Haber için
`news_recovery` vardı, akademik liste için karşılığı yoktu.

Tetik dar ve kapalı: akademik dil + haber/dosya isteği değil + iş hiç adım üretmemiş
+ planlayıcı model yok. Koşullardan biri düşerse eski davranış korunur.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import goal_executor as goals, llm
import test_goal_executor as fixture

ACADEMIC = 'Kuantum bilgisayarlar üzerine güncel akademik makaleleri listele'

ROWS = [
    {'provider': 'arxiv', 'title': 'Quantum metainterfaces', 'url': 'https://arxiv.org/abs/2604.08195v1',
     'published': '2026-11-20', 'snippet': 'We study normal contact of metainterfaces.'},
    {'provider': 'arxiv', 'title': 'Ikinci makale', 'url': 'https://arxiv.org/abs/2604.00002v1',
     'published': '2026-11-18', 'snippet': 'Second abstract.'},
]


def listing_output():
    """Gerçek modelsiz liste çıktısı (uydurma kanıt yerine üretim sözleşmesi).

    Üretimde bu çıktı `task_results.seal` ile mühürlenir; test de aynı mühürden geçirir.
    """
    from modules import task_results
    from modules.task_workers import academic_listing
    sealed = task_results.seal('research', dict(academic_listing([dict(row) for row in ROWS], ACADEMIC),
                                                owner='alice'))
    sealed['owner'] = 'alice'
    return sealed


class ModelFreeAcademicDeliveryTests(unittest.TestCase):
    def case(self):
        case = fixture.GoalTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def run_planner_down(self, request, execute=None):
        case = self.case()
        case.responses(llm.LocalModelError('Ollama kapalı'))
        target = execute or (lambda *a, **k: listing_output())
        with patch('modules.specialist_orchestrator.execute_step', side_effect=target):
            result = goals.run(case.runtime, request)
        return goals.latest('alice'), result

    def test_academic_listing_is_delivered_without_a_planner(self):
        job, result = self.run_planner_down(ACADEMIC)
        self.assertEqual([step['tool'] for step in job['steps']], ['research'])
        self.assertEqual(job['steps'][0]['state'], 'done')
        self.assertEqual(job['state'], 'done')
        self.assertEqual([goal['state'] for goal in job['goals']], ['done'])
        self.assertIn('Quantum metainterfaces', result)

    def test_news_request_keeps_its_own_recovery(self):
        job, _ = self.run_planner_down('yapay zeka haberleri')
        self.assertEqual([step['tool'] for step in job['steps']], [])   # akademik yol devreye girmez
        self.assertEqual(job['state'], 'paused')

    def test_plain_request_is_untouched(self):
        job, result = self.run_planner_down('Masaüstündeki dosyaları düzenle')
        self.assertEqual([step['tool'] for step in job['steps']], [])
        self.assertEqual(job['state'], 'paused')
        self.assertIn('henüz doğrulanmış bir sonuç yok', result)

    def test_failed_listing_keeps_the_old_behaviour(self):
        """Kaynak bulunamazsa uydurma teslim yok: hedef açık kalır, model yokluğu söylenir."""
        def boom(*_a, **_k):
            raise ValueError('Araştırma sorgusu için güvenilir açık kaynak bulunamadı.')
        job, result = self.run_planner_down(ACADEMIC, execute=boom)
        self.assertEqual(job['state'], 'paused')
        self.assertTrue(all(goal['state'] == 'pending' for goal in job['goals']))
        self.assertIn('henüz doğrulanmış bir sonuç yok', result)

    def test_trigger_guards(self):
        """Kapı dar kalmalı: adım varsa, istek boşsa veya akademik dil yoksa hiçbir şey yapılmaz."""
        job = {'id': 'j', 'owner': 'alice', 'request': ACADEMIC, 'state': 'paused', 'goals': [], 'steps': []}
        self.assertTrue(goals._model_free_academic_deliver.__doc__)
        self.assertFalse(goals._model_free_academic_deliver(None, dict(job, steps=[{'id': 's1'}])))
        self.assertFalse(goals._model_free_academic_deliver(None, dict(job, request='')))
        self.assertFalse(goals._model_free_academic_deliver(None, dict(job, request='hava nasıl')))
        self.assertFalse(goals._model_free_academic_deliver(None, dict(job, request='akademik makale raporu dosya oluştur')))


if __name__ == '__main__':
    unittest.main()


class GoalsAlreadyExistTests(unittest.TestCase):
    """Canlı kusur (22 Kasım 19:08): model hattı çöktü (Gemini 503 + Groq 429 + Cloudflare),
    hedefte dört boş hedef vardı ve model-dışı teslim **tetiklenmedi**; kullanıcıya yalnız
    "modele ulaşamıyorum" dendi. Kapı 'hedef listesi boş' diye şart koymuştu; doğru şart
    'hiç adım üretilmemiş' olmasıdır.
    """

    def test_delivery_runs_even_when_planner_created_goals_first(self):
        case = fixture.GoalTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        job = {'id': '0123456789abcdef', 'owner': 'alice', 'request': ACADEMIC, 'state': 'paused',
               'goals': [{'text': 'araştır', 'state': 'pending', 'evidence': []} for _ in range(4)],
               'steps': [], 'outputs': {}}
        goals._save(job)   # fixture deposu geçici kök: canlı kullanıcı kaydına dokunulmaz
        with patch('modules.specialist_orchestrator.execute_step', side_effect=lambda *a, **k: listing_output()):
            delivered = goals._model_free_academic_deliver(case.runtime, job)
        self.assertTrue(delivered)
        self.assertEqual([step['tool'] for step in job['steps']], ['research'])
        self.assertEqual(job['steps'][0]['state'], 'done')
        self.assertEqual([goal['state'] for goal in job['goals']], ['done'] * 4)

    def test_gate_only_requires_missing_steps(self):
        source = (Path(__file__).resolve().parents[1] / 'modules/goal_executor.py').read_text(encoding='utf-8')
        self.assertIn("if planner_pending and not resume and not job['steps']:", source)
        self.assertNotIn("not job['goals'] and not job['steps']:", source)
