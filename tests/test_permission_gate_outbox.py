"""Outbox ek izin kapısı; gerçek taşıyıcı/ağ ve kullanıcı deposu kullanılmaz."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import outbox, service_store, publish_services as services, llm, requests_state
from modules import permission_gate, permission_grants, permission_audit, permission_classify


class OutboxPermissionGateTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        root=Path(td.name)
        self.enterContext(patch.object(service_store,'ROOT',root/'outbox'))
        self.enterContext(patch.object(permission_grants,'ROOT',root/'grants'))
        self.enterContext(patch.object(permission_audit,'DATA_DIR',root))
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        req=requests_state._current.set(None);self.addCleanup(requests_state._current.reset,req)
        self.enterContext(patch.object(outbox.time,'time',return_value=1792418400.0))
        self.send=self.enterContext(patch.object(services,'send',return_value={'remote_id':'fake','scope':'provider_accepted'}))
        self.real_audit=permission_audit.record
        self.audit_root=root/'permission_audit'
        self.audit=self.enterContext(patch.object(permission_audit,'record'))
        self.target='ahmet@example.org'
        self.serial=0

    def prepare(self,**changes):
        self.serial+=1
        payload={'service':'gmail','destination':self.target,'subject':'Durum','text':'Kısa yanıt '+str(self.serial)}
        payload.update(changes)
        if payload['service'] != 'gmail':
            payload.pop('subject',None)
        return outbox.prepare('alice',payload,'permission-test-'+str(self.serial))

    def grant(self,target=None):
        permission_grants.grant_message('alice',target or self.target,600)

    def slots(self):
        with service_store.database('alice') as db:
            return db.execute('SELECT COUNT(*) FROM outbox_send_budget').fetchone()[0]

    def test_ask_keeps_existing_exact_content_preview_and_audits(self):
        oid=self.prepare()
        result=outbox.dispatch('alice',oid)
        self.assertEqual(result['state'],'approval')
        self.assertEqual(result['preview'],outbox.get('alice',oid)['payload'])
        self.send.assert_not_called()
        self.assertEqual(self.audit.call_args.args[:5],('alice','ask','message_out',self.target,'outbox'))
        self.assertEqual(self.slots(),0)

    def test_deny_blocks_even_explicit_approval_without_consuming_slot(self):
        oid=self.prepare()
        with patch.object(permission_gate,'decide',return_value={'decision':'deny','reason':'Gönderim kapalı.'}):
            result=outbox.dispatch('alice',oid,approve=True)
        self.assertEqual(result['state'],'blocked')
        self.assertEqual(result['text'],'Gönderim kapalı.')
        self.assertEqual(outbox.get('alice',oid)['state'],'prepared')
        self.send.assert_not_called()
        self.assertEqual(self.slots(),0)
        self.assertEqual(self.audit.call_args.args[1],'deny')

    def test_active_grant_allows_same_immutable_recipient_without_approve(self):
        self.grant();oid=self.prepare()
        with patch.object(permission_classify,'classify',wraps=permission_classify.classify) as classify:
            result=outbox.dispatch('alice',oid)
        self.assertEqual(result['state'],'done')
        self.assertEqual(self.send.call_args.args[1]['destination'],self.target)
        classify.assert_called_with('outbox','Gönder',self.target)
        self.assertEqual(self.audit.call_args.args[1],'allow')
        self.assertEqual(self.slots(),1)

    def test_expired_wrong_target_and_other_user_grants_do_not_allow(self):
        permission_grants.grant_message('alice',self.target,1,now=1792418300)
        self.grant('other@example.org')
        token=llm._key_context.set('bob')
        try:
            permission_grants.grant_message('bob',self.target,600)
        finally:
            llm._key_context.reset(token)
        result=outbox.dispatch('alice',self.prepare())
        self.assertEqual(result['state'],'approval')
        self.send.assert_not_called()

    def test_legacy_channel_grant_and_explicit_approval_keep_working(self):
        outbox.grant('alice','gmail',self.target,600)
        self.assertEqual(outbox.dispatch('alice',self.prepare())['state'],'done')
        self.assertEqual(self.audit.call_args.args[1],'allow')
        outbox.revoke('alice','gmail',self.target)
        self.assertEqual(outbox.dispatch('alice',self.prepare(),approve=True)['state'],'done')
        self.assertEqual(self.audit.call_args.args[1],'ask')

    def test_sensitive_guard_is_not_weakened_by_new_grant(self):
        self.grant()
        oid=self.prepare(text='token=PRIVATE_SESSION_CANARY_123')
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
        self.send.assert_not_called()
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'done')

    def test_global_and_channel_caps_apply_to_new_grants_and_manual_approval(self):
        self.grant()
        with patch.object(outbox,'DAILY_TOTAL_LIMIT',1):
            self.assertEqual(outbox.dispatch('alice',self.prepare())['state'],'done')
            for approve in (False,True):
                self.assertEqual(outbox.dispatch('alice',self.prepare(),approve=approve)['state'],'blocked')
        with patch.dict(outbox.DAILY_CHANNEL_LIMITS,{'gmail':1}):
            self.assertEqual(outbox.dispatch('alice',self.prepare(),approve=True)['state'],'blocked')
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(self.slots(),1)

    def test_duplicate_send_and_unknown_send_still_consume_budget(self):
        self.grant()
        self.send.side_effect=OSError('unknown transport outcome')
        first=self.prepare(text='Aynı cevap')
        self.assertEqual(outbox.dispatch('alice',first)['state'],'failed')
        second=self.prepare(text='Aynı cevap')
        self.assertEqual(outbox.dispatch('alice',second)['state'],'blocked')
        outbox.dispatch('alice',first,approve=True)
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(self.slots(),1)

    def test_gate_load_classify_and_audit_exceptions_fail_closed_without_raw_error(self):
        for module,name in [(permission_gate,'decide'),(permission_grants,'load'),
                            (permission_classify,'classify'),(permission_audit,'record')]:
            with self.subTest(name=name):
                oid=self.prepare()
                with patch.object(module,name,side_effect=RuntimeError('PRIVATE')),patch.object(outbox,'_record_failure') as diagnostic:
                    result=outbox.dispatch('alice',oid,approve=True)
                self.assertEqual(result['state'],'blocked')
                self.assertNotIn('PRIVATE',result['text'])
                diagnostic.assert_called()
                self.assertEqual(outbox.get('alice',oid)['state'],'prepared')
        self.send.assert_not_called()
        self.assertEqual(self.slots(),0)

    def test_invalid_decision_is_closed(self):
        with patch.object(permission_gate,'decide',return_value={'decision':'surprise','reason':'x'}):
            result=outbox.dispatch('alice',self.prepare(),approve=True)
        self.assertEqual(result['state'],'blocked')
        self.send.assert_not_called()

    def test_payload_hash_tampering_still_rejected_before_send(self):
        self.grant();oid=self.prepare()
        with service_store.database('alice') as db:
            payload={'service':'gmail','destination':'other@example.org','subject':'Durum','text':'değişti'}
            db.execute('UPDATE outbox SET payload=? WHERE id=?',(service_store.encode(payload),oid))
        with self.assertRaises(ValueError):outbox.dispatch('alice',oid,approve=True)
        self.send.assert_not_called()

    def test_telegram_whatsapp_adapters_use_same_gate(self):
        for service,dest in [('telegram','-12345'),('whatsapp','905001234567')]:
            with self.subTest(service=service):
                oid=self.prepare(service=service,destination=dest)
                # gmail-only subject is removed before preparing this separate channel.
                self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
                self.assertEqual(self.audit.call_args.args[2:5],('message_out',dest,'outbox'))
        self.send.assert_not_called()

    def test_real_audit_is_owner_scoped_and_does_not_store_message(self):
        self.audit.side_effect=self.real_audit
        oid=self.prepare(text='Metnin kendisi denetime yazılmaz')
        outbox.dispatch('alice',oid)
        rows=json.loads((self.audit_root/'alice.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['decision'],rows[0]['class'],rows[0]['via']),('ask','message_out','outbox'))
        self.assertNotIn('Metnin kendisi',str(rows))
        self.assertFalse((self.audit_root/'bob.json').exists())

    def test_preparation_poll_preserves_bound_prior_approval(self):
        oid=self.prepare(service='instagram',destination='123',image_url='https://example.org/image.jpg')
        self.send.side_effect=[services.Preparing(),{'remote_id':'ready'}]
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'approval')
        self.assertEqual(outbox.get('alice',oid)['state'],'preparing')
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'done')
        self.assertEqual(self.audit.call_args.args[1],'allow')
        self.assertEqual(self.slots(),1)

    def test_legacy_channel_grant_never_becomes_global_destination_grant(self):
        outbox.grant('alice','telegram','123',600)
        oid=self.prepare(service='instagram',destination='123',image_url='https://example.org/image.jpg')
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
        self.assertEqual(permission_grants.load('alice')['message_out'],{})
        self.send.assert_not_called()

    def test_generic_message_grant_does_not_authorize_publication(self):
        for service,dest in [('instagram','123'),('youtube','UC'+'a'*22)]:
            with self.subTest(service=service):
                self.grant(dest)
                if service=='instagram':
                    oid=self.prepare(service=service,destination=dest,image_url='https://example.org/image.jpg')
                else:
                    payload={'service':service,'destination':dest,'text':'video','subject':'Başlık',
                             'file':'/mock/video.mp4','file_sha256':'a'*64,'privacy':'private'}
                    oid=outbox.prepare('alice',payload,'publication-'+service)
                self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
        self.send.assert_not_called()

    def test_generic_message_grant_does_not_authorize_comment_reply(self):
        self.grant('123')
        payload={'service':'instagram','destination':'123','operation':'reply_comment','parent_id':'456','text':'Kısa yorum'}
        oid=outbox.prepare('alice',payload,'comment-reply')
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'approval')
        self.send.assert_not_called()
        outbox.grant('alice','instagram_reply','123',600)
        self.assertEqual(outbox.dispatch('alice',oid)['state'],'done')
