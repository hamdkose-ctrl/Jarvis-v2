"""BRAIN-03 dilim 2: mesaj gönderimi + rehber (BRAIN-MIG-092/093/094).

Sözleşme V2 §2: **model birincil semantik karar sahibidir**; deterministik regex/kelime listesi
onun önüne geçemez, kararını veto edemez ve model başarısız olduğunda yerine doğal dil kararı
veremez. Bu dosya bu hükmü mesaj/rehber akışında sınar.

Envanter yeri: `JARVIS_BRAIN_MIGRATION_MAP_V1.md` §13.1 mesaj satırı (092/093) ve
`engine_tools._contact_command` satırı (094); karar tablosu §14 satır 1–3. Emekli edilen yüzey
kapıları `modules/engine_commands.py` içindeydi (`is_whatsapp_message`, `quick_parse`,
`extract`, `_contact_command`). Birinci turda bu gramer `brain_understanding`'a taşınmıştı;
§3A/§3B gereği **oradan da kalkar**: `message.send`/`contacts.manage` artık ham cümleden
seçilmez ve modelden de yasaklanmaz.

Yeni zincir: kullanıcı cümlesi → model zarfı işlemi/yeteneyi/gövde-alıcı slotlarını ve
**dayanak alıntılarını** (`argument_sources`) seçer → Core her alanı kendi biçim
doğrulayıcısından ve dayanak eşitliğinden geçirir (uydurma/çelişen alan tüm öneriyi düşürür)
→ eksik alıcı/gövde mevcut `pending_msg` protokolünde kullanıcıya sorulur → onay kullanıcının
KENDİ cevabıdır → yürütücü yalnız kayıtlı ve tekil kişiye, kanonik numarayla gönderir.

Mock model zarfları **bağlantı kanıtıdır**, modelin doğal dili anladığının kanıtı değildir;
semantik kabul ayrıca gerçek sağlayıcıyla ölçülür (`scripts/brain_semantic_holdout.py`).
"""
from __future__ import annotations
from provider_fixture import routed_response, routed_plan

import ast
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_brain_pr3_raw_text_authority as pr3a  # noqa: E402  (kanonical harness'ın tek sahibi)
from modules import brain_core_map, engine_intents, messaging  # noqa: E402
from modules import brain_understanding as understanding  # noqa: E402
from modules.brain_contracts import RequestKind  # noqa: E402

ENGINE_COMMANDS = ROOT / "modules" / "engine_commands.py"
ENGINE_TOOLS = ROOT / "modules" / "engine_tools.py"
MESSAGING = ROOT / "modules" / "messaging.py"

CONFIRM_QUESTION = "kişisine şunu göndereyim mi"


def _handle_body() -> ast.FunctionDef:
    tree = ast.parse(ENGINE_COMMANDS.read_text(encoding="utf-8"), filename=str(ENGINE_COMMANDS))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "handle":
            return node
    raise AssertionError("modules/engine_commands.py::handle bulunamadı")


def _hint(text: str) -> str | None:
    return understanding._capability_hint(understanding._norm(text), understanding.TemporalNeed.STATIC)


# --------------------------------------------------------------------------- model zarf kızağı
#
# Bunlar BAĞLANTI kanıtıdır: sahte bir zarfın üretim zincirinin gerçek `_build` + Core +
# oturum yolundan geçip geçmediğini ölçer. Modelin doğal dili anladığının kanıtı değildir;
# semantik kabul ayrıca gerçek sağlayıcıyla ölçülür (`scripts/brain_semantic_holdout.py`).
# Tablo bir gramer değildir: her satır testin kendi cümlesine karşılık gelir ve dayanak
# alıntıları cümlenin kendisinden birebir alıntılandığı için dayanak denetiminden geçer.
_MESSAGE = understanding.MESSAGE_SEND_CAPABILITY
_CONTACTS = understanding.CONTACTS_MANAGE_CAPABILITY

MODEL_STUB_REPLIES: dict[str, tuple[str, dict, dict]] = {
    "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at": (
        _MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
        {"recipient": "ahmet'e", "body": "yarın geleceğim diye"}),
    "whatsapp'tan ahmet'e selam gönder": (
        _MESSAGE, {"recipient": "ahmet", "body": "selam"},
        {"recipient": "ahmet'e", "body": "selam"}),
    "whatsapp'tan zeynep'e selam gönder": (
        _MESSAGE, {"recipient": "zeynep", "body": "selam"},
        {"recipient": "zeynep'e", "body": "selam"}),
    "whatsapp'tan ayse'ye selam gönder": (
        _MESSAGE, {"recipient": "ayse", "body": "selam"},
        {"recipient": "ayse'ye", "body": "selam"}),
    "whatsapp'tan mehmet'e selam gönder": (
        _MESSAGE, {"recipient": "mehmet", "body": "selam"},
        {"recipient": "mehmet'e", "body": "selam"}),
    "whatsapp'tan ahmet'e mesaj gönder": (
        _MESSAGE, {"recipient": "ahmet", "body": ""}, {"recipient": "ahmet'e"}),
    "kişi ekle ahmet 0532 123 45 67": (
        _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"},
        {"name": "ahmet", "phone": "0532 123 45 67"}),
    "rehberim": (_CONTACTS, {"operation": "list"}, {}),
}


def _envelope(capability, arguments, sources=None, *, operation="direct_action",
              relation="NEW_REQUEST", confidence="MEDIUM", temporal="STATIC") -> str:
    import json
    from modules.brain_model_understanding import SCHEMA_VERSION
    action_rows = []
    if operation == "direct_action":
        action = {"action_id": "a1", "capability_id": capability, "arguments": dict(arguments),
                  "reference_slots": [], "depends_on": []}
        if sources is not None:
            action["argument_sources"] = dict(sources)
        action_rows = [action]
    return json.dumps({
        "schema_version": SCHEMA_VERSION, "operation": operation,
        "conversation_relation": relation, "temporal_need": temporal,
        "target_goal_ids": [], "goal": None,
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": confidence, "actions": action_rows,
    }, ensure_ascii=False)


def _chat_envelope() -> str:
    """Korunan bir devam turu için zarf: `protected_relation` çiti bunu reddeder."""
    return _envelope(None, None, None, operation="chat")


def _utterance_of(payload: str) -> str:
    import json
    row, _end = json.JSONDecoder().raw_decode(payload[payload.index("{"):])
    return row["utterance"]


def _stub_run(request, spec, payload, system, **kwargs):
    reply = MODEL_STUB_REPLIES.get(_utterance_of(payload))
    return _chat_envelope() if reply is None else _envelope(*reply)


class _ModelStubMixin:
    """Üretim turundaki tek bounded model çağrısını sahte zarfla besler (ağ yok)."""

    def _start_model_stub(self, run=None):
        self.model_calls: list[str] = []
        real_run = run or _stub_run

        def counted(request, spec, payload, system, **kwargs):
            self.model_calls.append(_utterance_of(payload))
            return real_run(request, spec, payload, system)

        self.enterContext(routed_plan(count=1))
        for target, value in (("modules.llm.current_user", lambda: self.owner),
                              ("modules.llm.provider", lambda: "groq"),
                              ("modules.llm.privacy.mode", lambda: "normal"),
                              ("modules.smart_router.selection",
                               lambda *a, **k: {"candidates": ["groq"]}),
                              ("modules.llm.dispatch", counted)):
            stub = patch(target, value)
            stub.start()
            self.addCleanup(stub.stop)
        return self.model_calls


class MessageCapabilityContractTests(unittest.TestCase):
    """Kanonical sözleşme: hint → Core intent → doğrulanmış argüman, tek sahibinden."""

    def test_the_capabilities_exist_and_are_core_mapped(self):
        self.assertEqual(understanding.MESSAGE_SEND_CAPABILITY, "message.send")
        self.assertEqual(understanding.CONTACTS_MANAGE_CAPABILITY, "contacts.manage")
        self.assertEqual(brain_core_map.CORE_INTENTS["message.send"][0], "message_send")
        self.assertEqual(brain_core_map.CORE_INTENTS["contacts.manage"][0], "contacts_manage")

    def test_the_message_proposal_carries_only_typed_slots(self):
        validate = brain_core_map.CORE_INTENTS["message.send"][1]
        # Brain küçük harfli token önerir; Türkçe büyük harf hükmü Core'undur (şehir dilimiyle
        # aynı katman ayrımı: anlam Brain'de, biçim Core'da).
        self.assertEqual(validate({"recipient": "ahmet", "body": "yarın geleceğim"}),
                         {"recipient": "Ahmet", "body": "yarın geleceğim"})
        self.assertEqual(validate({"recipient": "annem", "body": ""}),
                         {"recipient": "Annem", "body": ""})
        # Alıcı henüz bilinmiyorsa oturum kendi sorusunu sorar; boş slot geçerli bir öneridir.
        self.assertEqual(validate({"recipient": "", "body": ""}), {"recipient": "", "body": ""})

    def test_grounded_proper_name_case_is_not_a_core_format_error(self):
        # Source quoting is still checked by Brain. Core's format validator
        # must not reject normal Turkish proper-name casing (Ayşe / İpek).
        message = brain_core_map.CORE_INTENTS["message.send"][1]
        contact = brain_core_map.CORE_INTENTS["contacts.manage"][1]
        for supplied, expected in (("ayşe", "Ayşe"), ("Ayşe", "Ayşe"),
                                   ("AYŞE", "Ayşe"), ("İpek", "İpek"),
                                   ("IPEK", "Ipek"), ("Işık", "Işık")):
            with self.subTest(name=supplied):
                self.assertEqual(message({"recipient": supplied, "body": "selam"}),
                                 {"recipient": expected, "body": "selam"})
                self.assertEqual(contact({"operation": "add", "name": supplied,
                                          "phone": "0532 123 45 67"}),
                                 {"operation": "add", "name": expected,
                                  "phone": "905321234567"})
        for malformed in ("Ayşe'ye", "Ayşe@example.com", "Ayşe 2", "A", "Ali\\nVeli"):
            with self.subTest(malformed=malformed):
                self.assertIsNone(message({"recipient": malformed, "body": "selam"}))

    def test_core_rejects_malformed_message_slots(self):
        validate = brain_core_map.CORE_INTENTS["message.send"][1]
        for arguments in (
                {"recipient": "ahmet", "body": "x" * 4001},      # gövde sınırı
                {"recipient": "ahmet", "body": "a\x00b"},          # kontrol karakteri
                {"recipient": "ahmet@example.com", "body": "selam"},
                {"recipient": "ahmet 2", "body": "selam"},
                {"recipient": "a", "body": "selam"},
                {"recipient": 5, "body": "selam"},
                {"recipient": "ahmet", "body": 5},
                {"recipient": "ahmet", "body": "selam", "path": "C:/gizli.txt"},
                {"recipient": "ahmet", "body": "selam", "phone": "905321234567"}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(validate(arguments))

    def test_the_contact_proposal_normalises_the_number(self):
        validate = brain_core_map.CORE_INTENTS["contacts.manage"][1]
        self.assertEqual(validate({"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"}),
                         {"operation": "add", "name": "Ahmet", "phone": "905321234567"})
        self.assertEqual(validate({"operation": "add", "name": "ayşe", "phone": "+90 532 111 22 33"}),
                         {"operation": "add", "name": "Ayşe", "phone": "905321112233"})
        self.assertEqual(validate({"operation": "list"}), {"operation": "list"})
        for arguments in (
                {"operation": "add", "name": "ahmet", "phone": "123"},          # geçersiz numara
                {"operation": "add", "name": "", "phone": "0532 123 45 67"},
                {"operation": "add", "name": "ahmet 2", "phone": "0532 123 45 67"},
                {"operation": "delete", "name": "ahmet"},
                {"operation": "list", "name": "ahmet"},
                {"operation": "list", "phone": "905321234567"}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(validate(arguments))

    def test_a_rejected_message_proposal_produces_no_core_plan(self):
        self.assertIsNone(brain_core_map.core_plan("message.send", {"recipient": "ahmet 2", "body": ""}))
        self.assertTrue(brain_core_map.core_plan("message.send", {"recipient": "ahmet", "body": "selam"}))

    def test_a_message_field_is_a_typed_slot_not_a_denied_key(self):
        # §3A: alıcı ve gövde artık modelin önerebileceği tipli yuvalardır. Yetki yasağı anahtar
        # düzeyinde değil, DAYANAK düzeyindedir: her dolu alan kullanıcının kendi cümlesinden
        # alıntılanmış bir aralıkla gelmek zorundadır.
        from modules import brain_model_understanding as model
        self.assertNotIn("recipient", model._MODEL_DENIED_ARGUMENT_KEYS)
        self.assertNotIn("body", model._MODEL_DENIED_ARGUMENT_KEYS)
        self.assertIn("argument_sources", model.ACTION_KEYS)


class _ZarfHarness(unittest.TestCase):
    """Tek bounded zarf çağrısı: `_build` + Core kapısı gerçekten yürür (ağ yok)."""

    OWNER = "u-b3-dilim2"

    def _current(self, text):
        from modules.brain_contracts import ActiveContext
        request_id = "r-b3-dilim2"
        return understanding.understand(
            owner=self.OWNER, request_id=request_id, text=text,
            active_context=ActiveContext(owner=self.OWNER, request_id=request_id),
            candidates=(), references=())

    def _ask(self, text, raw):
        from modules import brain_model_understanding as model
        current = self._current(text)
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                routed_response(raw):
            return model.propose(owner=self.OWNER, text=text, current=current,
                                 arguments=dict(current.arguments))


class MessageModelAuthorityTests(_ZarfHarness):
    """Sözleşme §2: yetenek kararının sahibi modeldir; gramer onu seçemez de veto edemez de."""

    SEND = "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at"

    def test_the_model_can_propose_a_message_send(self):
        proposal = self._ask(self.SEND, _envelope(
            _MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
            {"recipient": "ahmet'e", "body": "yarın geleceğim diye"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, _MESSAGE)

    def test_the_model_can_propose_a_contact_write(self):
        text = "kişi ekle ahmet 0532 123 45 67"
        proposal = self._ask(text, _envelope(
            _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"},
            {"name": "ahmet", "phone": "0532 123 45 67"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, _CONTACTS)

    def test_the_model_can_propose_a_contact_list(self):
        proposal = self._ask("rehberim", _envelope(_CONTACTS, {"operation": "list"}, {}))
        self.assertIsNotNone(proposal)
        self.assertEqual(dict(proposal.actions[0].arguments).get("operation"), "list")

    def test_the_message_and_contact_capabilities_are_advertised_to_the_model(self):
        # §3A: kapalı yasak küme yalnız kalıcı şehir tercihidir; katalogda mesaj/rehber durur.
        import json
        from modules import brain_model_understanding as model
        from modules.brain_core_map import CORE_INTENTS
        captured: dict[str, str] = {}

        def fake_run(request, spec, text, system, **kwargs):
            captured["payload"] = text
            return _envelope("weather.read", {"location": "izmir"})

        current = self._current("bugün hava nasıl")
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                routed_plan(count=1), patch("modules.llm.dispatch", side_effect=fake_run):
            self.assertIsNotNone(model.propose(
                owner=self.OWNER, text="bugün hava nasıl", current=current,
                arguments=dict(current.arguments)))
        payload, _end = json.JSONDecoder().raw_decode(
            captured["payload"][captured["payload"].index("{"):])
        advertised = set(payload["allowed"]["capability_id"])
        self.assertEqual(set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertIn(_MESSAGE, advertised)
        self.assertIn(_CONTACTS, advertised)
        self.assertEqual(advertised & set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertFalse(payload["current"]["current_output"]["available"])
        self.assertNotIn("documents.export", advertised)
        self.assertEqual(advertised, set(CORE_INTENTS) - set(model._MODEL_DENIED_CAPABILITIES) - {"documents.export"})

    def test_no_deterministic_veto_keeps_the_models_message_decision(self):
        # §1/§3B: cümlede hiçbir deterministik yetenek seçimi kalmamalı ve modelin kararı
        # yine de benimsenmeli — eski hâlde yasağın kullanıcı yüzü "gramer zaten seçmişti" idi.
        deterministic = self._current(self.SEND)
        self.assertIsNone(deterministic.capability_hint)
        raw = _envelope(_MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
                        {"recipient": "ahmet'e", "body": "yarın geleceğim diye"})
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                routed_response(raw):
            adopted = understanding.apply_model_understanding(deterministic, self.SEND)
        self.assertEqual(adopted.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(adopted.capability_hint, _MESSAGE)
        self.assertEqual(adopted.arguments.get("recipient"), "ahmet")
        self.assertEqual(adopted.arguments.get("body"), "yarın geleceğim")


class MessageGroundingTests(_ZarfHarness):
    """§4: alanlar kullanıcının KENDİ cümlesinden doğar; Core dayanak eşitliğini doğrular."""

    SEND = "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at"

    def _send(self, arguments, sources):
        return self._ask(self.SEND, _envelope(_MESSAGE, arguments, sources))

    def test_grounded_slots_are_accepted_exactly_as_spoken(self):
        proposal = self._send({"recipient": "ahmet", "body": "yarın geleceğim"},
                              {"recipient": "ahmet'e", "body": "yarın geleceğim diye"})
        self.assertIsNotNone(proposal)
        arguments = dict(proposal.actions[0].arguments)
        self.assertEqual(arguments.get("recipient"), "ahmet")
        self.assertEqual(arguments.get("body"), "yarın geleceğim")

    def test_a_field_without_a_source_is_not_a_valid_proposal(self):
        # §6: uydurma alıcı/gövde reddedilir — anahtar yokluğu dayanak yokluğu sayılmaz.
        for arguments, sources in (
                ({"recipient": "ahmet", "body": "yarın geleceğim"}, None),
                ({"recipient": "ahmet", "body": "yarın geleceğim"}, {"body": "yarın geleceğim diye"}),
                ({"recipient": "ahmet", "body": "yarın geleceğim"}, {"recipient": "ahmet'e"}),
                ({"recipient": "ahmet", "body": "yarın geleceğim"}, {})):
            with self.subTest(sources=sources):
                self.assertIsNone(self._send(arguments, sources))

    def test_a_recipient_absent_from_the_utterance_is_rejected(self):
        self.assertIsNone(self._send({"recipient": "mehmet", "body": "yarın geleceğim"},
                                     {"recipient": "mehmet'e", "body": "yarın geleceğim diye"}))

    def test_a_body_absent_from_the_utterance_is_rejected(self):
        self.assertIsNone(self._send({"recipient": "ahmet", "body": "toplantıya katılmayacağım"},
                                     {"recipient": "ahmet'e",
                                      "body": "toplantıya katılmayacağım"}))

    def test_a_field_may_not_exceed_its_source_span(self):
        # Dayanak, alanı taşımıyor: "Ahmet Yılmaz" cümlede yok; alıcı uydurulmuş soyadla uzuyor.
        self.assertIsNone(self._send({"recipient": "ahmet yılmaz", "body": "yarın geleceğim"},
                                     {"recipient": "ahmet'e", "body": "yarın geleceğim diye"}))

    def test_a_source_may_not_be_quoted_from_another_sentence(self):
        # Alıntı yalnız İSTEK CÜMLESİNDEN olur: önceki turdan bir metin gövde olamaz.
        proposal = self._ask("tamam", _envelope(
            _MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
            {"recipient": "ahmet'e", "body": "yarın geleceğim diye"}))
        self.assertIsNone(proposal)

    def test_empty_slots_are_valid_and_left_to_the_session(self):
        # §4: eksik alıcı/gövde uydurulmaz; boş slot geçerli öneridir ve oturum kullanıcıya sorar.
        proposal = self._send({"recipient": "", "body": ""}, {})
        self.assertIsNotNone(proposal)
        arguments = dict(proposal.actions[0].arguments)
        self.assertEqual(arguments.get("recipient"), "")
        self.assertEqual(arguments.get("body"), "")

    def test_an_unknown_source_key_is_rejected(self):
        self.assertIsNone(self._send({"recipient": "ahmet", "body": ""},
                                     {"recipient": "ahmet'e", "query": "ahmet"}))

    def test_grounding_is_required_only_for_the_user_owned_fields(self):
        # A non-user-owned capability does not authorize actions by quoting an
        # optional, nonauthoritative argument_sources object. The Core still
        # validates its typed arguments; auxiliary sources cannot add any.
        for sources in (None, {}, {"location": "izmirde"}, {"approval": "invented"}):
            with self.subTest(sources=sources):
                proposal = self._ask("yarın izmirde hava nasıl", _envelope(
                    "weather.read", {"location": "izmir"}, sources))
                self.assertIsNotNone(proposal)
                self.assertEqual(proposal.actions[0].capability_id, "weather.read")
                self.assertEqual(proposal.actions[0].arguments["location"], "izmir")
                self.assertNotIn("approval", proposal.actions[0].arguments)
        # The wire schema permits only null or an object, not arbitrary values.
        for invalid in ("izmirde", [], 20):
            with self.subTest(invalid_shape=invalid):
                self.assertIsNone(self._ask("yarın izmirde hava nasıl", _envelope(
                    "weather.read", {"location": "izmir"}, invalid)))
        # User-owned message slots stay fail-closed when their real quotations
        # are missing; a weather-style untrusted hint is never a replacement.
        self.assertIsNone(self._send(
            {"recipient": "ahmet", "body": "yarın geleceğim"},
            {"recipient": "ahmet'e", "approval": "invented"}))

    def test_an_invented_phone_number_is_rejected_and_a_spoken_one_is_not(self):
        spoken = "kişi ekle ahmet 0532 123 45 67"
        grounded = self._ask(spoken, _envelope(
            _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"},
            {"name": "ahmet", "phone": "0532 123 45 67"}))
        self.assertIsNotNone(grounded)
        for phone in ("0532 999 99 99", "905321234567"):
            with self.subTest(phone=phone):
                self.assertIsNone(self._ask(spoken, _envelope(
                    _CONTACTS, {"operation": "add", "name": "ahmet", "phone": phone},
                    {"name": "ahmet", "phone": phone})))

    def test_an_invented_contact_name_is_rejected(self):
        self.assertIsNone(self._ask("kişi ekle mehmet 0532 123 45 67", _envelope(
            _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"},
            {"name": "ahmet", "phone": "0532 123 45 67"})))


class MessageModelFailureTests(_ZarfHarness):
    """§11 kör fallback yok: model yoksa/bozuksa etki yok, gramer kararı da yok."""

    SEND = "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at"

    def _grounded(self):
        return _envelope(_MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
                         {"recipient": "ahmet'e", "body": "yarın geleceğim diye"})

    def test_a_provider_exception_leaves_the_deterministic_decision_untouched(self):
        current = self._current(self.SEND)
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run_request", side_effect=RuntimeError("sağlayıcı yok")):
            adopted = understanding.apply_model_understanding(current, self.SEND)
        self.assertIsNone(adopted.capability_hint)
        self.assertNotEqual(adopted.request_kind, RequestKind.CAPABILITY)

    def test_a_malformed_envelope_is_rejected_without_a_fallback(self):
        current = self._current(self.SEND)
        for raw in ("", "not json", "{", json.dumps({"schema_version": "brain-understanding.v1"}),
                    json.dumps({key: None for key in ("schema_version", "operation")}),
                    self._grounded().replace('"arguments"', '"argumanlar"')):
            with self.subTest(raw=raw[:40]):
                with patch("modules.llm.current_user", return_value=self.OWNER), \
                        patch("modules.llm.provider", return_value="groq"), \
                        patch("modules.llm.privacy.mode", return_value="normal"), \
                        patch("modules.smart_router.selection",
                              return_value={"candidates": ["groq"]}), \
                        routed_response(raw):
                    adopted = understanding.apply_model_understanding(current, self.SEND)
                self.assertIsNone(adopted.capability_hint)

    def test_a_local_or_paid_route_is_not_used_for_the_message_decision(self):
        # §11: ücretli/yerel rota Brain tarafından sessizce kullanılmaz; regex yedeği de yoktur.
        current = self._current(self.SEND)
        for provider, privacy in (("ollama", "normal"), ("groq", "yerel"), ("openai", "normal")):
            with self.subTest(provider=provider, privacy=privacy):
                with patch("modules.llm.current_user", return_value=self.OWNER), \
                        patch("modules.llm.provider", return_value=provider), \
                        patch("modules.llm.privacy.mode", return_value=privacy), \
                        patch("modules.smart_router.selection",
                              return_value={"candidates": ["groq"]}), \
                        patch("modules.llm.dispatch") as run:
                    adopted = understanding.apply_model_understanding(current, self.SEND)
                run.assert_not_called()
                self.assertIsNone(adopted.capability_hint)


class NoDeterministicMessageCapabilityTests(unittest.TestCase):
    """§3B: hiçbir ham cümle `message.send`/`contacts.manage` yeteneğini deterministik seçemez.

    Beklenen tek doğru sonuç None'dır. Eski testler bu satırların message.send seçmesini
    istiyordu; o davranış sözleşme §15/1'in birinci yasak örneğidir ve burada tersine çevrildi.
    """

    MESSAGE_SENTENCES = (
        # Eski gramerin tanıdığı biçimler: artık hiçbiri yetenek seçmez.
        "whatsapp'tan ahmet'e mesaj gönder", "WhatsApp ile Ali'ye yaz",
        "whatsapptan ayşe'ye yarın geleceğim diye mesaj at", "wathsaap'tan anneme geliyorum yaz",
        "vatsap üzerinden mehmet'e ilet", "whatsapp'tan mesaj at",
        "whatsapp'tan yarın geleceğim diye ahmet'e mesaj at",
        "whatsapp ile toplantı iptal diye mehmet'e yaz",
        "anneme whatsapp'tan yaz", "whatsapp'tan herkese mesaj at", "whatsapp grubuna yaz",
        # Eski gramerin tanımadığı, modeli zorlayacak görülmeyen yeniden anlatımlar.
        "Ahmet'e whatsapptan ulaşır mısın", "numarası kayıtlı Ahmet'e whatsaptan yazıver",
        "lütfen whatsappdan anneme toplantı iptal ilet",
        "whatsapp uygulamasından ayşe hanıma selam iletir misin",
        "whatsapp'tan mehmet'e şu mesajı yolla: görüşürüz",
        # Soru / geçmiş zaman / olumsuz / alıntı: etki isteği değil.
        "whatsapp nasıl çalışır?", "whatsapp web telefonsuz çalışıyor mu",
        "whatsapp'ta sabitlenmiş sohbetleri göster", "whatsapp'tan ahmet'e mesaj attım",
        "whatsapp'tan ahmet'e mesaj attın mı?", "whatsapp mesajı göndermek ne demek",
        "telegram'dan ahmet'e mesaj at", "ahmet'e mesaj at",
        "whatsapp'tan mesaj gönderme", "yarın whatsapp'tan mesaj atmayı unutma",
        '"whatsapp\'tan mesaj gönder" demek zorunda mısın',
    )

    CONTACT_SENTENCES = (
        "kişi ekle ahmet 0532 123 45 67", "rehbere ekle ayşe +90 532 111 22 33",
        "ahmet'in numarası 0532 123 45 67", "kişileri listele", "kişileri göster",
        "rehberim", "Rehberim.", "numarasını kaydet mehmet 0532 111 22 33",
        "rehberimde kaç kişi var", "rehber nedir?", "kişileri listeleme nasıl yapılır",
        "kişi ekle ahmet 123",
    )

    def _semantic(self, text):
        from modules.brain_contracts import ActiveContext
        owner, request_id = "u-b3-dilim2", "r-b3-dilim2"
        return understanding.understand(
            owner=owner, request_id=request_id, text=text,
            active_context=ActiveContext(owner=owner, request_id=request_id),
            candidates=(), references=())

    def test_no_message_sentence_selects_the_message_capability(self):
        for text in self.MESSAGE_SENTENCES:
            with self.subTest(text=text):
                self.assertIsNone(_hint(text))
                self.assertIsNone(self._semantic(text).capability_hint)

    def test_no_message_sentence_carries_slots_invented_by_the_surface(self):
        for text in self.MESSAGE_SENTENCES:
            with self.subTest(text=text):
                arguments = self._semantic(text).arguments
                for owned in ("recipient", "body"):
                    self.assertNotIn(owned, arguments)

    def test_no_contact_sentence_selects_the_contacts_capability(self):
        for text in self.CONTACT_SENTENCES:
            with self.subTest(text=text):
                self.assertIsNone(_hint(text))
                self.assertIsNone(self._semantic(text).capability_hint)

    def test_no_contact_sentence_carries_slots_invented_by_the_surface(self):
        for text in self.CONTACT_SENTENCES:
            with self.subTest(text=text):
                arguments = self._semantic(text).arguments
                for owned in ("operation", "name", "phone"):
                    self.assertNotIn(owned, arguments)

    def test_the_message_and_contact_grammars_are_retired_not_renamed(self):
        tree = ast.parse(Path(understanding.__file__).read_text(encoding="utf-8"),
                         filename=str(understanding.__file__))
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        for retired in ("_message_request", "_message_arguments", "_message_fields",
                        "_message_body", "_message_remainder", "_contacts_request",
                        "_contacts_arguments"):
            with self.subTest(function=retired):
                self.assertNotIn(retired, functions)
                self.assertFalse(hasattr(understanding, retired))
        constants = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                constants |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        for retired in ("_WA_WORD", "_WA_CUE", "_WA_LEAD", "_MESSAGE_TAILS", "_MESSAGE_ADDRESS",
                        "_MESSAGE_ADDRESS_FUNCTION", "_MESSAGE_BODY_FILLERS",
                        "_NON_PERSON_RECIPIENTS", "_RECIPIENT_FOLD", "_CONTACT_NAME",
                        "_CONTACT_PHONE", "_CONTACTS_ADD_SHAPES", "_CONTACTS_LIST_REQUEST"):
            with self.subTest(constant=retired):
                self.assertNotIn(retired, constants)


class RetiredMessageDoorsTests(unittest.TestCase):
    """Yüzey kapıları fiziksel olarak kalkar: ham cümleyi okuyan ikinci bir otorite kalmaz."""

    def test_the_messaging_module_no_longer_decides_the_intent(self):
        source = MESSAGING.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(MESSAGING))
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("is_whatsapp_message", names)
        self.assertNotIn("quick_parse", names)

    def test_the_contact_grammar_is_gone_from_the_surface(self):
        tools = {node.name for node in ast.parse(ENGINE_TOOLS.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_contact_command", tools)

    def test_engine_commands_handle_never_reads_a_whatsapp_sentence(self):
        body = _handle_body()
        for node in ast.walk(body):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"is_whatsapp_message", "quick_parse", "extract", "_contact_command"},
                                 msg=f"ham mesaj kapısı yüzeyde: {ast.unparse(node)}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn("whatsapp", node.value.casefold(),
                                 msg=f"ham WhatsApp kalıbı yüzeyde: {node.value[:60]}")


class _MessageTurnHarness(pr3a._CanonicalAuthorityHarness, _ModelStubMixin):
    """Üretim zincirini model yolundan süren ortak tur kızağı (ağ yok, yan etiz mock)."""

    REGISTERED = {"Ahmet": "905321234567"}

    def setUp(self):
        super().setUp()
        # Onay okuması kullanıcının gerçek ayar dosyasına bağlı olmasın: testler kendi kararını verir.
        self.ctx.load_approve = Mock(return_value=True)
        self.ctx.profile.data["contacts"] = dict(self.REGISTERED)
        self.send = Mock(return_value="GÖNDERİLDİ")
        sender = patch.object(messaging, "send_whatsapp", self.send)
        sender.start()
        self.addCleanup(sender.stop)
        self._start_model_stub()

    def _threaded_turn(self, text):
        thread = Mock()
        self.ctx.threading = Mock(Thread=thread)
        entry, out, handle, feedback = self.turn_real(text, model_understanding=True)
        if thread.called:
            thread.call_args.kwargs["target"]()
        return entry, out, handle, feedback


class MessageTurnTests(_MessageTurnHarness):
    """Üretim zinciri: kullanıcı cümlesi → model zarfı → Core → mevcut `pending_msg` oturumu.

    Onay kullanıcının kendi cevabıdır. Alıcı güvenliği: gönderim yalnız **kayıtlı ve tekil**
    kişi için başlar; onay metni çözümlenen kişiyi ve numarasının sonunu gösterir; rehberde
    olmayan ad hiçbir koşulda gönderim çağrısına dönüşmez.
    """

    def test_a_whatsapp_request_opens_the_existing_session_from_typed_slots(self):
        text = "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at"
        entry, out, _handle, _ = self._threaded_turn(text)
        # §2: yetenek kararının sahibi modeldir — karar yüzeyde değil, zarfta doğar.
        self.assertIn(text, self.model_calls)
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, understanding.MESSAGE_SEND_CAPABILITY)
        session = self.ctx._session()
        self.assertEqual(session.pending_msg["to"], "Ahmet")
        self.assertEqual(session.pending_msg["text"], "yarın geleceğim")
        self.assertIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()

    def test_the_sender_runs_only_after_the_users_own_approval(self):
        self._threaded_turn("whatsapp'tan ahmet'e yarın geleceğim diye mesaj at")
        self.send.assert_not_called()
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ahmet", "yarın geleceğim", "905321234567"))

    def test_the_registered_contact_number_resolves_on_send(self):
        self.ctx.profile.data["contacts"] = {"Ahmet": "905321234567"}
        self._threaded_turn("whatsapp'tan ahmet'e yarın geleceğim diye mesaj at")
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args[2], "905321234567")

    def test_an_unknown_recipient_never_reaches_the_sender(self):
        # Eski test yalnız "numara uydurulmadı" diyordu: gönderim `phone=None` ile başlıyor ve
        # GUI ilk arama sonucu seçiliyordu. Güvenlik koşulu bu değil: çağrı hiç başlamamalı.
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan zeynep'e selam gönder")
        self.assertIn("rehber", str(out).casefold())
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)
        # Sonraki onay cümlesi de bir gönderim başlatamaz: akış kapanmıştır.
        self._threaded_turn("evet gönder")
        self.send.assert_not_called()

    def test_the_confirmation_names_the_resolved_contact_and_number(self):
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321234567"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e yarın geleceğim diye mesaj at")
        self.assertIn("Ahmet Yılmaz", str(out))
        self.assertIn("4567", str(out))
        self.send.assert_not_called()

    def test_a_typo_never_lands_on_a_different_contact(self):
        # "ayse" yazımı "Aysel"e kaymamalı: Türkçe karakter eşlemesi doğru kişiye gider.
        self.ctx.profile.data["contacts"] = {"Ayşe": "905324445566", "Aysel": "905321112233"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ayse'ye selam gönder")
        self.assertIn("Ayşe", str(out))
        self.assertNotIn("Aysel", str(out))
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ayşe", "selam", "905324445566"))

    def test_a_fuzzy_only_match_is_not_a_recipient(self):
        self.ctx.profile.data["contacts"] = {"Memet": "905321112233"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan mehmet'e selam gönder")
        self.assertIn("rehber", str(out).casefold())
        self.send.assert_not_called()

    def test_two_matches_require_an_explicit_choice(self):
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "905321110002"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("Ahmet Yılmaz", str(out))
        self.assertIn("Ahmet Demir", str(out))
        self.assertIn("Hangisine", str(out))
        self.assertEqual(self.ctx._session().pending_msg["text"], "selam")
        self.send.assert_not_called()
        _entry, out, _handle, _ = self._threaded_turn("Ahmet Demir")
        self.assertIn("Ahmet Demir", str(out))
        self.assertIn("0002", str(out))
        self.assertIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ahmet Demir", "selam", "905321110002"))

    def test_a_name_outside_the_known_set_never_sends(self):
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "905321110002"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        pending = dict(self.ctx._session().pending_msg)
        _entry, out, _handle, _ = self._threaded_turn("Zeynep")
        # The offered recipient set contains no Zeynep; independent model CHAT
        # cannot consume that State owner or silently replace its recipient.
        self.assertEqual(out, "CHAT")
        self.send.assert_not_called()
        self.assertEqual(self.ctx._session().pending_msg, pending)

    def test_a_missing_body_is_asked_by_the_session_not_invented(self):
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e mesaj gönder")
        self.assertIn("ne yazayım", str(out).casefold())
        self.assertEqual(self.ctx._session().pending_msg["to"], "Ahmet")
        self.send.assert_not_called()

    def test_a_corrupt_record_never_sends_and_the_refusal_names_the_number(self):
        # Kayıt adı var ama numarası bozuk: eşleşme sayılmaz, gönderim başlamaz, gerekçe söylenir.
        self.ctx.profile.data["contacts"] = {"Ahmet": "123"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("geçerli değil", str(out).casefold())
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)

    def test_an_injection_record_never_sends(self):
        # Ham değer URL parametresi kaçışı taşıyor: normalize edip "kurtarmak" bile yanlış
        # numara üretebilir (&cc=90 rakamları hedefe eklenir); kayıt tümden reddedilir.
        self.ctx.profile.data["contacts"] = {"Ahmet": "905321234567&cc=90"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("geçerli değil", str(out).casefold())
        self.send.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)

    def test_a_legacy_formatted_record_sends_the_canonical_number_after_approval(self):
        # Eski profil biçimleri (boşuklu/alan kodlu) çözümlemede kanonikleşir; onay ve gönderim
        # kullanıcının gördüğü kanonik numara üzerinden yürür.
        self.ctx.profile.data["contacts"] = {"Ahmet": "0532 123 45 67"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("4567", str(out))
        self.assertIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ahmet", "selam", "905321234567"))

    def test_approval_off_sends_a_registered_unique_contact_without_asking(self):
        # approve_sensitive=False yalnız evet/hayır sorusunu kaldırır; alıcı sözleşmesi kalır.
        self.ctx.load_approve.return_value = False
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.assertEqual(self.send.call_args.args, ("Ahmet", "selam", "905321234567"))

    def test_approval_off_still_refuses_an_unknown_recipient(self):
        self.ctx.load_approve.return_value = False
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan zeynep'e selam gönder")
        self.assertIn("rehber", str(out).casefold())
        self.send.assert_not_called()

    def test_approval_off_still_asks_for_an_explicit_choice_between_two_matches(self):
        # Belirsizlik çözümü hassas işlem onayı değildir; ayar kapalıyken de karar kullanıcınındır.
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "905321110002"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("Hangisine", str(out))
        self.send.assert_not_called()

    def test_approval_off_still_refuses_a_corrupt_number(self):
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {"Ahmet": "123"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("geçerli değil", str(out).casefold())
        self.send.assert_not_called()

    def test_a_broken_number_does_not_hide_name_ambiguity(self):
        # Bir geçerli + bir bozuk numaralı aynı isim: filtre yüzünden tek aday kalsa bile
        # belirsizlik açıktır; geçerli aday otomatik seçilmez.
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("Ahmet Yılmaz", str(out))
        self.assertIn("Ahmet Demir", str(out))
        self.assertIn("numarası geçersiz", str(out))
        self.assertIn("Hangisine", str(out))
        self.assertEqual(self.ctx._session().pending_msg["text"], "selam")
        self.send.assert_not_called()

    def test_selecting_the_invalid_candidate_never_sends(self):
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        _entry, out, _handle, _ = self._threaded_turn("Ahmet Demir")
        self.assertIn("geçerli değil", str(out).casefold())
        self.assertIn("kişi ekle", str(out).casefold())
        self.send.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)

    def test_selecting_the_valid_candidate_sends_after_approval(self):
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        _entry, out, _handle, _ = self._threaded_turn("Ahmet Yılmaz")
        self.assertIn("Ahmet Yılmaz", str(out))
        self.assertIn("0001", str(out))
        self.assertIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ahmet Yılmaz", "selam", "905321110001"))

    def test_approval_off_still_surfaces_mixed_validity_ambiguity(self):
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        _entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self.assertIn("Hangisine", str(out))
        self.assertIn("numarası geçersiz", str(out))
        self.send.assert_not_called()

    def test_approval_off_selecting_the_invalid_candidate_never_sends(self):
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        _entry, out, _handle, _ = self._threaded_turn("Ahmet Demir")
        self.assertIn("geçerli değil", str(out).casefold())
        self.send.assert_not_called()

    def test_open_recipient_question_accepts_only_exact_owner_contact_without_model(self):
        # "Ahmet Yılmaz" is an exact selection of an offered contact, not a
        # new natural-language intent. The State Gate owns this follow-up and
        # the canonical sender must still verify the saved phone number.
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {
            "Ahmet Yılmaz": "905321110001", "Ahmet Demir": "905321110002"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        model_count = len(self.model_calls)
        entry, response, _handle, feedback = self._threaded_turn("Ahmet Yılmaz")
        self.assertEqual(entry.stage, "state")
        self.assertEqual(entry.state_gate.protocol, "session.pending_msg.recipient")
        self.assertEqual(len(self.model_calls), model_count,
                         "bounded recipient selection must not invoke semantic model")
        self.assertNotIn(CONFIRM_QUESTION, str(response))
        self.send.assert_called_once_with("Ahmet Yılmaz", "selam", "905321110001")

    def test_recipient_selection_rejects_normalized_duplicate_without_side_effect(self):
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {
            "Ahmet Yılmaz": "905321110001", "AHMET YILMAZ": "905321110002"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        entry, _reply, _handle, _feedback = self._threaded_turn("Ahmet Yılmaz")
        self.assertNotEqual(entry.state_gate.protocol, "session.pending_msg.recipient")
        self.send.assert_not_called()

    def test_approval_off_selecting_the_valid_candidate_sends_without_asking(self):
        self.ctx.load_approve.return_value = False
        self.ctx.profile.data["contacts"] = {"Ahmet Yılmaz": "905321110001",
                                             "Ahmet Demir": "123"}
        self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        _entry, out, _handle, _ = self._threaded_turn("Ahmet Yılmaz")
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.assertEqual(self.send.call_args.args, ("Ahmet Yılmaz", "selam", "905321110001"))

    def test_a_contact_is_saved_to_the_active_profile_only(self):
        self._threaded_turn("kişi ekle ahmet 0532 123 45 67")
        self.assertEqual(self.ctx.profile.data.get("contacts"), {"Ahmet": "905321234567"})
        self.ctx.profile.reload() if hasattr(self.ctx.profile, "reload") else None

    def test_the_contact_list_comes_from_the_profile(self):
        self.ctx.profile.data["contacts"] = {"Ahmet": "905321234567", "Ayşe": "905321112233"}
        _entry, out, _handle, _ = self._threaded_turn("rehberim")
        self.assertIn("Ahmet", str(out))
        self.assertIn("Ayşe", str(out))

    def test_the_contact_answer_is_not_a_second_semantic_authority(self):
        # `engine_intents` yürütücüsü yalnız doğrulanmış tipli alanları okur; cümleyi yeniden ayrıştırmaz.
        source = Path(engine_intents.__file__).read_text(encoding="utf-8")
        self.assertIn('case "message_send"', source)
        self.assertIn('case "contacts_manage"', source)
        for retired in ("is_whatsapp_message", "quick_parse", "messaging.extract"):
            self.assertNotIn(retired, source)

    def test_a_question_about_whatsapp_opens_no_session(self):
        text = "whatsapp nasıl çalışır?"
        entry, _out, _handle, _ = self.turn_real(text, model_understanding=True)
        self.assertIn(text, self.model_calls)
        self.assertIsNone(self.ctx._session().pending_msg)
        self.assertEqual(self.send.call_count, 0)
        self.assertNotEqual(entry.understanding.capability_hint, understanding.MESSAGE_SEND_CAPABILITY)


def _reply(capability, arguments, sources=None):
    """Sabit bir zarfla cevap veren sahte sağlayıcı (dayanak/uydurma senaryoları için)."""
    def run(request, spec, payload, system, **kwargs):
        return _envelope(capability, arguments, sources)
    return run


class MessageSideEffectTests(_MessageTurnHarness):
    """§6: yetki değişimi güvenliği gevşetmez — yanıtlar yan etkiyi de ölçer.

    Her testte gönderim çağrısının **hiç başlamadığı** (`send_whatsapp.assert_not_called()`) ve
    oturumun açık kalmadığı (`pending_msg is None`) doğrulanır; sadece cevap metni yetmez.
    """

    def _assert_no_send_side_effect(self, out, entry, capability):
        self.assertNotEqual(entry.understanding.capability_hint, capability)
        self.assertIsNone(self.ctx._session().pending_msg)
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()

    def test_a_model_invented_recipient_and_body_never_reach_the_sender(self):
        # §4: alanlar kullanıcının kendi cümlesinden doğar. Dayanağı başka bir cümleden
        # alıntılanmış (bu testte: cümlede hiç geçmeyen) alıcı+gövde tüm öneriyi düşürür.
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "hasan", "body": "yarın buluşalım"},
            {"recipient": "hasan", "body": "yarın buluşalım"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)
        self._threaded_turn("evet gönder")
        self.send.assert_not_called()

    def test_a_message_proposal_without_grounding_sources_sends_nothing(self):
        # §4: dayanak zorunludur. Biçimce geçerli ("ahmet"/"selam" gerçekten söylemiş gibi)
        # ama alıntısı olmayan bir öneri de yürümez — biçim doğrulaması yetkinin yerini tutmaz.
        self._start_model_stub(run=_reply(_MESSAGE, {"recipient": "ahmet", "body": "selam"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)

    def test_a_provider_failure_does_not_fall_back_to_a_word_pattern(self):
        # §2: model başarısız olduğunda regex/kelime listesi onun yerine NL kararı veremez.
        def failing(request, spec, payload, system, **kwargs):
            raise RuntimeError("sağlayıcı yanıt vermedi")

        self._start_model_stub(run=failing)
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)

    def test_a_malformed_envelope_sends_nothing(self):
        self._start_model_stub(run=lambda request, spec, payload, system: "{bozuk")
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)

    def test_approval_off_does_not_open_the_gate_for_an_ungrounded_proposal(self):
        # `approve_sensitive=False` yalnız kullanıcının kendi onay sorusunu kaldırır; dayanak
        # denetimi ve alıcı sözleşmesi aşılamaz.
        self.ctx.load_approve.return_value = False
        self._start_model_stub(run=_reply(_MESSAGE, {"recipient": "ahmet", "body": "selam"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)

    def test_approval_off_does_not_send_on_a_provider_failure(self):
        self.ctx.load_approve.return_value = False

        def failing(request, spec, payload, system, **kwargs):
            raise RuntimeError("sağlayıcı yanıt vermedi")

        self._start_model_stub(run=failing)
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e selam gönder")
        self._assert_no_send_side_effect(out, entry, _MESSAGE)

    def test_an_invented_contact_number_is_never_saved(self):
        # Rehber yazması kalıcı profil verisidir: dayanağı cümlede olmayan numara kaydedilmez.
        self._start_model_stub(run=_reply(
            _CONTACTS, {"operation": "add", "name": "hasan", "phone": "0555 111 22 33"},
            {"name": "hasan", "phone": "0555 111 22 33"}))
        self._threaded_turn("kişi ekle ahmet 0532 123 45 67")
        self.assertEqual(self.ctx.profile.data.get("contacts"), dict(self.REGISTERED))


class RecipientResolutionTests(unittest.TestCase):
    """Alıcı çözümlemesi ölçülebilir ve muhafazakâr: yalnız kayıtlı defter, yalnız tekil eşleşme."""

    def test_the_contact_lookup_folds_turkish_letters_without_fuzzy_guessing(self):
        contacts = {"Ayşe": "905324445566", "Aysel": "905321112233"}
        self.assertEqual(messaging.contact_matches(contacts, "ayse"), [("Ayşe", "905324445566")])
        self.assertEqual(messaging.contact_matches({"Memet": "905321112233"}, "mehmet"), [])
        self.assertEqual(messaging.find_contact({"Memet": "905321112233"}, "mehmet"), None)

    def test_a_multi_word_name_matches_by_its_whole_word_prefix(self):
        contacts = {"Ahmet Yılmaz": "905321110001"}
        self.assertEqual(messaging.find_contact(contacts, "ahmet"), ("Ahmet Yılmaz", "905321110001"))
        self.assertEqual(messaging.find_contact(contacts, "ahm"), None)

    def test_two_matches_are_reported_as_ambiguous_not_picked(self):
        contacts = {"Ahmet Yılmaz": "905321110001", "Ahmet Demir": "905321110002"}
        self.assertEqual(len(messaging.contact_matches(contacts, "ahmet")), 2)
        self.assertIsNone(messaging.find_contact(contacts, "ahmet"))

    def test_the_sender_refuses_a_recipient_without_a_number(self):
        # GUI yolu kapalı: numara yoksa uygulama açılmaz, arama kutusu kullanılmaz, Enter basılmaz.
        with patch.object(messaging, "_find_window") as window:
            result = messaging._send_whatsapp("Zeynep", "selam", None)
        self.assertIn("göndermedim", result)
        window.assert_not_called()

    def test_the_gui_first_result_path_is_retired(self):
        source = MESSAGING.read_text(encoding="utf-8")
        self.assertNotIn('press("down")', source)
        self.assertNotIn('hotkey("ctrl", "f")', source)
        self.assertNotIn("open_application", source)


class PhoneRecordBoundaryTests(unittest.TestCase):
    """Kayıtlı numara çözümlemede doğrulanır: bozuk/metin/enjeksiyon kaydı eşleşme değildir."""

    def test_a_corrupt_empty_or_text_record_is_not_a_match(self):
        for phone in ("", None, "123", "numara yok", "0", "abcdefghij"):
            with self.subTest(phone=phone):
                self.assertEqual(messaging.contact_matches({"Ahmet": phone}, "ahmet"), [])
                self.assertIsNone(messaging.find_contact({"Ahmet": phone}, "ahmet"))

    def test_a_url_parameter_injection_record_is_not_a_match(self):
        for phone in ("905321234567&text=kötü", "905321234567&cc=90",
                      "905321234567?x=1", "905321234567#frag", "905321234567%20"):
            with self.subTest(phone=phone):
                self.assertEqual(messaging.contact_matches({"Ahmet": phone}, "ahmet"), [])
                self.assertIsNone(messaging.find_contact({"Ahmet": phone}, "ahmet"))

    def test_a_legacy_formatted_record_resolves_to_the_canonical_number(self):
        for raw, canonical in (("0532 123 45 67", "905321234567"),
                               ("+90 532 111 22 33", "905321112233"),
                               ("0532-123-45-67", "905321234567"),
                               ("(0532) 123 45 67", "905321234567")):
            with self.subTest(raw=raw):
                self.assertEqual(messaging.contact_matches({"Ahmet": raw}, "ahmet"),
                                 [("Ahmet", canonical)])

    def test_name_matches_are_independent_of_phone_validity(self):
        # Belirsizlik ad düzeyinde verilir: bozuk numaralı aday elenince kalan geçerli aday
        # otomatik seçilmez; iki Ahmet varsa karar kullanıcınındır.
        contacts = {"Ahmet Yılmaz": "905321110001", "Ahmet Demir": "123"}
        self.assertEqual(messaging.name_matches(contacts, "ahmet"), ["Ahmet Demir", "Ahmet Yılmaz"])
        self.assertIsNone(messaging.find_contact(contacts, "ahmet"))
        self.assertEqual(messaging.contact_matches(contacts, "ahmet"),
                         [("Ahmet Yılmaz", "905321110001")])


class SenderPhoneBoundaryTests(unittest.TestCase):
    """Son sınır yürütücüdür: URI'ye yalnız kanonik numara girer, ham değer asla."""

    def _keyboard(self):
        return SimpleNamespace(press=Mock(), hotkey=Mock(),
                               FailSafeException=type("FailSafe", (Exception,), {}))

    def test_the_sender_refuses_a_non_canonical_number_without_touching_the_desktop(self):
        keyboard = self._keyboard()
        for phone in ("+90 532 111 22 33", "0532 123 45 67", "905321234567&cc=90",
                      "905321234567&text=kötü", "123", "numara yok", 905321234567):
            with self.subTest(phone=phone):
                with patch.dict(sys.modules, pyautogui=keyboard), \
                        patch.object(messaging.os, "name", "nt"), \
                        patch.object(messaging.os, "startfile", create=True) as startfile, \
                        patch.object(messaging, "_find_window") as window, \
                        patch.object(messaging, "_pause"):
                    result = messaging._send_whatsapp("Ahmet", "selam", phone)
                self.assertIn("göndermedim", result)
                startfile.assert_not_called()
                window.assert_not_called()
                keyboard.press.assert_not_called()
                keyboard.hotkey.assert_not_called()

    def test_the_uri_carries_only_the_canonical_number_and_quoted_body(self):
        keyboard = self._keyboard()
        with patch.dict(sys.modules, pyautogui=keyboard), \
                patch.object(messaging.os, "name", "nt"), \
                patch.object(messaging.os, "startfile", create=True) as startfile, \
                patch.object(messaging, "_find_window", return_value=True), \
                patch.object(messaging, "_pause"):
            result = messaging._send_whatsapp("Ahmet", "selam & özel=yazı", "905321234567")
        startfile.assert_called_once_with(
            f"whatsapp://send?phone=905321234567&text={quote('selam & özel=yazı')}")
        keyboard.press.assert_called_once_with("enter")
        self.assertIn("gönderme komutunu uyguladım", result)


if __name__ == "__main__":
    unittest.main()
