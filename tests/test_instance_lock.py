"""Real subprocess instance-lock tests; no UI, microphone or provider calls."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT="import instance; instance.take_over(); print('ACQUIRED',flush=True); input()"


class InstanceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=dict(os.environ,JARVIS_DATA_DIR=self.temp.name)
        self.env.pop('JARVIS_RESTART_WAIT',None)
        self.children=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for child in self.children:
            if child.poll() is None:child.kill()
            child.communicate(timeout=5)

    def start(self,env=None,script=SCRIPT):
        child=subprocess.Popen([sys.executable,'-u','-c',script],cwd=ROOT,env=env or self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        return child

    def test_simultaneous_launches_acquire_exactly_once_and_keep_first_alive(self):
        children=[self.start(),self.start()]
        lines=[child.stdout.readline().strip() for child in children]
        self.assertEqual(lines.count('ACQUIRED'),1)
        first=children[lines.index('ACQUIRED')]
        other=children[1-lines.index('ACQUIRED')]
        other.wait(timeout=5)
        self.assertEqual(other.returncode,0)
        self.assertIsNone(first.poll())

    def test_crash_releases_lock_and_stale_pid_does_not_block_next_start(self):
        first=self.start();self.assertEqual(first.stdout.readline().strip(),'ACQUIRED')
        first.kill();first.wait(timeout=5)
        self.assertTrue((Path(self.temp.name)/'jarvis.pid').exists())
        second=self.start();self.assertEqual(second.stdout.readline().strip(),'ACQUIRED')

    def test_restart_child_waits_until_old_process_exits(self):
        first=self.start();self.assertEqual(first.stdout.readline().strip(),'ACQUIRED')
        restart=self.start(dict(self.env,JARVIS_RESTART_WAIT='1'),"import instance; print('WAITING',flush=True); instance.take_over(); print('ACQUIRED',flush=True); input()")
        self.assertEqual(restart.stdout.readline().strip(),'WAITING')
        first.communicate('\n',timeout=5)
        self.assertEqual(restart.stdout.readline().strip(),'ACQUIRED')
        self.assertIsNone(restart.poll())

    def test_early_shutdown_cleanup_keeps_lock_until_process_exits(self):
        first=self.start(script="import instance; instance.take_over(); instance.release(); print('ACQUIRED',flush=True); input()")
        self.assertEqual(first.stdout.readline().strip(),'ACQUIRED')
        second=self.start();out,_=second.communicate(timeout=5)
        self.assertNotIn('ACQUIRED',out)
        self.assertIsNone(first.poll())

    def test_acquisition_error_stops_startup(self):
        import instance
        with patch.object(instance,'_done',False),patch.object(instance,'DATA_DIR',Path(self.temp.name)),patch.object(instance,'LOCK_FILE',Path(self.temp.name)/'lock'),patch.object(instance,'_try_lock',side_effect=OSError('lock unavailable')):
            with self.assertRaises(SystemExit) as result:instance.take_over()
        self.assertEqual(result.exception.code,1)

    def test_same_process_repeated_acquisition_is_idempotent(self):
        child=self.start(script="import instance; instance.take_over(); instance.take_over(); print('ACQUIRED',flush=True); input()")
        self.assertEqual(child.stdout.readline().strip(),'ACQUIRED')
        other=self.start();out,_=other.communicate(timeout=5)
        self.assertNotIn('ACQUIRED',out)
