"""Faz 2 parts must run in the live paths, not only as standalone modules."""
import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import (
    advisory_router, event_channels, event_webhooks, goal_state_store, hooks, llm, publish_services,
    runtime_subscription, service_store, task_agents, task_queue, webhook_server,
)


class OwnerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for obj, name, value in ((service_store, 'ROOT', self.root / 'services'),
                                 (runtime_subscription, 'DATA_DIR', self.root),
                                 (task_agents, 'STORE', self.root / 'tasks')):
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        hooks.clear(); self.addCleanup(hooks.clear)
        p = patch('modules.privacy.blocked', return_value=None); p.start(); self.addCleanup(p.stop)


class QueueTests(OwnerFixture):
    VERIFY = [{'id': 'check', 'agent': 'verify', 'depends': [], 'input': {}}]

    def test_queue_list_uses_real_line_breaks_and_offers_run_now(self):
        qid = task_queue.enqueue('alice', self.VERIFY, 'kontrol', cron='0 9 * * *')
        text = task_queue.render_rows(task_queue.rows('alice'))
        self.assertNotIn('\\n', text)
        self.assertIn('\nCron: 0 9 * * *', text)
        self.assertIn('Şimdi çalıştır: kuyruk çalıştır ' + qid, text)

    def test_run_now_never_revives_cancelled_or_finished_work(self):
        qid = task_queue.enqueue('alice', self.VERIFY, 'kontrol', delay=600)
        task_queue.configure('alice', qid, operation='pause')
        self.assertEqual(task_queue.run_now('alice', qid), qid)
        self.assertEqual(task_queue.rows('alice')[0]['state'], 'queued')
        task_queue.cancel('alice', qid)
        with self.assertRaises(ValueError):
            task_queue.run_now('alice', qid)
        self.assertEqual(task_queue.rows('alice')[0]['state'], 'cancelled')

    def test_script_schedule_accepts_only_model_free_workers(self):
        with self.assertRaises(ValueError):
            task_queue.enqueue_script('alice', [{'id': 'r', 'agent': 'research', 'depends': [],
                                                 'input': {'url': 'https://example.org'}}], cron='0 9 * * *')
        qid = task_queue.enqueue_script('alice', self.VERIFY, cron='0 9 * * *')
        self.assertEqual(task_queue.rows('alice')[0]['id'], qid)

    def test_cron_keeps_its_cadence_after_a_blocked_run(self):
        qid = task_queue.enqueue('alice', self.VERIFY, 'kontrol', cron='*/5 * * * *')
        with service_store.database('alice') as db:
            db.execute('UPDATE queue SET due=0 WHERE id=?', (qid,))
        with patch.object(task_agents, 'execute', side_effect=RuntimeError('down')):
            task_queue.tick('alice')
        row = task_queue.rows('alice')[0]
        self.assertEqual(row['state'], 'queued')
        self.assertGreater(row['due'], time.time())
        self.assertEqual(row['error'], 'RuntimeError')

    def test_chat_commands_run_now_and_script_cron_without_model(self):
        with patch.object(llm, 'ask', side_effect=AssertionError('model çağrılmamalı')):
            text = task_agents.handle('alice', 'betik cron */10 * * * *: ' + json.dumps({'tasks': self.VERIFY}))
        self.assertIn('Cron: */10 * * * *', text)
        qid = task_queue.rows('alice')[0]['id']
        self.assertIn('öne aldım', task_agents.handle('alice', 'kuyruk çalıştır ' + qid))


class HookAndGateTests(OwnerFixture):
    def test_task_run_emits_agent_tool_and_kanban_hooks(self):
        seen = []
        for name in ('agent', 'tool', 'kanban'):
            hooks.register(name, lambda event, name=name: seen.append((name, event['payload'])))
        with patch.object(task_agents, '_worker', return_value={'state': 'done', 'text': 'tamam'}), \
             patch.object(task_agents.task_results, 'seal', side_effect=lambda kind, output: output):
            job = task_agents.execute('alice', [{'id': 'check', 'agent': 'verify', 'depends': [], 'input': {}}], 'kontrol')
        self.assertEqual(job['state'], 'done')
        names = [name for name, _ in seen]
        self.assertIn('agent', names); self.assertIn('kanban', names)
        tools = [payload for name, payload in seen if name == 'tool']
        self.assertEqual([t['phase'] for t in tools], ['start', 'end'])
        self.assertEqual(tools[-1]['state'], 'done')

    def test_broken_observer_never_breaks_the_run(self):
        hooks.register('tool', lambda event: (_ for _ in ()).throw(RuntimeError('gözlemci bozuk')))
        with patch.object(task_agents, '_worker', return_value={'state': 'done', 'text': 'tamam'}), \
             patch.object(task_agents.task_results, 'seal', side_effect=lambda kind, output: output):
            job = task_agents.execute('alice', [{'id': 'check', 'agent': 'verify', 'depends': [], 'input': {}}], 'kontrol')
        self.assertEqual(job['state'], 'done')

    def test_shared_gate_stops_worker_when_job_is_not_running(self):
        job = {'id': 'job1', 'state': 'cancelled', 'instruction': 'kontrol'}
        task = {'id': 'check', 'agent': 'verify', 'state': 'running', 'input': {},
                'execution': {'owner': 'alice', 'job_id': 'job1'}}
        with self.assertRaises(PermissionError):
            task_agents._gate('alice', job, task)
        job['state'] = 'running'
        self.assertEqual(task_agents._gate('alice', job, task)['phase'], 'execute')
        publish = dict(task, agent='publish', input={'service': 'gmail', 'destination': 'a@example.com', 'text': 'x'})
        self.assertEqual(task_agents._gate('alice', job, publish)['phase'], 'prepare')

    def test_model_hook_reports_metadata_only(self):
        seen = []
        hooks.register('model', lambda event: seen.append(event))
        with patch.object(llm, '_send', return_value='cevap'):
            self.assertEqual(llm.ask('gizli soru'), 'cevap')
        self.assertEqual(seen[0]['payload']['call'], 'ask')
        self.assertTrue(seen[0]['payload']['ok'])
        self.assertNotIn('gizli soru', json.dumps(seen[0], ensure_ascii=False))


class RuntimeSubscriptionProductionTests(OwnerFixture):
    def test_source_gets_one_waiting_goalstate_and_survives_version_moves(self):
        first = runtime_subscription.ensure_source('alice', 'watch1', goal='Kaynak takibi', fresh_after=0.0)
        self.assertEqual(runtime_subscription.ensure_source('alice', 'watch1', goal='Kaynak takibi', fresh_after=0.0), first)
        path = Path(runtime_subscription.rows('alice')[0]['goal_state_path'])
        state = goal_state_store.load(path)
        self.assertEqual(state['state'], 'waiting'); self.assertEqual(state['authority'], 'canonical')
        self.assertEqual(runtime_subscription.publish('alice', 'watch1', {'title': 'bir'}, occurred_at=time.time()), [first])
        # Another writer moves the version; evidence must still be appended.
        with service_store.database('alice') as db:
            db.execute('UPDATE runtime_subscriptions SET expected_job_version=0 WHERE id=?', (first,))
        self.assertEqual(runtime_subscription.publish('alice', 'watch1', {'title': 'iki'}, occurred_at=time.time()), [first])
        self.assertEqual(len(goal_state_store.load(path)['evidence']), 2)

    def test_removed_source_closes_subscription_and_goalstate(self):
        runtime_subscription.ensure_source('alice', 'watch2', goal='Kaynak takibi', fresh_after=0.0)
        path = Path(runtime_subscription.rows('alice')[0]['goal_state_path'])
        self.assertEqual(runtime_subscription.close_source('alice', 'watch2'), 1)
        self.assertEqual(goal_state_store.load(path)['state'], 'cancelled')
        self.assertEqual(runtime_subscription.publish('alice', 'watch2', {'title': 'x'}), [])


class EventChannelTests(unittest.TestCase):
    def runtime(self, prefs):
        profile = SimpleNamespace(slug='alice', data={'prefs': prefs})
        return SimpleNamespace(list_users=lambda: ['Alice'], _get_profile=lambda name: profile,
                               _emit_for=Mock(), notify=SimpleNamespace(send=Mock(return_value=True)), log=Mock())

    def test_one_event_reaches_ui_phone_and_log(self):
        runtime = self.runtime({'ntfy_topic': 'jarvis-x'})
        result = event_channels.deliver(runtime, 'alice', {'source': 'webhook:github', 'kind': 'incoming', 'payload': {'text': 'Yeni PR'}})
        self.assertEqual(result, {'ui': 'delivered', 'ntfy': 'delivered', 'log': 'delivered'})
        runtime._emit_for.assert_called_once()
        runtime.notify.send.assert_called_once()

    def test_phone_is_skipped_without_topic_and_total_failure_raises(self):
        runtime = self.runtime({})
        self.assertNotIn('ntfy', event_channels.deliver(runtime, 'alice', {'source': 's', 'kind': 'k', 'payload': {}}))
        runtime = self.runtime({'event_channels': ['ui']}); runtime._emit_for.side_effect = RuntimeError('ui yok')
        with self.assertRaises(RuntimeError):
            event_channels.deliver(runtime, 'alice', {'source': 's', 'kind': 'k', 'payload': {}})


class EventWebhookTests(OwnerFixture):
    SECRET = 'olay-imza-anahtari-uzun'

    def setUp(self):
        super().setUp()
        config = {'enabled': True, 'sources': {'github': {'secret': self.SECRET}}}
        p = patch.object(publish_services, 'configuration', return_value=config); p.start(); self.addCleanup(p.stop)

    def sign(self, raw):
        return 'sha256=' + hmac.new(self.SECRET.encode(), raw, hashlib.sha256).hexdigest()

    def test_signed_event_reaches_fanout_and_goalstate(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), webhook_server.Handler)
        server.allowed_owners = {'alice'}; server.event_notify = Mock()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            raw = json.dumps({'action': 'opened', 'text': 'Yeni PR açıldı'}).encode()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            connection.request('POST', '/event/alice/github', raw, {'X-Jarvis-Signature': self.sign(raw)})
            response = connection.getresponse(); self.assertEqual(response.status, 200); response.read(); connection.close()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            connection.request('POST', '/event/alice/github', raw, {'X-Jarvis-Signature': 'sha256=' + '0' * 64})
            response = connection.getresponse(); self.assertEqual(response.status, 403); response.read(); connection.close()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            connection.request('POST', '/event/alice/unknown', raw, {'X-Jarvis-Signature': self.sign(raw)})
            response = connection.getresponse(); self.assertEqual(response.status, 403); response.read(); connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        server.event_notify.assert_called_once()
        event = server.event_notify.call_args.args[1]
        self.assertEqual(event['source'], 'webhook:github')
        self.assertEqual(event['payload']['action'], 'opened')
        path = Path(runtime_subscription.rows('alice')[0]['goal_state_path'])
        self.assertEqual(goal_state_store.load(path)['evidence'][0]['payload']['action'], 'opened')

    def test_body_must_be_one_json_object(self):
        raw = b'[1,2]'
        with self.assertRaises(ValueError):
            event_webhooks.ingest('alice', 'github', raw, self.sign(raw))


class AdvisoryTests(unittest.TestCase):
    def test_schema_mismatch_never_shows_raw_json(self):
        raw = '{"options":[{"name":"A","pros":[],"cons":[]}],"recommendation":{"option":"A","rationale":"Hız önemli"}}'
        text = advisory_router.finalize('Hangisi daha iyi?', raw, settings={})
        self.assertNotIn('{', text); self.assertIn('Hız önemli', text)

    def test_prose_suggestion_line_is_rendered_or_dropped_by_setting(self):
        raw = 'Plan uygun görünüyor.\nÖneri (risk): Önce yedek al.'
        self.assertEqual(advisory_router.finalize('planım hazır', raw, settings={}),
                         'Plan uygun görünüyor.\n\nBurada dikkat et: Önce yedek al.')
        self.assertEqual(advisory_router.finalize('planım hazır', raw, settings={'proactive_suggestions': False}),
                         'Plan uygun görünüyor.')

    def test_triggers_catch_natural_phrasing_and_skip_unrelated_words(self):
        mode = advisory_router._mode
        self.assertEqual(mode('Bunu nasıl yaparım?'), 'guidance')
        self.assertEqual(mode('Excel tablosu nasıl yapılır'), 'guidance')
        self.assertEqual(mode('Eksiklerimi dürüstçe söyle'), 'critique')
        self.assertIsNone(mode('Malzeme eksik geldi'))
        self.assertIsNone(mode('Karar verdim, yarın gidiyorum'))
        self.assertEqual(mode('Gideyim mi kalayım mı?'), 'decision')


if __name__ == '__main__':
    unittest.main()
