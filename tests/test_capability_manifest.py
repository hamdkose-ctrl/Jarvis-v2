import copy
import json
import unittest


class CapabilityManifestTests(unittest.TestCase):
    def setUp(self):
        from modules import capability_manifest
        self.manifest = capability_manifest

    def test_current_catalogs_become_json_only_read_and_effect_views(self):
        catalog = self.manifest.catalog()
        rows = {row['id']: row for row in catalog['capabilities']}

        read = rows['task.research']
        self.assertEqual(read['permission_class'], 'read')
        self.assertEqual(read['effect_policy'], 'read_only')

        effect = rows['task.publish']
        self.assertEqual(effect['permission_class'], 'publish')
        self.assertEqual(effect['effect_policy'], 'external_write')

        self.assertIn('goal.document', rows)
        self.assertEqual(catalog['version'], 1)
        json.dumps(catalog, ensure_ascii=False)
        self.assertFalse(self._contains_callable(catalog))

    def test_existing_goal_and_tool_discovery_remain_visible(self):
        from modules import goal_tools, tool_contract

        catalog = self.manifest.catalog()
        ids = {row['id'] for row in catalog['capabilities']}
        self.assertTrue({f'goal.{kind}' for kind in goal_tools.LOCAL}.issubset(ids))

        discovered = tool_contract.load_all()
        for contract in discovered.values():
            for action in contract['actions']:
                suffix = '' if len(contract['actions']) == 1 else '.' + action['id']
                self.assertIn(f"tool.{contract['id']}{suffix}", ids)

    def test_tool_contract_binding_is_not_exposed_in_manifest_json(self):
        contract = {
            'id': 'demo', 'name': 'Demo', 'area': 'test', 'icon': 'gear',
            'actions': [{'id': 'run', 'name': 'Çalıştır', 'desc': 'Demo',
                         'class': 'read', 'params': {}}],
            'status': lambda: {'state': 'ready', 'detail': 'Hazır'},
            'cancel': lambda: None,
        }
        row = self.manifest.from_tool_contract(contract)
        self.assertEqual(row['id'], 'tool.demo')
        self.assertNotIn('status', row)
        self.assertNotIn('cancel', row)
        json.dumps(row, ensure_ascii=False)
        self.assertFalse(self._contains_callable(row))

    def test_duplicate_and_unknown_policy_values_fail_closed(self):
        row = self.manifest.from_task_tool('research')
        with self.assertRaises(ValueError):
            self.manifest.validate_catalog([row, copy.deepcopy(row)])
        for field, value in (
            ('permission_class', 'invented'),
            ('effect_policy', 'invented'),
            ('version', 99),
        ):
            with self.subTest(field=field):
                bad = copy.deepcopy(row)
                bad[field] = value
                with self.assertRaises(ValueError):
                    self.manifest.validate_catalog([bad])

    @staticmethod
    def _contains_callable(value):
        if callable(value):
            return True
        if isinstance(value, dict):
            return any(CapabilityManifestTests._contains_callable(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(CapabilityManifestTests._contains_callable(item) for item in value)
        return False


if __name__ == '__main__':
    unittest.main()
