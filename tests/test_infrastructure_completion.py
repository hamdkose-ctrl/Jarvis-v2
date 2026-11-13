import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from modules import personalization as profiles,learning,pc_contracts as pc,task_workflows as flows,task_agents as agents,llm,requests_state

class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for obj,key,value in ((profiles,'USERS_DIR',self.root/'users'),(pc,'ROOT',self.root/'pc'),(agents,'STORE',self.root/'tasks')):
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        (self.root/'users').mkdir()
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)

    def test_memory_changes_exact_owner_and_shared_handles(self):
        alice=profiles.Profile('Alice');same=profiles.Profile('Alice');bob=profiles.Profile('Bob')
        alice.add_fact('Eski bilgi');bob.add_fact('Eski bilgi')
        self.assertTrue(alice.edit_fact(0,'Eski bilgi','Yeni bilgi'))
        self.assertEqual(same.data['facts'],['Yeni bilgi']);self.assertEqual(bob.data['facts'],['Eski bilgi'])
        with self.assertRaises(ValueError):alice.edit_fact(0,'Eski bilgi','Başka bilgi')
        self.assertTrue(alice.edit_fact(0,'Yeni bilgi',None));self.assertEqual(alice.data['facts'],[])

    def test_screen_share_spelling_routes_to_existing_share_control(self):
        import re
        from types import SimpleNamespace
        from modules import engine_context
        from modules.session_state import SessionState
        control=Mock(return_value='paylaşım sonucu')
        runtime=SimpleNamespace(re=re,set_share=control,_session=lambda:SessionState())
        for text in ('ekran paylaşımını aç','ekran paylasımını aç','ekran paylasimini aç'):
            self.assertEqual(engine_context._user_controls(runtime,text,text),'paylaşım sonucu')
            control.assert_called_with('screen')
        engine_context._user_controls(runtime,'ekran paylasimini kapat','ekran paylasimini kapat')
        control.assert_called_with(None)

    def test_queue_status_uses_human_schedule_and_named_action(self):
        from modules import task_queue
        row={'id':'q1','job_id':'j1','state':'queued','due':100,'repeat_seconds':0,'instruction':'Gmail başlıklarını listele'}
        with patch.object(task_queue.time,'time',return_value=40):text=task_queue.render_rows([row])
        self.assertIn('Gmail başlıklarını listele',text);self.assertIn('60 saniye sonra',text)
        self.assertNotIn('queued',text);self.assertIn('kuyruk iptal q1',text)

    def test_memory_disk_failure_does_not_change_live_memory(self):
        p=profiles.Profile('Alice');p.add_fact('Eski bilgi')
        with patch.object(p,'save',side_effect=OSError('disk')):
            for value in ('Yeni bilgi',None):
                with self.assertRaises(OSError):p.edit_fact(0,'Eski bilgi',value)
                self.assertEqual(p.data['facts'],['Eski bilgi'])

    def test_memory_commands_exact_selection_and_no_model(self):
        p=profiles.Profile('Alice');p.add_fact('Motor gücü 5 kW')
        with patch.object(llm,'ask',side_effect=AssertionError('model')):
            self.assertIn('5 kW',learning.execute_typed(p, {'operation':'facts.list'}))
            learning.execute_typed(p, {'operation':'fact.edit','old':'Motor gücü 5 kW','text':'Motor gücü 7 kW'})
            self.assertEqual(p.data['facts'],['Motor gücü 7 kW'])
            learning.execute_typed(p, {'operation':'fact.forget','old':'Motor'})
            self.assertEqual(p.data['facts'],['Motor gücü 7 kW'])
            learning.execute_typed(p, {'operation':'fact.forget','old':'Motor gücü 7 kW'})
            self.assertEqual(p.data['facts'],[])

    def test_pc_invalid_input_and_foreign_request_do_not_execute(self):
        target=Mock()
        for action,args,kwargs in (('set_volume',(True,),{}),('window_action',('window','shell'),{}),
                                   ('open_application',('app',),{'shell':'secret'})):
            with self.assertRaises(ValueError):pc.call(action,target,args,kwargs)
        token=requests_state._current.set(('bob','r1'))
        try:
            with self.assertRaises(PermissionError):pc.call('set_volume',target,(10,),{},owner='alice')
        finally:requests_state._current.reset(token)
        target.assert_not_called()

    def test_pc_persistent_evidence_omits_input_and_failures_never_verify(self):
        result=pc.call('open_application',lambda name:'could not open SECRET',('SECRET',),{})
        self.assertIn('SECRET',result);record=pc.last_result();self.assertEqual(record['state'],'failed')
        saved=(self.root/'pc'/'alice.json').read_text();self.assertNotIn('SECRET',saved)
        self.assertFalse(record['replay_safe'])
        with self.assertRaises(OSError):pc.call('set_mute',Mock(side_effect=OSError()),(True,),{})
        self.assertEqual(pc.last_result()['state'],'failed')

    def test_pc_record_failure_stops_before_physical_operation(self):
        target=Mock()
        with patch.object(pc.os,'replace',side_effect=OSError('disk')):
            with self.assertRaises(OSError):pc.call('set_volume',target,(30,),{})
        target.assert_not_called()

    def test_shutdown_evidence_only_claims_dispatch(self):
        pc.call('shutdown_pc',lambda:True,(),{})
        self.assertEqual(pc.last_result()['scope'],'dispatch_only')
        for value in (None,0,False,'accepted'):
            pc.call('cancel_shutdown',lambda:value,(),{})
            self.assertEqual(pc.last_result()['state'],'failed')

    def test_workflows_use_existing_roles_and_no_planner_call(self):
        with patch.object(llm,'ask',side_effect=AssertionError('planner')):
            report=flows.build('rapor','https://example.com | Türkçe rapor')
            mail=flows.build('mail','M1 | kısa cevap taslağı')
            code=flows.build('kod','Hesaplama hatasını düzelt')
        self.assertEqual([t['agent'] for t in report],['research','writer','verify'])
        self.assertEqual([t['agent'] for t in mail],['account','writer','verify'])
        self.assertEqual([t['agent'] for t in code],['coder','verify'])
        for tasks in (report,mail,code):self.assertNotIn('publish',[t['agent'] for t in tasks])
        for kind,value in (('rapor','file:///etc/passwd | report'),('mail','person@example.com'),('rapor','missing separator')):
            with self.assertRaises(ValueError):flows.build(kind,value)

    def test_workflow_failure_blocks_writer_and_verifier(self):
        tasks=flows.build('rapor','https://example.com | report')
        with patch.object(agents,'worker',side_effect=ValueError('offline')) as worker:
            job=agents.execute('alice',tasks)
        worker.assert_called_once();self.assertEqual(job['state'],'incomplete')
        self.assertEqual([t['state'] for t in job['tasks']],['failed','blocked','blocked'])

    def test_acceptance_does_not_contact_accounts_or_hardware_by_default(self):
        from modules import acceptance_checks as acceptance,account_tools,service_health
        import updater
        with patch.object(updater,'verify_sync',return_value={'sync_state':'synced'}),patch.object(service_health,'report',return_value='safe'),patch.object(account_tools,'run') as accounts:
            report=acceptance.run(suite=False)
        accounts.assert_not_called()
        checks={r['check']:r['state'] for r in report['checks']}
        self.assertEqual(checks['gmail_attachment'],'pending');self.assertEqual(checks['calculator'],'pending')
        self.assertEqual(checks['wake_word_microphone'],'pending')

    def test_acceptance_cannot_reuse_previous_success_when_new_task_is_rejected(self):
        from modules import acceptance_checks as acceptance,service_health,desktop_agent
        from types import SimpleNamespace
        import updater,modules,sys
        old={'id':'old','status':'done'}
        control=SimpleNamespace(open_application=Mock(return_value=SimpleNamespace(ok=True)))
        with patch.dict(sys.modules,{'modules.system_control':control}),patch.object(modules,'system_control',control,create=True),patch.object(updater,'verify_sync',return_value={'sync_state':'synced'}),patch.object(service_health,'report',return_value='safe'),patch.object(acceptance.platform,'system',return_value='Windows'),patch.object(desktop_agent,'_BUSY',Mock(locked=Mock(return_value=False))),patch.object(desktop_agent,'_load',side_effect=[old,old]),patch.object(desktop_agent,'handle',return_value='busy'):
            report=acceptance.run(suite=False,desktop=True)
        self.assertEqual(next(r['state'] for r in report['checks'] if r['check']=='calculator'),'pending')

    def test_acceptance_uses_actual_new_desktop_identity_for_success(self):
        from modules import acceptance_checks as acceptance,service_health,desktop_agent
        from types import SimpleNamespace
        import updater,modules,sys
        control=SimpleNamespace(open_application=Mock(return_value=SimpleNamespace(ok=True)))
        def complete(job,**kwargs):
            job['status']='done';desktop_agent._save(job);return 'verified'
        with patch.dict(sys.modules,{'modules.system_control':control}),patch.object(modules,'system_control',control,create=True),patch.object(updater,'verify_sync',return_value={'sync_state':'synced'}),patch.object(service_health,'report',return_value='safe'),patch.object(acceptance.platform,'system',return_value='Windows'),patch.object(profiles,'get_active',return_value='Alice'),patch.object(desktop_agent,'STORE',self.root/'desktop'),patch.object(desktop_agent,'run',side_effect=complete):
            desktop_agent._save({'owner':'alice','status':'done','history':[]})
            report=acceptance.run(suite=False,desktop=True)
            first=desktop_agent._load('alice')['id']
            self.assertEqual(len(first),32)
            self.assertEqual(next(r['state'] for r in report['checks'] if r['check']=='calculator'),'passed')
            report=acceptance.run(suite=False,desktop=True)
            self.assertNotEqual(desktop_agent._load('alice')['id'],first)
            self.assertEqual(next(r['state'] for r in report['checks'] if r['check']=='calculator'),'passed')

if __name__=='__main__':unittest.main()
