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
        self.runtime=SimpleNamespace(profile=self.profile,_cur_source='yazı',pc_profile=lambda:self.profile,emit=Mock())
        model=patch.object(llm,'ask');self.ask=model.start();self.addCleanup(model.stop)

    def responses(self,*items):self.ask.side_effect=[json.dumps(x) if isinstance(x,dict) else x for x in items]
    def plan(self,*texts):return {'action':'plan','goals':list(texts)}
    def tool(self,kind,data,goal=0,depends=None):return {'action':'tool','goal':goal,'tool':kind,'input':data,'depends':depends or []}
    def done(self,*ids,goal=0):return {'action':'complete','goal':goal,'evidence':list(ids)}
    def finish(self):return {'action':'finish'}

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
            self.tool('browser',{'url':'https://example.com','instruction':'Yalnız oku'}),
            self.tool('writer',{'instruction':'Kaynağa göre rapor yaz','filename':'rapor.md'},depends=['s2']),
            'Gerçek kaynaklı rapor metni',self.done('s3'),
            self.tool('action',{'action':'note_add','params':{'text':'Tamamlandı'}},goal=1),
            self.done('s4',goal=1),self.finish())
        with patch.object(task_agents,'worker',side_effect=work),patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=goals.run(self.runtime,'Araştırıp raporu dosyaya kaydet ve not ekle')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertEqual([s['tool'] for s in job['steps']],['research','browser','writer','action'])
        self.assertIn('Gerçek kaynaklı rapor metni',Path(job['outputs']['s3']['file']).read_text())
        self.assertIn('https://example.com',Path(job['outputs']['s3']['file']).read_text())
        self.assertIn('Erişilemeyen kaynaklar',Path(job['outputs']['s3']['file']).read_text())
        bridge.note_add.assert_called_once_with(text='Tamamlandı',title='')
        self.assertIsNone(goals.latest('bob'))

    def test_all_goals_and_actual_successful_evidence_are_required(self):
        self.responses(self.plan('İş bir','İş iki'),self.finish(),self.done('invented'),RuntimeError('models unavailable'))
        result=goals.run(self.runtime,'İki işi de yap')
        job=goals.latest('alice');self.assertEqual(job['state'],'paused')
        self.assertTrue(all(g['state']=='pending' for g in job['goals']))
        self.assertIn('tamamlanmadı',result)

    def test_action_confirmation_is_persisted_and_only_exact_pending_action_runs(self):
        bridge=SimpleNamespace(note_delete=Mock(return_value=True))
        self.profile.data['items']=[{'id':7,'text':'selected note'}]
        self.responses(self.plan('Seçilen notu sil'),self.tool('action',{'action':'note_delete','params':{'nid':7}}))
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            result=goals.run(self.runtime,'7 kimlikli notu sil')
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
            goals.run(self.runtime,'Not ekle')
            goals.handle(self.runtime,'devam')
        self.assertEqual(goals.latest('alice')['state'],'review')
        bridge.note_add.assert_called_once()

    def test_done_tool_is_never_executed_twice_and_model_can_complete_other_goal(self):
        self.responses(self.plan('Durumu oku'),self.tool('diagnose',{'kind':'accounts'}),
            self.tool('diagnose',{'kind':'accounts'}),self.done('s1'),self.finish())
        with patch('modules.service_health.report',return_value='Yerel hesap durumu') as check:
            goals.run(self.runtime,'Hesap durumunu oku')
        check.assert_called_once_with('alice');self.assertEqual(goals.latest('alice')['state'],'done')

    def test_real_document_read_and_translation_share_goal_with_verified_source(self):
        path=self.root/'document.txt';path.write_text('Merhaba dünya',encoding='utf-8')
        self.runtime.tr=SimpleNamespace(translate=Mock(return_value='Hello world'))
        self.responses(self.plan('Belgeyi oku','İngilizceye çevir'),
            self.tool('document',{'operation':'read','path':str(path)}),self.done('s1'),
            self.tool('document',{'operation':'translate','path':str(path),'target':'English'},goal=1),self.done('s2',goal=1),self.finish())
        with patch.object(nxapi,'allowed',return_value=path):result=goals.run(self.runtime,'Dosyayı oku ve İngilizceye çevir')
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
            goals.run(self.runtime,'Hesabı kontrol et ve rapor oluştur')
        ident=goals.latest('alice')['id']
        self.responses(self.tool('writer',{'instruction':'Durum raporu','filename':'rapor.md'},goal=1,depends=['s1']),
            'Hesap durum raporu',self.done('s2',goal=1),self.finish())
        goals.handle(self.runtime,'devam et')
        job=goals.latest('alice');self.assertEqual(job['state'],'done');self.assertEqual(job['id'],ident)
        self.assertEqual(len(job['steps']),2)

    def test_owner_change_and_cancel_never_start_next_tool(self):
        def model(*args,**kwargs):
            self.runtime.profile=SimpleNamespace(slug='bob',data={})
            return json.dumps(self.plan('İş'))
        self.ask.side_effect=model
        from modules import requests_state
        with self.assertRaises(requests_state.Cancelled):goals.run(self.runtime,'İşi yap')
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
            result=goals.run(self.runtime,'New note diye not ekle')
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
            goals.run(self.runtime,'Notu ekle ve doğrula')
        self.assertEqual(len(goals.latest('alice')['steps']),3)

    def test_plain_action_classification_reaches_goal_instead_of_catalog_rejection(self):
        from modules import router
        for raw in ('{"intent":"chat","args":{}}','{"intent":"unknown","args":{}}'):
            result=router.classify('Araştırıp rapor hazırla',lambda *a:raw)
            self.assertEqual(result,{'intent':'task','args':{'request':'Araştırıp rapor hazırla'}})

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
            result=goals.run(self.runtime,'Mail başlıklarını oku ve yerel taslak yaz; gönderim yok')
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
        result=goals.run(self.runtime,'Bir saniyelik yazılı video dosyası oluştur, yayınlama')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        output=job['outputs']['s1'];self.assertTrue(Path(output['file']).is_file())
        self.assertTrue(task_results.verify(output,owner='alice'))
        self.assertAlmostEqual(output['media']['duration'],1,delta=.2)

    def test_desktop_completion_and_natural_consent_use_saved_native_id(self):
        from modules import desktop_agent
        native={'id':'native1','owner':'alice','status':'consent','history':[],'pending_app':'notepad','target':'Notepad','goal':'Metni yaz'}
        identity={'owner':'alice','job_id':'goal','task_id':'s1'}
        data={'target':'Notepad','goal':'Metni yaz'}
        def consent(*args,**kwargs):
            self.assertEqual(args[1],'PC izin ver')
            native.update(status='done',history=[{'verified':True}]);return 'Text entered'
        with patch.object(desktop_agent,'_load',return_value=native),patch.object(desktop_agent,'handle',side_effect=consent):
            out=goal_tools.execute(self.runtime,'desktop',data,{},identity,approval={'desktop_id':'native1'})
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


    def test_legacy_safe_dag_keeps_existing_task_journal_and_real_files(self):
        with patch.object(task_agents,'STORE',self.root/'legacy'):
            self.responses({'tasks':[{'id':'report','agent':'writer','input':{'instruction':'Yaz','filename':'test.md'}}]},'Kaydedilen gerçek rapor')
            result=goals.run(self.runtime,'Test raporu hazırla')
            self.assertIn('done',result)
            legacy=task_agents.recent('alice');job=goals.latest('alice')
            self.assertEqual(job['legacy_job'],legacy['id'])
            self.assertEqual(job['state'],'done')
            self.assertEqual(Path(legacy['outputs']['report']['file']).read_text(),'Kaydedilen gerçek rapor')
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
        goals.run(self.runtime,'Hesabı kontrol et api_key=unusual-value parola:another-value')
        prompt=self.ask.call_args.args[0]
        self.assertNotIn('unusual-value',prompt);self.assertNotIn('another-value',prompt)

    def test_interrupted_step_before_execution_can_resume_without_false_uncertainty(self):
        self.responses(self.plan('Not ekle'),self.tool('action',{'action':'note_add','params':{'text':'not'}}))
        from modules import requests_state
        with patch.object(goal_tools,'checkpoint',side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):goals.run(self.runtime,'Not ekle')
        job=goals.latest('alice');job['state']='paused';job['steps'][0]['state']='running';goals._save(job)
        bridge=SimpleNamespace(note_add=Mock(return_value={'id':1,'text':'not'}))
        self.responses(self.tool('action',{'action':'note_add','params':{'text':'not'}}),self.done('s2'),self.finish())
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)):
            goals.handle(self.runtime,'devam')
        bridge.note_add.assert_called_once();self.assertEqual(goals.latest('alice')['state'],'done')



    def test_old_completed_desktop_job_cannot_prove_new_rejected_request(self):
        from modules import desktop_agent
        old={'id':'old','owner':'alice','target':'Calculator','goal':'12+7','status':'done','history':[{'verified':True}]}
        with patch.object(desktop_agent,'_load',return_value=old),patch.object(desktop_agent,'handle',return_value='Başka görev çalışıyor'):
            result=goal_tools.execute(self.runtime,'desktop',{'target':'Calculator','goal':'12+7'}, {},{'owner':'alice'})
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



    def test_native_desktop_question_resumes_same_saved_job_without_recreating_it(self):
        from modules import desktop_agent
        native={'id':'native','owner':'alice','target':'Notepad','goal':'Metni yaz','status':'question','history':[{'verified':True}]}
        def resume(job,**kwargs):
            self.assertEqual(job['answer'],'Merhaba');job['status']='done';return 'Metin yazıldı'
        data={'target':'Notepad','goal':'Metni yaz','resume_id':'native','answer':'Merhaba'}
        with patch.object(desktop_agent,'_load',return_value=native),patch.object(desktop_agent,'run',side_effect=resume),patch.object(desktop_agent,'handle') as create:
            with self.assertRaises(PermissionError):goal_tools.execute(self.runtime,'desktop',data,{}, {'owner':'alice'})
            output=goal_tools.execute(self.runtime,'desktop',data,{}, {'owner':'alice','desktop_ids':['native']})
        self.assertEqual(output['state'],'done');create.assert_not_called()



    def test_code_file_or_test_request_goes_to_execution_not_chat_snippet(self):
        from modules import engine_intents
        with patch.object(goals,'run',return_value='Çalıştırıldı') as execute:
            result=engine_intents.dispatch(self.runtime,'code',{'task':'model rewrite'},'Toplama dosyasını oluştur ve test et','toplama dosyasını oluştur ve test et')
        self.assertEqual(result,'Çalıştırıldı');execute.assert_called_once_with(self.runtime,'Toplama dosyasını oluştur ve test et')

    def test_rejected_before_effect_can_find_alternative_without_review_stop(self):
        self.responses(self.plan('Durumu raporla'),self.tool('sharing',{'mode':'camera'}),
            self.tool('diagnose',{'kind':'accounts'}),self.done('s2'),self.finish())
        with patch('modules.service_health.report',return_value='Yerel hesap bilgisi'):
            result=goals.run(self.runtime,'Hesap durumunu raporla')
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
            result=goals.run(self.runtime,'İstanbul raporu dosyası ve İstanbul yazan 3 saniyelik video oluştur. Yayınlama.')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result);code.assert_not_called()
        self.assertFalse(job['steps'][0]['started'])
        self.assertTrue(Path(job['outputs']['s2']['file']).is_file())
        self.assertAlmostEqual(job['outputs']['s3']['media']['duration'],3,delta=.2)

    def test_legacy_locked_coder_review_can_resume_without_repeating_code(self):
        self.responses(self.plan('Rapor dosyası'),RuntimeError('offline'))
        goals.run(self.runtime,'Rapor dosyası oluştur')
        job=goals.latest('alice')
        job['state']='review';job['steps']=[{'id':'s1','goal':0,'tool':'coder','input':{'request':'Rapor üret'},'state':'failed','started':True,'depends':[],'signature':'old'}]
        job['outputs']={'s1':{'state':'failed','text':'Önce sohbetten parolalı geliştirme modunu aç.'}}
        goals._save(job)
        self.responses(self.tool('writer',{'instruction':'Rapor üret','filename':'rapor.md'}),'Rapor metni',self.done('s2'),self.finish())
        result=goals.handle(self.runtime,'devam et')
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
            result=goals.run(self.runtime,'Bir not oluştur')
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
            result=goals.run(self.runtime,'Türkiye yapay zekâ araştırmasını incele ve kaynaklı rapor dosyası oluştur')
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
        goals.run(self.runtime,'hedef devam',resume=True)
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
        goals.run(self.runtime,'Kaynaklı rapor oluştur')
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
        goals.run(self.runtime,'Rapor hazırla')
        self.assertTrue(self.ask.call_args_list)
        for call in self.ask.call_args_list:self.assertEqual(call.kwargs['max_tokens'],1200)



    def test_repeated_replanning_stops_without_overwriting_saved_goals_or_running_tools(self):
        self.responses(self.plan('Özgün hedef'),self.plan('Yanlış yeni hedef'),
                       self.plan('Yanlış yeni hedef'),self.plan('Yanlış yeni hedef'))
        with patch.object(goals,'_record',side_effect=AssertionError('no tool should run')):
            text=goals.run(self.runtime,'Kaynaklı rapor hazırla')
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
        goals.run(self.runtime,'Kaynaklı rapor hazırla')
        job=goals.latest('alice')
        self.assertEqual(job['goals'][0]['text'],'Özgün hedef')
        self.assertEqual(job['state'],'question')
        self.assertEqual(self.ask.call_count,3)



    def test_last_explicit_completion_finishes_without_another_model_call(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),
                       'Doğrulanmış dosya',self.done('s1'),RuntimeError('HTTP 429'))
        result=goals.run(self.runtime,'Rapor dosyası oluştur')
        job=goals.latest('alice')
        self.assertEqual(job['state'],'done',result)
        self.assertEqual(self.ask.call_count,4)

    def test_dated_news_discovery_report_verify_and_two_completions_do_not_need_final_model(self):
        from datetime import datetime,timezone,timedelta
        from modules import public_sources,service_store
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index='https://example.org/haberler';url='https://example.org/haber/yapay-zeka-projesi'
        quote='Üniversite yeni yapay zekâ araştırma projesini kamuoyuna duyurdu.'
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
            result=goals.run(self.runtime,'Türkiye yapay zekâ son gelişmelerini araştır, rapor oluştur ve dosyayı doğrula')
        job=goals.latest('alice');self.assertEqual(job['state'],'done',result)
        self.assertEqual(self.ask.call_count,9)
        self.assertEqual([s['state'] for s in job['steps']],['failed','done','done','done','done'])
        report=Path(job['outputs']['s4']['file']).read_text(encoding='utf-8')
        self.assertIn('Yayın tarihi: '+day,report);self.assertNotIn('1999',report)
        self.assertIn('<'+url+'>',report);self.assertTrue(goal_tools.verify(job['outputs']['s4'],'alice'))

    def test_already_completed_goals_resume_without_model_and_recheck_actual_file(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Doğrulanmış dosya',self.done('s1'))
        goals.run(self.runtime,'Rapor dosyası oluştur')
        job=goals.latest('alice');job['state']='paused';goals._save(job)
        self.ask.reset_mock();self.ask.side_effect=AssertionError('No extra model call')
        result=goals.run(self.runtime,'hedef devam',resume=True)
        self.assertEqual(goals.latest('alice')['state'],'done',result);self.ask.assert_not_called()

    def test_legacy_category_news_and_report_are_invalidated_without_deleting_file_or_goal(self):
        self.responses(self.plan('Rapor'),self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Eski kategori raporu',self.done('s1'))
        goals.run(self.runtime,'Rapor dosyası oluştur')
        job=goals.latest('alice');path=Path(job['outputs']['s1']['file'])
        job['request']='Türkiye yapay zekâ son gelişmeleri ve haberleri';job['state']='paused';goals._save(job)
        ident=job['id'];self.ask.side_effect=RuntimeError('HTTP 429')
        goals.run(self.runtime,'hedef devam',resume=True)
        job=goals.latest('alice')
        self.assertEqual(job['id'],ident);self.assertEqual(len(job['goals']),1)
        self.assertEqual(job['goals'][0]['state'],'pending');self.assertEqual(job['steps'][0]['state'],'failed')
        self.assertTrue(path.is_file());self.assertEqual(path.read_text(),'Eski kategori raporu')

    def test_news_and_mail_goal_resume_preserves_verified_mail_draft(self):
        from modules import account_tools
        snapshot={'owner':'alice','service':'gmail','operation':'read_message','fetched_at':1,
                  'message':{'id':'M1','from':'sender@example.com','subject':'Merhaba','body':'Yarın görüşelim.','format':'plain','truncated':False}}
        mail=task_results.seal('account',{'state':'done','text':account_tools.render_snapshot(snapshot),'snapshot':snapshot,'sha256':account_tools.digest(snapshot)})
        with patch('modules.model_wait.ask',return_value='Merhaba, görüşmek üzere.'):
            draft=task_agents.worker('alice',{'agent':'writer','input':{'instruction':'Mail cevabı yaz','filename':'mail-cevap.md'},'execution':{'request':'Son haberleri araştır ve mailime cevap taslağı yaz'}},{'s1':mail})
        job={'id':'c'*16,'owner':'alice','created':0,'request':'Son haberleri araştır ve mailime cevap taslağı yaz','state':'paused',
             'goals':[{'text':'Haber araştırması','state':'pending','evidence':[]},{'text':'Mail taslağı','state':'done','evidence':['s2']}],
             'steps':[{'id':'s1','goal':1,'tool':'account','input':{'service':'gmail','operation':'read_message','message_id':'M1'},'depends':[],'signature':'mail','state':'done'},
                      {'id':'s2','goal':1,'tool':'writer','input':{'instruction':'Mail cevabı yaz','filename':'mail-cevap.md'},'depends':['s1'],'signature':'draft','state':'done'}],
             'outputs':{'s1':mail,'s2':draft}}
        goals._save(job);self.ask.side_effect=RuntimeError('HTTP 429')
        goals.run(self.runtime,'hedef devam',resume=True)
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
            result=goals.run(self.runtime,'Güncel kaynakları kendin bul, kısa rapor dosyası oluştur ve doğrula.')
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
                goals.run(self.runtime,'Rapor dosyası oluştur');ident=goals.latest('alice')['id']
                self.responses(self.tool('writer',{'instruction':'Yaz','filename':'rapor.md'}),'Yerel rapor',self.done('s1'))
                result=goals.handle(self.runtime,command);job=goals.latest('alice')
                self.assertEqual(job['id'],ident);self.assertEqual(job['state'],'done',result)
                self.assertEqual(job.get('answers',[]),[])

    def test_short_resume_reaches_goal_before_dispatch_or_model_classification(self):
        from modules import engine_commands,command_manager
        runtime=SimpleNamespace(_tr_lower=str.casefold,_llm=SimpleNamespace(set_user_context=Mock()),profile=self.profile,
             _session=lambda:SimpleNamespace(speech_override=None),_cur_source='yazı',flags={},_close_jarvis=Mock(),set_sleep=Mock())
        with patch.object(command_manager,'engine_control',return_value=None),patch.object(goals,'handle',return_value='Kayıtlı hedef sürüyor') as handle,patch.object(command_manager,'dispatch') as dispatch:
            self.assertEqual(engine_commands.handle(runtime,'sürdür'),'Kayıtlı hedef sürüyor')
        handle.assert_called_once_with(runtime,'sürdür');dispatch.assert_not_called()

    def test_unavailable_planner_delivers_bounded_literal_news_report_without_more_models(self):
        from modules import public_sources,service_store
        from datetime import datetime,timezone,timedelta
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        index='https://example.org/haberler';article='https://example.org/haber/ai-project'
        html='<article><h1>Yapay zekâ araştırması</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Üniversite yapay zekâ araştırma projesini duyurdu. Araştırmacılar bilimsel çalışmanın ayrıntılarını kamuoyuyla paylaştı.</p></article>'
        calls=[]
        def fetch(url):
            calls.append(url)
            body='<a href="/haber/ai-project">Yapay zeka araştırması</a>' if url==index else html
            return {'url':url,'body':body.encode(),'content_type':'text/html'}
        self.responses(self.plan('Kaynakları araştır','Rapor dosyası oluştur ve doğrula'),
                       self.tool('research',{'url':index}),RuntimeError('HTTP 429; no model available'))
        with patch.object(public_sources,'fetch',side_effect=fetch),patch.object(service_store,'ROOT',self.root/'services'),patch('modules.privacy.blocked',return_value=None):
            result=goals.run(self.runtime,'Türkiye yapay zekâ son gelişmelerini araştır ve rapor dosyası oluştur')
            job=goals.latest('alice');ident=job['id']
            self.assertEqual(self.ask.call_count,3)
            self.assertEqual(job['state'],'paused');self.assertTrue(all(g['state']=='pending' for g in job['goals']))
            self.assertIn('Kısmi rapor dosyası:',result)
            output=job['outputs'][job['partial_report']]
            self.assertTrue(goal_tools.verify(output,'alice'));text=Path(output['file']).read_text(encoding='utf-8')
            self.assertIn('Yapay zekâ',text);self.assertIn(day,text);self.assertIn('<'+article+'>',text)
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
                    result=goals.run(self.runtime,'Son bilim haberlerini araştır')
                job=goals.latest('alice');self.assertEqual(job['state'],expected,result)
                if expected=='paused':self.assertTrue(any('keşfiyle tamamlanamaz' in f for f in job['feedback']))

    def test_resume_reopens_old_news_goal_completed_with_only_search_evidence(self):
        from modules import public_data
        self.responses(self.plan('Haber bağlantılarını bul'),self.tool('data',{'operation':'sources'}),self.done('s1'))
        goals.run(self.runtime,'Son bilim haberlerini araştır');job=goals.latest('alice');ident=job['id']
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
            result=goals.run(self.runtime,'Sadece https://example.org/haberler yapay zekâ son 7 gün gelişmelerini araştır ve rapor dosyası oluştur')
            job=goals.latest('alice');out=job['outputs'][job['partial_report']]
            self.assertTrue(goal_tools.verify(out,'alice'));self.assertIn('Kısmi rapor dosyası:',result)
            text=Path(out['file']).read_text(encoding='utf-8')
            self.assertIn(day,text);self.assertNotIn('2099',text);self.assertNotIn('foreign.org',text)
            self.assertEqual(self.ask.call_count,3);self.assertEqual(job['state'],'paused')
            self.assertFalse(any(s['input'].get('operation')=='news_search' for s in job['steps']))
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
        self.assertEqual(run.call_count,1);self.assertEqual(len(job['steps']),2)


if __name__=='__main__':unittest.main()
