import sys
import types
import unittest
from unittest import mock

import modules
from modules import acceptance_checks


class DesktopAcceptanceTests(unittest.TestCase):
    def test_multiple_calculator_windows_are_left_untouched(self):
        windows = [
            (10, 'Hesap Makinesi', 'calculatorapp'),
            (11, 'Hesap Makinesi', 'calculatorapp'),
        ]
        open_application = mock.Mock()
        handle = mock.Mock()
        desktop_agent = types.SimpleNamespace(
            _BUSY=mock.Mock(locked=mock.Mock(return_value=False)),
            _load=mock.Mock(),
            handle=handle,
        )
        system_control = types.SimpleNamespace(
            _app_windows=mock.Mock(return_value=windows),
            _select_window=mock.Mock(return_value=windows),
            open_application=open_application,
        )
        with mock.patch.object(acceptance_checks.platform, 'system', return_value='Windows'), \
                mock.patch.dict(sys.modules, {
                    'modules.desktop_agent': desktop_agent,
                    'modules.system_control': system_control,
                }), \
                mock.patch.object(modules, 'desktop_agent', desktop_agent, create=True), \
                mock.patch.object(modules, 'system_control', system_control, create=True):
            state, detail = acceptance_checks._desktop_calculator('acceptance-owner')

        self.assertEqual(state, 'pending')
        self.assertIn('Birden fazla', detail)
        open_application.assert_not_called()
        handle.assert_not_called()

    def test_single_calculator_window_is_reused_without_opening_another(self):
        window = (10, 'Hesap Makinesi', 'calculatorapp')
        open_application = mock.Mock()
        handle = mock.Mock()
        desktop_agent = types.SimpleNamespace(
            _BUSY=mock.Mock(locked=mock.Mock(return_value=False)),
            _load=mock.Mock(side_effect=[None, {'id': 'new', 'status': 'done'}]),
            handle=handle,
        )
        system_control = types.SimpleNamespace(
            _app_windows=mock.Mock(return_value=[window]),
            _select_window=mock.Mock(return_value=[window]),
            open_application=open_application,
        )
        with mock.patch.object(acceptance_checks.platform, 'system', return_value='Windows'), \
                mock.patch.dict(sys.modules, {
                    'modules.desktop_agent': desktop_agent,
                    'modules.system_control': system_control,
                }), \
                mock.patch.object(modules, 'desktop_agent', desktop_agent, create=True), \
                mock.patch.object(modules, 'system_control', system_control, create=True):
            state, _detail = acceptance_checks._desktop_calculator('acceptance-owner')

        self.assertEqual(state, 'passed')
        open_application.assert_not_called()
        handle.assert_called_once()


if __name__ == '__main__':
    unittest.main()
