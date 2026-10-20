from decimal import Decimal
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

    def test_non_questions_payment_send_alarm_and_percentage_are_unchanged(self):
        for text in ('6 dolar ödedim', '6 dolar gönder', 'dolar', '6', '6 tl',
                     'dolar alarmı kur 6 olunca haber ver', 'yüzde 6 dolar', '6% dolar',
                     'dolar nedir', '6 dolar nedir', '6..2 dolar'):
            with self.subTest(text=text):
                self.assertIsNone(finance.parse(text))


if __name__ == '__main__':
    unittest.main()
