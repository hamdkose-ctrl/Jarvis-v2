import copy
import unittest

from modules import permission_gate as gate


class PermissionGateTests(unittest.TestCase):
    def test_each_class_default_decision(self):
        rows = [
            (gate.READ, gate.ALLOW),
            (gate.LOCAL_REVERSIBLE, gate.ALLOW),
            (gate.LOCAL_DESTRUCTIVE, gate.ASK),
            (gate.EXTERNAL_WRITE, gate.ASK),
            (gate.MESSAGE_OUT, gate.ASK),
            (gate.PUBLISH, gate.ASK),
            (gate.MONEY_CREDENTIAL, gate.DENY),
            (gate.SYSTEM_CONFIG, gate.ASK),
        ]
        for action_class, expected in rows:
            action = {'class': action_class, 'target': 'hedef', 'via': 'desktop'}
            with self.subTest(action_class=action_class):
                result = gate.decide(action, now=100)
                self.assertEqual(result['decision'], expected)
                self.assertEqual(result['class'], action_class)
                self.assertTrue(result['reason'])

    def test_unknown_or_missing_class_is_ask(self):
        for action in [
            {'class': 'bilinmeyen', 'target': 'x', 'via': 'file'},
            {'target': 'x', 'via': 'file'},
        ]:
            with self.subTest(action=action):
                self.assertEqual(gate.decide(action)['decision'], gate.ASK)

    def test_invalid_via_is_ask(self):
        action = {'class': gate.READ, 'target': 'x', 'via': 'unknown'}
        self.assertEqual(gate.decide(action)['decision'], gate.ASK)

    def test_empty_message_or_publish_target_is_ask(self):
        for action_class in [gate.MESSAGE_OUT, gate.PUBLISH]:
            with self.subTest(action_class=action_class):
                action = {'class': action_class, 'target': '   ', 'via': 'outbox'}
                self.assertEqual(gate.decide(action)['decision'], gate.ASK)

    def test_message_grant_allows_exact_unexpired_target_case_insensitive_email(self):
        action = {'class': gate.MESSAGE_OUT, 'target': 'Ahmet@Example.Org', 'via': 'outbox'}
        grants = {gate.MESSAGE_OUT: {'ahmet@example.org': 200}}
        self.assertEqual(gate.decide(action, grants, now=100)['decision'], gate.ALLOW)

    def test_expired_or_other_target_grant_is_ask(self):
        action = {'class': gate.MESSAGE_OUT, 'target': 'ahmet@example.org', 'via': 'outbox'}
        for grants in [
            {gate.MESSAGE_OUT: {'ahmet@example.org': 100}},
            {gate.MESSAGE_OUT: {'ayse@example.org': 200}},
        ]:
            with self.subTest(grants=grants):
                self.assertEqual(gate.decide(action, grants, now=100)['decision'], gate.ASK)

    def test_wildcard_target_or_grant_never_allows(self):
        rows = [
            ({'class': gate.MESSAGE_OUT, 'target': '*', 'via': 'outbox'},
             {gate.MESSAGE_OUT: {'*': 200}}),
            ({'class': gate.MESSAGE_OUT, 'target': 'ahmet@example.org', 'via': 'outbox'},
             {gate.MESSAGE_OUT: {'*': 200}}),
            ({'class': gate.MESSAGE_OUT, 'target': '*', 'via': 'outbox'},
             {gate.MESSAGE_OUT: {'ahmet@example.org': 200}}),
        ]
        for action, grants in rows:
            with self.subTest(action=action, grants=grants):
                self.assertEqual(gate.decide(action, grants, now=100)['decision'], gate.ASK)

    def test_partial_message_target_never_matches(self):
        action = {'class': gate.MESSAGE_OUT, 'target': 'ahmet@example.org', 'via': 'outbox'}
        grants = {gate.MESSAGE_OUT: {'ahmet@': 200}}
        self.assertEqual(gate.decide(action, grants, now=100)['decision'], gate.ASK)

    def test_publish_and_money_grants_cannot_override_policy(self):
        grants = {
            gate.PUBLISH: {'site': 999999},
            gate.MONEY_CREDENTIAL: {'bank': 999999},
        }
        publish = {'class': gate.PUBLISH, 'target': 'site', 'via': 'browser'}
        money = {'class': gate.MONEY_CREDENTIAL, 'target': 'bank', 'via': 'browser'}
        self.assertEqual(gate.decide(publish, grants, now=100)['decision'], gate.ASK)
        self.assertEqual(gate.decide(money, grants, now=100)['decision'], gate.DENY)

    def test_system_config_apps_never_is_deny(self):
        grants = {'apps_never': ['terminal']}
        blocked = {'class': gate.SYSTEM_CONFIG, 'target': 'terminal', 'via': 'system'}
        other = {'class': gate.SYSTEM_CONFIG, 'target': 'ayarlar', 'via': 'system'}
        self.assertEqual(gate.decide(blocked, grants)['decision'], gate.DENY)
        self.assertEqual(gate.decide(other, grants)['decision'], gate.ASK)

    def test_via_does_not_change_same_action_decision(self):
        grants = {gate.MESSAGE_OUT: {'ahmet@example.org': 200}}
        decisions = []
        for via in ['outbox', 'desktop', 'browser', 'file', 'system']:
            action = {'class': gate.MESSAGE_OUT, 'target': 'ahmet@example.org', 'via': via}
            decisions.append(gate.decide(action, grants, now=100)['decision'])
        self.assertEqual(decisions, [gate.ALLOW] * 5)

    def test_inputs_are_not_mutated(self):
        action = {'class': gate.MESSAGE_OUT, 'target': 'Ahmet@Example.Org', 'via': 'outbox'}
        grants = {
            gate.MESSAGE_OUT: {'ahmet@example.org': 200},
            'apps_never': ['terminal'],
        }
        action_before = copy.deepcopy(action)
        grants_before = copy.deepcopy(grants)
        gate.decide(action, grants, now=100)
        self.assertEqual(action, action_before)
        self.assertEqual(grants, grants_before)


if __name__ == '__main__':
    unittest.main()
