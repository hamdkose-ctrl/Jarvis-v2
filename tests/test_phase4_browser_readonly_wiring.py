import json
import unittest
from unittest.mock import patch

from modules import task_workers


class Phase4BrowserReadonlyWiringTests(unittest.TestCase):
    def test_readonly_browser_mode_uses_contract_and_playwright_readonly_flag(self):
        page = {'url': 'https://example.test/guide', 'title': 'Guide', 'text': 'Public guide', 'controls': []}
        with patch('modules.browser_agent.run', side_effect=[
                {'state': 'done', 'page': page},
                {'state': 'done', 'page': page, 'steps': [
                    {'op': 'goto', 'url': page['url'], 'verified': True},
                    {'op': 'read', 'url': page['url'], 'verified': True},
                ]},
        ]) as run, patch('modules.browser_readonly.assert_readonly_action') as contract, \
             patch.object(task_workers.llm, 'ask', return_value=json.dumps({'actions': [{'op': 'read'}]})):
            result = task_workers.browser_task('alice', {
                'url': page['url'], 'instruction': 'Sayfayı özetle.', 'mode': 'readonly',
            })

        self.assertEqual(result['state'], 'done')
        contract.assert_called_once_with({'op': 'read'})
        self.assertEqual(run.call_args_list[0].kwargs['read_only'], True)
        self.assertEqual(run.call_args_list[1].kwargs['read_only'], True)


if __name__ == '__main__':
    unittest.main()
