import unittest


class RuntimeEventContractTests(unittest.TestCase):
    def setUp(self):
        from modules import runtime_event
        self.events = runtime_event

    def event(self, **changes):
        row = {'schema': 'runtime_event.v1', 'event_id': 'evt-1', 'source_event_key': 'watch:1',
               'source_generation': 3, 'subject_version': 7, 'occurred_at': 100.0,
               'kind': 'watch_finished', 'payload': {'result': 'passed'}}
        row.update(changes)
        return row

    def subscription(self):
        return {'source_event_key': 'watch:1', 'source_generation': 3,
                'subject_version': 7, 'resume_token': 'resume-1', 'fresh_after': 90.0}

    def test_fresh_matching_event_is_accepted_once(self):
        ledger = set()
        accepted = self.events.accept(self.event(), self.subscription(), ledger)
        self.assertEqual(accepted['event_id'], 'evt-1')
        self.assertEqual(ledger, {'evt-1'})

    def test_duplicate_stale_and_foreign_events_fail_closed(self):
        ledger = {'evt-1'}
        with self.assertRaises(self.events.DuplicateEventError):
            self.events.accept(self.event(), self.subscription(), ledger)
        for changes in ({'occurred_at': 89.0}, {'source_generation': 2}, {'subject_version': 6}):
            with self.subTest(changes=changes):
                with self.assertRaises(self.events.StaleEventError):
                    self.events.accept(self.event(**changes), self.subscription(), set())
