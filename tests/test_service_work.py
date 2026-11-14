import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from modules import service_store as store, outbox, publish_services as services, task_queue as queue, task_agents as agents, task_results, llm, browser_agent


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        for mod,name,sub in ((store,'ROOT','service'),(agents,'STORE','tasks'),(browser_agent,'STORE','browser'),
                             (services,'DATA_DIR','connections')):
            p=patch.object(mod,name,Path(self.tmp.name)/sub);p.start();self.addCleanup(p.stop)
        self.payload={'service':'gmail','destination':'friend@example.com','subject':'Hello','text':'Body'}
        self.receipt={'service':'gmail','destination':'friend@example.com','remote_id':'actual-id','scope':'provider_accepted'}

    def test_no_grant_waits_with_exact_preview_and_grant_is_destination_scoped(self):
        oid=outbox.prepare('alice',self.payload,'work')
        with patch.object(services,'send') as send:
            result=outbox.dispatch('alice',oid)
            self.assertEqual(result['state'],'approval');self.assertIn('Body',result['text']);send.assert_not_called()
            outbox.grant('alice','gmail','other@example.com')
            self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval');send.assert_not_called()
        outbox.grant('alice','gmail','friend@example.com')
        with patch.object(services,'send',return_value=self.receipt) as send:
            self.assertEqual(outbox.dispatch('alice',oid)['state'],'done')
            self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'done')
            send.assert_called_once()

    def test_same_work_key_cannot_change_payload_or_resend(self):
        oid=outbox.prepare('alice',self.payload,'key')
        self.assertEqual(oid,outbox.prepare('alice',self.payload,'key'))
        with self.assertRaises(ValueError):outbox.prepare('alice',{**self.payload,'text':'changed'},'key')
        with patch.object(services,'send',return_value=self.receipt):outbox.dispatch('alice',oid,approve=True)
        with patch.object(services,'send') as send:
            outbox.dispatch('alice',oid,approve=True);send.assert_not_called()

    def test_unknown_error_or_crash_never_replays(self):
        oid=outbox.prepare('alice',self.payload,'key')
        with patch.object(services,'send',side_effect=RuntimeError('token-secret-url')):
            self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'failed')
        self.assertEqual(outbox.get('alice',oid)['error'],'RuntimeError')
        with patch.object(services,'send') as send:
            outbox.dispatch('alice',oid,approve=True);send.assert_not_called()
        second=outbox.prepare('alice',self.payload,'second')
        with store.database('alice') as db:db.execute("UPDATE outbox SET state='sending' WHERE id=?",(second,))
        with patch.object(services,'send') as send:
            self.assertEqual(outbox.dispatch('alice',second,approve=True)['state'],'failed');send.assert_not_called()

    def test_payload_corruption_and_user_mismatch_block_before_call(self):
        oid=outbox.prepare('alice',self.payload,'key')
        with store.database('alice') as db:db.execute('UPDATE outbox SET payload=? WHERE id=?',(json.dumps({**self.payload,'text':'altered'}),oid))
        with patch.object(services,'send') as send:
            with self.assertRaises(ValueError):outbox.dispatch('alice',oid,approve=True)
            with self.assertRaises(PermissionError):outbox.dispatch('bob',oid,approve=True)
            send.assert_not_called()

    def test_cancel_and_expired_or_revoked_grants(self):
        oid=outbox.prepare('alice',self.payload,'key');outbox.cancel('alice',oid)
        with patch.object(services,'send') as send:
            self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'blocked');send.assert_not_called()
        oid=outbox.prepare('alice',self.payload,'key2');outbox.grant('alice','gmail','friend@example.com')
        outbox.revoke('alice','gmail','friend@example.com')
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
        with store.database('alice') as db:db.execute('INSERT INTO grants VALUES(?,?,?)',('gmail','friend@example.com',1))
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')

    def test_task_approval_is_bound_to_exact_job_and_receipt_is_rechecked(self):
        task={'id':'send','agent':'publish','input':self.payload}
        job=agents.execute('alice',[task]);self.assertEqual(job['state'],'approval')
        oid=job['outputs']['send']['id']
        with patch.object(services,'send',return_value=self.receipt) as send:
            with self.assertRaises(ValueError):agents.handle('alice','işlem onayla '+'0'*16)
            self.assertIn('done',agents.handle('alice','işlem onayla '+oid));send.assert_called_once()
        saved=agents.recent('alice');self.assertTrue(task_results.verify(saved['outputs']['send'],owner='alice'))
        saved['outputs']['send']['receipt']['remote_id']='forged'
        with self.assertRaises(ValueError):task_results.verify(saved['outputs']['send'],owner='alice')

    def test_queue_runs_once_and_restart_reuses_assigned_job(self):
        tasks=[{'id':'a','agent':'verify'}]
        qid=queue.enqueue('alice',tasks)
        def worker(owner,task,deps):return {'state':'done','text':'mock success'}
        with patch.object(agents,'worker',side_effect=worker) as work:
            queue.tick('alice');queue.tick('alice');work.assert_called_once()
        row=queue.rows('alice')[0];self.assertEqual(row['id'],qid);self.assertEqual(row['state'],'done')
        with store.database('alice') as db:db.execute("UPDATE queue SET state='running',lease=0 WHERE id=?",(qid,))
        with patch.object(agents,'worker') as work:
            queue.tick('alice');work.assert_not_called()
        self.assertEqual(queue.rows('alice')[0]['state'],'done')

    def test_queue_future_lease_cancel_and_external_effect_rejection(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}],delay=3600)
        with patch.object(agents,'worker') as work:
            queue.tick('alice');work.assert_not_called()
        queue.cancel('alice',qid);self.assertEqual(queue.rows('alice')[0]['state'],'cancelled')
        with self.assertRaises(ValueError):queue.enqueue('alice',[{'id':'a','agent':'publish','input':self.payload}])
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        with store.database('alice') as db:db.execute("UPDATE queue SET state='running',lease=? WHERE id=?",(time.time()+90,qid))
        with patch.object(agents,'worker') as work:
            queue.tick('alice');work.assert_not_called()

    def test_queue_cancel_race_before_first_worker_is_respected(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        original=agents.execute
        def execute(*args,**kwargs):
            queue.cancel('alice',qid)
            return original(*args,**kwargs)
        with patch.object(agents,'execute',side_effect=execute),patch.object(agents,'worker') as work:
            queue.tick('alice');work.assert_not_called()
        self.assertEqual(queue.rows('alice')[0]['state'],'cancelled')

    def test_queue_owner_busy_race_waits_and_reuses_assigned_job(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        assigned=queue.rows('alice')[0]['job_id'];original=agents.execute
        def execute(*args,**kwargs):
            with agents._active('alice'):return original(*args,**kwargs)
        notify=Mock()
        with patch.object(agents,'execute',side_effect=execute),patch.object(agents,'worker') as work:
            queue.tick('alice',notify);work.assert_not_called()
        row=queue.rows('alice')[0]
        self.assertEqual(row['state'],'queued');self.assertEqual(row['job_id'],assigned)
        notify.assert_not_called()
        with store.database('alice') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_runs').fetchone()[0],0)
        with patch.object(agents,'worker',return_value={'state':'done','text':'success'}) as work:
            queue.tick('alice');queue.tick('alice');work.assert_called_once()
        row=queue.rows('alice')[0]
        self.assertEqual(row['state'],'done');self.assertEqual(row['job_id'],assigned)

    def test_queue_resume_busy_race_does_not_repeat_completed_work(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        assigned=queue.rows('alice')[0]['job_id']
        with patch.object(agents,'worker',return_value={'state':'done','text':'success'}):
            agents.execute('alice',[{'id':'a','agent':'verify'}],job_id=assigned,queue_id=qid)
        with store.database('alice') as db:
            db.execute("UPDATE queue SET state='running',lease=0 WHERE id=?",(qid,))
        original=agents.continue_job
        def resume(*args,**kwargs):
            with agents._active('alice'):return original(*args,**kwargs)
        with patch.object(agents,'continue_job',side_effect=resume):queue.tick('alice')
        self.assertEqual(queue.rows('alice')[0]['state'],'queued')
        with patch.object(agents,'worker') as work:
            queue.tick('alice');work.assert_not_called()
        self.assertEqual(queue.rows('alice')[0]['state'],'done')

    def test_queue_busy_retry_does_not_revive_cancelled_work(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        original=agents.execute
        def execute(*args,**kwargs):
            queue.cancel('alice',qid)
            with agents._active('alice'):return original(*args,**kwargs)
        notify=Mock()
        with patch.object(agents,'execute',side_effect=execute),patch.object(agents,'worker') as work:
            queue.tick('alice',notify);work.assert_not_called()
        self.assertEqual(queue.rows('alice')[0]['state'],'cancelled');notify.assert_not_called()

    def test_queue_recovery_rejects_changed_plan_before_any_worker(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'research','input':{'url':'https://example.com'}}])
        assigned=queue.rows('alice')[0]['job_id']
        for task in ({'id':'a','agent':'publish','input':self.payload},
                     {'id':'a','agent':'research','input':{'url':'https://other.example.com'}},
                     {'id':'other','agent':'research','input':{'url':'https://example.com'}}):
            saved={'id':assigned,'state':'interrupted','queue_id':qid,
                   'tasks':[{**task,'state':'queued'}],'outputs':{}}
            # Model an external writer which first reads the *current*
            # journal. A blind stale overwrite is correctly rejected now.
            path=agents._job_path(agents._root('alice'),assigned)
            if path.exists():
                saved[agents._JOURNAL_FENCE]=agents._load('alice',assigned)[agents._JOURNAL_FENCE]
            agents._save(agents._root('alice'),saved)
            with store.database('alice') as db:
                db.execute("UPDATE queue SET state='running',lease=0 WHERE id=?",(qid,))
            with patch.object(agents,'worker',return_value={'state':'done'}) as work:
                queue.tick('alice');work.assert_not_called()
            self.assertEqual(queue.rows('alice')[0]['state'],'blocked')

    def test_queue_recovery_rejects_journal_from_another_queue(self):
        qid=queue.enqueue('alice',[{'id':'a','agent':'verify'}])
        other=queue.enqueue('alice',[{'id':'a','agent':'verify'}],delay=3600)
        assigned=next(r['job_id'] for r in queue.rows('alice') if r['id']==qid)
        agents._save(agents._root('alice'),{'id':assigned,'state':'interrupted','queue_id':other,
                       'tasks':[{'id':'a','agent':'verify','state':'queued'}],'outputs':{}})
        with patch.object(agents,'worker',return_value={'state':'done'}) as work:
            queue.tick('alice');work.assert_not_called()
        self.assertEqual(next(r['state'] for r in queue.rows('alice') if r['id']==qid),'blocked')

    def test_queue_recovery_rejects_changed_dependency_before_completed_or_new_steps(self):
        tasks=[{'id':'a','agent':'research','input':{'url':'https://example.com'}},
               {'id':'b','agent':'writer','input':{'instruction':'report'},'depends':['a']}]
        qid=queue.enqueue('alice',tasks);assigned=queue.rows('alice')[0]['job_id']
        changed=[dict(tasks[0],state='queued'),dict(tasks[1],state='queued',depends=[])]
        for state in ('interrupted','done'):
            saved={'id':assigned,'state':state,'queue_id':qid,
                   'tasks':changed,'outputs':{}}
            path=agents._job_path(agents._root('alice'),assigned)
            if path.exists():
                saved[agents._JOURNAL_FENCE]=agents._load('alice',assigned)[agents._JOURNAL_FENCE]
            agents._save(agents._root('alice'),saved)
            with store.database('alice') as db:
                db.execute("UPDATE queue SET state='running',lease=0 WHERE id=?",(qid,))
            with patch.object(agents,'worker',return_value={'state':'done'}) as work:
                queue.tick('alice');work.assert_not_called()
            self.assertEqual(queue.rows('alice')[0]['state'],'blocked')

    def test_adapter_gmail_mime_and_telegram_remote_identity(self):
        svc=Mock();svc.users.return_value.messages.return_value.send.return_value.execute.return_value={'id':'mail-id'}
        with patch.object(services,'google_service',return_value=svc),patch.object(services.privacy,'blocked',return_value=None):
            receipt=services.send('alice',self.payload,lambda _:None)
        self.assertEqual(receipt['remote_id'],'mail-id')
        body=svc.users.return_value.messages.return_value.send.call_args.kwargs['body']
        self.assertIn(b'To: friend@example.com',base64.urlsafe_b64decode(body['raw']))
        with patch.object(services,'configuration',return_value={'bot_token':'123:fake'}),patch.object(services,'_http',return_value={'ok':True,'result':{'message_id':5,'chat':{'id':-123}}}),patch.object(services.privacy,'blocked',return_value=None):
            result=services.send('alice',{'service':'telegram','destination':'-123','text':'Hi'},lambda _:None)
        self.assertEqual(result['remote_id'],'5')

    def test_meta_progress_and_whatsapp_costs_gate(self):
        from modules import social_reads
        config={'api_version':'v26.0','access_token':'secret','ig_user_id':'123'}
        progress=Mock()
        with patch.object(services,'configuration',return_value=config),patch.object(services,'_http',side_effect=[{'id':'10'},{'id':'20'}]) as http,patch.object(services.privacy,'blocked',return_value=None),patch.object(social_reads,'_get',return_value={'status_code':'FINISHED'}):
            result=services.send('alice',{'service':'instagram','destination':'123','text':'Caption','image_url':'https://example.com/image.jpg'},progress)
        self.assertEqual(result['remote_id'],'20');progress.assert_called_once_with({'container_id':'10'})
        with patch.object(services,'configuration',return_value=config),patch.object(services,'_http',return_value={'id':'10'}) as http,patch.object(services.privacy,'blocked',return_value=None),patch.object(social_reads,'_get',return_value={'status_code':'IN_PROGRESS'}):
            with self.assertRaises(RuntimeError):services.send('alice',{'service':'instagram','destination':'123','text':'Caption','image_url':'https://example.com/image.jpg'},progress)
            self.assertEqual(http.call_count,1)
        with patch.object(services,'configuration',return_value={**config,'phone_number_id':'123'}),patch.object(services,'_http') as http,patch.object(services.privacy,'blocked',return_value=None):
            with self.assertRaises(PermissionError):services.send('alice',{'service':'whatsapp','destination':'905001234567','text':'Hi'},lambda _:None)
            http.assert_not_called()

    def test_bad_destination_and_header_injection_rejected(self):
        for update in ({'destination':'Hamdi'},{'destination':'a@example.com\r\nBcc:b@example.com'}, {'subject':'x\r\ny'}, {'text':''}):
            with self.assertRaises(ValueError):services.validate({**self.payload,**update})

    def test_transport_diagnostics_do_not_leak_telegram_token_path(self):
        import requests
        token='123456:PRIVATE_TELEGRAM_SECRET'
        with patch.object(requests,'post',side_effect=RuntimeError('https://api.telegram.org/bot'+token+'/sendMessage')),self.assertLogs('jarvis',level='ERROR') as logs:
            with self.assertRaises(RuntimeError):services._http('https://api.telegram.org/bot'+token+'/sendMessage',{})
        self.assertNotIn(token,' '.join(logs.output))

    def test_standing_grant_does_not_auto_share_known_sensitive_text(self):
        outbox.grant('alice','gmail','friend@example.com')
        oid=outbox.prepare('alice',{**self.payload,'text':'IBAN: TR120006200000123456789012'},'sensitive')
        with patch.object(services,'send') as send:
            self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval');send.assert_not_called()

    def test_accepted_outbox_recovers_task_after_crash_without_resending(self):
        job=agents.execute('alice',[{'id':'send','agent':'publish','input':self.payload}])
        oid=job['outputs']['send']['id']
        with patch.object(services,'send',return_value=self.receipt):outbox.dispatch('alice',oid,approve=True)
        job['state']='interrupted';job['tasks'][0]['state']='interrupted';agents._save(agents._root('alice'),job)
        with patch.object(services,'send') as send:
            restored=agents.continue_job('alice',job['id']);send.assert_not_called()
        self.assertEqual(restored['state'],'done')

    def test_youtube_upload_checks_channel_and_local_file_digest(self):
        from modules import nxapi
        root=Path(self.tmp.name)/'videos';root.mkdir();video=root/'video.mp4';video.write_bytes(b'local-video')
        data={'service':'youtube','destination':'UC'+'a'*22,'file':str(video),'file_sha256':task_results.file_digest(video),
              'subject':'Title','text':'Description','privacy':'private'}
        svc=Mock();svc.channels.return_value.list.return_value.execute.return_value={'items':[{'id':data['destination']}]}
        svc.videos.return_value.insert.return_value.next_chunk.return_value=(None,{'id':'video-id'})
        with patch.object(nxapi,'FILES_DIR',root),patch.object(services,'configuration',return_value={'channel_id':data['destination']}),patch.object(services,'google_service',return_value=svc),patch.object(services.privacy,'blocked',return_value=None),patch.object(services,'media_upload',return_value=Mock()) as upload:
            self.assertEqual(services.send('alice',data,lambda _:None)['remote_id'],'video-id')
            upload.assert_called_once_with(video,'video/mp4')
            svc.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'wrong'}]}
            svc.videos.reset_mock()
            with self.assertRaises(PermissionError):services.send('alice',data,lambda _:None)
            svc.videos.assert_not_called()


if __name__=='__main__':unittest.main()
