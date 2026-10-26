import unittest
from unittest.mock import patch

from modules import browser_agent


class Phase4BrowserWiringTests(unittest.TestCase):
    def test_readonly_browser_validation_uses_readonly_contract(self):
        actions = [{'op': 'goto', 'url': 'https://example.test'}, {'op': 'read'}]
        with patch('modules.browser_readonly.assert_readonly_action') as contract:
            self.assertEqual(browser_agent.validate(actions, read_only=True), actions)
        self.assertEqual(contract.call_count, 2)


if __name__ == '__main__':
    unittest.main()
