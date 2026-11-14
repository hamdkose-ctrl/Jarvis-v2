import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from modules import message_inbox as inbox, service_store as store, account_tools as accounts, social_reads, publish_services as services, llm, task_results


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'ROOT',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        self.settings={'webhook_enabled':True,'app_secret':'secret-is-local-and-long','verify_token':'verify-token-long-enough','phone_number_id':'123'}
        p=patch.object(services,'configuration',return_value=self.settings);p.start();self.addCleanup(p.stop)
        from modules import scheduler_resource_gate
        self.enterContext(patch.object(scheduler_resource_gate,'_ACCOUNT_CLAIM_ROOT',Path(self.tmp.name)/'providers'))
        self.enterContext(patch.object(services,'DATA_DIR',Path(self.tmp.name)/'connections'))

    def payload(self,**changes):
        value={'metadata':{'phone_number_id':'123'},'messages':[{'id':'wamid.1','from':'905001234567','timestamp':'100','type':'text','text':{'body':'Merhaba'}}],**changes}
        return json.dumps({'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':value}]}]}).encode()

    def signature(self,raw):return 'sha256='+hmac.new(self.settings['app_secret'].encode(),raw,hashlib.sha256).hexdigest()

    def test_signed_inbox_deduplicates_and_keeps_user_separation(self):
        raw=self.payload();sig=self.signature(raw)
        self.assertEqual(inbox.ingest('alice',raw,sig)['stored'],1)
        self.assertEqual(inbox.ingest('alice',raw,sig)['stored'],0)
        out=task_results.seal('account',inbox.read('alice'))
        self.assertIn('Merhaba',out['text']);self.assertTrue(task_results.verify(out,owner='alice'))
        with self.assertRaises(PermissionError):inbox.read('bob')

    def test_bad_signature_disabled_webhook_or_wrong_phone_never_stores(self):
        raw=self.payload()
        for sig in ('','sha256='+'0'*64):
            with self.assertRaises(PermissionError):inbox.ingest('alice',raw,sig)
        self.settings['webhook_enabled']=False
        with self.assertRaises(PermissionError):inbox.ingest('alice',raw,self.signature(raw))
        self.settings['webhook_enabled']=True
        wrong=self.payload(metadata={'phone_number_id':'999'})
        self.assertEqual(inbox.ingest('alice',wrong,self.signature(wrong))['stored'],0)
        self.assertEqual(inbox.read('alice')['snapshot']['items'],[])

    def test_delivery_order_does_not_regress_read_to_sent_or_failed(self):
        for status,stamp in (('read','200'),('sent','100'),('failed','300')):
            raw=self.payload(messages=[],statuses=[{'id':'outgoing','status':status,'timestamp':stamp}])
            inbox.ingest('alice',raw,self.signature(raw))
        self.assertEqual(inbox.delivery('alice','outgoing')['status'],'read')
        self.assertIsNone(inbox.delivery('alice','other'))

    def test_local_inbox_can_read_offline_and_no_reply_is_sent(self):
        raw=self.payload();inbox.ingest('alice',raw,self.signature(raw))
        with patch.object(accounts.privacy,'blocked',return_value='Web kapalı'),patch.object(services,'send') as send:
            out=accounts.run('alice',{'service':'whatsapp','operation':'list_inbox'})
            self.assertEqual(out['state'],'done');send.assert_not_called()

    def test_youtube_comments_require_owned_video_and_report_first_page(self):
        svc=Mock();svc.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'own'}]}
        svc.videos.return_value.list.return_value.execute.return_value={'items':[{'id':'abcdefghijk','snippet':{'channelId':'own'}}]}
        svc.commentThreads.return_value.list.return_value.execute.return_value={'items':[{'snippet':{'topLevelComment':{'id':'comment','snippet':{'textDisplay':'Nice','authorDisplayName':'User'}}}}],'nextPageToken':'secret-cursor'}
        with patch.object(social_reads,'youtube',return_value=svc),patch.object(accounts.privacy,'blocked',return_value=None):
            out=task_results.seal('account',accounts.run('alice',{'service':'youtube','operation':'list_comments','resource_id':'abcdefghijk'}))
            self.assertIn('Nice',out['text']);self.assertNotIn('secret-cursor',str(out));self.assertTrue(out['snapshot']['has_more'])
            svc.videos.return_value.list.return_value.execute.return_value={'items':[{'id':'abcdefghijk','snippet':{'channelId':'other'}}]}
            svc.commentThreads.reset_mock()
            with self.assertRaises(PermissionError):accounts.run('alice',{'service':'youtube','operation':'list_comments','resource_id':'abcdefghijk'})
            svc.commentThreads.assert_not_called()

    def test_instagram_comments_require_matching_owner(self):
        self.settings.update(api_version='v26.0',ig_user_id='123',access_token='private')
        with patch.object(social_reads,'_get',side_effect=[{'id':'456','owner':{'id':'123'}},{'data':[{'id':'c','text':'Hello'}],'paging':{'next':'private-token-url'}}]),patch.object(accounts.privacy,'blocked',return_value=None):
            out=task_results.seal('account',accounts.run('alice',{'service':'instagram','operation':'list_comments','resource_id':'456'}))
        self.assertTrue(task_results.verify(out,owner='alice'));self.assertNotIn('private-token-url',str(out))
        with patch.object(social_reads,'_get',return_value={'id':'456','owner':{'id':'other'}}) as get,patch.object(accounts.privacy,'blocked',return_value=None):
            with self.assertRaises(PermissionError):accounts.run('alice',{'service':'instagram','operation':'list_comments','resource_id':'456'})
            self.assertEqual(get.call_count,1)

    def test_reels_preparation_is_reused_after_approval_and_not_published_twice(self):
        from modules import outbox,task_agents
        self.settings.update(api_version='v26.0',ig_user_id='123',access_token='private')
        data={'service':'instagram','destination':'123','text':'Caption','media_type':'REELS','video_url':'https://example.com/video.mp4'}
        oid=outbox.prepare('alice',data,'work')
        with patch.object(services,'_http',return_value={'id':'456'}) as post,patch.object(social_reads,'_get',return_value={'status_code':'IN_PROGRESS'}):
            result=outbox.dispatch('alice',oid,approve=True)
            self.assertEqual(result['state'],'approval');self.assertEqual(outbox.get('alice',oid)['state'],'preparing');self.assertEqual(post.call_count,1)
        with patch.object(services,'_http',return_value={'id':'published'}) as post,patch.object(social_reads,'_get',return_value={'status_code':'FINISHED'}):
            result=outbox.poll('alice',min_age=0)[0]
            self.assertEqual(result['state'],'done');self.assertEqual(post.call_count,1)
            self.assertTrue(post.call_args.args[0].endswith('/media_publish'))
            self.assertEqual(outbox.poll('alice'),[])

    def test_telegram_consuming_poll_saves_before_next_ack(self):
        self.settings.update(bot_token='123:fake',read_chat_id='123',consume_updates=True)
        rows={'ok':True,'result':[{'update_id':10,'message':{'chat':{'id':123},'text':'mine'}}]}
        with patch.object(services,'_http',return_value=rows) as post:
            accounts.run('alice',{'service':'telegram','operation':'list_updates'})
            self.assertNotIn('offset',post.call_args.args[1])
            accounts.run('alice',{'service':'telegram','operation':'list_updates'})
            self.assertEqual(post.call_args.args[1]['offset'],11)
        with store.database('alice') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM incoming WHERE service='telegram'").fetchone()[0],1)

    def test_reply_authority_is_separate_from_upload_and_reply_checks_channel(self):
        from modules import outbox
        channel='UC'+'a'*22
        data={'service':'youtube','destination':channel,'operation':'reply_comment','parent_id':'parent','text':'Thanks'}
        oid=outbox.prepare('alice',data,'reply')
        outbox.grant('alice','youtube',channel)
        with patch.object(services,'send') as send:
            self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval');send.assert_not_called()
        self.settings['channel_id']=channel
        svc=Mock();svc.channels.return_value.list.return_value.execute.return_value={'items':[{'id':channel}]}
        svc.comments.return_value.list.return_value.execute.return_value={'items':[{'id':'parent','snippet':{'videoId':'abcdefghijk'}}]}
        svc.videos.return_value.list.return_value.execute.return_value={'items':[{'snippet':{'channelId':channel}}]}
        svc.comments.return_value.insert.return_value.execute.return_value={'id':'reply-id','snippet':{'parentId':'parent'}}
        with patch.object(services,'google_service',return_value=svc):
            self.assertEqual(services.send('alice',data,lambda _:None)['remote_id'],'reply-id')
            svc.videos.return_value.list.return_value.execute.return_value={'items':[{'snippet':{'channelId':'other'}}]}
            svc.comments.return_value.insert.reset_mock()
            with self.assertRaises(PermissionError):services.send('alice',data,lambda _:None)
            svc.comments.return_value.insert.assert_not_called()

    def test_webhook_http_challenge_and_signature_paths(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.parse import urlencode
        from modules import webhook_server
        server=ThreadingHTTPServer(('127.0.0.1',0),webhook_server.Handler);server.allowed_owners={'alice'};server.notify=Mock()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            query=urlencode({'hub.mode':'subscribe','hub.verify_token':self.settings['verify_token'],'hub.challenge':'123'})
            connection.request('GET','/whatsapp/alice?'+query);response=connection.getresponse()
            self.assertEqual(response.status,200);self.assertEqual(response.read(),b'123');connection.close()
            raw=self.payload()
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            connection.request('POST','/whatsapp/alice',raw,{'X-Hub-Signature-256':self.signature(raw)})
            response=connection.getresponse();self.assertEqual(response.status,200);response.read();connection.close()
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            connection.request('POST','/whatsapp/alice',raw,{'X-Hub-Signature-256':'sha256='+'0'*64})
            response=connection.getresponse();self.assertEqual(response.status,403);response.read();connection.close()
            self.assertEqual(len(inbox.read('alice')['snapshot']['items']),1)
            server.notify.assert_called_once()
            self.assertEqual(server.notify.call_args.args[0],'alice')
        finally:server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
