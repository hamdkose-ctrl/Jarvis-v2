"""Independent known-answer checks, unsafe expressions and real tutor integration."""
import json
import unittest
from fractions import Fraction
from unittest.mock import patch
from modules import math_verifier as verifier, math_tutor as tutor
import test_math_tutor


class ArithmeticTests(unittest.TestCase):
    def test_exact_arithmetic_and_latex(self):
        cases = {'2^2+(-1)^3': 3, r'\frac{3}{3}': 1, r'\frac{\frac{1}{2}}{3}': Fraction(1,6), '0.1+0.2': Fraction(3,10), '2(3+1)':8, '3²-2³':1, '1,5/0,5':3, '2×3+4':10, '1e-2':Fraction(1,100)}
        for text, expected in cases.items():
            with self.subTest(text=text):self.assertEqual(verifier.calculate(text), expected)

    def test_no_code_execution_or_unbounded_calculation(self):
        for text in ('__import__("os").system("echo bad")', '(1).__class__', '[1][0]', '2**100000', '1e99999999', '1/0', 'True', 'a+1', 'sin(1)', '- ' * 30+'1'):
            with self.subTest(text=text), self.assertRaises(verifier.Unsupported):
                verifier.calculate(text)

    def work(self, final='1', goal='solve', scope='question'):
        return {'goal':goal,'scope':scope,'given':['x = 2','y = -1'], 'problem':r'\frac{x^2+y^3}{x-y}', 'steps':[
            {'kind':'intermediate','expression':'2^2+(-1)^3=4-1=3'},
            {'kind':'intermediate','expression':'2-(-1)=3'},
            {'kind':'final','expression':final}]}

    def test_distinguishes_numerator_three_from_final_answer_one(self):
        correct = verifier.verify(self.work())
        self.assertEqual(correct['status'], 'checked');self.assertEqual(correct['checked'],3)
        incorrect = verifier.verify(self.work(final='3'))
        self.assertEqual(incorrect['status'],'incorrect')
        self.assertEqual(incorrect['steps'][-1]['expected'],'1')

    def test_wrong_intermediate_and_unknown_symbol_are_distinct(self):
        work=self.work();work['steps'][0]['expression']='2^2+(-1)^3=5'
        self.assertEqual(verifier.verify(work)['status'],'incorrect')
        work['steps'][0]['expression']='z+1=5'
        result=verifier.verify(work)
        self.assertEqual(result['steps'][0]['status'],'unverified')
        work['steps'][-1]['expression']='z=1'
        self.assertEqual(verifier.verify(work)['steps'][-1]['status'],'unverified')

    def test_does_not_validate_entire_question_from_selected_area(self):
        work=self.work(final='3',scope='selection')
        self.assertEqual(verifier.verify(work)['steps'][-1]['status'],'unverified')

    def test_unknown_prefix_cannot_hide_false_numeric_equality(self):
        work=self.work();work['steps'][0]['expression']='z=3=5'
        self.assertEqual(verifier.verify(work)['steps'][0]['status'],'incorrect')

    def test_zero_division_cannot_be_presented_as_numeric_result(self):
        self.assertEqual(verifier.verify(None,'1/0=2')['status'],'incorrect')

    def test_plain_prose_does_not_extract_false_fragments_from_symbolic_equations(self):
        result=verifier.verify(None,'2x + 4 = 10. Önce 4 çıkar: 2x = 6. Kontrol: 2×3+4=10.')
        self.assertEqual(result['status'],'checked');self.assertEqual(result['checked'],1)
        self.assertEqual(verifier.verify(None,'2+2=5')['status'],'incorrect')


class TutorVerificationTests(unittest.TestCase):
    def setUp(self):
        fixture=test_math_tutor.MathTutorTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.profile=fixture.p

    def reply(self, expression):
        return json.dumps({'text':'Çözüm','work':{'given':[],'problem':'2+2','steps':[{'title':'Topla','expression':expression,'kind':'final'}]}})

    def test_wrong_model_result_is_recalculated_once(self):
        with patch.object(tutor.llm,'ask',side_effect=[self.reply('2+2=5'),self.reply('2+2=4')]) as model:
            result=tutor.solve(self.profile,'2+2 çöz')
        self.assertEqual(model.call_count,2)
        self.assertIn('Bağımsız aritmetik',model.call_args.args[0])
        self.assertEqual(result['verification']['status'],'checked')
        self.assertNotIn('2+2=5',result['text'])

    def test_two_wrong_responses_never_save_progress(self):
        with patch.object(tutor.llm,'ask',return_value=self.reply('2+2=5')) as model:
            with self.assertRaisesRegex(ValueError,'hatalı çözüm'):
                tutor.solve(self.profile,'2+2 çöz')
        self.assertEqual(model.call_count,2)
        self.assertFalse(self.profile.data['study'].get('math_turns'))

    def test_malformed_json_is_retried_once_without_saving_first_response(self):
        with patch.object(tutor.llm,'ask',side_effect=['{broken',self.reply('2+2=4')]) as model:
            result=tutor.solve(self.profile,'2+2 çöz')
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['verification']['status'],'checked')
        self.assertEqual(len(self.profile.data['study']['math_turns']),2)

    def test_two_malformed_json_responses_do_not_save_progress(self):
        with patch.object(tutor.llm,'ask',return_value='{broken') as model:
            with self.assertRaisesRegex(ValueError,'biçimi okunamadı'):
                tutor.solve(self.profile,'2+2 çöz')
        self.assertEqual(model.call_count,2)
        self.assertFalse(self.profile.data['study'].get('math_turns'))

    def test_unsupported_math_is_explicitly_unverified(self):
        with patch.object(tutor.llm,'ask',return_value=self.reply(r'\sin(x)=1')):
            result=tutor.solve(self.profile,'Sinüsü anlat')
        self.assertEqual(result['verification']['status'],'unverified')
        self.assertIn('doğrulanamadı',result['text'])
