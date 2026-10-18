"""Soru bekleyen eski hedef, açık yeni mail/plan komutunu yutmamalı (GPT raporu madde 3, 18 Ekim 2026).

Eski hata: goal_executor.handle, hedef 'question' durumundayken eylemle bitmeyen her cümleyi (ör. "bugünün planı")
hedefe cevap sayıyordu. Gerçek EngineContext.handle kullanılır; hedef kaydı ve Google taklittir, model çağrılmaz.
"""
import unittest
from unittest.mock import patch

from test_mail_calendar_fixes import ProfileCase, _runtime
from datetime import datetime

from modules import goal_executor


class PendingGoalTests(ProfileCase):
    def _ask(self, text):
        rt = _runtime(self, self.profile, datetime(2026, 10, 18, 9, 0))
        job = {'state': 'question', 'owner': rt.profile.slug, 'id': 'a' * 16}
        resumed = []
        with patch.object(goal_executor, 'latest', return_value=job), \
                patch.object(goal_executor, 'run', side_effect=lambda *a, **k: resumed.append(a[1]) or 'HEDEFE GİTTİ'):
            # Google taklit olduğu için mail cümleleri sınıflandırıcıya kadar düşebilir; önemli olan hedefe gitmemesi.
            with patch('modules.router.classify', side_effect=RuntimeError('sınıflandırıcıya düştü')):
                try:
                    reply = rt.handle(text)
                except RuntimeError:
                    reply = None
        return reply, resumed

    def test_new_plan_and_mail_commands_are_not_answers_to_the_pending_question(self):
        for text in ('bugünün planı', 'günümü planla', 'önemli maillerim', 'cevap vermediğim mailler'):
            with self.subTest(text=text):
                reply, resumed = self._ask(text)
                self.assertEqual(resumed, [], f'{text!r} bekleyen hedefe cevap sayıldı')

    def test_real_answers_still_reach_the_pending_goal(self):
        for text in ('son 7 gün', 'evet resmi kaynaklardan', 'Ankara'):
            with self.subTest(text=text):
                _reply, resumed = self._ask(text)
                self.assertEqual(resumed, [text])


if __name__ == '__main__':
    unittest.main()
