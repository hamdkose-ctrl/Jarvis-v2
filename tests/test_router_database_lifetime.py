"""SQLite handles must close on every path; Windows cannot unlink a live database.

Retain actual connections so garbage collection cannot conceal a missing close.
The real transactions, trace/qualification persistence and rollback stay live.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from modules import router_quota as quota,smart_router


class RouterDatabaseLifetimeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.opened=[];self.real_connect=sqlite3.connect
        def connect(*args,**kwargs):
            db=self.real_connect(*args,**kwargs);self.opened.append(db)
            return db
        p=patch.object(quota.sqlite3,'connect',side_effect=connect)
        p.start();self.addCleanup(p.stop)
        # Cleanup is explicit even in the RED phase, so the regression's own
        # retained references cannot lock the temporary directory on Windows.
        self.addCleanup(lambda:[db.close() for db in self.opened])

    def assert_closed(self):
        self.assertTrue(self.opened)
        for db in self.opened:
            with self.assertRaises(sqlite3.ProgrammingError,msg='Router left a SQLite handle open'):
                db.execute('SELECT 1')

    def test_trace_write_commits_then_read_and_list_close_their_handles(self):
        row={'request_id':'turn','call_id':'call','updated':time.time(),'state':'completed','attempts':[]}
        quota.write_trace('alice',row,directory=self.root)
        self.assertEqual(quota.read_trace('alice','turn',directory=self.root),row)
        self.assertEqual(quota.recent_traces('alice',directory=self.root),[row])
        self.assertIsNone(quota.read_trace('bob','turn',directory=self.root))
        self.assert_closed()

    def test_early_returns_without_trace_or_qualification_tables_close(self):
        quota.reserve('alice','groq','m',directory=self.root,application_limit=2)
        self.assertIsNone(quota.read_trace('alice','turn',directory=self.root))
        self.assertEqual(quota.recent_traces('alice',directory=self.root),[])
        self.assertFalse(quota.role_qualified('alice','groq','m',None,fingerprint='source',binding='key',directory=self.root))
        self.assert_closed()

    def test_trace_serialization_error_rolls_back_and_closes(self):
        row={'request_id':'bad','call_id':'call','updated':time.time(),'bad_value':float('nan')}
        with self.assertRaises(ValueError):quota.write_trace('alice',row,directory=self.root)
        self.assertIsNone(quota.read_trace('alice','bad',directory=self.root))
        self.assert_closed()

    def test_successful_qualification_is_committed_and_connections_close(self):
        spec=smart_router.ModelSpec('groq','m',binding='key')
        report={'state':'passed','scope':'holdout','semantic_acceptance':True,'corpus_sha256':'corpus',
            'head':'a'*40,'accuracy':1.0,'incorrect_action_proposals':0,'attempted_effects':0,
            'planned_cases':20,'provider_responses':20,
            'qualified_target':{'provider':'groq','model':'m','connection_id':None},
            'results':[{'responded':True,'correct':True} for _ in range(20)]}
        quota.qualify_role('alice',spec,report,fingerprint='source',directory=self.root,corpus_sha256='corpus',expected_cases=20)
        self.assertTrue(quota.role_qualified('alice','groq','m',None,fingerprint='source',binding='key',directory=self.root))
        self.assert_closed()

    def test_reconciliation_commits_and_early_return_closes(self):
        quota.reserve('alice','groq','m',directory=self.root,application_limit=3,token_budget=40,attempt_id='one')
        quota.reconcile('alice','one',{'total_tokens':7},directory=self.root)
        with closing(self.real_connect(self.root/'atomic_requests.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT token_units,actual_tokens FROM requests').fetchone(),(7,7))
        self.assert_closed()
