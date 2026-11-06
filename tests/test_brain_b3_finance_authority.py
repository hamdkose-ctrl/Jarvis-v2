"""BRAIN-03 dilim 3: finans fiyat okuması (BRAIN-MIG-101).

Envanter yeri: `JARVIS_BRAIN_MIGRATION_MAP_V1.md` §13.1 `finance.answer` satırı; karar
tablosu §14 satır 17. Retire edilen yüzey kapısı `modules/engine_commands.py` içindeydi:

    from modules import finance
    rate_reply = finance.answer(command)
    if rate_reply is not None:
        return rate_reply

Yani kur/kripto/altın/BIST cümlesini **domain modülü** ham metinden ayırıp capability'yi
kendisi seçiyordu. Yeni zincir: anlam kararı Brain'de (`finance_request`), biçim hükmü
Core'da (kapalı para birimi/hisse/altın kümeleri, pozitif sonlu miktar), etki tek
`finance_read` intent'inde; domain yalnız **veri çeker ve biçimlendirir** (`answer_request`).

Bu dosya RED olarak yazıldı: `finance.read` capability'si, Core validator'ı, intent sahibi
ve Brain tanıyıcısı yoktur; yüzey kapısı hâlâ ham cümleyi finance'a veriyor.
"""
from __future__ import annotations

import ast
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
    # `original` büyük/küçük harfe duyarlı sözlük için (BIST kodu `THYAO`).
    return understanding._capability_hint(understanding._norm(text), understanding.TemporalNeed.STATIC,
                                          original=text)


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


class FinanceUnderstandingTests(unittest.TestCase):
    """Tanıyıcı: kur/kripto/altın/BIST fiyat sorusu tek biçim hükmünden geçer."""

    def test_rate_questions_are_the_finance_capability(self):
        for text in ("dolar kaç lira", "100 dolar kaç TL", "euro kaç dolar",
                     "dolar ne kadar", "sterlin kaç lira"):
            with self.subTest(text=text):
                self.assertEqual(_hint(text), understanding.FINANCE_READ_CAPABILITY)

    def test_asset_and_stock_questions_are_the_finance_capability(self):
        for text in ("bitcoin kaç TL", "gram altın ne kadar", "çeyrek altın fiyatı",
                     "THYAO kaç lira", "bist 100 kaç puan"):
            with self.subTest(text=text):
                self.assertEqual(_hint(text), understanding.FINANCE_READ_CAPABILITY)

    def test_definition_forecast_alarm_and_other_meanings_stay_out(self):
        for text in ("dolar nedir", "kur ne demek", "euro 2024", "dolar dün kaçtı",
                     "dolar yarın ne olur", "dolar 30 olunca haber ver", "bitcoin analizi",
                     "borsa nasıl çalışır"):
            with self.subTest(text=text):
                self.assertIsNone(_hint(text))
        # "altın madalyası" altın fiyatı değildir; bu cümle tabanda da fiyat sorusu sayılmıyor.
        self.assertNotEqual(_hint("altın madalyası kaç lira"), understanding.FINANCE_READ_CAPABILITY)

    def test_the_typed_slots_mirror_the_domain_request(self):
        arguments = understanding._finance_arguments(understanding._norm("100 dolar kaç TL"))
        self.assertEqual(arguments.get("kind"), "rate")
        self.assertEqual(arguments.get("amount"), "100")
        self.assertEqual(arguments.get("source"), "USD")
        self.assertEqual(arguments.get("target"), "TRY")
        asset = understanding._finance_arguments(understanding._norm("gram altın ne kadar"))
        self.assertEqual(asset.get("asset"), "GOLD")
        self.assertEqual(asset.get("gold_kind"), "gram")
        # BIST kodu büyük harfle söylenir; slot çıkarımı orijinal metni görür (normalize edilmiş
        # metinde kod küçülür ve taban grameri de onu tanımaz).
        stock = understanding._finance_arguments("THYAO kaç lira")
        self.assertEqual(stock.get("stock"), "THYAO")


class FinanceRetirementTests(unittest.TestCase):
    """Ham kapı fiziksel olarak kalkar: domain ham cümleden capability seçmez."""

    def test_the_surface_no_longer_asks_finance_about_the_sentence(self):
        tree = ast.parse(ENGINE_COMMANDS.read_text(encoding="utf-8"), filename=str(ENGINE_COMMANDS))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(ast.unparse(node), "finance.answer",
                                    msg="ham finans kapısı yüzeyde")

    def test_the_only_remaining_answer_caller_is_the_diagnostic_script(self):
        owners: set[str] = set()
        for path in [*ROOT.glob("modules/*.py"), *ROOT.glob("scripts/*.py")]:
            owners |= _calls(path, "finance.answer")
        self.assertEqual(owners, {"scripts/finans_kaynak_testi.py"})

    def test_the_grammar_is_no_longer_owned_by_the_domain(self):
        source = FINANCE.read_text(encoding="utf-8")
        self.assertNotIn("def _asset(", source)
        self.assertNotIn("def _stock(", source)
        self.assertNotIn("def _bare_amount(", source)
        self.assertNotIn("def _amount_before(", source)
        # `parse` tek gramerin sahibine devreder; kendi gövdesinde kalıp yoktur.
        tree = ast.parse(source, filename=str(FINANCE))
        parse_fn = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "parse")
        self.assertLessEqual(len(parse_fn.body), 4,
                             msg=f"parse hâlâ kendi gramerini taşıyor: {ast.unparse(parse_fn)[:120]}")

    def test_the_brain_owns_the_recognizer(self):
        source = (ROOT / "modules" / "brain_understanding.py").read_text(encoding="utf-8")
        self.assertIn("def finance_request(", source)


class FinanceTurnTests(pr3a._CanonicalAuthorityHarness):
    """Üretim zinciri: Brain → Core → tek intent → domain fetch/format."""

    def setUp(self):
        super().setUp()
        self.answer = Mock(return_value="KUR TEST")
        patcher = patch.object(finance, "answer_request", self.answer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_rate_question_reaches_the_domain_through_the_typed_plan(self):
        entry, out, _handle, _ = self.turn_real("dolar kaç lira")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.assertIn("KUR TEST", str(out))

    def test_the_executor_receives_validated_slots_not_the_sentence(self):
        self.turn_real("100 dolar kaç TL")
        self.assertEqual(self.answer.call_count, 1)
        request = self.answer.call_args.args[0]
        self.assertEqual(request.get("source"), "USD")
        self.assertEqual(request.get("target"), "TRY")
        self.assertEqual(str(request.get("amount")), "100")
        self.assertNotIn("100 dolar kaç TL", str(request))

    def test_the_asset_path_is_typed_the_same_way(self):
        self.turn_real("gram altın ne kadar")
        self.assertEqual(self.answer.call_args.args[0].get("asset"), "GOLD")

    def test_a_capitalised_ticker_reaches_the_domain_as_a_closed_enum(self):
        entry, _out, _handle, _ = self.turn_real("THYAO kaç lira")
        self.assertEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.assertEqual(self.answer.call_args.args[0].get("stock"), "THYAO")

    def test_a_definition_question_never_reaches_the_domain(self):
        entry, _out, _handle, _ = self.turn_real("dolar nedir")
        self.assertNotEqual(entry.understanding.capability_hint, understanding.FINANCE_READ_CAPABILITY)
        self.answer.assert_not_called()

    def test_the_finance_answer_is_not_a_second_semantic_authority(self):
        # `engine_intents` yürütücüsü yalnız doğrulanmış tipli alanları domain sözleşmesine çevirir.
        source = Path(engine_intents.__file__).read_text(encoding="utf-8")
        self.assertIn('case "finance_read"', source)
        self.assertNotIn("finance.answer(", source)


if __name__ == "__main__":
    unittest.main()
