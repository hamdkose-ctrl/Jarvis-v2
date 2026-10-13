"""Real study files/questions/state; no live model or hardware."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from modules import study,studyexam as exam,llm
from test_study_exam_bank import SAMPLE,_Profile


class StudyQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.p=_Profile([{'id':1,'title':'2025.txt','kind':'exam','year':2025,'chars':len(SAMPLE)}])
        for module,name,value in [(study,'ROOT',self.root/'study'),(study,'_jobs',{}),(study,'_LAST_TOPIC',{})]:
            p=patch.object(module,name,value);p.start();self.addCleanup(p.stop)
        (study._dir(self.p)/'1.txt').write_text(SAMPLE)
        self.mk=next(iter(exam.bank(self.p)));self.p.data['study']['courses']=[self.mk]
        self.questions=exam.bank(self.p)[self.mk]['items']
        self.p.data['study']['topics']={self.mk:{q['id']:'Hücre' for q in self.questions}}

    def wait_jobs(self):
        until=time.monotonic()+4
        while any(j['state']=='running' for j in study._jobs.get(self.p.slug,[])) and time.monotonic()<until:threading.Event().wait(.01)
        self.assertFalse(any(j['state']=='running' for j in study._jobs.get(self.p.slug,[])))

    def test_small_question_bank_continues_after_every_question_answered(self):
        for _ in range(8):
            q=exam.quiz_next(self.p,self.mk);self.assertIsNotNone(q)
            ans=exam._find(self.p,q['id'])[1]['answer']
            exam.quiz_answer(self.p,q['id'],ans,q['attempt_id'])
        self.assertEqual(len(exam._results(self.p)),8)

    def test_duplicate_answer_records_once_and_new_attempt_can_repeat(self):
        q=exam.quiz_next(self.p,self.mk);ans=exam._find(self.p,q['id'])[1]['answer']
        first=exam.quiz_answer(self.p,q['id'],ans,q['attempt_id'])
        self.assertEqual(exam.quiz_answer(self.p,q['id'],ans,q['attempt_id']),first)
        self.assertEqual(len(exam._results(self.p)),1)
        nextq=exam.quiz_next(self.p,self.mk)
        with self.assertRaises(ValueError):exam.quiz_answer(self.p,q['id'],ans,q['attempt_id'])
        self.assertEqual(len(exam._results(self.p)),1)

    def test_invalid_choice_never_counts_as_wrong(self):
        q=exam.quiz_next(self.p,self.mk)
        for c in ('Z','AA',''):
            with self.assertRaises(ValueError):exam.quiz_answer(self.p,q['id'],c,q['attempt_id'])
        self.assertEqual(exam._results(self.p),[])

    def test_mock_snapshot_survives_year_rollover_and_does_not_expose_answer(self):
        session=exam.mock_start(self.p,3);qid=session['current']['id']
        self.p.data['study']['docs']=[{'id':n,'kind':'exam','title':f'{y}.txt','year':y} for n,y in [(2,2026),(3,2027),(4,2028)]]
        current=exam.mock_status(self.p)['current'];self.assertNotIn('answer',current);self.assertEqual(current['id'],qid)
        private=self.p.data['study']['mock_session']['questions'][qid]
        result=exam.mock_answer(self.p,qid,private['answer'],session['id'])
        self.assertTrue(result['result']['ok']);self.assertEqual(result['status']['answered'],1)
        exam.mock_answer(self.p,qid,private['answer'],session['id']);self.assertEqual(len(exam._results(self.p)),1)

    def test_old_mock_session_answer_cannot_grade_replacement_session(self):
        old=exam.mock_start(self.p,3);new=exam.mock_start(self.p,3)
        self.assertNotEqual(old['id'],new['id'])
        with self.assertRaises(ValueError):exam.mock_answer(self.p,old['current']['id'],'A',old['id'])
        self.assertEqual(exam._results(self.p),[])

    def test_same_filename_different_sessions_and_modified_content_are_distinct(self):
        source=self.root/'sinav.txt';source.write_text(SAMPLE)
        study.add_async(self.p,source,'exam',2026,'1. Dönem','1. Oturum')
        study.add_async(self.p,source,'exam',2026,'1. Dönem','2. Oturum');self.wait_jobs()
        added=[d for d in self.p.data['study']['docs'] if d.get('year')==2026]
        self.assertEqual(len(added),2);self.assertEqual(len({d['id'] for d in added}),2)
        self.assertTrue(study.add_async(self.p,source,'exam',2026,'1. Dönem','1. Oturum')['exists'])
        source.write_text(SAMPLE+'\nYeni içerik')
        study.add_async(self.p,source,'exam',2026,'1. Dönem','1. Oturum');self.wait_jobs()
        self.assertEqual(len(self.p.data['study']['docs']),4)

    def test_clear_during_load_does_not_restore_deleted_sources(self):
        source=self.root/'book.txt';source.write_text('Eski kitap metni')
        started=threading.Event();release=threading.Event()
        def read(path):started.set();release.wait(3);return Path(path).read_text()
        with patch.object(study.docs,'read_document',side_effect=read):
            study.add_async(self.p,source);self.assertTrue(started.wait(2));study.clear(self.p);release.set();self.wait_jobs()
        self.assertEqual(study.status(self.p)['docs'],[])

    def test_upload_uses_snapshot_when_original_file_changes(self):
        source=self.root/'book.txt';source.write_text('İlk kitap metni')
        started=threading.Event();release=threading.Event()
        def read(path):started.set();release.wait(3);return Path(path).read_text()
        with patch.object(study.docs,'read_document',side_effect=read):
            study.add_async(self.p,source);self.assertTrue(started.wait(2));source.write_text('Sonradan gelen başka kitap');release.set();self.wait_jobs()
        item=self.p.data['study']['docs'][-1]
        self.assertEqual(item['title'],'book.txt');self.assertEqual((study._dir(self.p)/f"{item['id']}.txt").read_text(),'İlk kitap metni')

    def test_lesson_topic_survives_restart_and_followup_uses_lock(self):
        with patch.object(llm,'embed',side_effect=ValueError('no embed')),patch.object(llm,'ask',return_value='Hücre anlatımı'):
            study.lesson(self.p,'Hücre','Biyoloji',self.mk)
        study._LAST_TOPIC.clear();self.assertEqual(study.last_topic(self.p),'Hücre')
        with patch.object(llm,'embed',side_effect=ValueError()),patch.object(study,'analyze_recent_exams',return_value={}),patch.object(llm,'ask',return_value='Daha sade açıklama') as model:
            study.ask(self.p,'Bunu daha sade anlat')
        self.assertIn('AKTİF KONU: Hücre',model.call_args.kwargs['system'])

    def test_empty_model_answer_is_not_progress(self):
        with patch.object(llm,'embed',side_effect=ValueError()),patch.object(llm,'ask',return_value=''):
            with self.assertRaises(ValueError):study.lesson(self.p,'Hücre')
        self.assertEqual(self.p.data['study']['progress'],[])

    def test_partial_topic_analysis_not_high_confidence(self):
        self.p.data['study']['topics']={}
        with patch.object(llm,'ask',return_value=json.dumps({'t':{self.questions[0]['id']:'Hücre'}})):
            result=study.analyze_recent_exams(self.p,True)
        self.assertEqual(result['coverage']['tagged'],1);self.assertEqual(result['confidence'],'düşük')

    def test_selected_source_followup_stays_in_source_and_clears_old_lesson(self):
        self.p.data['study']['lesson_context']={'topic':'Eski konu'}
        self.p.data['study']['mode']='source'
        with patch.object(llm,'ask',return_value='Kaynak yanıtı') as model,patch.object(study,'_search_items',side_effect=AssertionError('other source')):
            study.ask_source(self.p,'hücre',1,'source')
            self.assertNotIn('lesson_context',self.p.data['study'])
            study.ask(self.p,'Bunu daha sade anlat')
            self.assertIn('SEÇİLİ KAYNAK: 2025.txt',model.call_args.args[0])

    def test_clear_while_source_model_runs_cannot_reactivate_deleted_source(self):
        def answer(*args,**kwargs):study.clear(self.p);return 'Geç cevap'
        with patch.object(llm,'ask',side_effect=answer):
            with self.assertRaises(ValueError):study.ask_source(self.p,'hücre',1)
        self.assertNotIn('active_doc',self.p.data['study'])

    def test_broken_days_configuration_cannot_hang_scheduler(self):
        self.p.data['study']['plan_cfg']={'days':[],'minutes':'broken','time':'99:99'}
        plan=exam.plan(self.p,7);self.assertEqual(len(plan['days']),7)
        self.assertEqual(plan['cfg']['minutes'],60);self.assertEqual(plan['cfg']['time'],'20:00')


if __name__=='__main__':unittest.main()
