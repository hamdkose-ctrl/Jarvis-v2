import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from modules import web_window


class SingleWindowTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(_window_lock=threading.RLock(),_window_open_until=0.0,
            time=SimpleNamespace(monotonic=Mock(return_value=0),sleep=Mock()),
            _jarvis_hwnds=Mock(return_value=[]),_loading_hwnds=Mock(return_value=[]),_win_action=Mock(),
            _find_browser=Mock(return_value='msedge.exe'),sys=SimpleNamespace(argv=[]),DATA_DIR=Path('data'),
            subprocess=SimpleNamespace(Popen=Mock()),threading=SimpleNamespace(Thread=Mock()),_center_window=Mock())

    def test_simultaneous_open_calls_before_sse_launch_only_once(self):
        rt=self.runtime();barrier=threading.Barrier(5)
        def show():barrier.wait();web_window.open_window(rt,'http://127.0.0.1:1234')
        threads=[threading.Thread(target=show) for _ in range(5)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=2);self.assertFalse(t.is_alive())
        rt.subprocess.Popen.assert_called_once()

    def test_existing_or_loading_window_is_reused(self):
        for loading in (False,True):
            rt=self.runtime()
            (rt._loading_hwnds if loading else rt._jarvis_hwnds).return_value=[123]
            web_window.open_window(rt,'http://127.0.0.1:1234')
            rt.subprocess.Popen.assert_not_called();rt._win_action.assert_called_once_with('show')

    def test_visible_show_succeeds_without_opening_another_window(self):
        rt=self.runtime();rt._jarvis_hwnds.return_value=[123]
        user32=SimpleNamespace(IsWindowVisible=lambda h:True,IsIconic=lambda h:False,ShowWindow=Mock(),SetForegroundWindow=Mock())
        with patch.dict('sys.modules',{'ctypes':SimpleNamespace(windll=SimpleNamespace(user32=user32))}):
            self.assertTrue(web_window._win_action(rt,'show'))
        user32.ShowWindow.assert_not_called();user32.SetForegroundWindow.assert_called_once_with(123)

    def test_timeout_allows_reopening_a_closed_or_failed_window(self):
        rt=self.runtime();web_window.open_window(rt,'url')
        rt.time.monotonic.return_value=16
        web_window.open_window(rt,'url')
        self.assertEqual(rt.subprocess.Popen.call_count,2)

    def test_failed_launch_and_fallback_release_reservation(self):
        rt=self.runtime();rt.subprocess.Popen.side_effect=OSError('browser missing')
        with patch('webbrowser.open',return_value=False):web_window.open_window(rt,'url')
        self.assertEqual(rt._window_open_until,0)

    def test_fullscreen_reopen_clears_reservation_without_deadlock(self):
        rt=self.runtime();rt._window_open_until=15;rt._close_windows=Mock();rt._url='url'
        rt.open_window=lambda url:web_window.open_window(rt,url)
        web_window._reopen_window(rt)
        rt._close_windows.assert_called_once();rt.subprocess.Popen.assert_called_once()

if __name__=='__main__':unittest.main()
