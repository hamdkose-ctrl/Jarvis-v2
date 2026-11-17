import tempfile
import unittest
from pathlib import Path


class ArchitectureGuardTests(unittest.TestCase):
    def setUp(self):
        from modules import architecture_guard
        self.guard = architecture_guard

    def _scan_source(self, source: str, name='rogue.py'):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            modules = root / 'modules'
            modules.mkdir()
            (modules / name).write_text(source, encoding='utf-8')
            return self.guard.scan(root)

    def test_current_repository_has_no_stage_0_4_blockers(self):
        root = Path(__file__).resolve().parents[1]
        report = self.guard.scan(root)
        self.assertEqual(report['blockers'], [], report)
        self.assertEqual(report['scope'], 'stage-0-4')

    def test_ui_cannot_adopt_new_goal_control_or_execution_adapter_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for module in ('core_brain_adapter', 'canonical_goal_control', 'canonical_plan_revision', 'canonical_planning_queue',
                           'goal_approval','brain_batch_checkpoint'):
                with self.subTest(module=module):
                    (root / 'web_team.py').write_text(f'from modules import {module}\n', encoding='utf-8')
                    report = self.guard.scan(root)
                    self.assertIn('ARCH-006', {row['rule'] for row in report['blockers']})

    def test_direct_goalstate_cas_outside_canonical_adapters_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_durable_plan_task_requires_explicit_decision_context(self):
        report = self._scan_source(
            "from modules import runtime_execution_gate\n"
            "runtime_execution_gate.plan_task('coder', {}, approval_verified=False)\n"
        )
        self.assertIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_new_direct_goal_tools_executor_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_tools\n"
            "goal_tools.execute(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_worker_result_execute_outside_durable_orchestrator_is_blocker(self):
        report = self._scan_source(
            "from modules import worker_result_hook\n"
            "worker_result_hook.execute(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-007', {row['rule'] for row in report['blockers']})

    def test_runtime_event_subscription_gap_is_warning_not_blocker(self):
        report = self._scan_source("x = 1\n")
        self.assertIn('ARCH-W001', {row['rule'] for row in report['warnings']})
        self.assertNotIn('ARCH-W001', {row['rule'] for row in report['blockers']})

    def test_current_repository_has_production_runtime_event_producer(self):
        root = Path(__file__).resolve().parents[1]
        report = self.guard.scan(root)
        self.assertNotIn('ARCH-W001', {row['rule'] for row in report['warnings']})

    # -- Alias hardening -------------------------------------------------

    def test_from_import_function_alias_direct_call_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_tools import execute as run_tool\n"
            "run_tool(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_module_alias_attribute_call_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_tools as tools\n"
            "tools.execute(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_cas_function_alias_direct_call_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compare_and_swap as cas\n"
            "cas(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_gate_module_alias_attribute_call_without_context_is_blocker(self):
        report = self._scan_source(
            "import modules.runtime_execution_gate as gate\n"
            "gate.plan_task('coder', {}, approval_verified=False)\n"
        )
        self.assertIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_gate_module_alias_attribute_call_with_explicit_context_is_clean(self):
        report = self._scan_source(
            "import modules.runtime_execution_gate as gate\n"
            "gate.plan_task(\n"
            "    'coder', {}, approval_verified=False,\n"
            "    domain_invariant=1, domain_authority=2, user_authority=3,\n"
            "    job_authority=4, effect_state=5,\n"
            ")\n"
        )
        self.assertNotIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_cas_alias_inside_allowlisted_adapter_is_not_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compare_and_swap as cas\n"
            "cas(path, expected_version=1, next_state={})\n",
            name='goal_state_compat.py',
        )
        self.assertNotIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_execute_alias_inside_allowlisted_caller_is_not_blocker(self):
        report = self._scan_source(
            "import modules.goal_tools as tools\n"
            "tools.execute(runtime, 'publish', {}, {}, identity)\n",
            name='worker_result_hook.py',
        )
        self.assertNotIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_direct_call_rules_still_detected_without_alias(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    # -- Canonical GoalState storage writer allowlists ---------------------

    def test_direct_goalstate_create_outside_compat_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_function_alias_outside_compat_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import create as make\n"
            "make(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_module_alias_outside_compat_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_state_store as store\n"
            "store.create(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_inside_compat_adapter_is_clean(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n",
            name='goal_state_compat.py',
        )
        self.assertNotIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_direct_goalstate_compensate_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compensate(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_module_alias_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_state_store as store\n"
            "store.compensate(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_function_alias_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compensate as undo\n"
            "undo(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_inside_save_hook_is_clean(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compensate(path, previous_state={}, new_state={})\n",
            name='goal_state_save_hook.py',
        )
        self.assertNotIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_writer_allowlists_are_not_cross_permission(self):
        # Being inside the CAS adapter set does not authorize create().
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n",
            name='worker_result_commit.py',
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_cas_allowlist_behavior_is_unchanged(self):
        for name in ('worker_result_commit.py', 'runtime_event_commit.py'):
            report = self._scan_source(
                "from modules import goal_state_store\n"
                "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n",
                name=name,
            )
            self.assertNotIn('ARCH-001', {row['rule'] for row in report['blockers']}, name)
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n",
            name='goal_state_save_hook.py',
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    # -- BRAIN-03 dilim 2: semantik yetki (§7) -------------------------------
    #
    # Kural yetenek ADINI değil SAHİBİNİ denetler: ham cümleden yetenek seçen bir yüzey ya da
    # modelden yasaklayan bir küme, hangi dosyada veya hangi adla durduğu fark etmeksizin blocker.
    # Bu yüzden taşıma (`modules/xxx.py`'ya kopyalamak) ve yeniden adlandırma (`_pick_message`)
    # ihlali silmez; öteki yandan biçim/güvenlik denetimleri (numara regex'i, kapalı enum)
    # yetenek adı taşımadığı için hiç denetlenmez.

    def _semantic_blockers(self, source, name='rogue.py'):
        rows = self._scan_source(source, name=name)['blockers']
        return [row for row in rows if row['rule'] == 'ARCH-008']

    def test_a_word_list_that_picks_the_message_capability_is_a_blocker(self):
        report = self._semantic_blockers(
            "import re\n"
            "def _pick_message(text):\n"
            "    return 'message.send' if re.search(r'whatsapp|mesaj', text) else None\n"
        )
        self.assertEqual(len(report), 1, report)

    def test_a_contact_grammar_in_a_renamed_helper_is_still_a_blocker(self):
        # Dosya adı ve fonksiyon adı farklı: literalin sahibi denetlenir, adı değil.
        report = self._semantic_blockers(
            "import re\n"
            "KALIP = re.compile(r'rehbere ekle')\n"
            "def rehber_yorumu(text):\n"
            "    return 'contacts.manage' if KALIP.search(text) else None\n"
        )
        self.assertEqual(len(report), 1, report)

    def test_banning_the_model_from_a_user_owned_capability_is_a_blocker(self):
        report = self._semantic_blockers(
            "_DENIED = frozenset({'message.send', 'contacts.manage'})\n"
        )
        self.assertEqual(len(report), 2, report)

    def test_carrying_the_canonical_constant_outside_its_owner_is_a_blocker(self):
        # Taşımanın ikinci yolu: literal yerine sabiti import edip yüzeyde kullanmak.
        report = self._semantic_blockers(
            "from modules.brain_understanding import MESSAGE_SEND_CAPABILITY\n"
            "def _pick(text):\n"
            "    return MESSAGE_SEND_CAPABILITY if 'whatsapp' in text else None\n"
        )
        self.assertEqual(len(report), 1, report)

    def test_the_owner_definition_of_the_capability_is_not_a_blocker(self):
        self.assertEqual(self._semantic_blockers(
            'MESSAGE_SEND_CAPABILITY = "message.send"\n'
            'CONTACTS_MANAGE_CAPABILITY = "contacts.manage"\n',
            name='brain_understanding.py',
        ), [])

    def test_the_core_intent_table_key_is_not_a_blocker(self):
        self.assertEqual(self._semantic_blockers(
            "from modules.brain_understanding import (\n"
            "    CONTACTS_MANAGE_CAPABILITY, MESSAGE_SEND_CAPABILITY)\n"
            "CORE_INTENTS = {\n"
            "    MESSAGE_SEND_CAPABILITY: ('message_send', _message_args),\n"
            "    CONTACTS_MANAGE_CAPABILITY: ('contacts_manage', _contacts_args),\n"
            "}\n",
            name='brain_core_map.py',
        ), [])

    def test_the_grounding_contract_table_is_not_a_blocker(self):
        # Zarfın dayanak sözleşmesi de kapalı bir tablodur: yetenek ADI burada durur, karar değil.
        self.assertEqual(self._semantic_blockers(
            "_USER_OWNED_ARGUMENT_SLOTS = {\n"
            "    'message.send': frozenset({'recipient', 'body'}),\n"
            "    'contacts.manage': frozenset({'name', 'phone'}),\n"
            "}\n",
            name='brain_model_understanding.py',
        ), [])

    def test_a_renamed_denial_table_is_still_a_blocker(self):
        # Tabloyu meşru bir ada benzetmek yetmez: yalnız kapalı sözleşme tablosu exemption alır.
        self.assertEqual(len(self._semantic_blockers(
            "_MODEL_YASAK_KUME = frozenset({'message.send'})\n",
            name='brain_model_understanding.py',
        )), 1)

    def test_the_purpose_contract_table_is_not_a_blocker(self):
        # Amaç/önkoşul parite tablosu da kapalı sözleşme tablosudur: yetenek ADI anahtar olarak
        # durur, karar ya da yasak kümesi üretilmez; red kümesi yine aynı dosyada BLOCKER'dır.
        self.assertEqual(self._semantic_blockers(
            "_CAPABILITY_PURPOSES = {\n"
            "    'message.send': ('send a text message to a named contact', 'bounded recipient/body'),\n"
            "    'contacts.manage': ('add or list a contact', 'closed operation set'),\n"
            "}\n",
            name='brain_model_understanding.py',
        ), [])

    def test_format_and_security_controls_are_not_blocked(self):
        # İzin verilen deterministik denetimler: numara biçimi, kapalı enum, tip sınırı.
        self.assertEqual(self._semantic_blockers(
            "import re\n"
            "_PHONE = re.compile(r'^90\\d{10}$')\n"
            "_OPERATIONS = frozenset({'add', 'list'})\n"
            "def _args(arguments):\n"
            "    return {'phone': arguments['phone']} if _PHONE.fullmatch(arguments['phone']) else None\n"
        ), [])


if __name__ == '__main__':
    unittest.main()

