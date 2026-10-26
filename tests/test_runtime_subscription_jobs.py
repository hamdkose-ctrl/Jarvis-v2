"""Faz 2-2: the goal that adds a source watch owns its RuntimeEvent subscription.

One subscription system (`runtime_subscription`); a live goal binds itself with
`bind_job`, and `source_watch.poll` publishes new items into that goal's GoalState.
"""
import unittest
from unittest.mock import patch

from modules import (core_state_reducer, goal_extensions, goal_executor, goal_state, goal_state_store,
                     runtime_subscription as subs, source_watch)
from tests.test_capability_monitoring import SourceFixture


class JobSubscriptionFixture(SourceFixture):
    def setUp(self):
        super().setUp()
        p = patch.object(subs, 'DATA_DIR', self.root / 'data'); p.start(); self.addCleanup(p.stop)
        self.path = goal_executor._root('alice') / 'goal.goalstate.json'
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


class BindJobTests(JobSubscriptionFixture):
    def test_new_source_item_becomes_goal_evidence_once(self):
        ident = self.rule_with_baseline()
        sid = subs.bind_job('alice', 'goal', ident)
        self.assertIsNotNone(sid)
        self.new_article()
        self.assertEqual(len(self.poll(ident)), 1)
        evidence = self.evidence()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['source_event_key'], ident)
        self.assertEqual(goal_state_store.load(self.path)['state'], 'pending')  # evidence never decides completion
        # The goal owns the source: no second, synthetic source GoalState is opened.
        self.assertEqual([r['job_id'] for r in subs.rows('alice', active_only=True)], ['goal'])
        self.poll(ident)
        self.assertEqual(len(self.evidence()), 1)

    def test_bind_is_idempotent(self):
        ident = self.add()
        self.assertEqual(subs.bind_job('alice', 'goal', ident), subs.bind_job('alice', 'goal', ident))
        self.assertEqual(len(subs.rows('alice')), 1)

    def test_missing_or_finished_goal_is_not_bound(self):
        ident = self.add()
        self.assertIsNone(subs.bind_job('alice', '', ident))
        self.assertIsNone(subs.bind_job('alice', 'yok', ident))
        self.set_state('cancelled')
        self.assertIsNone(subs.bind_job('alice', 'goal', ident))
        self.assertEqual(subs.rows('alice'), [])

    def test_finished_goal_stops_taking_evidence(self):
        ident = self.rule_with_baseline()
        subs.bind_job('alice', 'goal', ident)
        self.set_state('cancelled')
        self.new_article()
        self.poll(ident)
        self.assertEqual(self.evidence(), [])
        rows = {r['job_id']: r for r in subs.rows('alice')}
        self.assertEqual(rows['goal']['active'], 0)

    def test_removed_rule_closes_goal_subscription(self):
        ident = self.add()
        subs.bind_job('alice', 'goal', ident)
        source_watch.remove('alice', ident)
        self.assertEqual(subs.rows('alice', active_only=True), [])


class MonitorBindingTests(JobSubscriptionFixture):
    def test_goal_that_adds_watch_owns_the_subscription(self):
        data = {'operation': 'add', 'url': self.index, 'terms': ['eğitim']}
        goal_extensions.execute(self.runtime, 'monitor', data,
                                self.identity(self.index + ' adresindeki eğitim duyurularını takip et'))
        rows = subs.rows('alice')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['job_id'], 'goal')
        self.assertEqual(rows[0]['source_event_key'], source_watch.rows('alice')[0]['id'])

    def test_job_without_canonical_goalstate_still_adds_watch_without_subscription(self):
        self.path.unlink()
        data = {'operation': 'add', 'url': self.index, 'terms': ['eğitim']}
        out = goal_extensions.execute(self.runtime, 'monitor', data,
                                      self.identity(self.index + ' adresindeki eğitim duyurularını takip et'))
        self.assertEqual(out['state'], 'done')
        self.assertEqual(subs.rows('alice'), [])


if __name__ == '__main__':
    unittest.main()
