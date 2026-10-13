"""Study, files, persistent tasks, release and upload error review regressions."""
import concurrent.futures
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_engine_modular  # Load the suite's hardware adapters before importing the web bridge.
from modules import math_tutor as mt, study, nxapi, tasks, release_workspace, main_documents


class RemainingReviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def test_new_math_source_does_not_send_previous_problem_to_model(self):
        first=self.root/'first.txt';first.write_text('Birinci soru')
        second=self.root/'second.txt';second.write_text('İkinci soru')
        profile=SimpleNamespace(slug='alice',data={},save=Mock())
        reply=json.dumps({'text':'Yöntemi adım adım inceleyelim.'})
        with patch.object(study,'ROOT',self.root/'study'),patch.object(nxapi,'allowed',side_effect=lambda path:Path(path)),patch.object(mt.llm,'ask',return_value=reply) as ask:
            mt.solve(profile,'Anlat',str(first))
            mt.solve(profile,'Anlat',str(second))
            prompt=json.loads(ask.call_args.args[0])
            self.assertEqual(prompt['previous'],[])
            self.assertEqual(prompt['attachment']['text'],'İkinci soru')
            mt.solve(profile,'O adımı tekrar anlat')
            self.assertTrue(json.loads(ask.call_args.args[0])['previous'])

    def test_same_second_photos_do_not_overwrite_each_other(self):
        one=self.root/'one.png';one.write_bytes(b'first')
        two=self.root/'two.png';two.write_bytes(b'second')
        runtime=SimpleNamespace(_PHOTO_DIR=self.root/'photos',profile=SimpleNamespace(slug='alice',data={}),time=SimpleNamespace(strftime=lambda fmt:'same_second',time=time.time),os=os,secrets=secrets)
        first=Path(main_documents._keep_photo(runtime,str(one)))
        second=Path(main_documents._keep_photo(runtime,str(two)))
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),b'first');self.assertEqual(second.read_bytes(),b'second')

    def test_concurrent_uploads_keep_each_payload(self):
        with patch.object(nxapi,'FILES_DIR',self.root/'files'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                paths=list(pool.map(lambda i:nxapi.save_upload('same.txt',str(i).encode()),range(32)))
            self.assertEqual(len(set(paths)),32)
            self.assertEqual({p.read_bytes() for p in paths},{str(i).encode() for i in range(32)})

    def test_task_updates_are_serialized_and_unknown_ids_are_rejected(self):
        data={'tasks':[],'next':1}
        def new_id():
            value=data['next'];time.sleep(.0001);data['next']=value+1
            return value
        profile=SimpleNamespace(data=data,_new_id=new_id,save=Mock())
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda i:tasks.add(profile,str(i),'2026-10-09'),range(40)))
        self.assertEqual(len({r['id'] for r in rows}),40)
        self.assertEqual(tasks.counts(profile),(0,40))
        with self.assertRaises(ValueError):tasks.toggle(profile,999)
        with self.assertRaises(ValueError):tasks.delete(profile,999)
        tasks.toggle(profile,rows[0]['id']);self.assertEqual(tasks.counts(profile),(1,40))
        self.assertEqual(tasks.clear_done(profile),1)

    def test_dependency_aliases_cannot_skip_environment_validation(self):
        for name in ('./requirements.txt','REQUIREMENTS.TXT'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'requirements.lock'):
                release_workspace.changed_environment(self.root,{name:b'new'},self.root)
        (self.root/'requirements.lock.txt').write_text('old==1')
        with self.assertRaisesRegex(ValueError,'sürüm kilidini'):
            release_workspace.changed_environment(self.root,{'./requirements.txt':b'new'},self.root)

    def test_incomplete_phone_upload_is_not_sent_and_temp_file_is_removed(self):
        import web
        from modules import filesend
        handler=object.__new__(web.Handler)
        handler.path='/upload?to=phone&name=report.txt'
        handler.rfile=io.BytesIO(b'partial')
        handler._json=Mock()
        folder=self.root/'upload'
        def temporary(**kwargs):folder.mkdir();return str(folder)
        with patch.object(web.tempfile,'mkdtemp',side_effect=temporary),patch.object(filesend,'send') as send:
            handler._upload(100)
        send.assert_not_called()
        self.assertFalse(folder.exists())
        self.assertFalse(handler._json.call_args.args[0]['ok'])

    def test_memory_proposals_do_not_log_the_private_fact_text(self):
        from modules import learning
        profile=SimpleNamespace(data={},save=Mock())
        with patch.object(learning.log,'info') as log:
            self.assertTrue(learning.propose(profile,['Özel müşteri bilgisi kaydı']))
        self.assertNotIn('Özel müşteri',str(log.call_args))
