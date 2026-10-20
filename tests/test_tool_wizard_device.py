import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from modules import llm, permission_policy, tool_contract, tool_wizard


class WizardDeviceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        for module, directory in ((tool_wizard, 'wizard'), (permission_policy, 'policy')):
            p = patch.object(module, 'ROOT', Path(self.tmp.name) / directory)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                case.calls.append(('GET', self.path, None))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                case.assertEqual(self.headers['X-Api-Key'], 'fake-device-key')
                case.calls.append(('POST', self.path, data))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.address = f'http://127.0.0.1:{server.server_port}/device'

    def add(self, **kwargs):
        return tool_wizard.add_device('alice', 'Sahte cihaz', self.address, 'fake-device-key', allow_private=True, **kwargs)

    def test_approval_masking_owner_and_contract(self):
        preview = self.add()
        self.assertEqual(preview['state'], 'approval')
        self.assertNotIn('fake-device-key', json.dumps(preview))
        self.assertEqual(tool_wizard.contracts('alice'), {})
        result = self.add(confirmed=True)
        self.assertNotIn('fake-device-key', json.dumps(result))
        self.assertNotIn(b'fake-device-key', (tool_wizard.ROOT / 'alice.json').read_bytes())
        contract = tool_contract.load_all()[result['id']]
        self.assertEqual(tool_contract.validate(contract), [])
        shown = tool_contract.describe(contract)
        self.assertNotIn(self.address, json.dumps(shown))
        self.assertNotIn('fake-device-key', json.dumps(shown))
        self.assertEqual({a['class'] for a in shown['actions']}, {'read', 'physical'})
        token = llm._key_context.set('bob')
        try:
            self.assertNotIn(result['id'], tool_contract.load_all())
        finally:
            llm._key_context.reset(token)
        self.assertEqual(self.calls, [])

    def test_read_and_physical_approval_deny_and_no_false_physical_claim(self):
        ident = self.add(confirmed=True)['id']
        self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'done')
        self.assertEqual(self.calls, [('GET', '/device', None)])
        payload = {'payload': '{"command":"example"}'}
        self.assertEqual(tool_wizard.execute('alice', ident, payload)['state'], 'approval')
        permission_policy.set('alice', ident, 'physical', 'allow')
        self.assertEqual(tool_wizard.execute('alice', ident, payload)['state'], 'approval')
        result = tool_wizard.execute('alice', ident, payload, approve=True)
        self.assertEqual(result['state'], 'done')
        self.assertIn('doğrulanmadı', result['detail'])
        self.assertEqual(self.calls[-1], ('POST', '/device', {'command': 'example'}))
        self.calls.clear()
        permission_policy.set('alice', ident, 'physical', 'deny')
        self.assertEqual(tool_wizard.execute('alice', ident, payload, approve=True)['state'], 'blocked')
        permission_policy.set('alice', ident, 'read', 'deny')
        self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_private_address_rules_are_explicit_and_metadata_destinations_rejected(self):
        for address in (self.address, 'http://localhost/device', 'http://192.168.1.2/device', 'http://[fd00::1]/device'):
            with self.assertRaises(ValueError):
                tool_wizard.add_device('alice', 'Device', address, 'fake-device-key', confirmed=True)
        for address in ('http://169.254.169.254/latest', 'http://0.0.0.0', 'http://224.0.0.1',
                        'http://user:pass@127.0.0.1', 'http://127.0.0.1/?key=secret', 'http://device.local', 'http://2130706433', 'http://127.0.0.1:0'):
            with self.assertRaises(ValueError):
                tool_wizard.add_device('alice', 'Device', address, 'fake-device-key', allow_private=True, confirmed=True)
        self.assertEqual(tool_wizard.contracts('alice'), {})

    def test_invalid_payload_gate_failure_and_transport_error_are_closed(self):
        ident = self.add(confirmed=True)['id']
        for parameters in ({'payload': 'not json'}, {'payload': '[]'}, {'extra': 'x'}, {'payload': 'x'*21000}):
            self.assertEqual(tool_wizard.execute('alice', ident, parameters, approve=True)['state'], 'blocked')
        with patch.object(permission_policy, 'apply', side_effect=RuntimeError('fake')):
            self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'blocked')
        with patch.object(tool_wizard, '_device_request', side_effect=OSError('fake')):
            self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_busy_cancel_does_not_invent_device_stop_and_redirect_is_rejected(self):
        from modules import tool_printer
        ident = self.add(confirmed=True)['id']
        contract = tool_contract.load_all()[ident]
        tool_wizard._DEVICE_BUSY.add(('alice', ident))
        try:
            self.assertEqual(contract['status']()['state'], 'running')
            self.assertFalse(contract['cancel']()['cancelled'])
            self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'blocked')
        finally:
            tool_wizard._DEVICE_BUSY.discard(('alice', ident))
        with patch.object(tool_printer.requests, 'request') as request:
            request.return_value.__enter__.return_value.status_code = 302
            self.assertEqual(tool_wizard.execute('alice', ident, {}, action='read')['state'], 'blocked')
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
