import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import Mock, patch
from modules import media_tools, task_results, account_tools, social_reads, publish_services, task_agents, llm, nxapi, service_store, task_queue


class MediaSocialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        for module,name,path in ((nxapi,'FILES_DIR',self.root),(task_agents,'STORE',self.root/'tasks'),(service_store,'ROOT',self.root/'service')):
            p=patch.object(module,name,path);p.start();self.addCleanup(p.stop)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg unavailable')
    def test_real_video_creation_and_changed_file_evidence(self):
        from PIL import Image
        source=self.root/'image.png';Image.new('RGB',(64,64),'blue').save(source)
        data={'image':str(source),'image_sha256':task_results.file_digest(source),'duration':1}
        out=task_results.seal('media',media_tools.run('alice',data))
        self.assertTrue(task_results.verify(out))
        self.assertEqual(out['media']['width'],1280);self.assertFalse(out['media']['has_audio'])
        Path(out['file']).write_bytes(b'changed')
        with self.assertRaises(ValueError):task_results.verify(out)

    def test_missing_media_tools_does_not_use_paid_provider(self):
        with patch.object(media_tools.shutil,'which',return_value=None):
            self.assertEqual(media_tools.run('alice',{'image':'x.png','image_sha256':'x'})['state'],'unavailable')

    def test_telegram_reads_only_configured_chat_and_never_changes_webhook(self):
        rows={'ok':True,'result':[{'update_id':1,'message':{'chat':{'id':123},'text':'mine'}},
                                   {'update_id':2,'message':{'chat':{'id':456},'text':'other'}}]}
        with patch.object(publish_services,'configuration',return_value={'bot_token':'123:fake','read_chat_id':'123'}),patch.object(publish_services,'_http',return_value=rows) as http,patch.object(account_tools.privacy,'blocked',return_value=None):
            out=task_results.seal('account',account_tools.run('alice',{'service':'telegram','operation':'list_updates','limit':5}))
        self.assertIn('mine',out['text']);self.assertNotIn('other',out['text']);self.assertTrue(task_results.verify(out,owner='alice'))
        self.assertTrue(http.call_args.args[0].endswith('/getUpdates'))
        self.assertNotIn('offset',http.call_args.args[1])

    def test_youtube_and_instagram_statistics_have_real_snapshot_checks(self):
        svc=Mock();svc.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'channel','snippet':{'title':'Title'},'statistics':{'viewCount':'10'}}]}
        with patch.object(social_reads,'youtube',return_value=svc),patch.object(account_tools.privacy,'blocked',return_value=None):
            out=task_results.seal('account',account_tools.run('alice',{'service':'youtube','operation':'channel_stats'}))
        self.assertTrue(task_results.verify(out,owner='alice'))
        with patch.object(publish_services,'configuration',return_value={'api_version':'v26.0','ig_user_id':'123','access_token':'secret'}),patch.object(social_reads,'_get',return_value={'id':'123','username':'me','followers_count':10}),patch.object(account_tools.privacy,'blocked',return_value=None):
            out=task_results.seal('account',account_tools.run('alice',{'service':'instagram','operation':'profile_stats'}))
        self.assertTrue(task_results.verify(out,owner='alice'))
        out['snapshot']['items'][0]['statistics']['followers_count']='999'
        with self.assertRaises(ValueError):task_results.verify(out)

    def test_recurring_job_saves_history_and_does_not_catch_up_all_missed_runs(self):
        qid=task_queue.enqueue('alice',[{'id':'read','agent':'verify'}],repeat_seconds=300)
        with patch.object(task_agents,'worker',return_value={'state':'done'}):task_queue.tick('alice')
        row=task_queue.rows('alice')[0]
        self.assertEqual(row['state'],'queued');self.assertNotEqual(row['job_id'],row['last_job_id'])
        with patch.object(task_agents,'worker') as worker:
            task_queue.tick('alice');worker.assert_not_called()
        with service_store.database('alice') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_runs WHERE qid=?',(qid,)).fetchone()[0],1)


if __name__=='__main__':unittest.main()
