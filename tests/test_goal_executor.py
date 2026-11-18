"""Common goals across tool families. No live provider, device or account calls."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from modules import goal_executor as goals, goal_tools, llm, nxapi, task_results, task_agents


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for obj,name,value in [(goals,'STORE',self.root/'goals'),(goals,'_ACTIVE',set()),(nxapi,'FILES_DIR',self.root/'files')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.profile=SimpleNamespace(slug='alice',data={'items':[]})
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        self.session=SimpleNamespace(last_doc=None)
        self.runtime=SimpleNamespace(profile=self.profile,_cur_source='yazı',pc_profile=lambda:self.profile,emit=Mock(),
                                     _session=lambda:self.session)
        transport=patch('modules.public_sources.fetch',side_effect=OSError('Taklit kaynak ağı kapalı'));transport.start();self.addCleanup(transport.stop)
        model=patch.object(llm,'ask');self.ask=model.start();self.addCleanup(model.stop)

    def responses(self,*items):self.ask.side_effect=[json.dumps(x) if isinstance(x,dict) else x for x in items]
    def plan(self,*texts):return {'action':'plan','goals':list(texts)}
    def tool(self,kind,data,goal=0,depends=None):return {'action':'tool','goal':goal,'tool':kind,'input':data,'depends':depends or []}
    def done(self,*ids,goal=0):return {'action':'complete','goal':goal,'evidence':list(ids)}
    def finish(self):return {'action':'finish'}

    def run_with_writer_consent(self, request, **kwargs):
        from writer_consent_fixture import run_with_explicit_writer_approval
        return run_with_explicit_writer_approval(self.runtime, request, **kwargs)

    def test_older_open_legacy_and_canonical_goals_survive_recent_closed_files(self):
        # An old open goal can be hidden by many newer completed journals.
        # Both legacy .json and canonical .execution.json must stay discoverable.
        import os
        import time
        from modules import execution_record, goal_state, goal_state_store
        root = goals._root('alice')
        legacy_id = 'e' * 16
        canonical_id = 'f' * 16
        current = time.time()

        def record(ident, label, state):
            return {'id': ident, 'owner': 'alice', 'request': label,
                    'state': state, 'steps': [], 'outputs': {}, 'goals': [],
                    'created': current - 60, 'updated': current - 10}

        legacy_path = root / (legacy_id + '.json')
        legacy_path.write_text(json.dumps(record(
            legacy_id, 'Eski açık hedef', 'paused',
        )), encoding='utf-8')
        os.utime(legacy_path, (current - 100, current - 100))

        canonical = record(canonical_id, 'Canonical çalışan hedef', 'running')
        canonical_path = execution_record.path_for(root, canonical_id)
        canonical_path.write_bytes(execution_record.encode(canonical))
        os.utime(canonical_path, (current - 90, current - 90))
        goal_state_store.create(root / (canonical_id + '.goalstate.json'),
                                goal_state.new(owner='alice', job_id=canonical_id,
                                               goal=canonical['request'],
                                               authority='canonical'))
        for index in range(20):
            ident = f'{index:016x}'
            path = root / (ident + '.json')
            path.write_text(json.dumps(record(
                ident, 'Yeni bitmiş hedef', 'done',
            )), encoding='utf-8')
            os.utime(path, (current + index, current + index))

        found = goals.open_jobs('alice')
        self.assertEqual({job['id'] for job in found}, {legacy_id, canonical_id})
        with patch('modules.result_presentation.inspect_job',
                   side_effect=AssertionError('Fast status must not hash outputs')):
            answer = goals.fast_status('alice')
        self.assertIn(legacy_id, answer)
        self.assertIn(canonical_id, answer)
        self.assertIn('kanıtı bu listede doğrulanmaz', answer)
        self.assertNotIn('Yeni bitmiş hedef', answer)

    def test_last_closed_goal_fast_status_is_lightweight_not_unverified_success(self):
        root=goals._root('alice')
        ident='b'*16
        (root/(ident+'.json')).write_text(json.dumps({
            'id':ident, 'owner':'alice', 'request':'Kapanmış büyük rapor',
            'state':'done', 'goals':[], 'steps':[{'id':'s1','state':'done'}],
            'outputs':{'s1':{'state':'done','file':'/unknown/big-report.pdf'}},
        }),encoding='utf-8')
        with patch('modules.result_presentation.inspect_job',
                   side_effect=AssertionError('Status may not rehash file')):
            summary=goals.fast_status('alice')
        self.assertIn('Son hedef', summary)
        self.assertIn('kanıt kontrol edilmedi', summary)
        self.assertNotIn('/unknown/big-report.pdf', summary)

    def test_fast_goal_status_does_not_present_unverified_done_as_success(self):
        with patch.object(goals, 'open_jobs', return_value=[{
            'id': 'a'*16, 'owner': 'alice', 'request': 'Büyük rapor',
            'state': 'done', 'steps': [{'id': 's1', 'state': 'done'}],
            'outputs': {'s1': {'state': 'done', 'file': '/unverified/large.bin'}},
        }]), patch('modules.result_presentation.inspect_job',
                  side_effect=AssertionError('No expensive proof read in quick view')):
            message = goals.fast_status('alice')
        self.assertIn('kanıt kontrol edilmedi', message)
        self.assertNotIn('/unverified/large.bin', message)

    def test_research_failure_browser_alternative_writer_file_and_second_goal(self):
        image=self.root/'screen.png';image.write_bytes(b'real saved screenshot fixture')
        browser=task_results.seal('browser',{'state':'done','steps':[{'verified':True}],
            'page':{'url':'https://example.com','text':'actual source'},'image':str(image)})
        original=task_agents.worker
        def work(owner,task,deps):
            if task['agent']=='research':raise RuntimeError('HTTP source unavailable')
            if task['agent']=='browser':return browser
            return original(owner,task,deps)
        bridge=SimpleNamespace(note_add=Mock(return_value={'id':1,'text':'Tamamlandı'}))
        self.responses(self.plan('Kaynaklı rapor dosyası','Not kaydı'),
            self.tool('research',{'url':'https://example.com'}),
            self.tool('browser',{'url':'https://example.com','instruction':'Yalnız oku','mode':'readonly'}),
            self.tool('writer',{'instruction':'Kaynağa göre rapor yaz','filename':'rapor.md'},depends=['s2']),
            'Gerçek kaynaklı rapor metni',self.done('s3'),
            self.tool('action',{'action':'note_add','params':{'text':'Tamamlandı'}},goal=1),
            self.done('s4',goal=1),self.finish())
        with patch.object(task_agents,'worker',side_effect=work),patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=self.run_with_writer_consent('Araştırıp raporu dosyaya kaydet ve not ekle')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertEqual([s['tool'] for s in job['steps']],['research','browser','writer','action'])
        self.assertIn('Gerçek kaynaklı rapor metni',Path(job['outputs']['s3']['file']).read_text())
        self.assertIn('https://example.com',Path(job['outputs']['s3']['file']).read_text())
        self.assertIn('Erişilemeyen kaynaklar',Path(job['outputs']['s3']['file']).read_text())
        bridge.note_add.assert_called_once_with(text='Tamamlandı',title='')
        self.assertIsNone(self.session.last_doc)
        self.assertIsNone(goals.latest('bob'))

    def test_a_chat_research_report_becomes_the_session_output_for_export(self):
        report=task_results.seal('research',{'state':'done','text':'Kaynağa dayalı araştırma raporu.',
            'source':'https://example.com','source_chars':500})
        original=task_agents.worker
        def work(owner,task,deps):
            return report if task['agent']=='research' else original(owner,task,deps)
        self.responses(self.plan('Şirketlerin yapay zekâ kullanımını araştır'),
            self.tool('research',{'url':'https://example.com','question':'yapay zekâ kullanımı'}),
            self.done('s1'),self.finish())
        with patch.object(task_agents,'worker',side_effect=work):
            result=goals.run(self.runtime,'Şirketlerin yapay zekâ kullanımını araştır')
        self.assertEqual(goals.latest('alice')['state'],'done',result)
        self.assertIn('Kaynağa dayalı araştırma raporu',result)
        self.assertEqual(self.session.last_doc,(result,"","arastirma"))
        from modules.brain_context import document_fingerprint
        self.assertEqual(len(document_fingerprint(self.session.last_doc)),64)

    def test_a_research_goal_that_delivered_its_file_keeps_that_path_instead(self):
        report=task_results.seal('research',{'state':'done','text':'Kaynağa dayalı araştırma raporu.',
            'source':'https://example.com','source_chars':500})
        original=task_agents.worker
        def work(owner,task,deps):
            return report if task['agent']=='research' else original(owner,task,deps)
        self.responses(self.plan('Araştır ve raporu dosyaya yaz'),
            self.tool('research',{'url':'https://example.com','question':'yapay zekâ'}),
            self.tool('writer',{'instruction':'Kaynağa göre rapor yaz','filename':'rapor.md'},depends=['s1']),
            'Kaynağa dayalı araştırma raporu metni',
            self.done('s1','s2'),self.finish())
        with patch.object(task_agents,'worker',side_effect=work):
            result=self.run_with_writer_consent('Araştır ve raporu dosyaya yaz')
        job=goals.latest('alice')
        self.assertEqual(job['state'],'done',result)
        self.assertTrue(job['outputs']['s2'].get('file'))
        self.assertIsNone(self.session.last_doc)

    def test_a_non_research_goal_does_not_claim_a_saved_report(self):
        bridge=SimpleNamespace(note_add=Mock(return_value={'id':1,'text':'Tamamlandı'}))
        self.responses(self.plan('Not ekle'),
            self.tool('action',{'action':'note_add','params':{'text':'Tamamlandı'}}),
            self.done('s1'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=goals.run(self.runtime,'Not ekle')
        self.assertEqual(goals.latest('alice')['state'],'done',result)
        self.assertIsNone(self.session.last_doc)

    def test_all_goals_and_actual_successful_evidence_are_required(self):
        self.responses(self.plan('İş bir','İş iki'),self.finish(),self.done('invented'),RuntimeError('models unavailable'))
        result=self.run_with_writer_consent('İki işi de yap')
        job=goals.latest('alice');self.assertEqual(job['state'],'paused')
        self.assertTrue(all(g['state']=='pending' for g in job['goals']))
        self.assertIn('tamamlanmadı',result)

    def test_action_confirmation_is_persisted_and_only_exact_pending_action_runs(self):
        bridge=SimpleNamespace(note_delete=Mock(return_value=True))
        self.profile.data['items']=[{'id':7,'text':'selected note'}]
        self.responses(self.plan('Seçilen notu sil'),self.tool('action',{'action':'note_delete','params':{'nid':7}}))
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=self.run_with_writer_consent('7 kimlikli notu sil')
        self.assertEqual(goals.latest('alice')['state'],'approval');bridge.note_delete.assert_not_called()
        self.assertIn('onay',result.casefold())
        goals.handle(self.runtime,'sürdür')
        self.assertEqual(goals.latest('alice')['state'],'approval');bridge.note_delete.assert_not_called()
        self.responses(self.done('s1'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            goals.handle(self.runtime,'hedef onayla')
        bridge.note_delete.assert_called_once_with(nid=7)
        self.assertEqual(goals.latest('alice')['state'],'done')

    def test_unsafe_exception_does_not_trigger_alternative_duplicate_action(self):
        bridge=SimpleNamespace(note_add=Mock(side_effect=RuntimeError('connection lost after write')))
        self.responses(self.plan('Not ekle'),self.tool('action',{'action':'note_add','params':{'text':'note'}}))
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            self.run_with_writer_consent('Not ekle')
            goals.handle(self.runtime,'devam')
        self.assertEqual(goals.latest('alice')['state'],'review')
        bridge.note_add.assert_called_once()

    def test_done_tool_is_never_executed_twice_and_model_can_complete_other_goal(self):
        self.responses(self.plan('Durumu oku'),self.tool('diagnose',{'kind':'accounts'}),
            self.tool('diagnose',{'kind':'accounts'}),self.done('s1'),self.finish())
        with patch('modules.service_health.report',return_value='Yerel hesap durumu') as check:
            self.run_with_writer_consent('Hesap durumunu oku')
        check.assert_called_once_with('alice');self.assertEqual(goals.latest('alice')['state'],'done')

    def test_real_document_read_and_translation_share_goal_with_verified_source(self):
        path=self.root/'document.txt';path.write_text('Merhaba dünya',encoding='utf-8')
        self.runtime.tr=SimpleNamespace(translate=Mock(return_value='Hello world'))
        self.responses(self.plan('Belgeyi oku','İngilizceye çevir'),
            self.tool('document',{'operation':'read','path':str(path)}),self.done('s1'),
            self.tool('document',{'operation':'translate','path':str(path),'target':'English'},goal=1),self.done('s2',goal=1),self.finish())
        with patch.object(nxapi,'allowed',return_value=path):result=self.run_with_writer_consent('Dosyayı oku ve İngilizceye çevir')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertIn('Hello world',result)
        path.write_text('changed')
        with self.assertRaises(ValueError):goal_tools.verify(job['outputs']['s1'],'alice')

    def test_desktop_active_owner_gate_and_camera_not_opened_implicitly(self):
        identity={'owner':'alice','job_id':'1','task_id':'s1'}
        self.runtime._cur_source='telefon'
        with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'desktop',{'target':'Calculator','goal':'12+7'}, {},identity)
        self.runtime._cur_source='yazı';self.runtime.vision=SimpleNamespace(mode=lambda:None)
        with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'observe',{'kind':'camera','question':'incele'}, {},identity)

    def test_failed_read_can_be_resumed_after_restart_without_losing_completed_goals(self):
        self.responses(self.plan('Durumu oku','Rapor dosyası'),self.tool('diagnose',{'kind':'accounts'}),self.done('s1'),RuntimeError('offline'))
        with patch('modules.service_health.report',return_value='Account check'):
            self.run_with_writer_consent('Hesabı kontrol et ve rapor oluştur')
        ident=goals.latest('alice')['id']
        self.responses(self.tool('writer',{'instruction':'Durum raporu','filename':'rapor.md'},goal=1,depends=['s1']),
            'Hesap durum raporu',self.done('s2',goal=1),self.finish())
        goals.handle(self.runtime,'devam et')
        pending=goals.latest('alice')
        self.assertEqual(pending['state'],'approval')
        self.run_with_writer_consent('hedef onayla',resume=True,approve=True,
                                     expected_job_id=pending['id'],
                                     expected_control=goals.control_key(pending))
        job=goals.latest('alice');self.assertEqual(job['state'],'done');self.assertEqual(job['id'],ident)
        self.assertEqual(len(job['steps']),2)

    def test_owner_change_and_cancel_never_start_next_tool(self):
        def model(*args,**kwargs):
            self.runtime.profile=SimpleNamespace(slug='bob',data={})
            return json.dumps(self.plan('İş'))
        self.ask.side_effect=model
        from modules import requests_state
        with self.assertRaises(requests_state.Cancelled):self.run_with_writer_consent('İşi yap')
        self.assertEqual(goals.latest('alice')['state'],'cancelled');self.assertIsNone(goals.latest('bob'))

    def test_paid_selection_and_unknown_shell_are_not_available_to_model(self):
        for kind,data in [('shell',{'command':'whatever'}),('action',{'action':'llm_set','params':{'provider':'openai'}})]:
            with self.assertRaises(ValueError):goal_tools.validate(kind,data)

    def test_goal_context_is_bounded_and_complete_output_remains_local(self):
        job={'request':'goal','goals':[],'steps':[],'outputs':{}}
        for i in range(24):
            ident='s'+str(i);job['outputs'][ident]={'state':'done','text':'x'*100000,'file':'report.md'}
        self.assertLess(len(json.dumps(goals._context(job))),16000)
        self.assertEqual(len(job['outputs']['s0']['text']),100000)

    def test_lost_write_response_is_reconciled_from_real_profile_without_repeating(self):
        def add(**params):
            self.profile.data['items'].append({'id':8,'text':params['text']})
            raise RuntimeError('Response lost after durable write')
        bridge=SimpleNamespace(note_add=Mock(side_effect=add))
        self.responses(self.plan('Not ekle'),self.tool('action',{'action':'note_add','params':{'text':'New note'}}),self.done('s1'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=self.run_with_writer_consent('New note diye not ekle')
        self.assertEqual(goals.latest('alice')['state'],'done',result)
        self.assertTrue(goals.latest('alice')['outputs']['s1']['reconciled'])
        bridge.note_add.assert_called_once()

    def test_active_state_can_be_read_again_after_a_mutation(self):
        bridge=SimpleNamespace(note_add=Mock(return_value=True))
        self.responses(self.plan('Notu ekle ve doğrula'),
            self.tool('action',{'action':'notes_list','params':{}}),
            self.tool('action',{'action':'note_add','params':{'text':'New note'}}),
            self.tool('action',{'action':'notes_list','params':{}}),self.done('s3'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            self.run_with_writer_consent('Notu ekle ve doğrula')
        self.assertEqual(len(goals.latest('alice')['steps']),3)

    def test_plain_action_classification_reaches_goal_instead_of_catalog_rejection(self):
        import test_brain_production_entry as fixtures
        # Kaldırılan legacy sınıflandırıcı model "chat"/"unknown" dese de eylem cümlesini goal
        # yürütücüsüne devrediyordu. Canonical kapı aynı devri model hiç çağrılmadan yapar.
        self.ask.side_effect=AssertionError('Canonical kapı model çağrısı yapmaz')
        semantic,route=fixtures.door('Araştırıp rapor hazırla')
        self.assertEqual(route,{'intent':'task','args':{'request':'Araştırıp rapor hazırla'}})

    def test_native_task_intent_uses_common_executor_without_magic_command_prefix(self):
        from modules import engine_intents
        with patch.object(goals,'run',return_value='done') as run:
            self.assertEqual(engine_intents.dispatch(self.runtime,'task',{'request':'Araştır ve belge üret'},'original','original'),'done')
        run.assert_called_once_with(self.runtime,'original')

    def test_account_read_and_draft_use_actual_worker_contract_and_never_send(self):
        from modules import google_api,account_tools,publish_services
        service=Mock();messages=service.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value={'messages':[{'id':'m1'}]}
        messages.get.return_value.execute.return_value={'id':'m1','payload':{'headers':[{'name':'from','value':'Sender <sender@example.com>'},{'name':'Subject','value':'Test'}]}}
        self.responses(self.plan('Mail başlıklarını oku','Yerel taslak hazırla'),
            self.tool('account',{'service':'gmail','operation':'list_unread','limit':5}),self.done('s1'),
            self.tool('writer',{'instruction':'Yerel cevap taslağı yaz','filename':'mail-cevap.md'},goal=1,depends=['s1']),
            'Merhaba, mesajınız alınmıştır.',self.done('s2',goal=1),self.finish())
        with patch.object(google_api,'_service',return_value=service),patch.object(account_tools.privacy,'blocked',return_value=None),patch.object(publish_services,'send') as send:
            result=self.run_with_writer_consent('Mail başlıklarını oku ve yerel taslak yaz; gönderim yok')
        self.assertEqual(goals.latest('alice')['state'],'done',result);send.assert_not_called()
        self.assertIn('Test',result);self.assertTrue(Path(goals.latest('alice')['outputs']['s2']['file']).exists())

    def test_outbound_requires_user_goal_and_matching_target_even_with_existing_grant(self):
        from modules import publish_services
        identity={'owner':'alice','job_id':'job','task_id':'s1','request':'Araştırıp rapor hazırla'}
        data={'service':'gmail','destination':'someone@example.com','subject':'Subject','text':'text'}
        with patch.object(publish_services,'send') as send:
            with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'publish',data,{},identity)
            identity['request']='friend@example.com adresine gönder'
            with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'publish',data,{},identity)
            identity['request']='someone@example.com adresine gönderme, yalnız taslak'
            with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'publish',data,{},identity)
        send.assert_not_called()

    def test_schedule_persists_exact_safe_plan_and_blocks_background_sends(self):
        from modules import service_store,task_queue
        tasks=[{'id':'list','agent':'account','input':{'service':'gmail','operation':'list_unread','limit':5}}]
        data={'tasks':tasks,'request':'Mail başlıklarını oku','seconds':120}
        identity={'owner':'alice','job_id':'job','task_id':'s1'}
        with patch.object(service_store,'ROOT',self.root/'services'):
            output=goal_tools.execute(self.runtime,'schedule',data,{},identity)
            row=task_queue.rows('alice')[0]
            self.assertEqual(output['queue_id'],row['id']);self.assertEqual(row['state'],'queued')
            data['tasks']=[{'id':'send','agent':'publish','input':{'service':'gmail','destination':'friend@example.com','subject':'S','text':'T'}}]
            with self.assertRaises(ValueError):goal_tools.execute(self.runtime,'schedule',data,{},identity)

    def test_sharing_checks_actual_state_and_cannot_be_opened_by_source_instructions(self):
        mode={'value':None}
        self.runtime.vision=SimpleNamespace(mode=lambda:mode['value'])
        self.runtime.set_share=Mock(side_effect=lambda value:mode.update(value=value) or 'changed')
        identity={'owner':'alice','job_id':'job','task_id':'s1','request':'Kamerayı aç ve incele'}
        out=goal_tools.execute(self.runtime,'sharing',{'mode':'camera'},{},identity)
        self.assertTrue(goal_tools.verify(out,'alice'))
        identity['request']='Rapor oluştur'
        with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'sharing',{'mode':'screen'},{},identity)
        identity['request']='Kamerayı kapat'
        with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'sharing',{'mode':'camera'},{},identity)
        self.runtime.set_share=Mock(return_value='claimed stopped')
        with self.assertRaises(ValueError):goal_tools.execute(self.runtime,'sharing',{'mode':'off'},{},identity)

    def test_system_volume_requires_actual_readback_and_pc_owner(self):
        import sys
        with patch.dict(sys.modules,{'pyautogui':SimpleNamespace()}):
            from modules import system_control
        identity={'owner':'alice','job_id':'job','task_id':'s1'}
        with patch.object(system_control,'set_volume',return_value=True),patch.object(system_control,'current_volume',return_value=40):
            out=goal_tools.execute(self.runtime,'system',{'operation':'volume','level':40},{},identity)
            self.assertTrue(goal_tools.verify(out,'alice'))
        with patch.object(system_control,'set_volume',return_value=True),patch.object(system_control,'current_volume',return_value=20):
            with self.assertRaises(ValueError):goal_tools.execute(self.runtime,'system',{'operation':'volume','level':40},{},identity)
        self.runtime.pc_profile=lambda:SimpleNamespace(slug='bob')
        with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'system',{'operation':'mute','on':True},{},identity)

    def test_real_media_file_is_created_and_verified_through_common_loop(self):
        import shutil
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('FFmpeg unavailable')
        self.responses(self.plan('Kısa video dosyası üret'),
            self.tool('media',{'scenes':[{'caption':'Ortak yürütücü kabul testi','duration':1}],'layout':'landscape'}),self.done('s1'),self.finish())
        result=self.run_with_writer_consent('Bir saniyelik yazılı video dosyası oluştur, yayınlama')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        output=job['outputs']['s1'];self.assertTrue(Path(output['file']).is_file())
        self.assertTrue(task_results.verify(output,owner='alice'))
        self.assertAlmostEqual(output['media']['duration'],1,delta=.2)

    def test_desktop_completion_and_natural_consent_use_saved_native_id(self):
        # Aşama C: sürdürme yalnız Scheduler'ın bağladığı native kimlikle olur;
        # eski approval={'desktop_id':…} tüketici yolu kaldırıldı.
        from modules import desktop_agent
        native={'id':'native1','owner':'alice','status':'consent','history':[],'pending_app':'notepad','target':'Notepad','goal':'Metni yaz'}
        identity={'owner':'alice','job_id':'goal','task_id':'s1','_canonical_desktop_resume':'native1'}
        data={'target':'Notepad','goal':'Metni yaz'}
        def consent(*args,**kwargs):
            self.assertEqual(args[1],'PC izin ver')
            native.update(status='done',history=[{'verified':True}]);return 'Text entered'
        with patch.object(desktop_agent,'_load',return_value=native),patch.object(desktop_agent,'handle',side_effect=consent):
            out=goal_tools.execute(self.runtime,'desktop',data,{},identity)
        self.assertEqual(out['state'],'done');self.assertEqual(out['desktop_id'],'native1')

    def test_validation_and_permission_errors_never_launch_shell_or_change_provider(self):
        for kind,data in [('system',{'operation':'volume','level':True}),('sharing',{'mode':'arbitrary'}),
            ('schedule',{'tasks':[],'request':'x','seconds':120}),('action',{'action':'unknown','params':{}})]:
            with self.assertRaises(ValueError):goal_tools.validate(kind,data)

    def test_adapter_settings_never_put_unknown_secret_values_in_goal_or_model_context(self):
        bridge=SimpleNamespace(settings=Mock(return_value={'saved':{'api_key':'custom-secret-value','nested':{'token':'unusual-secret'}}}))
        identity={'owner':'alice','job_id':'job','task_id':'s1'}
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            output=goal_tools.execute(self.runtime,'action',{'action':'settings','params':{}},{},identity)
        self.assertNotIn('custom-secret-value',json.dumps(output));self.assertNotIn('unusual-secret',json.dumps(output))
        self.assertIn('true',output['text'])


    def test_legacy_safe_dag_preserves_journal_but_cannot_write_without_core_consent(self):
        with patch.object(task_agents,'STORE',self.root/'legacy'):
            self.responses({'tasks':[{'id':'report','agent':'writer','input':{'instruction':'Yaz','filename':'test.md'}}]},RuntimeError('model offline'))
            result=goals.run(self.runtime,'Test raporu hazırla')
            legacy=task_agents.recent('alice');job=goals.latest('alice')
            self.assertEqual(job['legacy_job'],legacy['id'])
            self.assertEqual(legacy['state'],'approval')
            self.assertEqual(legacy['outputs']['report']['state'],'approval')
            self.assertNotEqual(job['state'],'done')
            self.assertIn('onay',result)
            # Legacy queues cannot mint Core's single-use writer approval.
            # Never represent this parked legacy task as a completed file.
            self.assertFalse(list(self.root.rglob('test.md')))
        with self.assertRaises(ValueError):
            goals._parse(json.dumps({'tasks':[{'id':'browse','agent':'browser','input':{'url':'https://example.com','instruction':'Click'}}]}))

    def test_conversion_creates_actual_document_without_save_dialog(self):
        from docx import Document
        source=self.root/'source.txt';source.write_text('Merhaba dünya',encoding='utf-8')
        with patch.object(nxapi,'allowed',return_value=source):
            result=goal_tools.execute(self.runtime,'document',{'operation':'convert','path':str(source),'format':'docx'}, {},{'owner':'alice'})
        target=Path(result['file'])
        self.assertEqual(target.suffix,'.docx');self.assertTrue(goal_tools.verify(result,'alice'))
        self.assertIn('Merhaba dünya','\n'.join(p.text for p in Document(target).paragraphs))
        target.write_text('changed')
        with self.assertRaises(ValueError):goal_tools.verify(result,'alice')

    def test_secret_fields_in_user_request_are_removed_before_planner_call(self):
        self.responses(RuntimeError('offline'))
        self.run_with_writer_consent('Hesabı kontrol et api_key=unusual-value parola:another-value')
        prompt=self.ask.call_args.args[0]
        self.assertNotIn('unusual-value',prompt);self.assertNotIn('another-value',prompt)

    def test_interrupted_step_before_execution_can_resume_without_false_uncertainty(self):
        self.responses(self.plan('Not ekle'),self.tool('action',{'action':'note_add','params':{'text':'not'}}))
        # Model a process crash, NOT user cancellation. Explicit Cancelled
        # closes canonical GoalState permanently; power loss before any
        # effect must leave the journal resumable without a duplicate effect.
        with patch.object(goal_tools,'checkpoint',side_effect=KeyboardInterrupt('crash before effect')):
            with self.assertRaises(KeyboardInterrupt):self.run_with_writer_consent('Not ekle')
        job=goals.latest('alice');job['state']='paused';job['steps'][0]['state']='running';goals._save(job)
        bridge=SimpleNamespace(note_add=Mock(return_value={'id':1,'text':'not'}))
        self.responses(self.tool('action',{'action':'note_add','params':{'text':'not'}}),self.done('s2'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            goals.handle(self.runtime,'devam')
        bridge.note_add.assert_called_once();self.assertEqual(goals.latest('alice')['state'],'done')

    def test_explicit_cancellation_before_execution_is_terminal_on_resume(self):
        from modules import requests_state, goal_state_store
        self.responses(self.plan('Not ekle'),self.tool('action',{'action':'note_add','params':{'text':'not'}}))
        with patch.object(goal_tools,'checkpoint',side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):
                self.run_with_writer_consent('Not ekle')
        job=goals.latest('alice')
        self.assertEqual(job['state'],'cancelled')
        path=goals.STORE/'alice'/(job['id']+'.goalstate.json')
        self.assertEqual(goal_state_store.load(path)['state'],'cancelled')
        bridge=SimpleNamespace(note_add=Mock())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            goals.handle(self.runtime,'devam')
        bridge.note_add.assert_not_called()
        self.assertEqual(goal_state_store.load(path)['state'],'cancelled')



    def test_old_completed_desktop_job_cannot_prove_new_rejected_request(self):
        from modules import desktop_agent
        old={'id':'old','owner':'alice','target':'Calculator','goal':'12+7','status':'done','history':[{'verified':True}]}
        identity={'owner':'alice','_canonical_scheduler_offer':{'owner':'alice','job_id':'goal','node_id':'s1'}}
        with patch.object(desktop_agent,'_load',return_value=old),patch.object(desktop_agent,'handle',return_value='Başka görev çalışıyor'):
            result=goal_tools.execute(self.runtime,'desktop',{'target':'Calculator','goal':'12+7'}, {},identity)
        self.assertEqual(result['state'],'blocked');self.assertTrue(result['retry_safe'])

    def test_followup_answers_and_tool_inputs_are_redacted_before_planning(self):
        job={'request':'request','goals':[],'steps':[{'id':'s1','goal':0,'tool':'coder','state':'failed','depends':[],
             'input':{'request':'parola: unusual-input'}}], 'outputs':{},'answers':['parola: unusual-answer'],'feedback':[]}
        context=json.dumps(goals._context(job))
        self.assertNotIn('unusual-input',context);self.assertNotIn('unusual-answer',context)



    def test_observe_privacy_gate_runs_before_capture_or_model_and_strict_errors_propagate(self):
        self.runtime.desktop=SimpleNamespace(screenshot=Mock())
        self.runtime.ask_image=Mock(return_value='Ekran açıklaması')
        identity={'owner':'alice'}
        with patch.object(goal_tools.privacy,'blocked',return_value='Gizli modda kapalı'):
            with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'observe',{'kind':'screen','question':'incele'}, {},identity)
        self.runtime.desktop.screenshot.assert_not_called();self.runtime.ask_image.assert_not_called()
        with patch.object(llm.privacy,'mode',return_value='gizli'):
            with self.assertRaises(PermissionError):llm.ask_image('unused.png','q',strict=True)
        self.runtime.desktop.screenshot.side_effect=lambda path:Path(path).write_bytes(b'captured-frame')
        self.runtime.ask_image.side_effect=RuntimeError('No image model')
        with patch.object(goal_tools.privacy,'blocked',return_value=None):
            with self.assertRaises(RuntimeError):goal_tools.execute(self.runtime,'observe',{'kind':'screen','question':'incele'}, {},identity)
        self.assertTrue(self.runtime.ask_image.call_args.kwargs['strict'])
        self.assertFalse(Path(self.runtime.ask_image.call_args.args[0]).exists())



    def test_native_desktop_question_has_no_legacy_answer_channel(self):
        # Aşama C: motorun soru turunu model answer/resume_id alanlarıyla
        # sürdürmek kaldırıldı; Scheduler turu salt blokeli döner (Aşama D:
        # kanonik cevap kanalı).
        from modules import desktop_agent
        native={'id':'native','owner':'alice','target':'Notepad','goal':'Metni yaz','status':'question','history':[{'verified':True}]}
        identity={'owner':'alice','_canonical_desktop_resume':'native'}
        with patch.object(desktop_agent,'_load',return_value=native),patch.object(desktop_agent,'run') as run, \
             patch.object(desktop_agent,'handle') as create,patch.object(desktop_agent,'render',return_value='Soru: hangi dosya?'):
            output=goal_tools.execute(self.runtime,'desktop',{'target':'Notepad','goal':'Metni yaz'},{},identity)
        self.assertEqual(output['state'],'blocked');self.assertFalse(output['retry_safe'])
        self.assertEqual(output['desktop_id'],'native')
        run.assert_not_called();create.assert_not_called()
        for smuggled in ({'answer':'Merhaba'},{'resume_id':'native'}):
            with self.subTest(**smuggled),self.assertRaises(ValueError):
                goal_tools.validate('desktop',{'target':'Notepad','goal':'Metni yaz',**smuggled})



    def test_execution_request_goes_to_execution_not_chat_snippet(self):
        """The legacy 'code' case is gone; the canonical 'task' projection still never degrades an
        execution request into a chat snippet."""
        from modules import engine_intents
        with patch.object(goals,'run',return_value='Çalıştırıldı') as execute:
            result=engine_intents.dispatch(self.runtime,'task',{'request':'model rewrite'},'Toplama dosyasını oluştur ve test et','toplama dosyasını oluştur ve test et')
        self.assertEqual(result,'Çalıştırıldı');execute.assert_called_once_with(self.runtime,'Toplama dosyasını oluştur ve test et')

    def test_rejected_before_effect_can_find_alternative_without_review_stop(self):
        self.responses(self.plan('Durumu raporla'),self.tool('sharing',{'mode':'camera'}),
            self.tool('diagnose',{'kind':'accounts'}),self.done('s2'),self.finish())
        with patch('modules.service_health.report',return_value='Yerel hesap bilgisi'):
            result=self.run_with_writer_consent('Hesap durumunu raporla')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertFalse(job['steps'][0]['started'])



    def test_physical_action_aliases_cannot_bypass_active_pc_owner(self):
        self.runtime._cur_source='telefon'
        for action,params in [('file_open',{'path':'report.txt'}),('open_folder',{}),('win',{'action':'full'}),('set_flag',{'name':'mic','value':True})]:
            with self.subTest(action=action),patch.object(goal_tools.app_actions,'_owned') as bridge:
                with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'action',{'action':action,'params':params},{},{'owner':'alice'})
                bridge.assert_not_called()



    def test_locked_coder_does_not_block_real_report_and_video_delivery(self):
        import shutil
        from modules import developer
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('FFmpeg unavailable')
        self.responses(self.plan('İstanbul raporu','İstanbul videosu'),
            self.tool('coder',{'request':'Rapor ve video oluştur'}),
            self.tool('writer',{'instruction':'İstanbul hakkında kısa rapor','filename':'istanbul.md'}),
            'İstanbul iki kıtaya yayılan bir şehirdir.',self.done('s2'),
            self.tool('media',{'scenes':[{'caption':'İstanbul','duration':3}],'layout':'landscape'},goal=1),self.done('s3',goal=1),self.finish())
        with patch.object(developer,'status',return_value={'enabled':False,'unlocked':False}),patch.object(developer,'handle') as code:
            result=self.run_with_writer_consent('İstanbul raporu dosyası ve İstanbul yazan 3 saniyelik video oluştur. Yayınlama.')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result);code.assert_not_called()
        self.assertFalse(job['steps'][0]['started'])
        self.assertTrue(Path(job['outputs']['s2']['file']).is_file())
        self.assertAlmostEqual(job['outputs']['s3']['media']['duration'],3,delta=.2)

    def test_legacy_locked_coder_review_can_resume_without_repeating_code(self):
        self.responses(self.plan('Rapor dosyası'),RuntimeError('offline'))
        self.run_with_writer_consent('Rapor dosyası oluştur')
        job=goals.latest('alice')
        job['state']='review';job['steps']=[{'id':'s1','goal':0,'tool':'coder','input':{'request':'Rapor üret'},'state':'failed','started':True,'depends':[],'signature':'old'}]
        job['outputs']={'s1':{'state':'failed','text':'Önce sohbetten parolalı geliştirme modunu aç.'}}
        goals._save(job)
        self.responses(self.tool('writer',{'instruction':'Rapor üret','filename':'rapor.md'}),'Rapor metni',self.done('s2'),self.finish())
        result=goals.handle(self.runtime,'devam et')
        pending=goals.latest('alice')
        self.assertEqual(pending['state'],'approval',result)
        result=self.run_with_writer_consent('hedef onayla',resume=True,approve=True,
                                            expected_job_id=pending['id'],
                                            expected_control=goals.control_key(pending))
        self.assertEqual(goals.latest('alice')['state'],'done',result)
        self.assertEqual(len(goals.latest('alice')['steps']),2)

    def test_planner_timeout_preserves_job_and_late_tool_is_never_executed(self):
        import threading
        release=threading.Event();exited=threading.Event()
        def slow(*args,**kwargs):
            try:
                release.wait(2)
                return json.dumps(self.tool('action',{'action':'note_add','params':{'text':'late'}}))
            finally:exited.set()
        self.ask.side_effect=slow
        with patch.object(goals,'PLANNER_SECONDS',.03),patch.object(goal_tools,'execute') as execute:
            result=self.run_with_writer_consent('Bir not oluştur')
            job=goals.latest('alice');ident=job['id']
            self.assertEqual(job['state'],'paused');self.assertIn('Geç yanıt',result)
            self.assertEqual(job['steps'],[])
            release.set();self.assertTrue(exited.wait(1))
            execute.assert_not_called()
            self.assertEqual(goals.latest('alice')['id'],ident)
            self.assertEqual(goals.latest('alice')['steps'],[])

    def test_context_has_today_in_istanbul_and_source_wait_is_visible(self):
        from datetime import datetime, timezone, timedelta
        job={'id':'a'*16,'owner':'alice','request':'son gelişmeler','state':'running','goals':[],
             'steps':[{'id':'s1','goal':0,'tool':'research','state':'running','depends':[],
                       'input':{'url':'https://example.org/source'}}],'outputs':{}}
        context=goals._context(job)
        self.assertEqual(context['current_date'],datetime.now(timezone(timedelta(hours=3))).date().isoformat())
        self.assertIn('Denenen kaynak: https://example.org/source',goals.render(job))

    def test_explicit_no_information_research_is_not_sealed_as_success(self):
        self.ask.return_value='Verilen kaynakta herhangi bir bilgi yer almamaktadır. Kaynakta desteklenen bir yanıt verilememektedir.'
        with patch('modules.browser.page_text',return_value='Bu sayfa yalnız arama menüsü ve genel gezinme metninden oluşur. '*8):
            with self.assertRaisesRegex(ValueError,'başarı sayılmadı'):
                task_agents.worker('alice',{'agent':'research','input':{'url':'https://example.org/'}},{})

    def test_empty_source_then_dns_failure_then_new_source_delivers_same_goal_report(self):
        import requests
        def page(url):
            if 'unreachable.example' in url:raise requests.ConnectionError('NameResolutionError: getaddrinfo failed')
            return 'Gerçek kaynak metni. Türkiye yapay zekâ araştırması 15 Ekim tarihinde duyuruldu. '*3
        self.responses(self.plan('Kaynaklı güncel rapor dosyası'),
            self.tool('research',{'url':'https://empty.example/'}),
            'Verilen kaynakta herhangi bir bilgi yer almamaktadır.',
            self.tool('research',{'url':'https://unreachable.example/'}),
            self.tool('research',{'url':'https://working.example/news'}),
            json.dumps({'supported':True,'answer':'15 Ekim tarihli araştırma duyuruldu.','quotes':['Türkiye yapay zekâ araştırması 15 Ekim tarihinde duyuruldu.']}),
            self.tool('writer',{'instruction':'Kaynakla sınırlı rapor','filename':'rapor.md'},depends=['s3']),
            '# Araştırma\n15 Ekim tarihli duyuru. Kaynak: https://working.example/news',
            self.done('s4'),self.finish())
        with patch('modules.browser.page_text',side_effect=page):
            result=self.run_with_writer_consent('Türkiye yapay zekâ araştırmasını incele ve kaynaklı rapor dosyası oluştur')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertEqual([step['state'] for step in job['steps']],['failed','failed','done','done'])
        self.assertEqual(len(job['goals']),1)
        path=Path(job['outputs']['s4']['file']);report=path.read_text()
        for url in ('https://empty.example/','https://unreachable.example/','https://working.example/news'):
            self.assertIn(url,report)
        self.assertTrue(goal_tools.verify(job['outputs']['s4'],'alice'))

    def test_resuming_old_no_information_receipt_keeps_id_and_invalidates_its_evidence(self):
        output=task_results.seal('research',{'state':'done','text':'Kaynakta desteklenen bir yanıt verilememektedir.','source':'https://example.org/','source_chars':100})
        job={'id':'b'*16,'owner':'alice','request':'Kaynaklı rapor','created':0,'state':'paused',
             'goals':[{'text':'Rapor','state':'done','evidence':['s1']}],
             'steps':[{'id':'s1','goal':0,'tool':'research','input':{'url':'https://example.org/'},'depends':[],'signature':'old','state':'done'}],
             'outputs':{'s1':output}}
        goals._save(job);self.ask.side_effect=RuntimeError('model unavailable')
        self.run_with_writer_consent('hedef devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['id'],job['id']);self.assertEqual(len(after['steps']),1)
        self.assertEqual(after['steps'][0]['state'],'failed')
        self.assertEqual(after['goals'][0]['evidence'],[])
        self.assertIn('https://example.org/',after['unavailable_sources'])

    def test_invalid_research_invalidates_transitive_reports_without_deleting_files(self):
        report=self.root/'saved-report.md';report.write_text('Önceki rapor')
        job={'state':'running','goals':[{'state':'done','evidence':['s3']}],
             'steps':[{'id':'s1','tool':'research','input':{'url':'https://example.org'},'depends':[],'state':'done'},
                      {'id':'s2','tool':'writer','input':{'instruction':'Rapor'},'depends':['s1'],'state':'done'},
                      {'id':'s3','tool':'writer','input':{'instruction':'Özet'},'depends':['s2'],'state':'done'}],
             'outputs':{'s1':{'state':'done'},'s2':{'state':'done','file':str(report)},'s3':{'state':'done'}}}
        goals._invalidate_outputs(job,'s1','Kaynak geçersiz')
        self.assertTrue(all(s['state']=='failed' for s in job['steps']))
        self.assertEqual(job['goals'][0],{'state':'pending','evidence':[]})
        self.assertEqual(report.read_text(),'Önceki rapor')

    def test_failed_goal_removes_prior_green_classification_and_keeps_failure_trace(self):
        llm.take_route();self.addCleanup(llm.take_route)
        llm.note_route('Cevap: Gemini · classification',True)
        llm.note_route('Groq beklemede',False)
        self.ask.side_effect=RuntimeError('No eligible model')
        self.run_with_writer_consent('Kaynaklı rapor oluştur')
        notes=llm.take_route()
        self.assertFalse(any(ok for _,ok in notes))
        self.assertIn(('Groq beklemede',False),notes)
        self.assertEqual(goals.latest('alice')['state'],'paused')

    def test_planner_catalog_compacts_repetition_without_removing_action_arguments_or_permissions(self):
        full=goal_tools.catalog();compact=goal_tools.planner_catalog()
        restored=[dict(zip(compact['action_columns'],row)) for row in compact['actions']]
        self.assertEqual(restored,full['actions'])
        for key in full:
            if key!='actions':self.assertEqual(compact[key],full[key])
        self.assertLess(len(json.dumps(compact,ensure_ascii=False,separators=(',',':'))),len(json.dumps(full,ensure_ascii=False))*.8)

    def test_planner_asks_for_a_short_tool_reply_instead_of_a_full_report(self):
        self.responses(self.plan('Rapor'),RuntimeError('stop'))
        self.run_with_writer_consent('Rapor hazırla')
        self.assertTrue(self.ask.call_args_list)
        for call in self.ask.call_args_list:self.assertEqual(call.kwargs['max_tokens'],1200)



    def test_repeated_replanning_stops_without_overwriting_saved_goals_or_running_tools(self):
        self.responses(self.plan('Özgün hedef'),self.plan('Yanlış yeni hedef'),
                       self.plan('Yanlış yeni hedef'),self.plan('Yanlış yeni hedef'))
        with patch.object(goals,'_record',side_effect=AssertionError('no tool should run')):
            text=self.run_with_writer_consent('Kaynaklı rapor hazırla')
        job=goals.latest('alice')
        self.assertEqual(self.ask.call_count,4)
        self.assertEqual(job['goals'][0]['text'],'Özgün hedef')
        self.assertEqual(job['steps'],[])
        self.assertEqual(job['state'],'paused')
        self.assertIn('tekrar planlamaya',job['blocker'])
        self.assertIn('3 kez',text)
        self.assertIn('kayıtlı plan VAR',self.ask.call_args_list[1].kwargs['system'])

    def test_replanning_rejection_can_recover_to_a_valid_next_action(self):
        self.responses(self.plan('Özgün hedef'),self.plan('Yanlış yeni hedef'),
                       {'action':'ask','question':'Hangi tarih aralığı?'})
        self.run_with_writer_consent('Kaynaklı rapor hazırla')
        job=goals.latest('alice')
        self.assertEqual(job['goals'][0]['text'],'Özgün hedef')
        self.assertEqual(job['state'],'question')
        self.assertEqual(self.ask.call_count,3)



    def test_last_explicit_completion_finishes_without_another_model_call(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),
                       'Doğrulanmış dosya',self.done('s1'),RuntimeError('HTTP 429'))
        result=self.run_with_writer_consent('Rapor dosyası oluştur')
        job=goals.latest('alice')
        self.assertEqual(job['state'],'done',result)
        self.assertEqual(self.ask.call_count,4)

    def test_dated_news_discovery_report_verify_and_two_completions_do_not_need_final_model(self):
        from datetime import datetime,timezone,timedelta
        from modules import public_sources,service_store
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index='https://example.org/haberler';url='https://example.org/haber/yapay-zeka-projesi'
        quote='Türkiye üniversiteleri yeni yapay zekâ araştırma projesini kamuoyuna duyurdu.'
        def fetch(address):
            html=('<h1>Haberler</h1><a href="/haber/yapay-zeka-projesi">Yapay zeka projesi</a>') if address==index else ('<article><h1>Yapay zeka projesi</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>'+quote+' Bilimsel çalışma araştırmacılarla birlikte yürütülüyor.</p></article>')
            return {'url':address,'body':html.encode(),'content_type':'text/html'}
        self.responses(self.plan('Haberleri araştır','Rapor dosyası ve doğrulama'),
            self.tool('research',{'url':index}),
            self.tool('data',{'operation':'headlines','url':index,'query':'yapay zeka'}),
            self.tool('research',{'url':url}),{'supported':True,'answer':'Yanlış tarih: 1999','quotes':[quote]},
            self.done('s3'),self.tool('writer',{'instruction':'Kaynaklı haber raporu','filename':'rapor.md'},goal=1,depends=['s3']),
            self.tool('verify',{},goal=1,depends=['s4']),self.done('s4','s5',goal=1),RuntimeError('HTTP 429'))
        with patch.object(public_sources,'fetch',side_effect=fetch),patch.object(service_store,'ROOT',self.root/'services'),patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Türkiye yapay zekâ son gelişmelerini araştır, rapor oluştur ve dosyayı doğrula. Kaynak: '+index)
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertEqual(self.ask.call_count,9)
        self.assertEqual([s['state'] for s in job['steps']],['failed','done','done','done','done'])
        report=Path(job['outputs']['s4']['file']).read_text(encoding='utf-8')
        self.assertIn('Yayın tarihi: '+day,report);self.assertNotIn('1999',report)
        self.assertIn('<'+url+'>',report);self.assertTrue(goal_tools.verify(job['outputs']['s4'],'alice'))

    def test_already_completed_goals_resume_without_model_and_recheck_actual_file(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Doğrulanmış dosya',self.done('s1'))
        self.run_with_writer_consent('Rapor dosyası oluştur')
        job=goals.latest('alice');job['state']='paused';goals._save(job)
        self.ask.reset_mock();self.ask.side_effect=AssertionError('No extra model call')
        result=self.run_with_writer_consent('hedef devam',resume=True)
        self.assertEqual(goals.latest('alice')['state'],'done',result);self.ask.assert_not_called()

    def test_legacy_category_news_and_report_are_invalidated_without_deleting_file_or_goal(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Eski kategori raporu',self.done('s1'))
        self.run_with_writer_consent('Rapor dosyası oluştur')
        job=goals.latest('alice');path=Path(job['outputs']['s1']['file'])
        job['request']='Türkiye yapay zekâ son gelişmeleri ve haberleri';job['state']='paused';goals._save(job)
        ident=job['id'];self.ask.side_effect=RuntimeError('HTTP 429')
        self.run_with_writer_consent('hedef devam',resume=True)
        job=goals.latest('alice')
        self.assertEqual(job['id'],ident);self.assertEqual(len(job['goals']),1)
        self.assertEqual(job['goals'][0]['state'],'pending');self.assertEqual(job['steps'][0]['state'],'failed')
        self.assertTrue(path.is_file());self.assertEqual(path.read_text(),'Eski kategori raporu')

    def test_news_and_mail_goal_resume_preserves_verified_mail_draft(self):
        from modules import account_tools
        snapshot={'owner':'alice','service':'gmail','operation':'read_message','fetched_at':1,
                  'message':{'id':'M1','from':'sender@example.com','subject':'Merhaba','body':'Yarın görüşelim.','format':'plain','truncated':False}}
        mail=task_results.seal('account',{'state':'done','text':account_tools.render_snapshot(snapshot),'snapshot':snapshot,'sha256':account_tools.digest(snapshot)})
        from writer_consent_fixture import native_writer_after_consent
        # This fixture constructs an already-completed historical draft. It
        # tests readback integrity, not the permission path for creating it.
        with patch('modules.model_wait.ask',return_value='Merhaba, görüşmek üzere.'),native_writer_after_consent():
            draft=task_agents.worker('alice',{'agent':'writer','input':{'instruction':'Mail cevabı yaz','filename':'mail-cevap.md'},'execution':{'request':'Son haberleri araştır ve mailime cevap taslağı yaz'}},{'s1':mail})
        job={'id':'c'*16,'owner':'alice','created':0,'request':'Son haberleri araştır ve mailime cevap taslağı yaz','state':'paused',
             'goals':[{'text':'Haber araştırması','state':'pending','evidence':[]},{'text':'Mail taslağı','state':'done','evidence':['s2']}],
             'steps':[{'id':'s1','goal':1,'tool':'account','input':{'service':'gmail','operation':'read_message','message_id':'M1'},'depends':[],'signature':'mail','state':'done'},
                      {'id':'s2','goal':1,'tool':'writer','input':{'instruction':'Mail cevabı yaz','filename':'mail-cevap.md'},'depends':['s1'],'signature':'draft','state':'done'}],
             'outputs':{'s1':mail,'s2':draft}}
        goals._save(job);self.ask.side_effect=RuntimeError('HTTP 429')
        self.run_with_writer_consent('hedef devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['steps'][1]['state'],'done');self.assertEqual(after['goals'][1]['state'],'done')
        self.assertTrue(goal_tools.verify(after['outputs']['s2'],'alice'))

    def test_unsupported_page_discovers_real_article_then_writes_and_verifies_report(self):
        from modules import public_sources,service_store
        index='https://example.org/news'
        article='https://example.org/news/ai-project'
        quote='16 Ekim 2026 tarihinde yeni yapay zeka projesi duyuruldu.'
        bad='Bu sayfa yalnız kurumsal iletişim ve adres bilgilerini içerir. '*3
        html=('<html><body><a href="/sports">Spor etkinliği</a><a href="/news/ai-project">Yapay zeka projesi duyurusu</a></body></html>').encode()
        self.responses(self.plan('Kaynaklı rapor dosyası'),
            self.tool('research',{'url':'https://example.org/irrelevant','question':'Yapay zeka projesi?'}),
            {'supported':False,'answer':'','quotes':[]},
            self.tool('data',{'operation':'headlines','url':index,'query':'yapay zeka'}),
            self.tool('research',{'url':article,'question':'Yapay zeka projesi?'}),
            {'supported':True,'answer':quote,'quotes':[quote]},
            self.tool('writer',{'instruction':'Kaynağı koruyarak rapor yaz.','filename':'rapor.md'},depends=['s3']),
            '# Araştırma raporu\n'+quote+'\nKaynak: '+article,
            self.tool('verify',{},depends=['s4']),self.done('s3','s4','s5'),self.finish())
        with patch('modules.browser.page_text',side_effect=lambda url:(quote+' Projede üniversiteler ve araştırma kurumları birlikte çalışıyor.') if url==article else bad), \
             patch.object(public_sources,'fetch',return_value={'url':index,'body':html,'content_type':'text/html'}), \
             patch.object(service_store,'ROOT',self.root/'services'),patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Güncel kaynakları kendin bul, kısa rapor dosyası oluştur ve doğrula.')
            job=goals.latest('alice')
            self.assertEqual(job['state'],'done',result)
            self.assertEqual(job['steps'][0]['state'],'failed')
            self.assertEqual(job['outputs']['s2']['structured']['items'][0]['url'],article)
            content=Path(job['outputs']['s4']['file']).read_text()
            self.assertIn(quote,content);self.assertIn(article,content)
            self.assertIn('Erişilemeyen kaynaklar',content)
            self.assertTrue(goal_tools.verify(job['outputs']['s4'],'alice'))
            self.assertEqual(job['outputs']['s5']['state'],'done')

    def test_short_resume_aliases_keep_goal_and_are_not_saved_as_answers(self):
        for command in ('sürdür','SÜRDÜR!','surdur','hedef sürdür','hedef surdur'):
            with self.subTest(command=command):
                self.responses(self.plan('Dosya'),RuntimeError('HTTP 429'))
                self.run_with_writer_consent('Rapor dosyası oluştur');ident=goals.latest('alice')['id']
                self.responses(self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Yerel rapor',self.done('s1'))
                result=goals.handle(self.runtime,command);job=goals.latest('alice')
                if job['state']=='approval':
                    result=goals.run(self.runtime,'hedef onayla',resume=True,approve=True,
                                     expected_job_id=job['id'],
                                     expected_control=goals.control_key(job))
                    job=goals.latest('alice')
                self.assertEqual(job['id'],ident);self.assertEqual(job['state'],'done',result)
                self.assertEqual(job.get('answers',[]),[])

    def test_short_resume_reaches_goal_before_dispatch_or_model_classification(self):
        from modules import engine_commands,command_manager
        runtime=SimpleNamespace(_tr_lower=str.casefold,_llm=SimpleNamespace(set_user_context=Mock()),profile=self.profile,
             _session=lambda:SimpleNamespace(speech_override=None),_cur_source='yazı',flags={},_close_jarvis=Mock(),set_sleep=Mock())
        with patch('modules.brain_entry.matched_protocol', side_effect=lambda *names: 'goal.resume' in names), patch.object(command_manager,'engine_control',return_value=None),patch.object(goals,'handle',return_value='Kayıtlı hedef sürüyor') as handle,patch.object(command_manager,'dispatch') as dispatch:
            self.assertEqual(engine_commands.handle(runtime,'sürdür'),'Kayıtlı hedef sürüyor')
        handle.assert_called_once_with(runtime,'sürdür');dispatch.assert_not_called()

    def test_unavailable_planner_delivers_bounded_literal_news_report_without_more_models(self):
        from modules import public_sources,service_store
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index='https://example.org/haberler';article='https://example.org/haber/ai-project'
        html='<article><h1>Yapay zekâ araştırması</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Türkiye üniversiteleri yapay zekâ araştırma projesini duyurdu. Araştırmacılar bilimsel çalışmanın ayrıntılarını kamuoyuyla paylaştı.</p></article>'
        calls=[]
        def fetch(url):
            calls.append(url)
            body='<a href="/haber/ai-project">Yapay zeka araştırması</a>' if url==index else html
            return {'url':url,'body':body.encode(),'content_type':'text/html'}
        self.responses(self.plan('Kaynakları araştır','Rapor dosyası oluştur ve doğrula'),
                       self.tool('research',{'url':index}),RuntimeError('HTTP 429; no model available'))
        with patch.object(public_sources,'fetch',side_effect=fetch),patch.object(service_store,'ROOT',self.root/'services'),patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Türkiye yapay zekâ son gelişmelerini araştır ve rapor dosyası oluştur. Kaynak: '+index)
            job=goals.latest('alice');ident=job['id']
            self.assertEqual(self.ask.call_count,3)
            self.assertEqual(job['state'],'paused');self.assertTrue(all(g['state']=='pending' for g in job['goals']))
            self.assertIn('Kısmi rapor dosyası:',result)
            output=job['outputs'][job['partial_report']]
            self.assertTrue(goal_tools.verify(output,'alice'));text=Path(output['file']).read_text(encoding='utf-8')
            self.assertIn('Yapay zekâ',text);self.assertIn(day,text);self.assertIn('<'+article+'>',text)
            self.assertEqual(sum(s['tool']=='writer' and s.get('recovery',False) for s in job['steps']),1,
                             'One consented report must not be emitted twice on resume')
            self.assertLessEqual(sum(s.get('recovery',False) for s in job['steps']),10)
            previous_steps=len(job['steps']);previous_calls=len(calls)
            self.ask.side_effect=RuntimeError('Still no model')
            goals.handle(self.runtime,'sürdür')
            self.assertEqual(goals.latest('alice')['id'],ident)
            self.assertEqual(len(goals.latest('alice')['steps']),previous_steps);self.assertEqual(len(calls),previous_calls)

    def test_model_free_recovery_does_not_grant_or_attempt_external_operations(self):
        from modules import news_recovery
        job={'state':'approval','request':'Yapay zekâ haberlerini araştır, rapor dosyası oluştur ve gönder','goals':[{'state':'pending'}]}
        with patch.object(goals,'_record') as run:
            news_recovery.deliver(self.runtime,job)
        run.assert_not_called()

    def test_news_search_can_complete_discovery_but_not_news_research_even_through_verify(self):
        from modules import public_data
        for label,expected in [('Haber bağlantılarını bul','done'),('Son gelişmeleri araştır','paused')]:
            with self.subTest(label=label):
                self.responses(self.plan(label),self.tool('data',{'operation':'news_search','query':'science'}),
                               self.tool('verify',{},depends=['s1']),self.done('s2'),RuntimeError('HTTP 429'))
                value={'items':[{'title':'Article','url':'https://example.org/a','published':''}],
                       'scope':'İndeks tarihi yayın tarihi değildir.'}
                with patch.object(public_data,'news_search',return_value=value):
                    result=self.run_with_writer_consent('Son bilim haberlerini araştır')
                job=goals.latest('alice');self.assertEqual(job['state'],expected,result)
                if expected=='paused':self.assertTrue(any('keşfiyle tamamlanamaz' in f for f in job['feedback']))

    def test_resume_reopens_old_news_goal_completed_with_only_search_evidence(self):
        from modules import public_data
        self.responses(self.plan('Haber bağlantılarını bul'),self.tool('data',{'operation':'sources'}),self.done('s1'))
        self.run_with_writer_consent('Son bilim haberlerini araştır');job=goals.latest('alice');ident=job['id']
        job['goals'][0]['text']='Son haberleri araştır';job['state']='paused';goals._save(job)
        self.responses(RuntimeError('HTTP 429'))
        goals.handle(self.runtime,'sürdür');job=goals.latest('alice')
        self.assertEqual(job['id'],ident);self.assertEqual(job['state'],'paused')
        self.assertEqual(job['goals'][0]['state'],'pending');self.assertEqual(job['goals'][0]['evidence'],[])

    def test_direct_publisher_recovery_verifies_partial_file_without_search(self):
        from modules import public_sources,service_store,public_data
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index='https://example.org/haberler';article='https://example.org/news/ai'
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==index:body=('<html><a href="'+article+'">Yapay zekâ haberi</a></html>').encode()
            elif url==article:body=('<article><h1>Bilimsel proje</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Yeni yapay zekâ araştırma projesi üniversite tarafından kamuoyuna duyuruldu. Projenin ayrıntıları bu sayfada açıklandı.</p></article>').encode()
            else:raise AssertionError('Unexpected URL: '+url)
            return {'url':url,'body':body,'content_type':'text/html'}
        self.responses(self.plan('Kaynak araştır','Rapor dosyası oluştur ve doğrula'),
                       self.tool('research',{'url':index}),RuntimeError('HTTP 429'))
        with patch.object(public_sources,'fetch',side_effect=fetch),patch.object(service_store,'ROOT',self.root/'services'),patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Sadece https://example.org/haberler yapay zekâ son 7 gün gelişmelerini araştır ve rapor dosyası oluştur')
            job=goals.latest('alice');out=job['outputs'][job['partial_report']]
            self.assertTrue(goal_tools.verify(out,'alice'));self.assertIn('Kısmi rapor dosyası:',result)
            text=Path(out['file']).read_text(encoding='utf-8')
            self.assertIn(day,text);self.assertNotIn('2099',text);self.assertNotIn('foreign.org',text)
            self.assertEqual(self.ask.call_count,3);self.assertEqual(job['state'],'paused')
            self.assertFalse(any(s['input'].get('operation')=='news_search' for s in job['steps']))
            self.assertEqual(sum(s['tool']=='writer' and s.get('recovery',False) for s in job['steps']),1,
                             'One consented report must not be emitted twice on resume')
            self.assertLessEqual(sum(s.get('recovery',False) for s in job['steps']),10)
            self.assertTrue(all(url.startswith('https://example.org/') for url in calls))

    def test_model_free_recovery_honors_remaining_turn_budget(self):
        from modules import news_recovery
        job={'id':'d'*16,'state':'running','owner':'alice','request':'Yapay zekâ haberlerini araştır ve rapor dosyası oluştur',
             'goals':[{'state':'pending'}],'steps':[{'id':'s1','tool':'research','input':{'url':'https://example.org/haberler'}}],'outputs':{}}
        def record(runtime,job,step):
            step['state']='failed';job['outputs'][step['id']]={'state':'failed'}
        with patch.object(goals,'_record',side_effect=record) as run:
            news_recovery.deliver(self.runtime,job,max_new_steps=1)
        self.assertEqual(run.call_count,0);self.assertEqual(len(job['steps']),1)

    def test_premature_finish_delivers_existing_news_file_without_model_or_fetch(self):
        from modules import public_sources
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        url='https://example.org/haber/ai'
        quote='Türkiye üniversiteleri yapay zekâ araştırma projesini bilimsel sonuçlarıyla kamuoyuna duyurdu.'
        html=('<article><h1>Yeni araştırma</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>'+quote+' Çalışmanın ayrıntıları kamuoyuyla paylaşıldı.</p></article>').encode()
        self.responses(self.plan('Son haberleri araştır','Türkçe raporu kaydet ve doğrula'),
            self.tool('research',{'url':url}),{'supported':True,'answer':quote,'quotes':[quote]},
            self.done('s1'),self.finish())
        with patch.object(public_sources,'fetch',return_value={'url':url,'body':html}) as fetch,patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Son 7 gün Türkiye yapay zekâ haberlerini araştır ve Türkçe rapor dosyası oluştur. Kaynak: '+url)
        job=goals.latest('alice')
        self.assertEqual(self.ask.call_count,5);fetch.assert_called_once()
        self.assertEqual(job['state'],'paused');self.assertEqual(job['goals'][0]['state'],'done')
        self.assertEqual(job['goals'][1]['state'],'pending')
        report=job['outputs'][job['partial_report']]
        self.assertTrue(goal_tools.verify(report,'alice'));self.assertIn(day,Path(report['file']).read_text())
        self.assertEqual([s['tool'] for s in job['steps']],['research','writer','verify'])
        self.assertIn('Kısmi rapor dosyası:',result)
        self.responses(self.finish())
        with patch.object(public_sources,'fetch',side_effect=AssertionError('No new fetch')):
            goals.handle(self.runtime,'hedef devam')
        resumed=goals.latest('alice');self.assertEqual(resumed['id'],job['id'])
        self.assertEqual(len(resumed['steps']),3)

    def test_repeated_incomplete_finish_stops_after_three_rejections(self):
        self.responses(self.plan('Bir iş'),self.finish(),self.finish(),self.finish())
        result=self.run_with_writer_consent('Bir iş yap')
        self.assertEqual(self.ask.call_count,4)
        self.assertEqual(goals.latest('alice')['state'],'paused')
        self.assertIn('3 kez',result)

    def test_bare_resume_without_goal_never_falls_through_to_chat(self):
        self.assertEqual(goals.handle(self.runtime,'devam'),'Sürdürülecek kayıtlı hedef yok.')
        self.ask.assert_not_called()

    def test_invalid_fileless_news_plans_try_bounded_source_recovery(self):
        self.responses(self.plan('Son haberleri araştır'),
            {'action':'invalid'},{'action':'invalid'},{'action':'invalid'})
        from modules import news_recovery
        with patch.object(news_recovery,'deliver') as recover:
            self.run_with_writer_consent('Yapay zekâ son dakika haberleri')
        recover.assert_called_once_with(self.runtime,goals.latest('alice'),max_new_steps=24)
        self.assertEqual(self.ask.call_count,4)
        self.assertEqual(goals.latest('alice')['state'],'paused')

    def test_generic_fileless_news_tries_publisher_recovery_before_planner(self):
        from modules import news_recovery
        with patch.object(news_recovery,'deliver') as recover, \
                patch.object(goals,'_finish_completed',side_effect=lambda _job:recover.called):
            self.run_with_writer_consent('Son dakika haberleri')
        recover.assert_called_once_with(self.runtime,goals.latest('alice'),max_new_steps=24)
        self.ask.assert_not_called()

    def test_generic_fileless_news_pauses_when_bounded_recovery_has_no_evidence(self):
        from modules import news_recovery
        with patch.object(news_recovery,'deliver') as recover:
            result=self.run_with_writer_consent('Son dakika haberleri')
        job=goals.latest('alice')
        recover.assert_called_once_with(self.runtime,job,max_new_steps=24)
        self.ask.assert_not_called()
        self.assertEqual(job['state'],'paused')
        self.assertEqual(job['goals'][0]['state'],'pending')
        self.assertEqual(job['steps'],[])
        self.assertIn('doğrulanmış',result)

    def test_bare_resume_closed_goal_says_it_is_closed_without_model(self):
        self.responses(self.plan('İş'),RuntimeError('models unavailable'))
        self.run_with_writer_consent('İş yap');job=goals.latest('alice')
        job['state']='cancelled';goals._save(job);self.ask.reset_mock()
        self.assertIn('iptal',goals.handle(self.runtime,'devam'))
        self.ask.assert_not_called()

    def test_resume_question_delivers_saved_news_without_asking_planner_again(self):
        from modules import public_sources
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        url='https://example.org/haber/ai'
        quote='Türkiye üniversiteleri yapay zekâ araştırma projesini bilimsel sonuçlarıyla kamuoyuna duyurdu.'
        body=('<article><h1>Yeni proje</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>'+quote+' Araştırmanın ayrıntıları kamuoyuyla paylaşıldı.</p></article>').encode()
        self.responses(self.plan('Araştır','Rapor dosyası oluştur'),self.tool('research',{'url':url}),
            {'supported':True,'answer':quote,'quotes':[quote]},self.done('s1'),
            {'action':'ask','question':'Türkiye yapay zekâ gelişmelerini araştır ve rapor dosyası oluştur.'})
        with patch.object(public_sources,'fetch',return_value={'url':url,'body':body}),patch('modules.privacy.blocked',return_value=None):
            self.run_with_writer_consent('Türkiye yapay zekâ son 7 gün gelişmelerini araştır ve rapor dosyası oluştur. Kaynak: '+url)
        original=goals.latest('alice');self.assertEqual(original['state'],'question')
        self.ask.reset_mock()
        with patch.object(public_sources,'fetch',side_effect=AssertionError('No fetch')):
            result=goals.handle(self.runtime,'devam')
        job=goals.latest('alice');self.assertEqual(job['id'],original['id']);self.ask.assert_not_called()
        self.assertEqual(job['state'],'approval',result)
        self.assertFalse(any(o.get('file') for o in job['outputs'].values()))
        result=goals.run(self.runtime,'hedef onayla',resume=True,approve=True,
                         expected_job_id=job['id'],expected_control=goals.control_key(job))
        job=goals.latest('alice');self.ask.assert_not_called()
        self.assertTrue(goal_tools.verify(job['outputs'][job['partial_report']],'alice'))
        self.assertIn('Kısmi rapor dosyası:',result)
        self.assertEqual(job['goals'][1]['state'],'pending')
        self.responses({'action':'ask','question':'Hangi ek kurum incelensin?'})
        goals.handle(self.runtime,'devam')
        self.assertEqual(goals.latest('alice')['state'],'question')
        self.responses({'action':'ask','question':'Ek kurum kapsamı kaydedildi.'})
        goals.handle(self.runtime,'Boğaziçi Üniversitesi')
        self.assertIn('Boğaziçi Üniversitesi',goals.latest('alice')['answers'])


    def test_three_guessed_news_urls_are_rejected_without_fetch_or_unbounded_plans(self):
        from modules import public_sources, news_recovery
        self.responses(self.plan('Türkiye haberlerini araştır'),
            self.tool('research',{'url':'https://www.veri'}),
            self.tool('research',{'url':'https://tubitak.gov.tr/tr/bilim-kalkinimi/yapay-zeka'}),
            self.tool('research',{'url':'https://turkiye.gov.tr/uydurulan/yapay-zeka'}))
        with patch.object(public_sources,'fetch') as fetch,patch.object(news_recovery,'deliver') as recovery:
            result=self.run_with_writer_consent('Türkiye yapay zekâ haberlerini araştır ve rapor dosyası oluştur')
        fetch.assert_not_called();recovery.assert_called_once()
        self.assertEqual(self.ask.call_count,4)
        self.assertEqual(goals.latest('alice')['steps'],[])
        self.assertIn('3 kez',result)

    def test_vague_news_question_recovers_without_asking_user_or_another_model(self):
        from modules import news_recovery
        self.responses(self.plan('Araştır ve rapor oluştur'),{'action':'ask','question':'Eksik somut bilgi.'})
        with patch.object(news_recovery,'deliver') as recovery:
            result=self.run_with_writer_consent('Türkiye yapay zekâ haberlerini araştır ve rapor dosyası oluştur')
        recovery.assert_called_once();self.assertEqual(self.ask.call_count,2)
        self.assertEqual(goals.latest('alice')['state'],'paused')
        self.assertIn('Yeni bilgi vermen gerekmiyor',result)
        self.assertNotIn('Eksik somut bilgi',result)

    def test_vague_question_real_file_recovers_two_publishers_with_no_more_models(self):
        from modules import public_sources,publisher_news
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index_rows=publisher_news.sources_for('Türkiye yapay zekâ haberleri')[:2]
        index_urls=[s['url'] for s in index_rows]
        domains=['https://publisher-one.org','https://publisher-two.net']
        fetched=[]
        def fetch(url):
            fetched.append(url)
            if url in index_urls:
                # A publisher can redirect to its current site; use its returned URL.
                base=domains[index_urls.index(url)]
                return {'url':base+'/','body':b'<a href="/news/ai">Yapay zeka projesi</a><a href="/news/ai2">Yapay zeka ikinci haber</a>'}
            body=('<article><h1>Yeni yapay zekâ projesi</h1><time itemprop="datePublished" datetime="'+day+'"></time>'
                '<p>Türkiye üniversiteleri yapay zekâ araştırma projesini bilimsel sonuçlarıyla kamuoyuna duyurdu. Araştırmacılar yeni projenin kapsamını açıkladı.</p></article>')
            return {'url':url,'body':body.encode()}
        self.responses(self.plan('Türkiye güncel haberlerini araştır','Rapor dosyası oluştur'),{'action':'ask','question':'Eksik somut bilgi'})
        with patch.object(publisher_news,'sources_for',return_value=index_rows),patch.object(public_sources,'fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            result=self.run_with_writer_consent('Türkiye yapay zekâ son 7 gün haberlerini araştır ve rapor dosyası oluştur')
        job=goals.latest('alice');self.assertEqual(self.ask.call_count,2)
        self.assertIn('Kısmi rapor dosyası:',result)
        output=job['outputs'][job['partial_report']]
        self.assertTrue(goal_tools.verify(output,'alice'))
        text=Path(output['file']).read_text(encoding='utf-8')
        for domain in domains:self.assertIn(domain+'/news/ai',text)
        self.assertEqual(job['state'],'paused')
        self.assertTrue(all(goal['state']=='pending' for goal in job['goals']))
        self.assertLessEqual(len(fetched),6)
        self.assertEqual(len(fetched),len(set(fetched)), 'pipeline evidence was downloaded twice')
        # A later verified source can extend a partial report, preserving its old file.
        from modules import news_recovery
        old_path=Path(output['file']);old_bytes=old_path.read_bytes();old_id=job['partial_report']
        new_id='s'+str(len(job['steps'])+1)
        step={'id':new_id,'tool':'research','goal':0,'input':{'url':'https://publisher-three.edu.tr/news/ai'},
              'depends':[],'signature':'third-source','state':'queued','source_only':True}
        job['steps'].append(step)
        with patch.object(public_sources,'fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            goals._record(self.runtime,job,step)
        with patch.object(public_sources,'fetch',side_effect=AssertionError('No network on report refresh')):
            news_recovery.deliver(self.runtime,job,existing_only=True,max_new_steps=2)
            self.assertEqual(job['state'],'approval')
            self.assertEqual(job['partial_report'],old_id)
            # A new evidence-bound report needs a NEW owner/job/step consent.
            pending=goals.latest('alice')
            goals.run(self.runtime,'hedef onayla',resume=True,approve=True,
                      expected_job_id=pending['id'],
                      expected_control=goals.control_key(pending))
            job=goals.latest('alice')
            refreshed=job['partial_report'];count=len(job['steps'])
            news_recovery.deliver(self.runtime,job,existing_only=True,max_new_steps=2)
        self.assertNotEqual(old_id,refreshed);self.assertEqual(count,len(job['steps']))
        self.assertEqual(old_bytes,old_path.read_bytes())
        self.assertIn('publisher-three.edu.tr',Path(job['outputs'][refreshed]['file']).read_text())
        self.assertTrue(goal_tools.verify(job['outputs'][refreshed],'alice'))

    def test_recovery_permission_refusal_is_not_swallowed_into_more_planning(self):
        from modules import news_recovery
        self.responses(self.plan('Araştır'),{'action':'ask','question':'Eksik somut bilgi'})
        with patch.object(news_recovery,'deliver',side_effect=PermissionError('owner mismatch')):
            with self.assertRaises(PermissionError):
                self.run_with_writer_consent('Türkiye yapay zekâ haberlerini araştır ve rapor dosyası oluştur')
        self.assertEqual(self.ask.call_count,2)

    def test_broad_news_requires_two_publishers_not_two_subdomains(self):
        from modules import public_sources
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        quote='Türkiye üniversiteleri yapay zekâ araştırma projesini bilimsel sonuçlarıyla kamuoyuna duyurdu.'
        body=('<article><h1>Yapay zekâ projesi</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>'+quote+' Projenin ayrıntıları araştırmacılarla paylaşıldı.</p></article>').encode()
        outputs={};steps=[]
        for i,url in enumerate(['https://haber.ornek.edu.tr/news/ai','https://www.ornek.edu.tr/news/ai','https://baska.edu.tr/news/ai']):
            ident='s'+str(i+1)
            with patch.object(public_sources,'fetch',return_value={'url':url,'body':body}),patch('modules.privacy.blocked',return_value=None):
                outputs[ident]=task_agents.worker('alice',{'agent':'research','input':{'url':url},'execution':{
                    'request':'Türkiye yapay zekâ haberleri','source_only':True}}, {})
            steps.append({'id':ident,'tool':'research','input':{'url':url},'depends':[],'state':'done'})
        job={'request':'Türkiye yapay zekâ son gelişmelerini araştır','steps':steps,'outputs':outputs}
        goal={'text':'Türkiye güncel haberlerini araştır'}
        for evidence in [['s1'],['s1','s2']]:
            with self.assertRaisesRegex(ValueError,'Araştırma kısmi'):
                goals._check_news_completion(job,goal,evidence)
        goals._check_news_completion(job,goal,['s1','s3'])
        self.ask.assert_not_called()

    def test_news_preview_never_cuts_a_url_or_marks_old_single_source_complete(self):
        from modules import research_evidence
        url='https://example.org/'+('x'*1300)
        source={'url':url,'title':'Yeni haber','published':'2026-10-16','text':'source'}
        output={'state':'done','text':'x'*1300+'\n'+url,'news_report_evidence':{'sources':{'s1':{'news_article':source}}}}
        preview=research_evidence.preview(output)
        self.assertIn(url,preview);self.assertIn('1 haber, 1 farklı yayıncı',preview)
        quote='Yeni haberde doğrulanmış kaynak bulgusu ve açıklaması yer alıyor. '
        article={'url':url,'title':'Yeni haber','published':'2026-10-16','text':quote*3}
        verified=task_results.seal('research',{'state':'done','text':quote,'source':url,'source_chars':len(quote*3),
                                             'news_article':article,'source_quotes':[quote]})
        with patch.object(goals,'_check_news_completion',side_effect=ValueError('Partial')):
            text=goals.render({'owner':'alice','id':'a'*16,'state':'question','request':'Türkiye haberleri',
                'goals':[{'text':'Araştır','state':'done','evidence':['s1']}],
                'steps':[{'id':'s1','tool':'research','state':'done','goal':0,'input':{},'depends':[]}],
                'outputs':{'s1':verified},'question':'Eksik somut bilgi'})
        self.assertNotIn('✓',text);self.assertIn('Kısmi:',text);self.assertNotIn('Eksik somut bilgi',text)

if __name__=='__main__':unittest.main()

