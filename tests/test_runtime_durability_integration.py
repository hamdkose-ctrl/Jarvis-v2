import json
import tempfile
import unittest
from pathlib import Path


class RuntimeDurabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        from modules import crash_recovery, effect_journal, runtime_event
        self.crash_recovery = crash_recovery
        self.effect_journal = effect_journal
        self.runtime_event = runtime_event
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def intent(self, effect_id='effect-1'):
        return {
            'schema': 'effect_intent.v1',
            'effect_id': effect_id,
            'owner': 'alice',
            'job_id': 'job-1',
            'command_id': 'cmd-1',
            'capability_id': 'task.publish',
            'capability_version': '1',
            'input_digest': 'a' * 64,
        }

    def receipt(self, effect_id='effect-1'):
        return {
            'schema': 'effect_receipt.v1',
            'effect_id': effect_id,
            'provider_receipt_ref': 'provider:receipt:1',
            'verified': True,
        }

    def event(self, event_id='event-1'):
        return {
            'schema': 'runtime_event.v1',
            'event_id': event_id,
            'source_event_key': 'watch:mail',
            'source_generation': 2,
            'subject_version': 7,
            'occurred_at': 100.0,
            'kind': 'mail_changed',
            'payload': {'message_id': 'm1'},
        }

    def subscription(self):
        return {
            'source_event_key': 'watch:mail',
            'source_generation': 2,
            'subject_version': 7,
            'resume_token': 'resume-1',
            'fresh_after': 50.0,
        }

    def test_effect_journal_survives_restart_and_drives_recovery(self):
        path = self.root / 'effects.json'
        journal = self.effect_journal.PersistentJournal(path)
        journal.record_intent(self.intent())

        restarted = self.effect_journal.PersistentJournal(path)
        self.assertEqual(restarted.status('effect-1'), 'unknown')
        self.assertEqual(
            self.crash_recovery.decide(restarted, 'effect-1')['action'],
            'read_only_reconcile',
        )

        restarted.record_receipt(self.receipt())
        restarted_again = self.effect_journal.PersistentJournal(path)
        self.assertEqual(restarted_again.status('effect-1'), 'succeeded')
        self.assertEqual(
            self.crash_recovery.decide(restarted_again, 'effect-1')['action'],
            'no_retry',
        )

    def test_effect_journal_rejects_corrupt_persisted_state(self):
        path = self.root / 'effects.json'
        path.write_text('{bad json', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.effect_journal.PersistentJournal(path)

    def test_runtime_event_dedup_survives_restart(self):
        path = self.root / 'events.json'
        seen = self.runtime_event.PersistentSeen(path)
        accepted = self.runtime_event.accept(self.event(), self.subscription(), seen)
        self.assertEqual(accepted['event_id'], 'event-1')

        restarted = self.runtime_event.PersistentSeen(path)
        self.assertIn('event-1', restarted)
        with self.assertRaises(self.runtime_event.DuplicateEventError):
            self.runtime_event.accept(self.event(), self.subscription(), restarted)

    def test_runtime_event_seen_store_rejects_corrupt_state(self):
        path = self.root / 'events.json'
        path.write_text(json.dumps({'schema': 'wrong', 'event_ids': []}), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.runtime_event.PersistentSeen(path)


if __name__ == '__main__':
    unittest.main()
