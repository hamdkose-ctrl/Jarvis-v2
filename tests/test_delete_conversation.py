import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
import threading
from modules import history
from web_chat import WebChat


class DeleteConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(history,'DIR',Path(self.temp.name));self.patch.start();self.addCleanup(self.patch.stop)
        self.rows=[{'id':'old','role':'user','text':'Keep old','ts':'2026-10-06 12:00:00'},
                   {'id':'selected','role':'user','text':'Remove selected','ts':'2026-10-07 12:00:00'},
                   {'id':'new','role':'assistant','text':'Keep new','ts':'2026-10-08 12:00:00'}]
        self.path=history._path('alice')
        self.path.write_text(''.join(json.dumps(row)+'\n' for row in self.rows),encoding='utf-8')

    def test_history_append_uses_real_jsonl_lines_and_survives_trim(self):
        with patch.object(history, '_MAX_BYTES', 256):
            for index in range(12):
                row = history.append('alice', 'user', 'new row ' + str(index))
                self.assertIsNotNone(row)
        raw = self.path.read_bytes()
        self.assertTrue(raw.endswith(b'\n'))
        self.assertNotIn(b'\\n', raw)
        for line in raw.splitlines():
            self.assertIsInstance(json.loads(line), dict)
        self.assertFalse(list(self.path.parent.glob('.history-trim-*')))

    def test_busy_history_is_not_deleted_or_reported_as_appended(self):
        from modules import file_resource_guard, resource_leases
        before = self.path.read_bytes()
        with file_resource_guard.claim_paths(self.path):
            with self.assertRaises(resource_leases.LeaseConflict):
                history.delete_day('alice', '2026-10-07')
            self.assertIsNone(history.append('alice', 'user', 'must not claim save'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob('.history-delete-*')))

    def test_only_selected_day_and_user_are_deleted(self):
        other=history._path('bob');other.write_bytes(self.path.read_bytes());before=other.read_bytes()
        self.assertEqual(history.delete_day('alice','2026-10-07'),1)
        self.assertEqual([r['id'] for r in history.read('alice')],['old','new'])
        self.assertEqual(other.read_bytes(),before)

    def test_invalid_date_and_path_are_rejected(self):
        before=self.path.read_bytes()
        for day in ('','2026-02-30','2026-10-07suffix','../other'):
            with self.assertRaises(ValueError):history.delete_day('alice',day)
        with self.assertRaises(ValueError):history.delete_day('../bob','2026-10-07')
        self.assertEqual(self.path.read_bytes(),before)

    def test_write_failure_preserves_history(self):
        before=self.path.read_bytes()
        with patch.object(history.os,'replace',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):history.delete_day('alice','2026-10-07')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(Path(self.temp.name).glob('.history-delete-*')))

    def test_failed_delete_does_not_publish_deleted_ids_to_ui(self):
        before = self.path.read_bytes()
        selected = set()
        with patch.object(history.os, 'replace',
                          side_effect=OSError('durable replace failed')):
            with self.assertRaises(OSError):
                history.delete_day('alice', '2026-10-07', selected)
        self.assertEqual(selected, set())
        self.assertEqual(self.path.read_bytes(), before)

    def test_deleted_rows_do_not_return_from_live_log(self):
        owner=SimpleNamespace(slug='alice',name='Alice',data={'learning_buffer':['staged']},save=lambda:None);state=SimpleNamespace(last_doc='cached')
        events=[{'user':'Alice','hid':'old'},{'user':'Alice','hid':'selected'},{'user':'Bob','hid':'selected'}]
        runtime=SimpleNamespace(_p=lambda:owner,history=history,
            engine=SimpleNamespace(event_log=events,_event_lock=threading.RLock(),_sessions=SimpleNamespace(for_owner=lambda slug:state)),
            llm=SimpleNamespace(_histories={'alice':['cached'],'bob':['keep']}))
        runtime.llm.reset_history = lambda user: runtime.llm._histories.__setitem__(user, [])
        bridge=WebChat();bridge._runtime=runtime
        result=bridge.history_delete_conversation('2026-10-07')
        self.assertEqual(result['removed'],1)
        self.assertEqual(events,[{'user':'Alice','hid':'old'},{'user':'Bob','hid':'selected'}])
        self.assertEqual(runtime.llm._histories['bob'],['keep']);self.assertIsNone(state.last_doc)
        self.assertNotIn('learning_buffer',owner.data)
