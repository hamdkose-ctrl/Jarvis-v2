import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from modules import web_window

class WindowCallbackTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(config=SimpleNamespace(load_settings=lambda: {}, WAKE_WORD='Jarvis', save_settings=Mock()), engine=SimpleNamespace(flags={'mic': True, 'sleep': False}, events=Mock(), set_sleep=Mock()), hub=SimpleNamespace(state='idle', publish=Mock()), _show_main=Mock(), _set_mic=Mock(), _aname=lambda: 'Jarvis', _widget_should_hide=lambda: False, _shutdown=Mock(), threading=Mock(), _widget=None, _tray=None)

    def test_widget_callbacks_use_injected_runtime(self):
        rt = self.runtime(); callbacks = {}
        def widget(state, actions, **kwargs):
            callbacks.update(actions)
            self.assertEqual(state(), ('idle', rt.engine.flags))
            return SimpleNamespace(run=Mock())
        module = SimpleNamespace(available=lambda: True, Widget=widget)
        with patch.dict('sys.modules', {'modules.widget': module}), patch('modules.widget', module, create=True):
            self.assertTrue(web_window._run_widget(rt))
        callbacks['talk'](); rt.engine.events.put.assert_called_once_with(('listen',))
        callbacks['mic'](); rt._set_mic.assert_called_once_with(False)
        callbacks['sleep'](); rt.engine.set_sleep.assert_called_once_with(True)

    def test_tray_callbacks_use_injected_runtime(self):
        rt = self.runtime(); received = {}
        def start(show, mic, is_mic, quit, **kwargs):
            received.update(mic=mic, is_mic=is_mic, **kwargs)
            return 'tray'
        module = SimpleNamespace(start=start)
        with patch.dict('sys.modules', {'modules.tray': module}), patch('modules.tray', module, create=True):
            web_window._start_tray(rt)
        self.assertEqual(rt._tray, 'tray')
        received['mic'](); rt._set_mic.assert_called_once_with(False)
        received['on_sleep'](); rt.engine.set_sleep.assert_called_once_with(True)
        self.assertFalse(received['is_widget']())
