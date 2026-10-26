"""Durable RuntimeEvent subscription: real source_watch rows -> Reducer/CAS evidence."""
import json
import unittest
from unittest.mock import patch

from modules import (core_state_reducer, goal_extensions, goal_executor, goal_state, goal_state_store,
                     runtime_event, runtime_event_subscription as subs, source_watch)
from tests.test_capability_monitoring import SourceFixture


class SubscriptionFixture(SourceFixture):
    def setUp(self):
        super().setUp()
        self.goal_root = goal_executor._root('alice')
        self.path = self.goal_root / 'goal.goalstate.json'
        goal_state_store.create(self.path, goal_state.new(
            owner='alice', job_id='goal', goal='okul duyurularını izle', execution_mode='durable'))

    def new_article(self, slug='new', text='Yarın tüm okullarda eğitim tatil edildi.'):
        self.items.insert(0, (slug, 'Duyuru ' + slug, '2026-10-26'))
        self.articles['https://example.org/' + slug] = '<html><body>' + text + '</body></html>'

    def rule_with_baseline(self):
        ident = self.add(['tatil'])
        self.poll(ident)  # first scan is a silent baseline
        return ident

    def evidence(self):
        return [row for row in goal_state_store.load(self.path)['evidence'] if row.get('kind') == 'runtime_event']

    def set_state(self, target):
        state = goal_state_store.load(self.path)
        next_state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_state', 'state': target, 'reason_code': 'TEST'})
        goal_state_store.compare_and_swap(self.path, expected_version=state['version'], next_state=next_state)


class SubscriptionTests(SubscriptionFixture):
    def test_new_source_item_becomes_goalstate_evidence_once(self):
        ident = self.rule_with_baseline()
        row = subs.subscribe('alice', 'goal', ident, now=0)
        self.new_article()
        self.assertEqual(len(self.poll(ident)), 1)

        summary = subs.pump('alice')
        self.assertEqual(summary['committed'], 1)
        evidence = self.evidence()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['event_kind'], subs.EVENT_KIND)
        self.assertEqual(evidence[0]['resume_token'], row['resume_token'])
        self.assertEqual(evidence[0]['source_event_key'], 'source_watch:' + ident)
        self.assertIn('tatil', evidence[0]['payload']['quote'])
        state = goal_state_store.load(self.path)
        self.assertEqual(state['state'], 'pending')  # evidence never decides completion
        self.assertEqual(state['audit'][-1]['reason_code'], 'RUNTIME_EVENT_ACCEPTED')

        again = subs.pump('alice')
        self.assertEqual((again['committed'], again['duplicate']), (0, 1))
        self.assertEqual(len(self.evidence()), 1)

    def test_restart_reloads_subscription_and_seen_ledger_from_disk(self):
        ident = self.rule_with_baseline()
        subs.subscribe('alice', 'goal', ident, now=0)
        self.new_article()
        self.poll(ident)
        subs.pump('alice')
        version = goal_state_store.load(self.path)['version']
        # Nothing lives in memory: a fresh process sees the same registry/ledger.
        registry = json.loads((self.goal_root / subs.REGISTRY).read_text(encoding='utf-8'))
        self.assertEqual(registry['subscriptions'][0]['state'], 'active')
        self.assertEqual(len(runtime_event.PersistentSeen(self.goal_root / subs.SEEN)), 1)
        self.assertEqual(subs.pump('alice')['committed'], 0)
        self.assertEqual(goal_state_store.load(self.path)['version'], version)

    def test_events_before_subscription_are_filtered_as_not_fresh(self):
        ident = self.rule_with_baseline()
        self.new_article()
        self.poll(ident)
        subs.subscribe('alice', 'goal', ident)
        self.assertEqual(subs.pump('alice')['committed'], 0)
        self.assertEqual(self.evidence(), [])

    def test_stamp_mismatch_is_rejected_by_freshness_boundary(self):
        ident = self.rule_with_baseline()
        row = subs.subscribe('alice', 'goal', ident, now=0)
        self.new_article()
        self.poll(ident)
        stored = source_watch.rule_events('alice', ident, 0)[0]
        event = subs.event_for({**row, 'source_generation': row['source_generation'] + 1}, stored)
        with self.assertRaises(runtime_event.StaleEventError):
            runtime_event.accept(event, subs.contract(row), set())

    def test_subscribe_is_idempotent_and_resubscribe_gets_new_generation(self):
        ident = self.rule_with_baseline()
        first = subs.subscribe('alice', 'goal', ident)
        self.assertEqual(subs.subscribe('alice', 'goal', ident), first)
        self.assertTrue(subs.close('alice', first['subscription_id'], 'TEST'))
        second = subs.subscribe('alice', 'goal', ident)
        self.assertNotEqual(second['resume_token'], first['resume_token'])
        self.assertEqual(second['source_generation'], first['source_generation'] + 1)

    def test_terminal_job_closes_subscription_without_writing(self):
        ident = self.rule_with_baseline()
        row = subs.subscribe('alice', 'goal', ident, now=0)
        self.set_state('done')
        self.new_article()
        self.poll(ident)
        version = goal_state_store.load(self.path)['version']
        self.assertEqual(subs.pump('alice')['closed'], 1)
        self.assertEqual(goal_state_store.load(self.path)['version'], version)
        closed = subs.subscriptions('alice')[0]
        self.assertEqual((closed['subscription_id'], closed['state'], closed['close_reason']),
                         (row['subscription_id'], 'closed', 'JOB_TERMINAL'))
        with self.assertRaises(core_state_reducer.TerminalStateError):
            subs.subscribe('alice', 'goal', ident)

    def test_removed_source_rule_closes_subscription(self):
        ident = self.rule_with_baseline()
        subs.subscribe('alice', 'goal', ident)
        source_watch.remove('alice', ident)
        self.assertEqual(subs.pump('alice')['closed'], 1)
        self.assertEqual(subs.subscriptions('alice')[0]['close_reason'], 'SOURCE_REMOVED')

    def test_fan_out_to_two_jobs_watching_same_source(self):
        other = self.goal_root / 'goal2.goalstate.json'
        goal_state_store.create(other, goal_state.new(owner='alice', job_id='goal2', goal='ikinci hedef'))
        ident = self.rule_with_baseline()
        subs.subscribe('alice', 'goal', ident, now=0)
        subs.subscribe('alice', 'goal2', ident, now=0)
        self.new_article()
        self.poll(ident)
        self.assertEqual(subs.pump('alice')['committed'], 2)
        self.assertEqual(len(self.evidence()), 1)
        self.assertEqual(len(goal_state_store.load(other)['evidence']), 1)

    def test_cas_race_reloads_version_once(self):
        ident = self.rule_with_baseline()
        subs.subscribe('alice', 'goal', ident, now=0)
        self.new_article()
        self.poll(ident)
        real = goal_state_store.load
        calls = {'n': 0}

        def racing_load(path):
            state = real(path)
            calls['n'] += 1
            if calls['n'] == 2:  # first version read inside _commit
                self.set_state('running')
            return state
        with patch.object(subs.goal_state_store, 'load', side_effect=racing_load):
            self.assertEqual(subs.pump('alice')['committed'], 1)
        self.assertEqual(len(self.evidence()), 1)

    def test_corrupt_registry_fails_closed(self):
        ident = self.rule_with_baseline()
        subs.subscribe('alice', 'goal', ident)
        (self.goal_root / subs.REGISTRY).write_text('{bad', encoding='utf-8')
        with self.assertRaises(ValueError):
            subs.pump('alice')

    def test_owner_without_registry_is_a_noop_and_creates_nothing(self):
        self.assertEqual(subs.pump('bob')['committed'], 0)
        self.assertFalse((goal_executor.STORE / 'bob').exists())


class MonitorBindingTests(SubscriptionFixture):
    def test_goal_that_adds_watch_owns_the_subscription(self):
        data = {'operation': 'add', 'url': self.index, 'terms': ['eğitim']}
        goal_extensions.execute(self.runtime, 'monitor', data,
                                self.identity(self.index + ' adresindeki eğitim duyurularını takip et'))
        rows = subs.subscriptions('alice')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['job_id'], 'goal')
        self.assertEqual(rows[0]['source_id'], source_watch.rows('alice')[0]['id'])

    def test_job_without_canonical_goalstate_still_adds_watch_without_subscription(self):
        self.path.unlink()
        data = {'operation': 'add', 'url': self.index, 'terms': ['eğitim']}
        out = goal_extensions.execute(self.runtime, 'monitor', data,
                                      self.identity(self.index + ' adresindeki eğitim duyurularını takip et'))
        self.assertEqual(out['state'], 'done')
        self.assertEqual(subs.subscriptions('alice'), [])


if __name__ == '__main__':
    unittest.main()
