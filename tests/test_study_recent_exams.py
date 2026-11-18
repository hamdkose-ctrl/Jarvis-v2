import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeProfile:
    def __init__(self):
        self.slug='hamdi'; self.data={}; self.n=1
    def _new_id(self):
        n=self.n; self.n+=1; return n
    def save(self): pass


class RecentExamStudyTests(unittest.TestCase):
    def test_recent_three_exam_years_and_legacy_books(self):
        from modules import study
        p=FakeProfile(); p.data['study']={'mode':'teacher','docs':[
            {'id':1,'title':'kitap.pdf'},
            {'id':2,'title':'2022.pdf','kind':'exam','year':2022},
            {'id':3,'title':'2023.pdf','kind':'exam','year':2023},
            {'id':4,'title':'2024.pdf','kind':'exam','year':2024},
            {'id':5,'title':'2025.pdf','kind':'exam','year':2025}], 'progress':[]}
        st=study.status(p)
        self.assertEqual(st['recent_exam_years'],[2025,2024,2023])
        self.assertEqual(st['exam_priority'],70)
        self.assertEqual(st['books'][0]['kind'],'book')

    def test_add_exam_keeps_year_and_kind(self):
        from modules import study
        p=FakeProfile()
        with tempfile.TemporaryDirectory() as td, patch.object(study,'ROOT',Path(td)):
            f=Path(td)/'soru.txt'; f.write_text('1. Soru: örnek',encoding='utf-8')
            item=study.add_exam(p,str(f),2025)
            self.assertEqual(item['kind'],'exam'); self.assertEqual(item['year'],2025)

    def test_prompt_distinguishes_exam_from_answer_key(self):
        from modules import study
        s=study._system('teacher',True,profile=FakeProfile())
        self.assertIn('cevap anahtarı gibi değil',s)
        self.assertIn('%70',s)


if __name__=='__main__': unittest.main()

class RecentExamAnalysisTests(unittest.TestCase):
    def test_aggregate_finds_top_rising_and_types(self):
        from modules import study
        data={"years":{
            "2025":{"question_count":10,"topics":[{"name":"Motorlar","count":5},{"name":"Koruma","count":3},{"name":"Ölçme","count":2}],"question_types":[{"name":"Hesaplama","count":6},{"name":"Kavram","count":4}]},
            "2024":{"question_count":10,"topics":[{"name":"Motorlar","count":3},{"name":"Koruma","count":4},{"name":"Ölçme","count":3}],"question_types":[{"name":"Hesaplama","count":5},{"name":"Kavram","count":5}]},
            "2023":{"question_count":10,"topics":[{"name":"Motorlar","count":2},{"name":"Koruma","count":5},{"name":"Ölçme","count":3}],"question_types":[{"name":"Hesaplama","count":4},{"name":"Kavram","count":6}]}
        },"confidence":"yüksek"}
        a=study._aggregate_exam_analysis(data,[2025,2024,2023])
        self.assertEqual(a['question_count'],30)
        self.assertEqual(a['top_topics'][0]['name'],'Koruma')
        self.assertEqual(a['rising_topics'][0]['name'],'Motorlar')
        self.assertEqual(a['question_types'][0]['name'],'Hesaplama')

    def test_exam_signature_uses_only_recent_three_years(self):
        from modules import study
        s={'docs':[{'id':1,'kind':'exam','year':2022,'chars':10},{'id':2,'kind':'exam','year':2023,'chars':20},
                   {'id':3,'kind':'exam','year':2024,'chars':30},{'id':4,'kind':'exam','year':2025,'chars':40}]}
        sig=study._exam_signature(s)
        self.assertNotIn('1:2022',sig)
        self.assertIn('4:2025:40',sig)
