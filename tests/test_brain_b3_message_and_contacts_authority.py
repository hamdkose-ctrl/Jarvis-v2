"""BRAIN-03 dilim 2: mesaj gönderimi + rehber (BRAIN-MIG-092/093/094).

Envanter yeri: `JARVIS_BRAIN_MIGRATION_MAP_V1.md` §13.1 mesaj satırı (092/093) ve
`engine_tools._contact_command` satırı (094); karar tablosu §14 satır 1–3. Retire edilen
yüzey kapıları `modules/engine_commands.py` içindeydi:

    elif runtime.messaging.is_whatsapp_message(cmd_lower):
        fast = runtime.messaging.quick_parse(cmd_lower, ...)
        to, text = fast if fast else runtime.messaging.extract(command, runtime.ask)
    contact_reply = runtime._contact_command(command, cmd_lower)

Üçü de ham cümleden capability/hedef/etki seçiyordu. Yeni zincir: Understanding
`message.send` / `contacts.manage` önerisini üretir, Core alıcı-gövde-telefon **biçimini**
doğrular, mesaj oturumu ve gönderim onayı mevcut `pending_msg` protokolünde kalır (onay
kullanıcının kendi "evet gönder" cevabıdır). Kişi defteri yalnız etkin kullanıcının
profilidir; alıcı çözümlemesi kayıtlı defterde bounded aramadır — uydurma numara üretilmez.

Bu dosya RED olarak yazıldı: `message.send`/`contacts.manage` capability'si, Core
validator'ı ve intent sahibi yoktur; yüzey kapıları hâlâ ham cümleyi okuyor.
"""
from __future__ import annotations

import ast
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

    def test_the_model_envelope_cannot_invent_a_message_body(self):
        # Gönderim onayı kullanıcının kendi cevabıdır; modelin uydurduğu gövde alıcıdan bağımsız
        # bir yetki olurdu. Alıcı anahtarı zaten yasaktı, gövde anahtarı da kapalı kümeye girer.
        from modules import brain_model_understanding as model
        self.assertIn("body", model._MODEL_DENIED_ARGUMENT_KEYS)


class MessageEnvelopeDenialTests(unittest.TestCase):
    """Model zarfı kullanıcının söylemediği bir gönderimi/rehber kaydını öneremez."""

    OWNER = "u-b3-dilim2"

    def _current(self, text):
        from modules.brain_contracts import ActiveContext
        request_id = "r-b3-dilim2"
        return understanding.understand(
            owner=self.OWNER, request_id=request_id, text=text,
            active_context=ActiveContext(owner=self.OWNER, request_id=request_id),
            candidates=(), references=())

    def _envelope(self, capability, arguments):
        import json
        from modules.brain_model_understanding import SCHEMA_VERSION
        return json.dumps({
            "schema_version": SCHEMA_VERSION, "operation": "direct_action",
            "conversation_relation": "NEW_REQUEST", "temporal_need": "STATIC",
            "target_goal_ids": [], "goal": None,
            "clarification": {"required": False, "question": None, "reason_code": None},
            "confidence": "MEDIUM",
            "actions": [{"action_id": "a1", "capability_id": capability,
                         "arguments": arguments, "reference_slots": [], "depends_on": []}]})

    def _ask(self, text, raw):
        from modules import brain_model_understanding as model
        current = self._current(text)
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", return_value=raw):
            return model.propose(owner=self.OWNER, text=understanding._norm(text),
                                 current=current, arguments=dict(current.arguments))

    def test_a_model_proposed_send_or_contact_write_is_not_a_valid_proposal(self):
        # Alıcı ve gövde kullanıcının kendi cümlesinden doğar; Core yalnız BİÇİM hükmeder, yani
        # şeklen geçerli ama uydurulmuş bir çifti ayıramaz. Red bu yüzden yetenek düzeyindedir.
        for capability, arguments in (
                (understanding.MESSAGE_SEND_CAPABILITY, {"recipient": "ahmet", "body": "selam"}),
                (understanding.CONTACTS_MANAGE_CAPABILITY,
                 {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"}),
                (understanding.CONTACTS_MANAGE_CAPABILITY, {"operation": "list"})):
            with self.subTest(capability=capability, arguments=arguments):
                self.assertIsNone(self._ask("bugün hava nasıl", self._envelope(capability, arguments)))

    def test_the_denial_is_a_closed_capability_set(self):
        from modules import brain_model_understanding as model
        self.assertEqual(set(model._MODEL_DENIED_CAPABILITIES),
                         {understanding.WEATHER_CITY_SET_CAPABILITY,
                          understanding.WEATHER_CITY_RESET_CAPABILITY,
                          understanding.MESSAGE_SEND_CAPABILITY,
                          understanding.CONTACTS_MANAGE_CAPABILITY})

    def test_the_prompt_catalogue_does_not_advertise_the_denied_capabilities(self):
        import json
        from modules import brain_model_understanding as model
        from modules.brain_core_map import CORE_INTENTS
        captured: dict[str, str] = {}

        def fake_run(owner, text, send, *, route, exclude_providers):
            captured["payload"] = text
            return self._envelope("weather.read", {"location": "izmir"})

        current = self._current("bugün hava nasıl")
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", side_effect=fake_run):
            self.assertIsNotNone(model.propose(
                owner=self.OWNER, text="bugün hava nasıl", current=current,
                arguments=dict(current.arguments)))
        payload, _end = json.JSONDecoder().raw_decode(
            captured["payload"][captured["payload"].index("{"):])
        advertised = set(payload["allowed"]["capability_id"])
        self.assertEqual(advertised & set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertIn("weather.read", advertised)
        self.assertEqual(advertised, set(CORE_INTENTS) - set(model._MODEL_DENIED_CAPABILITIES))

    def test_the_users_own_message_sentence_is_untouched_by_the_denial(self):
        # Yasağın kullanıcı yüzü: gerçek cümlede deterministik satır zaten `message.send` taşır.
        text = "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at"
        deterministic = self._current(text)
        self.assertEqual(deterministic.capability_hint, understanding.MESSAGE_SEND_CAPABILITY)
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run",
                      return_value=self._envelope(understanding.MESSAGE_SEND_CAPABILITY,
                                                  {"recipient": "ahmet", "body": "başka metin"})):
            adopted = understanding.apply_model_understanding(deterministic, text)
        self.assertEqual(adopted.capability_hint, understanding.MESSAGE_SEND_CAPABILITY)
        self.assertEqual(adopted.arguments.get("body"), "yarın geleceğim")


class MessageUnderstandingTests(unittest.TestCase):
    """Tanıyıcı: WhatsApp mesaj cümlesi tek biçim hükmünden geçer; soru/geçmiş zaman değildir."""

    def test_a_whatsapp_send_sentence_is_the_message_capability(self):
        for text in ("whatsapp'tan ahmet'e mesaj gönder", "WhatsApp ile Ali'ye yaz",
                     "whatsapptan ayşe'ye yarın geleceğim diye mesaj at",
                     "wathsaap'tan anneme geliyorum yaz", "vatsap üzerinden mehmet'e ilet"):
            with self.subTest(text=text):
                self.assertEqual(_hint(text), understanding.MESSAGE_SEND_CAPABILITY)

    def test_the_typed_slots_are_split_once(self):
        cases = {
            "whatsapp'tan ahmet'e mesaj gönder": ("ahmet", ""),
            "whatsapp ile ali'ye yarın geleceğim diye mesaj at": ("ali", "yarın geleceğim"),
            "whatsapp'tan anneme geliyorum yaz": ("annem", "geliyorum"),
            "whatsapptan ayşe'ye toplantı iptal diye yaz": ("ayşe", "toplantı iptal"),
            # Alıcı söylenmediyse slot boş kalır: uydurma alıcı yazılmaz, oturum kendisi sorar.
            "whatsapp'tan mesaj at": ("", ""),
            # Türkçe'de adres sonda da durabilir; gövde adresin dışında kalır (taban LLM
            # çıkarıcısı bu sırayı çözüyordu, yeni gramer de çözüyor).
            "whatsapp'tan yarın geleceğim diye ahmet'e mesaj at": ("ahmet", "yarın geleceğim"),
            "whatsapp ile toplantı iptal diye mehmet'e yaz": ("mehmet", "toplantı iptal"),
        }
        for text, (recipient, body) in cases.items():
            with self.subTest(text=text):
                arguments = understanding._message_arguments(understanding._norm(text))
                self.assertEqual(arguments.get("recipient"), recipient)
                self.assertEqual(arguments.get("body"), body)

    def test_an_ambiguous_address_yields_no_slots_rather_than_a_wrong_body(self):
        # İki dative adayı varsa ("eve" gövdenin parçası, "anneme" alıcı) hangisinin ad olduğu
        # hükme bağlanmaz: yanlış gövdeyi onaya sunmak, kullanıcıya yanlış metin göndertir.
        arguments = understanding._message_arguments(
            understanding._norm("whatsapp'tan yarın eve geleceğim diye anneme mesaj at"))
        self.assertEqual(arguments.get("recipient"), "")
        self.assertEqual(arguments.get("body"), "")

    def test_a_broadcast_or_group_word_is_never_a_recipient(self):
        # "herkese"/"grubuna" kişi adı değildir: slot boş kalır, oturum alıcıyı sorar.
        for text in ("whatsapp'tan herkese mesaj at", "whatsapp grubuna yaz",
                     "whatsapp'tan herkese selam gönder", "whatsapp ile gruba yaz"):
            with self.subTest(text=text):
                self.assertEqual(understanding._message_arguments(understanding._norm(text)).get("recipient"), "")

    def test_a_channel_word_never_leaks_into_the_body(self):
        arguments = understanding._message_arguments(understanding._norm("anneme whatsapp'tan yaz"))
        self.assertEqual(arguments.get("recipient"), "annem")
        self.assertEqual(arguments.get("body"), "")
        self.assertEqual(understanding._message_arguments(
            understanding._norm("whatsapp'tan ahmet'e whatsapp yaz")).get("body"), "")

    def test_a_question_about_whatsapp_is_not_a_send_request(self):
        for text in ("whatsapp nasıl çalışır?", "whatsapp web telefonsuz çalışıyor mu",
                     "whatsapp'ta sabitlenmiş sohbetleri göster",
                     "whatsapp'tan ahmet'e mesaj attım", "whatsapp'tan ahmet'e mesaj attın mı?",
                     "whatsapp mesajı göndermek ne demek",
                     # WhatsApp geçmiyorsa alan seçilmez: başka bir mesaj kanalı tahmin edilmez.
                     "telegram'dan ahmet'e mesaj at", "ahmet'e mesaj at"):
            with self.subTest(text=text):
                self.assertIsNone(_hint(text))


class ContactsUnderstandingTests(unittest.TestCase):
    """Rehber yazma/listeleme de tipli bir öneridir; ham cümleden etki seçilmez."""

    def test_the_contact_add_shapes_are_understood(self):
        self.assertEqual(_hint("kişi ekle ahmet 0532 123 45 67"), understanding.CONTACTS_MANAGE_CAPABILITY)
        self.assertEqual(_hint("rehbere ekle ayşe +90 532 111 22 33"), understanding.CONTACTS_MANAGE_CAPABILITY)
        self.assertEqual(_hint("ahmet'in numarası 0532 123 45 67"), understanding.CONTACTS_MANAGE_CAPABILITY)
        self.assertEqual(understanding._contacts_arguments(understanding._norm("kişi ekle ahmet 0532 123 45 67")),
                         {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"})

    def test_the_contact_list_shapes_are_understood(self):
        for text in ("kişileri listele", "kişileri göster", "rehberim", "Rehberim."):
            with self.subTest(text=text):
                self.assertEqual(_hint(text), understanding.CONTACTS_MANAGE_CAPABILITY)
                self.assertEqual(understanding._contacts_arguments(understanding._norm(text)),
                                 {"operation": "list"})

    def test_a_chat_sentence_about_the_directory_is_not_a_contact_write(self):
        for text in ("rehber nedir?", "kişileri listeleme nasıl yapılır",
                     "kişi ekle ahmet 123", "rehberimde kaç kişi var"):
            with self.subTest(text=text):
                self.assertIsNone(_hint(text))


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


class MessageTurnTests(pr3a._CanonicalAuthorityHarness):
    """Üretim zinciri: Brain → Core → mevcut `pending_msg` oturumu; onay kullanıcının cevabı.

    Alıcı güvenliği: gönderim yalnız **kayıtlı ve tekil** kişi için başlar; onay metni
    çözümlenen kişiyi ve numarasının sonunu gösterir; rehberde olmayan ad hiçbir koşulda
    gönderim çağrısına dönüşmez.
    """

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

    def _threaded_turn(self, text):
        thread = Mock()
        self.ctx.threading = Mock(Thread=thread)
        entry, out, handle, feedback = self.turn_real(text)
        if thread.called:
            thread.call_args.kwargs["target"]()
        return entry, out, handle, feedback

    def test_a_whatsapp_request_opens_the_existing_session_from_typed_slots(self):
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ahmet'e yarın geleceğim diye mesaj at")
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
        _entry, out, _handle, _ = self._threaded_turn("Zeynep")
        self.assertIn("rehber", str(out).casefold())
        self.send.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)

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
        entry, _out, _handle, _ = self.turn_real("whatsapp nasıl çalışır?")
        self.assertIsNone(self.ctx._session().pending_msg)
        self.assertEqual(self.send.call_count, 0)
        self.assertNotEqual(entry.understanding.capability_hint, understanding.MESSAGE_SEND_CAPABILITY)


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
