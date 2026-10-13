import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

class Profile:
    slug='fixture'
    def __init__(self):
        self.data={'study':{'docs':[{'id':1,'title':'Motorlar.txt','kind':'book'}, {'id':2,'title':'Başka.txt','kind':'book'}]}}
        self.n=20
    def _new_id(self):
        self.n+=1
        return self.n
    def save(self): pass

class SourceAndPlannerTests(unittest.TestCase):
    def test_empty_start_uses_selected_document_and_records_it(self):
        from modules import study
        p=Profile()
        with tempfile.TemporaryDirectory() as td, patch.object(study,'ROOT',Path(td)), patch.object(study.llm,'ask',return_value='Motor açıklaması') as ask:
            d=Path(td)/p.slug;d.mkdir()
            (d/'1.txt').write_text('Asenkron motorun dönmesi stator alanına bağlıdır.',encoding='utf8')
            (d/'2.txt').write_text('DİĞER DOSYAYA AİT ÖZEL İÇERİK',encoding='utf8')
            r=study.ask_source(p,'',1)
            prompt=ask.call_args.args[0]
            self.assertIn('stator alanına',prompt)
            self.assertNotIn('DİĞER DOSYAYA',prompt)
            self.assertIn('Kaynak: Motorlar.txt',r['text'])
            self.assertTrue(any('alıştırma sorusu' in q for q in r['questions']))
            self.assertEqual(p.data['study']['active_doc'],1)
            study.ask(p,'çalışmaya başla')
            self.assertIn('Motorlar.txt',ask.call_args.args[0])
    def test_no_source_and_deleted_selection_report_error(self):
        from modules import study
        p=Profile();p.data['study']['docs']=[]
        with self.assertRaisesRegex(ValueError,'kaynak'):
            study.source_info(p)
        with self.assertRaises(ValueError):
            study.source_info(Profile(),999)
    def test_task_dates_and_existing_undated_tasks_are_preserved(self):
        from modules import tasks
        p=Profile();old={'id':3,'text':'Eski görev','done':False};p.data['tasks']=[old]
        dated=tasks.add(p,'Rapor','2026-10-12')
        self.assertEqual(dated['when'],'2026-10-12')
        natural=tasks.add(p,'yarın motor bakımını yap')
        self.assertEqual(natural['when'],(datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d'))
        self.assertNotIn('when',old)
        tasks.toggle(p,dated['id'])
        self.assertTrue(dated['done'])
        with self.assertRaises(ValueError):tasks.add(p,'Yanlış tarih','2026-02-30')
