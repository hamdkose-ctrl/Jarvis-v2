from decimal import Decimal
from contextlib import nullcontext
import unittest
from unittest.mock import patch
from modules import finance


class BareAmountTests(unittest.TestCase):
    def test_bare_dollar_forms(self):
        for text in ('6 dolar', '6 dolar.', '6 Dolar', '6 doları'):
            with self.subTest(text=text):
                self.assertEqual(finance.parse(text), {'amount': Decimal(6), 'source': 'USD', 'target': 'TRY', 'list': None})

    def test_euro_and_existing_conversion(self):
        self.assertEqual(finance.parse('100 euro'), {'amount': Decimal(100), 'source': 'EUR', 'target': 'TRY', 'list': None})
        self.assertEqual(finance.parse('6 dolar kaç tl'), {'amount': Decimal(6), 'source': 'USD', 'target': 'TRY', 'list': None})

    def test_answer_with_only_fake_rates(self):
        with patch.object(finance, 'rates', return_value=({'USD': Decimal(40), 'TRY': Decimal(1)}, 'Taklit kaynak')) as rates:
            reply = finance.answer('6 dolar')
        self.assertIsInstance(reply, str)
        self.assertIn('6 dolar', reply)
        self.assertIn('TL eder', reply)
        self.assertIn('Taklit kaynak', reply)
        self.assertNotIn('e-posta', reply)
        rates.assert_called_once_with(['USD', 'TRY'])

    def test_pending_recipient_question_does_not_swallow_currency_but_accepts_address(self):
        from datetime import datetime
        import uuid
        from test_mail_calendar_fixes import ProfileCase, _runtime
        from modules import brain_entry, goal_executor as goals, requests_state
        fixture = ProfileCase()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        rt = _runtime(self, fixture.profile, datetime(2026, 10, 20, 12, 0))

        def say(text):
            # BRAIN-03 dilim 3: fiyat cevabı artık ham yüzeyden değil canonical plandan gelir
            # (`finance.read` → `engine_intents.finance_read` → `finance.answer_request`).
            # Bu yüzden tur, üretimdeki gibi bir Brain girişi bağlanarak koşulur; aksi hâlde
            # `handle` fail-closed durur ve sipariş sırası ölçülmez olurdu.
            rid = 'fin-bare-' + uuid.uuid4().hex[:8]
            requests_state.register(rt.profile.slug, rid)
            with requests_state.activate(rt.profile.slug, rid):
                entry = brain_entry.prepare(rt, owner=rt.profile.slug, request_id=rid,
                                            text=text, source='yazı')
                out, _feedback, _ = brain_entry.handoff(rt, entry, rt.handle, text)
            return entry, out

        job = {'state': 'question', 'question': 'Alıcının e-posta adresi nedir?'}
        with patch.object(goals, 'latest', return_value=job), \
             patch.object(goals, 'age', return_value=0), \
             patch.object(goals, 'active', return_value=False), \
             patch.object(goals, 'run', return_value='Hedef yanıtı alındı.') as resume, \
             patch.object(finance, 'rates', return_value=({'USD': Decimal(40), 'TRY': Decimal(1)}, 'Taklit kaynak')), \
             nullcontext("ikinci classifier fiziksel olarak kaldırıldı"):
            with self.subTest(command='6 dolar'):
                entry, reply = say('6 dolar')
                self.assertEqual(entry.understanding.capability_hint, 'finance.read')
                self.assertIn('TL eder', reply)
                self.assertIn('Taklit kaynak', reply)
                resume.assert_not_called()
                self.assertTrue(goals._is_fast_command('6 dolar'))
            resume.reset_mock()
            with self.subTest(command='ali@ornek.com'):
                _entry, reply = say('ali@ornek.com')
                self.assertEqual(reply, 'Hedef yanıtı alındı.')
                resume.assert_called_once_with(rt, 'ali@ornek.com', resume=True)
                self.assertFalse(goals._is_fast_command('ali@ornek.com'))

    def test_non_questions_payment_send_alarm_and_percentage_are_unchanged(self):
        for text in ('6 dolar ödedim', '6 dolar gönder', 'dolar', '6', '6 tl',
                     'dolar alarmı kur 6 olunca haber ver', 'yüzde 6 dolar', '6% dolar',
                     'dolar nedir', '6 dolar nedir', '6..2 dolar'):
            with self.subTest(text=text):
                self.assertIsNone(finance.parse(text))


if __name__ == '__main__':
    unittest.main()
