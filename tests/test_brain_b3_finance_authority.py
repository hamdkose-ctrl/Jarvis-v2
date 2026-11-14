"""BRAIN-03 dilim 3: model-owned finance price requests (BRAIN-MIG-101).

Envanter yeri: `JARVIS_BRAIN_MIGRATION_MAP_V1.md` §13.1 `finance.answer` satırı; karar
tablosu §14 satır 17. Retire edilen yüzey kapısı `modules/engine_commands.py` içindeydi:

    from modules import finance
    rate_reply = finance.answer(command)
    if rate_reply is not None:
        return rate_reply

Yani kur/kripto/altın/BIST cümlesini **domain modülü** ham metinden ayırıp capability'yi
kendisi seçiyordu. Yeni zincir: anlam kararı birincil model zarfında, biçim hükmü
Core'da (kapalı para birimi/hisse/altın kümeleri, pozitif sonlu miktar), etki tek
`finance_read` intent'inde; domain yalnız **veri çeker ve biçimlendirir** (`answer_request`).

Testler model zarfının üretim zincirine bağlandığını doğrular; modelin semantik doğruluğu
yerel taklitlerle kanıtlanmış sayılmaz.
"""
from __future__ import annotations
from provider_fixture import routed_plan

import ast
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_brain_pr3_raw_text_authority as pr3a  # noqa: E402  (kanonical harness'ın tek sahibi)
from modules import brain_core_map, engine_intents, finance  # noqa: E402
from modules import brain_understanding as understanding  # noqa: E402
from modules.brain_contracts import RequestKind  # noqa: E402

ENGINE_COMMANDS = ROOT / "modules" / "engine_commands.py"
FINANCE = ROOT / "modules" / "finance.py"


def _hint(text: str) -> str | None:
    return understanding._capability_hint(understanding._norm(text), understanding.TemporalNeed.STATIC)


def _calls(path: Path, marker: str) -> set[str]:
    """`marker` (örn. "finance.answer") çağrısının sahibi dosyalar; tanımlar sayılmaz."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    owners: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            text = ast.unparse(target) if hasattr(ast, "unparse") else ""
            if text.endswith(marker):
                owners.add(str(path.relative_to(ROOT)).replace("\\", "/"))
    return owners


class FinanceCapabilityContractTests(unittest.TestCase):
    """Kanonical sözleşme: hint → Core intent → doğrulanmış tipli argüman."""

    def test_the_capability_exists_and_is_core_mapped(self):
        self.assertEqual(understanding.FINANCE_READ_CAPABILITY, "finance.read")
        self.assertEqual(brain_core_map.CORE_INTENTS["finance.read"][0], "finance_read")

    def test_the_rate_slots_are_form_checked_against_closed_currency_sets(self):
        validate = brain_core_map.CORE_INTENTS["finance.read"][1]
        self.assertEqual(validate({"kind": "rate", "source": "USD", "target": "TRY"}),
                         {"kind": "rate", "source": "USD", "target": "TRY"})
        self.assertEqual(validate({"kind": "rate", "amount": "100", "source": "USD", "target": "EUR"}),
                         {"kind": "rate", "amount": "100", "source": "USD", "target": "EUR"})
        self.assertEqual(validate({"kind": "rate", "codes": ["USD", "EUR"]}),
                         {"kind": "rate", "codes": ["USD", "EUR"]})

    def test_core_rejects_malformed_or_invented_finance_slots(self):
        validate = brain_core_map.CORE_INTENTS["finance.read"][1]
        for arguments in (
                {},                                                        # kind yok
                {"kind": "trade", "source": "USD", "target": "TRY"},       # kapalı kümede yok
                {"kind": "rate", "source": "XXX", "target": "TRY"},        # uydurma kod
                {"kind": "rate", "source": "USD", "target": "BTC"},        # hedef para birimi değil
                {"kind": "rate"},                                          # kaynak/hedef yok
                {"kind": "rate", "source": "USD", "target": "TRY", "codes": ["USD"]},
                {"kind": "rate", "codes": []},                             # boş liste
                {"kind": "rate", "codes": ["USD", "XXX"]},
                {"kind": "rate", "amount": "-5", "source": "USD", "target": "TRY"},
                {"kind": "rate", "amount": "0", "source": "USD", "target": "TRY"},
                {"kind": "rate", "amount": "abc", "source": "USD", "target": "TRY"},
                {"kind": "rate", "amount": "1" * 20, "source": "USD", "target": "TRY"},
                {"kind": "rate", "source": "USD", "target": "TRY", "path": "C:/gizli.txt"},
                {"kind": "asset", "asset": "PAXG"},                        # kapalı kümede yok
                {"kind": "asset", "asset": "GOLD", "gold_kind": "kulce"},
                {"kind": "stock", "stock": "XXXXX"}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(validate(arguments))

    def test_the_asset_and_stock_slots_are_typed(self):
        validate = brain_core_map.CORE_INTENTS["finance.read"][1]
        self.assertEqual(validate({"kind": "asset", "asset": "BTC"}),
                         {"kind": "asset", "asset": "BTC", "target": "TRY"})
        self.assertEqual(validate({"kind": "asset", "asset": "GOLD", "gold_kind": "gram", "target": "USD"}),
                         {"kind": "asset", "asset": "GOLD", "gold_kind": "gram", "target": "USD"})
        self.assertEqual(validate({"kind": "stock", "stock": "THYAO"}), {"kind": "stock", "stock": "THYAO"})

    def test_a_rejected_proposal_produces_no_core_plan(self):
        self.assertIsNone(brain_core_map.core_plan("finance.read", {"kind": "rate", "source": "XXX"}))
        self.assertTrue(brain_core_map.core_plan("finance.read", {"kind": "rate", "source": "USD",
                                                                  "target": "TRY"}))


class FinanceModelContractTests(unittest.TestCase):
    """Finance values are model-proposed and Core-validated, never phrase-classified."""

    def test_deterministic_understanding_does_not_classify_finance_phrases(self):
        for text in ("dolar kaç lira", "100 dolar kaç TL", "bitcoin kaç TL",
                     "gram altın ne kadar", "THYAO kaç lira", "bist 100 kaç puan"):
            with self.subTest(text=text):
                self.assertNotEqual(_hint(text), understanding.FINANCE_READ_CAPABILITY)
        self.assertFalse(hasattr(understanding, "finance_request"))
        self.assertFalse(hasattr(understanding, "_finance_arguments"))

    def test_finance_model_schema_exposes_only_typed_domain_values(self):
        from modules.brain_model_understanding import _supplied_schema
        schema = _supplied_schema("finance.read")
        self.assertEqual(set(schema["kind"]), {"rate", "asset", "stock"})
        self.assertIn("USD", schema["rate"]["source"])
        self.assertIn("BTC", schema["asset"]["asset"])
        self.assertIn("THYAO", schema["stock"]["stock"])


class FinanceRetirementTests(unittest.TestCase):
    """Ham kapı fiziksel olarak kalkar: domain ham cümleden capability seçmez."""

    def test_the_surface_no_longer_asks_finance_about_the_sentence(self):
        tree = ast.parse(ENGINE_COMMANDS.read_text(encoding="utf-8"), filename=str(ENGINE_COMMANDS))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(ast.unparse(node), "finance.answer",
                                    msg="ham finans kapısı yüzeyde")

    def test_no_runtime_or_diagnostic_answer_parser_remains(self):
        owners: set[str] = set()
        for path in [*ROOT.glob("modules/*.py"), *ROOT.glob("scripts/*.py")]:
            owners |= _calls(path, "finance.answer")
        self.assertEqual(owners, set())
        self.assertFalse(hasattr(finance, "answer"))
        self.assertFalse(hasattr(finance, "parse"))
        self.assertFalse(hasattr(finance, "is_conversion"))

    def test_the_runtime_has_no_finance_phrase_parser(self):
        source = FINANCE.read_text(encoding="utf-8")
        for retired in ("def parse(", "def is_conversion(", "def answer(", "_GOLD_CUE",
                        "_GOLD_OTHER", "_NUMBER_WORDS", "def _mentions("):
            self.assertNotIn(retired, source)
        brain = (ROOT / "modules" / "brain_understanding.py").read_text(encoding="utf-8")
        self.assertNotIn("finance_request", brain)
        self.assertNotIn("_finance_arguments", brain)


class FinanceTurnTests(pr3a._CanonicalAuthorityHarness):
    """Üretim zinciri: Brain → Core → tek intent → domain fetch/format."""

    def setUp(self):
        super().setUp()
        self.answer = Mock(return_value="KUR TEST")
        patcher = patch.object(finance, "answer_request", self.answer)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.model = Mock(return_value=_model_envelope("chat"))
        self.enterContext(routed_plan(count=1))
        for target, value in (
                ("modules.llm.current_user", lambda: self.owner),
                ("modules.llm.provider", lambda: "groq"),
                ("modules.llm.privacy.mode", lambda: "normal"),
                ("modules.smart_router.selection", lambda *a, **k: {"candidates": ["groq"]}),
                ("modules.llm.dispatch", self.model)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _propose(self, arguments):
        self.model.return_value = _model_envelope(
            "direct_action", arguments, capability=understanding.FINANCE_READ_CAPABILITY)

    def test_a_rate_question_reaches_the_domain_through_the_typed_plan(self):
        self._propose({"kind": "rate", "source": "USD", "target": "TRY"})
        entry, out, _handle, _ = self.turn_real("dolar kaç lira", model_understanding=True)
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.assertIn("KUR TEST", str(out))
        self.model.assert_called_once()

    def test_currency_conversion_is_model_owned_not_text_translation(self):
        self._propose({"kind": "rate", "amount": "50", "source": "EUR", "target": "USD"})
        entry, _out, _handle, _ = self.turn_real("50 euroyu dolara çevir", model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.assertEqual(self.answer.call_args.args[0]["source"], "EUR")
        self.assertEqual(self.answer.call_args.args[0]["target"], "USD")

    def test_the_executor_receives_validated_slots_not_the_sentence(self):
        self._propose({"kind": "rate", "amount": "100", "source": "USD", "target": "TRY"})
        self.turn_real("100 dolar kaç TL", model_understanding=True)
        self.assertEqual(self.answer.call_count, 1)
        request = self.answer.call_args.args[0]
        self.assertEqual(request.get("source"), "USD")
        self.assertEqual(request.get("target"), "TRY")
        self.assertEqual(str(request.get("amount")), "100")
        self.assertNotIn("100 dolar kaç TL", str(request))

    def test_the_asset_path_is_typed_the_same_way(self):
        self._propose({"kind": "asset", "asset": "GOLD", "gold_kind": "gram", "target": "TRY"})
        self.turn_real("gram altın ne kadar", model_understanding=True)
        self.assertEqual(self.answer.call_args.args[0].get("asset"), "GOLD")

    def test_a_capitalised_ticker_reaches_the_domain_as_a_closed_enum(self):
        self._propose({"kind": "stock", "stock": "THYAO"})
        entry, _out, _handle, _ = self.turn_real("THYAO kaç lira", model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.assertEqual(self.answer.call_args.args[0].get("stock"), "THYAO")

    def test_a_definition_question_never_reaches_the_domain(self):
        entry, _out, _handle, _ = self.turn_real("dolar nedir", model_understanding=True)
        self.assertNotEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.answer.assert_not_called()
        self.model.assert_called_once()

    def test_the_finance_answer_is_not_a_second_semantic_authority(self):
        # `engine_intents` yürütücüsü yalnız doğrulanmış tipli alanları domain sözleşmesine çevirir.
        source = Path(engine_intents.__file__).read_text(encoding="utf-8")
        self.assertIn('case "finance_read"', source)
        self.assertNotIn("finance.answer(", source)


def _model_envelope(operation, arguments=None, *, capability=None):
    from modules.brain_model_understanding import SCHEMA_VERSION
    actions = []
    if operation == "direct_action":
        actions = [{
            "action_id": "a1", "capability_id": capability, "arguments": arguments or {},
            "reference_slots": [], "depends_on": [],
        }]
    return json.dumps({
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "STATIC",
        "target_goal_ids": [],
        "goal": None,
        "actions": actions,
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": "MEDIUM",
    })


if __name__ == "__main__":
    unittest.main()
