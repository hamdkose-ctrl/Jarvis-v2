import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from modules import llm, permission_policy, tool_contract, tool_printer


class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.actor = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, self.actor)
        self.patches = [patch.object(tool_printer, 'ROOT', Path(self.tmp.name) / 'printer'),
                        patch.object(permission_policy, 'ROOT', Path(self.tmp.name) / 'policy')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.printing = True
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                case.calls.append(('GET', self.path, None))
                self.send_response(200)
                self.end_headers()
                data = ({'state': 'Printing' if case.printing else 'Operational'}
                        if self.path == '/api/job' else
                        {'result': {'status': {'print_stats': {'state': 'printing' if case.printing else 'cancelled'}}}})
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                case.calls.append(('POST', self.path, data))
                case.assertEqual(self.headers.get('X-Api-Key'), 'fake-test-key')
                if self.path.endswith('/cancel') or data.get('command') == 'cancel':
                    case.printing = False
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.address = f'http://127.0.0.1:{self.server.server_port}'

    def configure(self, backend='octoprint'):
        return tool_printer.configure('alice', backend, self.address, 'fake-test-key')

    def test_contract_and_private_masked_configuration(self):
        self.assertEqual(tool_contract.validate(tool_printer.CONTRACT), [])
        self.assertEqual({a['class'] for a in tool_printer.CONTRACT['actions']}, {'physical'})
        config = self.configure()
        self.assertNotIn(self.address, json.dumps(config))
        self.assertNotIn('fake-test-key', json.dumps(config))
        self.assertNotIn(b'fake-test-key', (tool_printer.ROOT / 'alice.json').read_bytes())
        with patch.object(llm, '_key_context') as actor:
            actor.get.return_value = 'bob'
            self.assertEqual(tool_printer.status()['state'], 'not_connected')
            with self.assertRaises(PermissionError):
                self.configure()
        self.assertEqual(self.calls, [])

    def test_each_action_requires_approval_and_deny_overrides(self):
        self.configure()
        self.assertEqual(tool_printer.run('alice', 'pause')['state'], 'approval')
        permission_policy.set('alice', 'printer', 'physical', 'allow')
        self.assertEqual(tool_printer.run('alice', 'pause')['state'], 'approval')
        permission_policy.set('alice', 'printer', 'physical', 'deny')
        self.assertEqual(tool_printer.run('alice', 'pause', approve=True)['state'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_both_backends_cancel_and_read_back(self):
        for backend, endpoint in [('octoprint', '/api/job'), ('moonraker', '/printer/print/cancel')]:
            with self.subTest(backend=backend):
                self.printing = True
                self.configure(backend)
                self.assertEqual(tool_printer.status()['state'], 'running')
                self.assertEqual(tool_printer.cancel()['state'], 'approval')
                self.assertFalse(any(row[0] == 'POST' for row in self.calls))
                result = tool_printer.run('alice', 'cancel', approve=True)
                self.assertEqual(result['state'], 'done')
                self.assertIn(('POST', endpoint, {'command': 'cancel'} if backend == 'octoprint' else {}), self.calls)
                self.assertEqual(tool_printer.status()['state'], 'ready')
                self.calls.clear()

    def test_stop_calls_only_running_contracts_in_scoped_confirmation(self):
        self.configure()
        tool_printer.cancel_running('alice')
        self.assertFalse(self.printing)
        self.calls.clear()
        tool_printer.cancel_running('alice')
        self.assertFalse(any(row[0] == 'POST' for row in self.calls))
        self.assertEqual(tool_printer.cancel()['state'], 'approval')

    def test_fail_closed_and_invalid_configuration(self):
        self.configure()
        with patch.object(permission_policy, 'apply', side_effect=RuntimeError('test')):
            self.assertEqual(tool_printer.run('alice', 'cancel', approve=True)['state'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_stop_bridge_invokes_tools_before_request_cancel(self):
        import ast
        import types
        tree = ast.parse(Path('web.py').read_text(encoding='utf-8'))
        bridge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
        method = next(n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name == 'stop_task')
        events = []
        namespace = {'_p': lambda: types.SimpleNamespace(slug='alice'),
                     'engine': types.SimpleNamespace(requests_state=types.SimpleNamespace(cancel=lambda owner: events.append(('request', owner)))),
                     'hub': types.SimpleNamespace(publish=lambda *args: None)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'web.py', 'exec'), namespace)
        with patch.object(tool_printer, 'cancel_running', side_effect=lambda owner: events.append(('tools', owner))):
            namespace['stop_task'](None)
        self.assertEqual(events, [('tools', 'alice'), ('request', 'alice')])

    def test_no_false_cancel_success_or_redirect_following(self):
        self.configure()
        with patch.object(tool_printer, '_http', return_value={'state': 'Printing'}):
            self.assertEqual(tool_printer.run('alice', 'cancel', approve=True)['state'], 'unverified')
        with patch.object(tool_printer.requests, 'request') as request:
            request.return_value.__enter__.return_value.status_code = 302
            self.assertEqual(tool_printer.run('alice', 'cancel', approve=True)['state'], 'blocked')
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            self.assertNotIn('verify', request.call_args.kwargs)

    def test_rejects_invalid_addresses_owner_and_filename(self):
        self.configure()
        for address in ['file:///tmp/a', 'http://user:secret@localhost', 'http://localhost/?key=x', 'http://localhost/#a']:
            with self.assertRaises(ValueError):
                tool_printer.configure('alice', 'octoprint', address, 'fake-test-key')
        with self.assertRaises(ValueError):
            tool_printer.configure('../bob', 'octoprint', self.address, 'fake-test-key')
        self.assertEqual(tool_printer.run('alice', 'start', filename='../bad', approve=True)['state'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_stop_isolates_failed_tool_and_ignores_idle(self):
        from unittest.mock import Mock
        idle, running = Mock(), Mock(return_value={'cancelled': True})
        contracts = {'bad': {'id': 'bad', 'status': Mock(side_effect=ValueError('fake')), 'cancel': Mock()},
                     'idle': {'id': 'idle', 'status': lambda: {'state': 'ready'}, 'cancel': idle},
                     'running': {'id': 'running', 'status': lambda: {'state': 'running'}, 'cancel': running}}
        with patch.object(tool_contract, 'load_all', return_value=contracts):
            result = tool_printer.cancel_running('alice')
        self.assertEqual(result['bad']['state'], 'error')
        self.assertTrue(result['running']['cancelled'])
        running.assert_called_once_with()
        idle.assert_not_called()

    def test_approved_start_pause_resume_use_fixed_endpoints(self):
        for backend in ('octoprint', 'moonraker'):
            self.configure(backend)
            for action in ('start', 'pause', 'resume'):
                with self.subTest(backend=backend, action=action):
                    self.calls.clear()
                    result = tool_printer.run('alice', action, filename='part.gcode', approve=True)
                    self.assertEqual(result['state'], 'done')
                    posts = [row for row in self.calls if row[0] == 'POST']
                    self.assertEqual(len(posts), 1)
                    if backend == 'moonraker':
                        self.assertEqual(posts[0][1], '/printer/print/' + action)
                    elif action == 'start':
                        self.assertEqual(posts[0][1:], ('/api/files/local/part.gcode', {'command': 'select', 'print': True}))
                    else:
                        self.assertEqual(posts[0][1:], ('/api/job', {'command': 'pause', 'action': action}))


if __name__ == '__main__':
    unittest.main()
