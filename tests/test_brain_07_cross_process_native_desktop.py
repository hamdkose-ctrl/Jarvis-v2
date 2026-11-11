"""BRAIN-07: one shared physical desktop across separate Jarvis processes.

No native UI action, real model, provider or device is executed.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import desktop_agent as agent


_HOLD_DESKTOP = """
import sys
import time
from pathlib import Path
from unittest.mock import patch
from modules import desktop_agent as agent
with patch.object(agent, 'STORE', Path(sys.argv[1])):
    with agent._desktop_claim() as owned:
        if not owned:
            sys.exit(19)
        Path(sys.argv[2]).write_text('held', encoding='utf-8')
        time.sleep(30)
"""


class CrossProcessNativeDesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup_temp)
        self.root = Path(self.tmp.name) / "desktop_tasks"
        patcher = patch.object(agent, 'STORE', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cwd = Path(__file__).resolve().parents[1]

    def _cleanup_temp(self):
        # A just-terminated Python child can leave a transient Win32 open
        # handle while the OS finishes process teardown. Never swallow a
        # persistently leaked handle: bounded retries must eventually pass.
        deadline = time.monotonic() + 8
        while True:
            try:
                self.tmp.cleanup()
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)

    def _assert_desktop_reclaimed(self):
        # Verify that termination really released the cross-process claim,
        # not merely that Popen.wait() returned. The successor may not
        # continue until it can acquire the *same* physical resource.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with agent._desktop_claim() as owned:
                if owned:
                    return
            time.sleep(.05)
        self.fail(
            'Desktop OS claim remained occupied after holder exit; '
            'check live owner process and Windows file handles.'
        )

    def stop_other_process(self, child):
        try:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
        finally:
            child.stderr.close()
        self.assertIsNotNone(child.returncode)
        self._assert_desktop_reclaimed()

    def start_other_process(self):
        ready = self.root.parent / 'holder-ready.flag'
        child = subprocess.Popen(
            [sys.executable, '-c', _HOLD_DESKTOP, str(self.root), str(ready)],
            cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        start = time.monotonic()
        while not ready.exists() and child.poll() is None and time.monotonic() - start < 8:
            time.sleep(.02)
        if not ready.exists():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            stderr = child.stderr.read().decode('utf-8', 'replace')
            child.stderr.close()
            self.fail('Separate process failed to claim desktop: ' + stderr)
        return child

    def test_cross_process_busy_never_replaces_saved_job(self):
        with agent._desktop_claim() as claimed:
            self.assertTrue(claimed)
            with agent._desktop_claim() as nested:
                self.assertFalse(nested)
            with agent._desktop_claim(run_handoff=True) as valid_handoff:
                self.assertTrue(valid_handoff)
                agent._ctx.native_running = True
                try:
                    with agent._desktop_claim(run_handoff=True) as duplicate_run:
                        self.assertFalse(duplicate_run)
                finally:
                    agent._ctx.native_running = False
        self.assertFalse(agent._BUSY.locked())
        old = {'owner':'alice','id':'old-native','target':'Calculator',
               'goal':'old task','status':'waiting','history':[]}
        agent._save(old)
        before = agent._path('alice').read_bytes()
        child = self.start_other_process()
        try:
            with patch.object(agent, '_run_claimed') as native:
                result = agent.handle(
                    'alice', 'PC görevi: Hesap Makinesi | 12 ile 7 topla',
                    current=lambda:'alice',
                )
            self.assertIn('Başka bir masaüstü', result)
            native.assert_not_called()
            self.assertEqual(agent._path('alice').read_bytes(), before)
        finally:
            self.stop_other_process(child)

        with patch.object(agent, '_run_claimed', return_value='ready') as native:
            result = agent.handle(
                'alice', 'PC görevi: Hesap Makinesi | 12 ile 7 topla',
                current=lambda:'alice',
            )
        self.assertEqual(result, 'ready')
        native.assert_called_once()
        self.assertNotEqual(agent._path('alice').read_bytes(), before)

    def test_stale_direct_run_cannot_overwrite_newer_native_job(self):
        original = {
            'id': 'job-old', 'owner': 'alice', 'target': 'Calculator',
            'goal': 'old task', 'status': 'waiting', 'history': [],
        }
        agent._save(original)
        stale = dict(original)
        agent._save(dict(original, id='job-new', goal='new task'))
        before = agent._path('alice').read_bytes()
        class NeverUI:
            def observe(self, *_):
                raise AssertionError('Stale job reached physical desktop')
        result = agent.run(stale, ui=NeverUI())
        self.assertIn('görevi değişti', result)
        self.assertEqual(agent._path('alice').read_bytes(), before)

    def test_stale_same_id_approval_snapshot_cannot_dispatch(self):
        old = {
            'id': 'stable-id', 'owner': 'alice', 'target': 'Calculator',
            'goal': 'old task', 'status': 'approval', 'history': [],
            'approval': {'id':'before'}, 'pending_effect': None,
        }
        agent._save(old)
        stale = dict(old)
        agent._save(dict(old, approval={'id':'after'}))
        before = agent._path('alice').read_bytes()
        class NeverUI:
            def observe(self, *_):
                raise AssertionError('Stale approval reached physical desktop')
        result = agent.run(stale, ui=NeverUI(), approval='before')
        self.assertIn('görevi değişti', result)
        self.assertEqual(agent._path('alice').read_bytes(), before)

    def test_different_owner_does_not_bypass_one_physical_desktop(self):
        child = self.start_other_process()
        try:
            with patch.object(agent, '_run_claimed') as native:
                result = agent.handle(
                    'bob', 'PC görevi: Not Defteri | bir metin yaz',
                    current=lambda:'bob',
                )
            self.assertIn('Başka bir masaüstü', result)
            self.assertFalse(agent._path('bob').exists())
            native.assert_not_called()
        finally:
            self.stop_other_process(child)

    def test_direct_run_never_observes_ui_when_other_process_owns_desktop(self):
        child = self.start_other_process()
        try:
            job = {'owner':'alice','target':'Calculator','goal':'read only',
                   'status':'running','history':[]}
            class NeverUI:
                def observe(self, *_):
                    raise AssertionError('UI observation started while OS claim was held')
            result = agent.run(job, ui=NeverUI(), read_only=True)
            self.assertIn('Başka bir masaüstü', result)
        finally:
            self.stop_other_process(child)


if __name__ == '__main__':
    unittest.main()
