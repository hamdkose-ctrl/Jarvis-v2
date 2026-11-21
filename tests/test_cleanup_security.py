import ast
import http.cookiejar
import http.client
import logging
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticTests(unittest.TestCase):
    def test_traceback_retains_location_without_secret_message_or_cause(self):
        from modules import diagnostics
        diagnostics._recent.clear()
        with self.assertLogs('jarvis', level='ERROR') as captured:
            try:
                try:
                    raise ValueError('PRIVATE-INPUT secret-token')
                except ValueError as cause:
                    raise RuntimeError('provider-url?key=secret-token') from cause
            except Exception:
                diagnostics.record_failure('tests:provider_failure')
                diagnostics.record_failure('tests:provider_failure')
        self.assertEqual(len(captured.output), 1)
        output = captured.output[0]
        # Source snippets can also contain literal secrets: formatter must omit them.
        self.assertNotIn('secret-token', output)
        self.assertNotIn('PRIVATE-INPUT', output)
        self.assertIn('tests:provider_failure', output)
        self.assertIn('RuntimeError', output)

    def test_every_broad_catch_has_diagnostic(self):
        for file in list(ROOT.glob('*.py')) + list((ROOT/'modules').rglob('*.py')):
            for node in ast.walk(ast.parse(file.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == 'Exception':
                    first = node.body[0]
                    call = first.value.func if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) else None
                    diagnostic = (isinstance(call, ast.Name) and call.id == '_record_failure') or (
                        isinstance(call, ast.Attribute) and call.attr == '_record_failure'
                        and isinstance(call.value, ast.Name) and call.value.id == 'runtime')
                    self.assertTrue(diagnostic,
                                    f'{file.name}:{node.lineno}')

    def test_http_location_fallback_removed(self):
        from modules import weather
        with patch.object(weather, '_cached', return_value=None), patch.object(weather.requests, 'get', side_effect=weather.requests.RequestException()) as get:
            self.assertIsNone(weather.locate_me())
            self.assertEqual(get.call_count, 1)
            self.assertTrue(get.call_args.args[0].startswith('https://'))

    def test_backups_never_publish(self):
        import updater
        from modules import git_publish as publish
        self.assertFalse(updater._publishable_path('.backups/old/main.py'))
        with tempfile.TemporaryDirectory() as folder, patch.object(publish, 'ROOT', Path(folder)):
            hidden = Path(folder)/'.backups'/'old'/'main.py'
            hidden.parent.mkdir(parents=True)
            hidden.write_text('private backup')
            (Path(folder)/'main.py').write_text('public source')
            files = publish._publishable_files()
            self.assertEqual(set(files), {'main.py'})


class DesktopAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_privacy_voice_and_pending
        import web
        cls.web = web
        cls.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def test_query_token_denied_and_header_session_cookie_limits(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base+'/api/snapshot?t='+self.web.TOKEN, data=b'[]', timeout=3)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(error.exception.headers['Connection'], 'close')
        self.assertEqual(error.exception.read(), b'yasak')
        error.exception.close()
        jar = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        request = urllib.request.Request(self.base+'/session', data=b'', headers={'X-Jarvis-Token': self.web.TOKEN})
        with client.open(request, timeout=3) as response:
            cookie = response.headers['Set-Cookie']
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Strict', cookie)
            self.assertNotIn(self.web.TOKEN, cookie)
        self.assertEqual(len(jar), 1)
        # Cookie authenticates GET resources; it must not authorize a command POST.
        with self.assertRaises(urllib.error.HTTPError) as error:
            client.open(self.base+'/api/snapshot', data=b'[]', timeout=3)
        self.assertEqual(error.exception.code, 403)
        with patch.object(self.web.bridge, 'snapshot', return_value={'ready': True}):
            request = urllib.request.Request(self.base+'/api/snapshot', data=b'[]', headers={'X-Jarvis-Token': self.web.TOKEN})
            with client.open(request, timeout=3) as response:
                self.assertIn(b'"ready": true', response.read())
        fake = self.web.Handler.__new__(self.web.Handler)
        fake.server = self.server
        fake.command = 'GET'
        fake.headers = {'Cookie': cookie.split(';')[0]}
        self.assertEqual(fake._token(), self.web.TOKEN)
        fake.headers = {'Cookie': 'jarvis_session_other=wrong'}
        self.assertEqual(fake._token(), '')
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=3)
        connection.request('GET', '/events', headers={'Cookie': cookie.split(';')[0]})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline(), b'retry: 1500\n')
        response.close()
        connection.close()

    def test_rejected_post_drains_only_bounded_body_and_restores_timeout(self):
        for length, transfer, expected in (('2', '', 2), ('65537', '', 0),
                                            ('-1', '', 0), ('bad', '', 0),
                                            ('2', 'chunked', 0)):
            fake = self.web.Handler.__new__(self.web.Handler)
            fake.headers = {'Content-Length': length, 'Transfer-Encoding': transfer}
            fake.connection = Mock()
            fake.connection.gettimeout.return_value = 7
            fake.rfile = Mock()
            fake.rfile.read1.return_value = b'[]'
            fake._send = Mock()
            fake._reject_post()
            self.assertTrue(fake.close_connection)
            if expected:
                fake.rfile.read1.assert_called_once_with(expected)
            else:
                fake.rfile.read1.assert_not_called()
            fake.connection.settimeout.assert_called_with(7)
            fake._send.assert_called_once_with(403, b'yasak', 'text/plain', {'Connection': 'close'})

    def test_rejected_post_read_failure_still_sends_forbidden(self):
        fake = self.web.Handler.__new__(self.web.Handler)
        fake.headers = {'Content-Length': '2'}
        fake.connection = Mock()
        fake.connection.gettimeout.return_value = None
        fake.rfile = Mock()
        fake.rfile.read1.side_effect = TimeoutError()
        fake._send = Mock()
        fake._reject_post()
        fake._send.assert_called_once_with(403, b'yasak', 'text/plain', {'Connection': 'close'})
        fake.connection.settimeout.assert_called_with(None)

    def test_rejected_post_never_dispatches_pipelined_command(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=3)
        self.addCleanup(connection.close)
        body = b'[]POST /api/snapshot HTTP/1.1\r\n\r\n'
        with patch.object(self.web.bridge, 'snapshot') as snapshot:
            connection.request('POST', '/api/snapshot', body=body)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            self.assertEqual(response.getheader('Connection'), 'close')
            self.assertEqual(response.read(), b'yasak')
            response.close()
            snapshot.assert_not_called()

    def test_retired_background_upload_and_view_are_closed(self):
        image = b'\xff\xd8\xfftest-image'
        with tempfile.TemporaryDirectory() as folder, patch.object(self.web, 'DATA_DIR', Path(folder)):
            old_image = Path(folder) / 'arka_plan.img'
            old_image.write_bytes(image)
            request = urllib.request.Request(self.base+'/upload?to=bg&name=bg', data=image, headers={'X-Jarvis-Token': self.web.TOKEN})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(old_image.read_bytes(), image)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base+'/arka_plan?v=1', timeout=3)
            self.assertEqual(error.exception.code, 404)

    def test_desktop_document_limits_external_active_content(self):
        with urllib.request.urlopen(self.base+'/', timeout=3) as response:
            policy = response.headers['Content-Security-Policy']
            directives = dict((part.strip().split(' ', 1) + [''])[:2]
                              for part in policy.split(';'))
            self.assertEqual(directives['connect-src'], "'self'")
            self.assertEqual(directives['object-src'], "'none'")
            self.assertEqual(directives['base-uri'], "'none'")
            self.assertEqual(directives['frame-ancestors'], "'none'")
            self.assertNotIn('https:', directives['script-src'])
            self.assertNotIn('unsafe-eval', directives['script-src'])
            self.assertEqual(directives['frame-src'], 'https://www.youtube-nocookie.com')
            self.assertIn('data:', directives['img-src'])
            self.assertIn('blob:', directives['media-src'])


if __name__ == '__main__':
    unittest.main()
