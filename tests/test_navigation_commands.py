import unittest
from unittest.mock import Mock


class NavigationCommandsTests(unittest.TestCase):
    def setUp(self):
        from tests.test_verified_execution import user_context
        user_context(self)

    def test_local_notes_and_calendar_open_commands(self):
        from modules import selfctl
        for command in ('not sayfasını aç', 'not defterini aç', 'takvimi aç', 'takvim sayfasını aç'):
            with self.subTest(command=command):
                emit = Mock()
                reply = selfctl.handle(command, emit)
                emit.assert_called_once_with('nav', 'tools|takvim')
                self.assertIn('sayfasını açıyorum', reply)

    def test_unnamed_user_request_opens_form_not_creates_user_named_open(self):
        from modules import selfctl
        for command in ('yeni bir kullanıcı aç', 'yeni kullanıcı aç', 'yeni kullanıcı oluştur', 'yeni kullanıcı ekle'):
            emit = Mock()
            self.assertIn('Yeni Kullanıcı', selfctl.handle(command, emit))
            emit.assert_called_once_with('nav', 'settings|kullanici')

    def test_pc_or_windows_qualified_names_are_not_jarvis_pages(self):
        from modules import selfctl
        for command in ('pc ayarlar aç', 'pc ayarlarını aç', 'windows ayarları aç', 'windows ayarlarını aç', 'bilgisayar ayarları aç',
                        'pc not defteri aç', 'pc not defterini aç', 'bilgisayar not defterini aç',
                        'pc ses ayarlarını aç', 'windows ses ayarlarını aç', 'windows gizlilik ayarlarını aç'):
            with self.subTest(command=command):
                emit = Mock()
                self.assertIsNone(selfctl.handle(command, emit))
                emit.assert_not_called()

    def test_jarvis_own_pages_still_open_by_plain_or_jarvis_names(self):
        from modules import selfctl
        for command, target in (('ayarları aç', 'settings|genel'), ('jarvis ayarlarını aç', 'settings|genel'),
                                ('not defterini aç', 'tools|takvim')):
            with self.subTest(command=command):
                emit = Mock()
                self.assertIn('sayfasını açıyorum', selfctl.handle(command, emit))
                emit.assert_called_once_with('nav', target)

    def test_pc_qualifier_is_ignored_when_finding_the_windows_app(self):
        from unittest.mock import patch
        from modules import system_control
        with patch.object(system_control, '_match_installed', side_effect=lambda n: ('Ayarlar', 'appid', 'x') if n == 'ayarlar' else None):
            for spoken in ('pc ayarlar', 'windows ayarları', 'bilgisayar ayarlarını', 'ayarlar'):
                with self.subTest(spoken=spoken):
                    self.assertEqual(system_control.find_app(spoken), 'Ayarlar')
        with patch.object(system_control, '_match_installed', return_value=None):
            for spoken in ('pc not defteri', 'pc not defterini', 'bilgisayar not defteri'):
                with self.subTest(spoken=spoken):
                    self.assertEqual(system_control.find_app(spoken), 'not defteri')

    def test_fixed_app_launch_holds_no_pipes_so_slow_apps_cannot_time_it_out(self):
        import subprocess
        from unittest.mock import patch
        from modules import system_control
        with patch.object(system_control.subprocess, 'run', return_value=Mock(returncode=0)) as run,              patch.object(system_control, '_visible_application', side_effect=[None, 1]),              patch.object(system_control.logging, 'getLogger'):
            self.assertTrue(system_control.open_application('paint').ok)
        kwargs = run.call_args.kwargs
        self.assertNotIn('capture_output', kwargs)
        for stream in ('stdin', 'stdout', 'stderr'):
            self.assertIs(kwargs[stream], subprocess.DEVNULL)

    def test_windows_settings_pages_open_by_topic_and_stay_separate_from_jarvis_pages(self):
        from unittest.mock import patch
        from modules import system_control
        cases = (('wifi ayarlarını aç', 'network-wifi'), ('bluetooth ayarlarını aç', 'bluetooth'), ('ekran ayarlarını aç', 'display'),
                 ('güncelleme ayarlarını aç', 'windowsupdate'), ('pc ses ayarlarını aç', 'sound'),
                 ('windows gizlilik ayarlarını aç', 'privacy'), ('karanlık mod ayarlarını göster', 'colors'))
        for command, page in cases:
            from types import SimpleNamespace
            start=Mock()
            windows_os=SimpleNamespace(**vars(system_control.os));windows_os.name='nt';windows_os.startfile=start
            with self.subTest(command=command), patch.object(system_control,'os',windows_os), patch.object(system_control, '_visible_application', return_value=1):
                reply = system_control.windows_settings(command)
                start.assert_called_once_with('ms-settings:' + page)
                self.assertTrue(reply.ok)
        for command in ('ses ayarlarını aç', 'gizlilik ayarlarını aç', 'jarvis ekran ayarlarını aç', 'ayarları aç',
                        'pc ayarlarını aç', 'wifi ayarları nedir', 'hafıza sayfasını aç'):
            with self.subTest(command=command), patch.object(system_control.os, 'startfile', create=True) as start:
                self.assertIsNone(system_control.windows_settings(command))
                start.assert_not_called()

    def test_windows_settings_does_not_claim_success_without_a_window(self):
        from unittest.mock import patch
        from modules import system_control
        clock = iter([0, 0, 11, 11, 11])
        from types import SimpleNamespace
        windows_os=SimpleNamespace(**vars(system_control.os));windows_os.name='nt';windows_os.startfile=Mock()
        with patch.object(system_control,'os',windows_os), patch.object(system_control, '_visible_application', return_value=None), patch.object(system_control.time, 'monotonic', side_effect=lambda: next(clock)), patch.object(system_control.time, 'sleep'):
            reply = system_control.windows_settings('wifi ayarlarını aç')
        self.assertFalse(reply.ok)
        self.assertIn('Açıldı demiyorum', reply)

    def test_windows_settings_on_non_windows_do_not_launch_or_claim_success(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from modules import system_control
        other_os=SimpleNamespace(**vars(system_control.os));other_os.name='posix';other_os.startfile=Mock()
        with patch.object(system_control,'os',other_os):reply=system_control.windows_settings('wifi ayarlarını aç')
        other_os.startfile.assert_not_called();self.assertFalse(reply.ok)
        self.assertIn("yalnız Windows'ta",reply)

    def test_live_prompt_keeps_pc_and_windows_qualifier_for_the_engine(self):
        from modules import live
        prompt = live.build_prompt('Jarvis', 'Hamdi', '')
        self.assertIn('SİLMEDEN', prompt)
        self.assertIn('PC ayarlarını aç', prompt)

    def test_singular_and_plural_pc_settings_both_find_the_windows_app(self):
        from unittest.mock import patch
        from modules import system_control
        with patch.object(system_control, '_match_installed', side_effect=lambda n: ('Ayarlar', 'appid', 'x') if n == 'ayarlar' else None):
            for spoken in ('pc ayarını', 'pc ayarları', 'windows ayarı', 'windows ayarlarını'):
                with self.subTest(spoken=spoken):
                    self.assertEqual(system_control.find_app(spoken), 'Ayarlar')

    def test_real_note_content_is_not_navigation(self):
        from modules import selfctl
        emit = Mock()
        self.assertIsNone(selfctl.handle('not ekle: kapıyı aç', emit))
        emit.assert_not_called()
