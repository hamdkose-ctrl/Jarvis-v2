"""Real receipt, file, Core and rendering seams; no provider/device effects."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_engine_modular  # noqa: F401
from modules import goal_executor, goal_tools, task_agents, task_results


class ResultDeliveryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)

    def writer(self,text='Doğrulanmış rapor'):
        path=self.root/'report.md';path.write_text(text,encoding='utf-8')
        return task_results.seal('writer',{'state':'done','text':text,'file':str(path),'sha256':task_results.file_digest(path)})

    def task_job(self,output,state='done'):
        return {'owner':'alice','id':'delivery','state':state,'tasks':[
            {'id':'s1','agent':'writer','state':'done','depends':[],'input':{}}], 'outputs':{'s1':output}}

    def goal_job(self,output):
        return {'owner':'alice','id':'delivery','request':'Rapor oluştur','state':'done',
                'steps':[{'id':'s1','tool':'writer','state':'done','input':{},'goal':0,'depends':[]}],
                'goals':[{'text':'Rapor','state':'done','evidence':['s1']}],'outputs':{'s1':output}}

    def test_task_summary_does_not_claim_deleted_artifact_is_ready(self):
        output=self.writer();job=self.task_job(output)
        Path(output['file']).unlink();before=deepcopy(job)
        reply=task_agents.render_summary(job)
        self.assertNotIn('Dosya: '+output['file'],reply)
        self.assertIn('doğrulanamadı',reply)
        self.assertEqual(job,before)

    def test_goal_render_does_not_show_stale_success_or_artifact(self):
        output=self.writer();job=self.goal_job(output)
        Path(output['file']).write_text('changed',encoding='utf-8')
        reply=goal_executor.render(job)
        self.assertNotIn('✓ Rapor',reply);self.assertNotIn('Dosya: '+output['file'],reply)
        self.assertIn('doğrulanamadı',reply)
        self.assertEqual(job['state'],'done','presentation cannot change lifecycle')

    def test_empty_inbox_does_not_hide_a_later_failure(self):
        job={'owner':'alice','id':'delivery','state':'incomplete','tasks':[
            {'id':'mail','agent':'account','state':'done','depends':[],'input':{}},
            {'id':'write','agent':'writer','state':'failed','depends':['mail'],'input':{}}],
            'outputs':{'mail':{'state':'done','snapshot':{'operation':'list_unread','items':[]}},
                       'write':{'state':'failed','text':'Rapor diske yazılamadı.'}}}
        reply=task_agents.render_summary(job)
        self.assertIn('Rapor diske yazılamadı',reply);self.assertIn('tamamlanmadı',reply)

    def test_failed_child_does_not_hide_verified_parent_partial_result(self):
        output=self.writer();job=self.task_job(output,state='incomplete')
        job['tasks'].append({'id':'child','agent':'publish','state':'failed','depends':['s1'],'input':{}})
        job['outputs']['child']={'state':'failed','text':'Gönderim başarısız.'}
        reply=task_agents.render_summary(job)
        self.assertIn('Doğrulanmış rapor',reply);self.assertIn('Gönderim başarısız',reply)
        self.assertIn('Dosya: '+output['file'],reply)

    def test_missing_or_wrong_kind_receipt_is_not_a_success(self):
        output=self.writer();output['verification']['agent']='verify';output['checks']={'fake':True}
        with self.assertRaises(ValueError):task_results.verify(output,owner='alice',expected_kind='writer')
        reply=task_agents.render_summary(self.task_job({'state':'done','text':'İşi yaptım.'}))
        self.assertNotIn('İşi yaptım',reply);self.assertIn('doğrulanamadı',reply)

    def test_status_progress_counts_current_verified_outputs(self):
        output=self.writer();job=self.goal_job(output)
        Path(output['file']).unlink()
        reply=goal_executor.status_summary(job)
        self.assertIn('0/1',reply);self.assertNotIn(output['file'],reply)
        self.assertIn('doğrulanamadı',reply)

    def test_partial_report_path_needs_the_same_file_evidence(self):
        output=self.writer();job=self.goal_job(output)
        job['state']='paused';job['goals'][0].update(state='pending',evidence=[])
        job['partial_report']='s1';Path(output['file']).unlink()
        reply=goal_executor.render(job)
        self.assertNotIn('Kısmi rapor dosyası: '+output['file'],reply)

    def test_malformed_legacy_steps_are_unavailable_without_a_render_crash(self):
        from modules import result_presentation
        job=self.goal_job(self.writer())
        job['steps']=[{'state':'done'},None,{'id':'missing-state'}]
        before=deepcopy(job)
        checked=result_presentation.inspect_job(job,'goal')
        self.assertEqual(checked['verified'],frozenset())
        self.assertEqual(checked['job']['state'],'incomplete')
        self.assertIn('doğrulanamadı',goal_executor.render(job))
        self.assertEqual(job,before)

    def test_orphan_output_cannot_leak_an_artifact_or_a_source_into_progress(self):
        from modules import result_presentation
        job=self.goal_job(self.writer())
        job['outputs']['orphan']={'state':'done','file':'SECRET-report.md',
            'news_article':{'url':'https://secret.example/hidden'},'text':'UNPROVED BODY'}
        checked=result_presentation.inspect_job(job,'goal')
        self.assertIn('orphan',checked['unverified'])
        self.assertEqual(checked['job']['outputs']['orphan'],
                         {'state':'unavailable','text':result_presentation.UNVERIFIED})
        reply=goal_executor.status_summary(job)+goal_executor.render(job)
        for secret in ('SECRET-report.md','secret.example','UNPROVED BODY'):
            self.assertNotIn(secret,reply)

    def test_completed_goal_keeps_verified_replacement_after_a_failed_attempt(self):
        from modules import result_presentation
        job=self.goal_job(self.writer())
        job['steps'].insert(0,{'id':'old','tool':'research','state':'failed',
                              'input':{},'goal':0,'depends':[]})
        job['outputs']['old']={'state':'failed','text':'İlk kaynak yanıt vermedi.'}
        before=deepcopy(job)
        checked=result_presentation.inspect_job(job,'goal')
        self.assertEqual(checked['job']['state'],'done')
        self.assertEqual(checked['verified'],frozenset({'s1'}))
        self.assertIn('1/2',goal_executor.status_summary(job))
        self.assertEqual(job,before)

    def test_short_presentation_keeps_complete_file_identity_and_discloses_truncation(self):
        from modules import result_presentation
        output=self.writer('Kaynak metni. '*350);job=self.task_job(output)
        with patch.object(result_presentation,'style_snapshot',return_value={'version':'jarvis-response.v1','verbosity':'kısa'}):
            reply=task_agents.render_summary(job)
        self.assertLess(len(reply),1500);self.assertIn(output['file'],reply)
        self.assertIn('devamı',reply)

    def test_unverified_native_pc_done_flag_is_not_a_receipt(self):
        output=goal_tools.local_result('alice','desktop','İşlem yapıldı.',desktop_id='pc1',
                    receipt={'service':'desktop_uia','remote_id':'pc1'})
        with self.assertRaises(ValueError):goal_tools.verify(output,'alice')

    def test_foreign_account_content_is_not_delivered(self):
        from modules import account_tools
        snapshot={'service':'gmail','operation':'list_unread','owner':'bob','query':'is:unread in:inbox',
                  'limit':3,'items':[{'id':'m1','from':'private','subject':'FOREIGN SECRET'}],
                  'fetched_at':1.,'has_more':False}
        output=task_results.seal('account',{'state':'done','snapshot':snapshot,
                  'text':account_tools.render_snapshot(snapshot),'sha256':account_tools.digest(snapshot)})
        job=self.task_job(output);job['tasks'][0]['agent']='account'
        reply=task_agents.render_summary(job)
        self.assertNotIn('FOREIGN SECRET',reply);self.assertIn('doğrulanamadı',reply)

    def test_research_claim_cannot_disagree_with_its_literal_value_quote(self):
        with self.assertRaises(ValueError):
            task_results.seal('research',{'state':'done','text':'Claim','source':'https://example.com',
                'source_chars':200,'source_quotes':['Resmi raporda toplam 12 görev tamamlandığı açıklandı.'],
                'source_claims':[{'subject':'görev','value':'999','url':'https://example.com',
                    'scope':'','as_of':'','evidence':'Resmi raporda toplam 12 görev tamamlandığı açıklandı.'}]})

    def test_waiting_reason_and_unknown_are_distinct_from_success(self):
        output=self.writer();job=self.goal_job(output)
        job['state']='review';job['blocker']='Dış işlemin sonucu belirsiz; yeniden gönderilmedi.'
        reply=goal_executor.status_summary(job)
        self.assertIn('sonucu belirsiz',reply);self.assertIn('Bekleme nedeni:',reply)
        self.assertIn('yeniden gönderilmedi',reply)

    def test_complete_gate_rejects_a_receipt_for_a_different_tool(self):
        job=self.goal_job(task_results.seal('verify',{'state':'done','checks':{'fake':True}}))
        with self.assertRaises(ValueError):goal_executor._finish_completed(job)

    def test_native_pc_snapshot_keeps_historical_verified_steps_without_replaying_device(self):
        native={'owner':'alice','id':'native1','target':'Calculator','goal':'12 + 7','status':'done',
                'history':[{'op':'invoke','verified':True}]}
        output=goal_tools._desktop_result('alice',native,'Sonuç 19.')
        self.assertTrue(goal_tools.verify(output,'alice',kind='desktop',data={'target':'Calculator','goal':'12 + 7'}))
        native['history'][0]['verified']=False
        self.assertTrue(goal_tools.verify(output,'alice'))
        output['desktop_evidence']['history'][0]['verified']=False
        with self.assertRaises(ValueError):goal_tools.verify(output,'alice')

    def test_changed_dependency_cannot_leave_a_boolean_verifier_success(self):
        output=self.writer();job=self.task_job(output)
        job['tasks'].append({'id':'check','agent':'verify','state':'done','depends':['s1'],'input':{}})
        job['outputs']['check']=task_results.seal('verify',{'state':'done','checks':{'s1':True}})
        Path(output['file']).unlink()
        from modules import result_presentation
        checked=result_presentation.inspect_job(job,'task')
        self.assertEqual(checked['verified'],frozenset())
        self.assertEqual(checked['job']['state'],'incomplete')

    def test_publish_receipt_is_read_back_from_real_outbox_without_resending(self):
        import test_service_work as fixture
        from modules import outbox,publish_services
        case=fixture.WorkTests();case.setUp();self.addCleanup(case.doCleanups)
        oid=outbox.prepare('alice',case.payload,'b10-proof')
        with patch.object(publish_services,'send',return_value=case.receipt) as send:
            output=task_results.seal('publish',outbox.dispatch('alice',oid,approve=True))
        job=self.task_job(output);job['tasks'][0]['agent']='publish'
        with patch.object(publish_services,'send',side_effect=AssertionError('delivery resent')):
            self.assertNotIn('doğrulanamadı',task_agents.render_summary(job))
            output['receipt']['destination']='other@example.com'
            job['outputs']['s1']=output
            self.assertIn('doğrulanamadı',task_agents.render_summary(job))
        self.assertEqual(send.call_count,1)

    def test_reversed_verifier_chain_cannot_hide_a_missing_source_artifact(self):
        from modules import result_presentation
        output=self.writer();job=self.task_job(output)
        for ident,dep in (('check2','check1'),('check1','s1')):
            job['tasks'].append({'id':ident,'agent':'verify','state':'done','depends':[dep],'input':{}})
            job['outputs'][ident]=task_results.seal('verify',{'state':'done','checks':{dep:True}})
        Path(output['file']).unlink()
        checked=result_presentation.inspect_job(job,'task')
        self.assertEqual(checked['verified'],frozenset())
        self.assertEqual(checked['unverified'],frozenset({'s1','check1','check2'}))
        self.assertEqual(checked['job']['state'],'incomplete')


    def test_ui_projection_downgrades_missing_evidence_without_changing_control_identity(self):
        from modules import team_center
        output=self.writer();job=self.goal_job(output);before=deepcopy(job)
        control=goal_executor.control_key(job)
        Path(output['file']).unlink()
        view=team_center._job('alice',job,'goal')
        self.assertEqual(view['state'],'incomplete');self.assertEqual(view['record_state'],'done')
        self.assertEqual(view['control'],control)
        self.assertEqual(view['steps'][0]['artifacts'],[])
        self.assertFalse(view['steps'][0]['has_receipt'])
        self.assertIn('doğrulanamadı',view['question'])
        self.assertEqual(job,before)


class FrozenResultTests(unittest.TestCase):
    def accepted(self):
        import test_brain_07_typed_canonical_e2e as fixture
        case=fixture.TypedCanonicalFlowTests();case.setUp();self.addCleanup(case.doCleanups)
        return case,case._accepted_canonical_research_for_crash_test()

    def test_accepted_core_output_hash_binds_progress_and_hides_tampered_text(self):
        from modules import execution_record
        case,job_id=self.accepted();root=goal_executor._owner_root(case.owner)
        job=execution_record.load(root,case.owner,job_id)
        job['outputs']['first']['text']='UNCOMMITTED SOURCE SECRET'
        reply=goal_executor.render(job)
        self.assertNotIn('UNCOMMITTED SOURCE SECRET',reply);self.assertIn('doğrulanamadı',reply)

    def test_completed_read_uses_frozen_style_and_does_not_redecide_completion(self):
        from modules import canonical_goal_flow,result_presentation,execution_record
        case,job_id=self.accepted();sink=Mock(return_value={'ui':'delivered'})
        with patch.object(canonical_goal_flow,'_semantic_proposal',return_value={
                'action':'complete','goal':0,'evidence':['first']}):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(case.owner,job_id,sink))
        before=execution_record.load(goal_executor._owner_root(case.owner),case.owner,job_id)
        with patch.object(result_presentation,'style_snapshot',side_effect=AssertionError('new style read')), \
             patch.object(goal_executor,'_check_news_completion',side_effect=AssertionError('new completion decision')):
            reply=canonical_goal_flow.read_completed_result(case.owner,job_id)
        self.assertIn('Verified crash-safe source',reply)
        self.assertEqual(execution_record.load(goal_executor._owner_root(case.owner),case.owner,job_id),before)
        self.assertEqual(sink.call_count,1)

    def test_finished_canonical_cache_cannot_replace_the_accepted_result(self):
        import test_brain_07_typed_canonical_e2e as fixture
        from modules import canonical_goal_flow,execution_record
        case=fixture.TypedCanonicalFlowTests();case.setUp();self.addCleanup(case.doCleanups)
        job_id=case._accepted_canonical_research_for_crash_test()
        sink=Mock(return_value={'ui':'delivered'})
        with patch.object(canonical_goal_flow,'_semantic_proposal',return_value={
                'action':'complete','goal':0,'evidence':['first']}):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(case.owner,job_id,sink))
        root=goal_executor._owner_root(case.owner)
        journal=execution_record.load(root,case.owner,job_id)
        journal['_canonical_result_text']='FORGED DONE SENT AN EMAIL'
        canonical_goal_flow.release_guard.atomic(execution_record.path_for(root,job_id),execution_record.encode(journal))
        with self.assertRaises(ValueError):canonical_goal_flow.read_completed_result(case.owner,job_id)
        self.assertEqual(sink.call_count,1,'read cannot resend')


if __name__=='__main__':unittest.main()
