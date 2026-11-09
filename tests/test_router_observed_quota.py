"""Observed vendor headers are conservative deny-only evidence; no paid/API calls."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from modules import usage_meter

class ObservedQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(usage_meter, '_dir', return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.stamp = 1_794_700_000.
        self.now = datetime.fromtimestamp(self.stamp, tz=timezone(timedelta(hours=3)))

    def store(self, row, *, owner='alice', provider='groq', model='m1'):
        import json
        path = Path(self.tmp.name) / (owner+'.limits.json')
        path.write_text(json.dumps({provider:{model:row}}), encoding='utf-8')

    def test_zero_token_header_blocks_until_reset(self):
        self.store({'t':self.now.isoformat(), 'tok_left':0, 'tok_reset':'1m30s'})
        self.assertEqual(usage_meter.observed_exhaustion('alice','groq','m1',now=self.stamp),
                         {'seconds':90, 'kind':'tokens'})
        self.assertIsNone(usage_meter.observed_exhaustion('alice','groq','m1',now=self.stamp+90))

    def test_waits_for_the_later_of_two_exhausted_limits(self):
        self.store({'t':self.now.isoformat(), 'tok_left':0, 'tok_reset':'45s',
                    'req_left':0, 'req_reset':'2m'})
        self.assertEqual(usage_meter.observed_exhaustion('alice','groq','m1',now=self.stamp+10),
                         {'seconds':110,'kind':'requests'})

    def test_no_unknown_or_invalid_evidence_grants_or_denies_quota(self):
        for row in (
            {'t':self.now.isoformat(), 'tok_left':0, 'tok_reset':'tomorrow'},
            {'t':self.now.isoformat(), 'tok_left':-1, 'tok_reset':'10s'},
            {'t':self.now.isoformat(), 'tok_left':'0', 'tok_reset':'10s'},
            {'t':'2020-01-01T12:00:00+03:00','tok_left':0,'tok_reset':'1h'},
            {'t':self.now.isoformat(), 'tok_left':5, 'tok_reset':'10s'},
            {'t':'bad', 'tok_left':0, 'tok_reset':'10s'},
        ):
            self.store(row)
            self.assertIsNone(usage_meter.observed_exhaustion('alice','groq','m1',now=self.stamp))
        self.assertIsNone(usage_meter.observed_exhaustion('bob','groq','m1',now=self.stamp))
        self.assertIsNone(usage_meter.observed_exhaustion('alice','groq','other',now=self.stamp))

    def test_reset_parser_requires_closed_durations(self):
        self.assertEqual(usage_meter._reset_duration_seconds('1m30s'),90)
        self.assertEqual(usage_meter._reset_duration_seconds('500ms'),.5)
        for bad in ('tomorrow','-1s','0s','1m 30s','999999d','','1h;rm -rf /'):
            self.assertIsNone(usage_meter._reset_duration_seconds(bad))

if __name__ == '__main__':
    unittest.main()
