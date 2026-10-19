"""Browser permission gate integration: deny can only tighten existing approval policy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import browser_agent as browser


class BrowserPermissionGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = patch.object(browser, 'STORE', Path(self.tmp.name))
        store.start()
        self.addCleanup(store.stop)

    def page(self, *, url='https://shop.example.com/form', signature=None):
        page = Mock()
        page.url = url
        page.title.return_value = 'Form'
        item = Mock()
        item.count.return_value = 1
        item.is_visible.return_value = True
        item.get_attribute.return_value = None
        item.evaluate.return_value = signature or json.dumps({
            'tag': 'button', 'type': '', 'id': 'send', 'name': '',
            'text': 'Gönder', 'href': '', 'formAction': '', 'formMethod': ''
        })
        page.locator.return_value = item
        item.inner_text.return_value = 'Form Text'
        return page, item

    def test_money_action_is_denied_before_preview_or_click_and_uses_domain_target(self):
        signature = json.dumps({
            'tag': 'button', 'type': '', 'id': 'pay', 'name': '',
            'text': 'Öde', 'href': '', 'formAction': '', 'formMethod': ''
        })
        page, item = self.page(url='https://shop.example.com/checkout?step=2', signature=signature)
        root = browser._root('alice')
        action = {'op': 'click', 'selector': '#pay', 'expect_text': 'paid'}
        with patch('modules.permission_grants.load', return_value={}), \
             patch('modules.permission_audit.record') as audit:
            with self.assertRaisesRegex(ValueError, 'Para ve kimlik'):
                browser._execute(page, root, [action], owner='alice')
        item.click.assert_not_called()
        self.assertFalse((root / 'pending.json').exists())
        args = audit.call_args.args
        self.assertEqual(args[1], 'deny')
        self.assertEqual(args[3], 'shop.example.com')
        self.assertEqual(args[4], 'browser')

    def test_ask_reason_is_visible_but_existing_click_approval_still_controls(self):
        page, item = self.page()
        root = browser._root('alice')
        action = {'op': 'click', 'selector': '#send', 'expect_text': 'sent'}
        with patch('modules.permission_grants.load', return_value={}), \
             patch('modules.permission_audit.record'):
            result = browser._execute(page, root, [action], owner='alice')
        self.assertEqual(result['state'], 'approval')
        self.assertIn('Mesaj gönderimi hedef onayı ister.', result['message'])
        item.click.assert_not_called()

    def test_allow_never_removes_existing_interactive_approval(self):
        signature = json.dumps({
            'tag': 'button', 'type': '', 'id': 'read', 'name': '',
            'text': 'Oku', 'href': '', 'formAction': '', 'formMethod': ''
        })
        page, item = self.page(signature=signature)
        root = browser._root('alice')
        action = {'op': 'click', 'selector': '#read', 'expect_text': 'opened'}
        with patch('modules.permission_grants.load', return_value={}), \
             patch('modules.permission_audit.record'):
            result = browser._execute(page, root, [action], owner='alice')
        self.assertEqual(result['state'], 'approval')
        item.click.assert_not_called()

    def test_every_previewed_action_is_gated_without_exposing_fill_value(self):
        signature = json.dumps({
            'tag': 'button', 'type': '', 'id': 'next', 'name': '',
            'text': 'Devam', 'href': '', 'formAction': '', 'formMethod': ''
        })
        page, item = self.page(signature=signature)
        root = browser._root('alice')
        actions = [
            {'op': 'click', 'selector': '#next', 'expect_text': 'next'},
            {'op': 'fill', 'selector': '#password', 'value': 'PRIVATE'},
        ]
        with patch('modules.permission_grants.load', return_value={}), \
             patch('modules.permission_audit.record'):
            with self.assertRaisesRegex(ValueError, 'Para ve kimlik') as caught:
                browser._execute(page, root, actions, owner='alice')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertFalse((root / 'pending.json').exists())
        item.click.assert_not_called()
        item.fill.assert_not_called()

    def test_gate_failure_fails_closed_before_browser_effect(self):
        page, item = self.page()
        root = browser._root('alice')
        action = {'op': 'click', 'selector': '#send', 'expect_text': 'sent'}
        with patch('modules.permission_classify.classify_detail', side_effect=RuntimeError('PRIVATE')):
            with self.assertRaisesRegex(ValueError, 'İzin denetimi tamamlanamadı') as caught:
                browser._execute(page, root, [action], owner='alice')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertFalse((root / 'pending.json').exists())
        item.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
