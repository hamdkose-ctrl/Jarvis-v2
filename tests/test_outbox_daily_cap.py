import importlib.util
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from modules import llm, outbox, publish_services as services, service_store


class DailyCapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(service_store, 'ROOT', Path(temporary.name))
        root.start(); self.addCleanup(root.stop)
        credentials=patch.object(services,'DATA_DIR',Path(temporary.name)/'connections')
        credentials.start();self.addCleanup(credentials.stop)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        self.clock = patch.object(outbox.time, 'time', return_value=datetime(2026, 10, 18, 10, tzinfo=timezone.utc).timestamp())
        self.now = self.clock.start(); self.addCleanup(self.clock.stop)
        self.limits = {'gmail': 2, 'telegram': 2, 'whatsapp': 2, 'instagram': 2, 'youtube': 2}
        constants = patch.dict(outbox.__dict__, DAILY_CHANNEL_LIMITS=self.limits, DAILY_TOTAL_LIMIT=3, DUPLICATE_WINDOW_SECONDS=600)
        constants.start(); self.addCleanup(constants.stop)
        self.send = Mock(side_effect=lambda owner, data, progress, **kw: {
            'service': data['service'], 'destination': data['destination'], 'remote_id': 'mock-id', 'scope': 'provider_accepted'})
        transport = patch.object(services, 'send', self.send)
        transport.start(); self.addCleanup(transport.stop)
        self.serial = 0
        from modules import scheduler_resource_gate
        self.enterContext(patch.object(scheduler_resource_gate,'_ACCOUNT_CLAIM_ROOT',Path(temporary.name)/'providers'))

    def payload(self, service='gmail', text=None, destination=None, **extra):
        self.serial += 1
        data = {'service': service, 'destination': destination or {
            'gmail': 'friend@example.com', 'telegram': '-123', 'whatsapp': '905001234567',
            'instagram': '123', 'youtube': 'UC' + 'a' * 22}[service],
            'text': text or 'Benzersiz içerik ' + str(self.serial)}
        if service in ('gmail', 'youtube'): data['subject'] = 'Konu'
        if service == 'instagram': data['image_url'] = 'https://example.com/image.jpg'
        if service == 'youtube': data.update(file='/mock/video.mp4', file_sha256='a' * 64, privacy='private')
        return data | extra

    def prepare(self, payload=None, module=outbox):
        payload = payload or self.payload()
        return module.prepare('alice', payload, 'work-' + str(self.serial))

    def dispatch(self, payload=None, approve=True, module=outbox):
        return module.dispatch('alice', self.prepare(payload, module), approve=approve)

    def test_limit_is_allowed_but_limit_plus_one_is_blocked(self):
        for _ in range(2): self.assertEqual(self.dispatch()['state'], 'done')
        result = self.dispatch()
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('günlük sınır', result['text'].lower())
        self.assertIn('2', result['text'])
        self.assertEqual(self.send.call_count, 2)

    def test_cap_applies_before_approval_and_after_a_previous_preview(self):
        self.assertEqual(self.dispatch()['state'], 'done')
        pending = self.prepare()
        self.assertEqual(outbox.dispatch('alice', pending)['state'], 'approval')
        self.assertEqual(self.dispatch()['state'], 'done')
        self.assertEqual(outbox.dispatch('alice', pending)['state'], 'blocked')
        self.assertEqual(outbox.dispatch('alice', pending, approve=True)['state'], 'blocked')
        self.assertEqual(self.send.call_count, 2)

    def test_channel_separation_and_global_ceiling(self):
        self.dispatch(); self.dispatch()
        self.assertEqual(self.dispatch(self.payload('telegram'))['state'], 'done')
        self.assertEqual(self.dispatch(self.payload('whatsapp'))['state'], 'blocked')
        self.assertEqual(self.send.call_count, 3)

    def test_each_supported_channel_has_its_own_ceiling(self):
        for service in self.limits:
            with self.subTest(service=service), patch.dict(outbox.__dict__, DAILY_TOTAL_LIMIT=100):
                for _ in range(2): self.assertEqual(self.dispatch(self.payload(service))['state'], 'done')
                self.assertEqual(self.dispatch(self.payload(service))['state'], 'blocked')
        self.assertEqual(self.send.call_count, 10)

    def test_standing_grant_does_not_bypass_cap_or_change_expiry(self):
        outbox.grant('alice', 'gmail', 'friend@example.com', seconds=600)
        for _ in range(2): self.assertEqual(self.dispatch(approve=False)['state'], 'done')
        self.assertEqual(self.dispatch(approve=False)['state'], 'blocked')
        with service_store.database('alice') as db:
            self.assertEqual(db.execute('SELECT expires FROM grants').fetchone()[0], self.now.return_value + 600)

    def test_count_resets_at_istanbul_midnight_not_utc_midnight(self):
        self.now.return_value = datetime(2026, 10, 18, 20, 59, tzinfo=timezone.utc).timestamp()
        self.dispatch(); self.dispatch()
        self.assertEqual(self.dispatch()['state'], 'blocked')
        self.now.return_value += 60
        self.assertEqual(self.dispatch()['state'], 'done')

    def test_counter_is_persistent_in_a_fresh_module_instance(self):
        self.dispatch(); self.dispatch()
        spec = importlib.util.spec_from_file_location('outbox_fresh_for_test', outbox.__file__)
        fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
        with patch.dict(fresh.__dict__, DAILY_CHANNEL_LIMITS=self.limits, DAILY_TOTAL_LIMIT=3, DUPLICATE_WINDOW_SECONDS=600):
            self.assertEqual(self.dispatch(module=fresh)['state'], 'blocked')
        self.assertEqual(self.send.call_count, 2)

    def test_same_recipient_same_content_is_blocked_even_with_new_work_key(self):
        self.dispatch(self.payload(text='Aynı içerik'))
        result = self.dispatch(self.payload(text='Aynı içerik', operation='send_mail'))
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('aynı içerik', result['text'].lower())
        self.assertEqual(self.send.call_count, 1)

    def test_instagram_default_image_type_cannot_bypass_duplicate_guard(self):
        self.dispatch(self.payload('instagram', text='Aynı görsel'))
        repeated = self.payload('instagram', text='Aynı görsel', media_type='IMAGE')
        self.assertEqual(self.dispatch(repeated)['state'], 'blocked')
        self.assertEqual(self.send.call_count, 1)

    def test_same_content_other_recipient_and_after_window_are_allowed(self):
        with patch.dict(outbox.__dict__, DAILY_CHANNEL_LIMITS={'gmail': 10}, DAILY_TOTAL_LIMIT=10):
            self.assertEqual(self.dispatch(self.payload(text='Metin'))['state'], 'done')
            self.assertEqual(self.dispatch(self.payload(text='Metin', destination='other@example.com'))['state'], 'done')
            self.now.return_value += 601
            self.assertEqual(self.dispatch(self.payload(text='Metin'))['state'], 'done')

    def test_unknown_send_consumes_budget_and_cannot_be_repeated_under_new_id(self):
        self.send.side_effect = RuntimeError('PRIVATE_TOKEN')
        self.assertEqual(self.dispatch(self.payload(text='Aynı içerik'))['state'], 'failed')
        self.assertEqual(self.dispatch(self.payload(text='Aynı içerik'))['state'], 'blocked')
        self.assertEqual(self.send.call_count, 1)

    def test_preparing_poll_does_not_count_same_publication_twice(self):
        self.limits['instagram'] = 1
        oid = self.prepare(self.payload('instagram'))
        self.send.side_effect = services.Preparing()
        self.assertEqual(outbox.dispatch('alice', oid, approve=True)['state'], 'approval')
        self.send.side_effect = lambda owner, data, progress, **kw: {'service': 'instagram', 'destination': '123', 'remote_id': 'id', 'scope': 'provider_accepted'}
        self.assertEqual(outbox.dispatch('alice', oid)['state'], 'done')
        self.assertEqual(self.dispatch(self.payload('instagram'))['state'], 'blocked')

    def test_preparing_from_yesterday_must_fit_todays_cap(self):
        self.limits['instagram'] = 1
        oid = self.prepare(self.payload('instagram'))
        self.send.side_effect = services.Preparing()
        outbox.dispatch('alice', oid, approve=True)
        self.now.return_value += 86400
        self.send.side_effect = lambda owner, data, progress, **kw: {
            'service':data['service'],'destination':data['destination'],'remote_id':'id','scope':'provider_accepted'}
        self.assertEqual(self.dispatch(self.payload('instagram'))['state'], 'done')
        self.assertEqual(outbox.dispatch('alice', oid, approve=True)['state'], 'blocked')

    def test_concurrent_dispatches_cannot_exceed_cap(self):
        ids = [self.prepare() for _ in range(5)]
        barrier = threading.Barrier(5)
        def dispatch(oid):
            token = llm._key_context.set('alice')
            try:
                barrier.wait(timeout=10)
                return outbox.dispatch('alice', oid, approve=True)['state']
            finally: llm._key_context.reset(token)
        with ThreadPoolExecutor(max_workers=5) as pool:
            states = list(pool.map(dispatch, ids))
        # A provider-wide live claim may reject simultaneous admission before
        # budget/approval consumption. Explicitly retry only those NOT started;
        # the SQLite daily cap must still permit exactly two total sends.
        for index, state in enumerate(states):
            if state == 'blocked':
                states[index] = outbox.dispatch('alice', ids[index], approve=True)['state']
        self.assertEqual(states.count('done'), 2)
        self.assertEqual(states.count('blocked'), 3)
        self.assertEqual(self.send.call_count, 2)

    def test_previous_journal_sends_are_counted_when_budget_is_first_created(self):
        for _ in range(2):
            oid = self.prepare()
            with service_store.database('alice') as db:
                db.execute("UPDATE outbox SET state='accepted',updated=? WHERE id=?", (self.now.return_value, oid))
        self.assertEqual(self.dispatch()['state'], 'blocked')
        self.send.assert_not_called()

    def test_no_authorization_still_waits_and_cancelled_does_not_consume(self):
        oid = self.prepare()
        self.assertEqual(outbox.dispatch('alice', oid)['state'], 'approval')
        outbox.cancel('alice', oid)
        self.assertEqual(self.dispatch()['state'], 'done')
        self.assertEqual(self.dispatch()['state'], 'done')
        self.send.assert_called()

    def test_repeat_window_spans_midnight(self):
        self.now.return_value = datetime(2026, 10, 18, 20, 59, tzinfo=timezone.utc).timestamp()
        self.dispatch(self.payload(text='Aynı içerik'))
        self.now.return_value += 120
        self.assertEqual(self.dispatch(self.payload(text='Aynı içerik'))['state'], 'blocked')

    def test_comment_replies_share_service_daily_cap(self):
        self.limits['youtube'] = 1
        self.dispatch(self.payload('youtube'))
        self.serial += 1
        reply = {'service': 'youtube', 'operation': 'reply_comment', 'destination': 'UC' + 'a' * 22,
                 'parent_id': 'comment_1', 'text': 'Cevap'}
        self.assertEqual(self.dispatch(reply)['state'], 'blocked')

    def test_budget_and_duplicate_guard_are_user_scoped(self):
        self.limits['gmail'] = 1
        data = self.payload(text='Aynı içerik')
        self.dispatch(data)
        token = llm._key_context.set('bob')
        try:
            oid = outbox.prepare('bob', data, 'other-owner')
            self.assertEqual(outbox.dispatch('bob', oid, approve=True)['state'], 'done')
        finally: llm._key_context.reset(token)

    def test_transaction_failure_rolls_back_claim_and_budget_before_network(self):
        from contextlib import contextmanager
        self.limits['gmail'] = 1
        oid = self.prepare()
        database = service_store.database
        @contextmanager
        def interrupted(owner):
            with database(owner) as db:
                yield db
                if db.execute('SELECT state FROM outbox WHERE id=?', (oid,)).fetchone()[0] == 'sending':
                    raise OSError('simulated transaction interruption')
        with patch.object(service_store, 'database', interrupted):
            with self.assertRaises(OSError): outbox.dispatch('alice', oid, approve=True)
        self.send.assert_not_called()
        self.assertEqual(outbox.get('alice', oid)['state'], 'prepared')
        self.assertEqual(outbox.dispatch('alice', oid, approve=True)['state'], 'done')


if __name__ == '__main__': unittest.main()
