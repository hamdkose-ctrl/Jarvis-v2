"""A pending notice must not hold a standalone process open."""
from pathlib import Path
import subprocess
import sys
import unittest

class DeferredTests(unittest.TestCase):
    def test_pending_notice_does_not_delay_process_exit(self):
        result=subprocess.run([sys.executable,'-c',
            "from modules.deferred import start; start(30,lambda:print('late')); print('exit')"],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'exit')
