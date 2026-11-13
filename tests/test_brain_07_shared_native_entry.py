"""BRAIN-07 single-PR integration: one physical browser/desktop resource.

No Playwright, native window, keyboard action or external provider is invoked.
The browser ownership test does use a real independent Python process and
the same OS-lock primitive used in production.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import sys
import tempfile
import unittest

from modules import browser_agent, desktop_agent, system_control, resource_leases


class SharedNativeResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, attr, value in (
            (browser_agent, 'STORE', self.root / 'browsers'),
            (browser_agent, '_BROWSER_CLAIM_ROOT', self.root / 'browser-claims'),
            (desktop_agent, 'STORE', self.root / 'desktop'),
            (desktop_agent, '_PHYSICAL_DESKTOP_CLAIM_ROOT',
             self.root / 'desktop-claims'),
        ):
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def test_second_browser_process_cannot_own_the_same_profile(self):
        script = """
from pathlib import Path
import sys
from modules import browser_agent
browser_agent.STORE = Path(sys.argv[1])
browser_agent._BROWSER_CLAIM_ROOT = Path(sys.argv[2])
with browser_agent._browser_claim('alice'):
    print('READY', flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen(
            [sys.executable, '-c', script, str(browser_agent.STORE),
             str(browser_agent._BROWSER_CLAIM_ROOT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = child.stdout.readline().strip()
            self.assertEqual(ready, 'READY', child.stderr.read() if child.poll() is not None else '')
            with patch.object(browser_agent, '_run',
                              side_effect=AssertionError('browser launched during live claim')) as run:
                with self.assertRaises(resource_leases.LeaseConflict):
                    browser_agent.run('alice', headless=True)
                run.assert_not_called()
        finally:
            if child.poll() is None:
                child.stdin.write('release\n')
                child.stdin.flush()
            child.communicate(timeout=20)
        with patch.object(browser_agent, '_run', return_value={'state': 'done'}) as run:
            self.assertEqual(browser_agent.run('alice', headless=True), {'state': 'done'})
            run.assert_called_once()

    def test_visible_browser_refuses_when_desktop_is_occupied(self):
        @contextmanager
        def busy(*, run_handoff=False):
            yield False
        with patch.object(desktop_agent, '_desktop_claim', side_effect=busy), \
             patch.object(browser_agent, '_run',
                          side_effect=AssertionError('no UI launch')) as run:
            self.assertEqual(
                browser_agent.run('alice', headless=False)['state'], 'blocked',
            )
            run.assert_not_called()

    def test_system_windows_share_desktop_claim_with_native_agent(self):
        @contextmanager
        def busy(*, run_handoff=False):
            yield False
        facade = system_control._permission_instrument(
            'window_action',
            lambda *_args, **_kwargs: self.fail('native action entered'),
        )
        with patch.object(system_control, '_permission_decision'), \
             patch.object(desktop_agent, '_desktop_claim', side_effect=busy):
            self.assertFalse(facade('Notepad', 'focus')['ok'])

    def test_system_window_shortcut_borrows_one_owner_claim_for_nested_window(self):
        seen = []
        @contextmanager
        def owned(*, run_handoff=False):
            seen.append(run_handoff)
            yield True
        inner = system_control._permission_instrument(
            'window_action', lambda *_args: {'ok': True, 'hwnd': 123},
        )
        outer = system_control._permission_instrument(
            'window_shortcut', lambda *_args: inner('Notepad', 'focus'),
        )
        with patch.object(system_control, '_permission_decision'), \
             patch.object(desktop_agent, '_desktop_claim', side_effect=owned):
            self.assertTrue(outer('Notepad', 'copy')['ok'])
        self.assertEqual(seen, [True, True])


if __name__ == '__main__':
    unittest.main()
