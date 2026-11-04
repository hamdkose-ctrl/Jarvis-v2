from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextAction,
    ContextReference,
    ConversationRelation,
    RequestKind,
    TemporalNeed,
)
from modules.brain_understanding import is_sequenced, sequence_steps, understand


OWNER = "hamdi"
RID = "req-understanding-1"
RESERVED = {
    "allowed",
    "permission",
    "permission_granted",
    "approved",
    "authorized",
    "completed",
    "done",
    "effect_allowed",
    "execute",
}


def ref(ident: str, kind: str, *, source: str = "test", **provenance) -> ContextReference:
    return ContextReference(
        id=ident,
        kind=kind,
        source=source,
        owner=OWNER,
        provenance=provenance,
    )


def ctx(*, owner: str = OWNER, request_id: str = RID, topic: str | None = None, **groups) -> ActiveContext:
    return ActiveContext(owner=owner, request_id=request_id, topic=topic, **groups)


def authority_keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict) or hasattr(value, "items"):
        for key, item in value.items():
            if isinstance(key, str) and key in RESERVED:
                found.add(key)
            found.update(authority_keys(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(authority_keys(item))
    return found


class BrainUnderstandingTests(unittest.TestCase):
    def call(
        self,
        text: str,
        *,
        active_context: ActiveContext | None = None,
        candidates=(),
        references=(),
        owner: str = OWNER,
        request_id: str = RID,
    ):
        return understand(
            owner=owner,
            request_id=request_id,
            text=text,
            active_context=active_context or ctx(),
            candidates=tuple(candidates),
            references=tuple(references),
        )

    def test_owner_request_and_context_fences_fail_closed(self):
        with self.assertRaises(ValueError):
            self.call("merhaba", owner="")
        with self.assertRaises(ValueError):
            self.call("merhaba", request_id="")
        with self.assertRaises(ValueError):
            self.call("merhaba", active_context=ctx(owner="other"))
        with self.assertRaises(ValueError):
            self.call("merhaba", active_context=ctx(request_id="other"))

    def test_cross_owner_reference_fails_closed(self):
        foreign = ContextReference(id="x", kind="note", source="test", owner="other")
        with self.assertRaises(ValueError):
            self.call("x", references=(foreign,))
        with self.assertRaises(ValueError):
            self.call("x", candidates=(foreign,))

    def test_references_must_be_existing_candidate_objects(self):
        arbitrary = ref("n-arbitrary", "note", title="Arbitrary")
        other = ref("n-other", "note", title="Other")
        with self.assertRaises(ValueError):
            self.call("Arbitrary", candidates=(), references=(arbitrary,))
        with self.assertRaises(ValueError):
            self.call("Arbitrary", candidates=(other,), references=(arbitrary,))

        canonical = ref("n-same", "note", title="Same")
        clone = ContextReference(
            id=canonical.id,
            kind=canonical.kind,
            source=canonical.source,
            owner=canonical.owner,
            provenance={"title": "Same"},
        )
        with self.assertRaises(ValueError):
            self.call("Same", candidates=(canonical,), references=(clone,))

    def test_new_request_is_default_without_context_claim(self):
        result = self.call("kuantum dolanıklık nedir?")
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_answer_to_open_pending_requires_semantic_fit(self):
        pending = ref(
            "pending_weather_location",
            "pending_state",
            source="session_state",
            field="pending_weather_location",
        )
        active = ctx(pending_references=(pending,))
        result = self.call("İstanbul", active_context=active, candidates=(pending,))
        self.assertEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.pending_owner, "session.pending_weather_location")
        self.assertNotEqual(result.request_kind, RequestKind.CLARIFY)

    def test_weather_pending_rejects_unrelated_short_sentence(self):
        pending = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        active = ctx(pending_references=(pending,))
        result = self.call("yarın toplantım var", active_context=active, candidates=(pending,))
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_message_pending_accepts_bounded_recipient_and_text_answers(self):
        rows = (
            ({"to": "", "text": "", "stage": "to"}, "Ebru", "session.pending_msg.to"),
            ({"to": "Ebru", "text": "", "stage": "text"}, "Yarın geliyorum.",
             "session.pending_msg.text"),
        )
        for value, text, owner in rows:
            with self.subTest(stage=value["stage"]):
                pending = ref("pending_msg", "pending_state", field="pending_msg", value=value)
                active = ctx(pending_references=(pending,))
                result = self.call(text, active_context=active, candidates=(pending,))
                self.assertEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
                self.assertEqual(result.pending_owner, owner)

    def test_specific_location_owner_outranks_a_generic_message_text_slot(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        message = ref("pending_msg", "pending_state", field="pending_msg",
                      value={"to": "Ebru", "text": "", "stage": "text"})
        active = ctx(pending_references=(weather, message))
        result = self.call("İstanbul", active_context=active, candidates=(weather, message))
        self.assertEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.pending_owner, "session.pending_weather_location")

    def test_recipient_and_location_tie_is_a_fail_closed_ambiguity(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        message = ref("pending_msg", "pending_state", field="pending_msg",
                      value={"to": "", "text": "", "stage": "to"})
        active = ctx(pending_references=(weather, message))
        result = self.call("İstanbul", active_context=active, candidates=(weather, message))
        self.assertEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertIsNone(result.pending_owner)
        self.assertEqual(result.request_kind, RequestKind.CLARIFY)
        self.assertTrue(result.needs_input)
        self.assertIn("MULTIPLE_PENDING_ANSWER_OWNERS", result.ambiguities)

    def test_typed_clarify_owner_outranks_an_open_location_question(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        clarify = ref(
            "pending_action", "pending_state", source="session_state",
            field="pending_action", active=True, targets=("Chrome", "Edge"),
            value={"stage": "clarify", "command": "aç", "owner": OWNER, "expires": 9999999999,
                   "proposal": {"kind": "app.open"}},
        )
        active = ctx(pending_references=(clarify, weather))
        result = self.call("Chrome", active_context=active, candidates=(clarify, weather))
        self.assertEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.pending_owner, "session.pending_action.clarify")
        self.assertEqual(result.capability_hint, "app.open")
        self.assertEqual(result.arguments["app"], "Chrome")

    def test_independent_capability_carries_no_pending_owner(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        active = ctx(pending_references=(weather,))
        result = self.call("notlarımı göster", active_context=active, candidates=(weather,))
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIsNone(result.pending_owner)

    def message_draft(self):
        return ref("pending_msg", "pending_state", field="pending_msg",
                   value={"to": "Ebru", "text": "", "stage": "text"})

    def test_capability_classes_are_never_the_pending_message_answer(self):
        pending = self.message_draft()
        active = ctx(pending_references=(pending,))
        cases = (
            ("notlarımı göster", "notes.read"),
            ("hava nasıl", "weather.read"),
            ("iyi günler İngilizceye çevir", "text.translate"),
            # Bu ikisi eskiden `None`'dı: etkiyi ham cümleyi ikinci kez yorumlayan legacy dal
            # seçiyordu. PR3A'dan sonra capability'nin tek sahibi Understanding, etkinin tek
            # sahibi Core intent (weather -> runtime._weather, screen_capture -> desktop.screenshot).
            ("hava durumuna bak", "weather.read"),
            ("ekran görüntüsü al", "screen.capture"),
        )
        for text, hint in cases:
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(pending,))
                self.assertIs(result.request_kind, RequestKind.CAPABILITY)
                self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)
                self.assertIsNone(result.pending_owner)
                self.assertEqual(result.capability_hint, hint)

    def test_definition_questions_are_not_legacy_capability_commands(self):
        # "hava durumu nedir" bir komut değil açıklama sorusudur; legacy sahibi adına
        # capability sayılırsa Core manifesti doğrulayamaz ve sohbet fail-closed clarify olurdu.
        for text in ("hava durumu nedir", "ekran görüntüsü ne demek"):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertIs(result.request_kind, RequestKind.CHAT)
                self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_file_capabilities_are_never_the_pending_message_answer(self):
        pending = self.message_draft()
        file = ref("/data/rapor.docx", "file", path="/data/rapor.docx", name="rapor.docx")
        active = ctx(pending_references=(pending,))
        cases = (
            ("rapor.docx dosyasını incele", "analyze"),
            ("rapor.docx dosyasını İngilizceye çevir", "translate"),
            ("rapor.docx dosyasını PDF'e dönüştür", "convert"),
        )
        for text, operation in cases:
            with self.subTest(text=text):
                result = self.call(text, active_context=active,
                                   candidates=(pending, file), references=(file,))
                self.assertIs(result.request_kind, RequestKind.CAPABILITY)
                self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)
                self.assertIsNone(result.pending_owner)
                self.assertEqual(result.capability_hint, "files.read")
                self.assertEqual(result.arguments.get("operation"), operation)
                self.assertEqual(result.arguments.get("path"), "/data/rapor.docx")

    def test_translation_with_a_brain_source_is_capability_not_message_text(self):
        pending = self.message_draft()
        source = ref("turn-1", "conversation_turn", role="user", text="gizli metin",
                     ts=(datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"))
        active = ctx(pending_references=(pending,))
        result = self.call("bunu İngilizceye çevir", active_context=active,
                           candidates=(pending, source))
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIsNone(result.pending_owner)
        self.assertEqual(result.arguments["translate"]["text"], "gizli metin")

    def test_typed_clarify_answer_owns_the_turn_while_a_message_draft_is_open(self):
        message = self.message_draft()
        clarify = ref(
            "pending_action", "pending_state", source="session_state",
            field="pending_action", active=True, targets=("Chrome", "Edge"),
            value={"stage": "clarify", "command": "aç", "owner": OWNER, "expires": 9999999999,
                   "proposal": {"kind": "app.open"}},
        )
        active = ctx(pending_references=(clarify, message))
        result = self.call("Chrome", active_context=active, candidates=(clarify, message))
        self.assertIs(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.pending_owner, "session.pending_action.clarify")
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, "app.open")

    def test_free_form_bodies_are_owned_by_the_message_text_slot(self):
        # pending_msg(stage=text) bounded bir kimlik/mekân slotu değil, free-text foreground slot'tur:
        # selam, soru cümlesi ve doğal sohbet dili mesaj gövdesidir.
        pending = self.message_draft()
        active = ctx(pending_references=(pending,))
        for text in ("Selam", "Nasılsın?", "İyi misin?", "Yarın geliyor musun?",
                     "Selam, nasılsın? Yarın görüşelim mi?", "Kuantum hakkında konuşalım"):
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(pending,))
                self.assertIs(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
                self.assertEqual(result.pending_owner, "session.pending_msg.text")

    def test_recipient_slot_stays_bounded_while_the_body_slot_is_free_form(self):
        recipient = ref("pending_msg", "pending_state", field="pending_msg",
                        value={"to": "", "text": "", "stage": "to"})
        active = ctx(pending_references=(recipient,))
        bounded = self.call("Ebru", active_context=active, candidates=(recipient,))
        self.assertEqual(bounded.pending_owner, "session.pending_msg.to")
        for text in ("nasılsın?", "kuantum hakkında konuşalım"):
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(recipient,))
                self.assertIsNone(result.pending_owner)
                self.assertIsNot(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_recipient_slot_accepts_multi_word_names_without_a_word_count_rule(self):
        recipient = ref("pending_msg", "pending_state", field="pending_msg",
                        value={"to": "", "text": "", "stage": "to"})
        active = ctx(pending_references=(recipient,))
        for text in ("Mehmet Ali Yılmaz", "Mehmet Ali Can Yılmaz", "Ayşe Nur Demir"):
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(recipient,))
                self.assertIs(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
                self.assertEqual(result.pending_owner, "session.pending_msg.to")

    def test_recipient_slot_rejects_sentence_shapes_not_identity_names(self):
        recipient = ref("pending_msg", "pending_state", field="pending_msg",
                        value={"to": "", "text": "", "stage": "to"})
        active = ctx(pending_references=(recipient,))
        for text in ("Selam nasılsın bugün", "kuantum hakkında konuşalım",
                     "nasılsın?", "bugün hava nasıl?"):
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(recipient,))
                self.assertIsNone(result.pending_owner)
                self.assertIsNot(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_registered_contact_evidence_strengthens_the_recipient_owner(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        message = ref("pending_msg", "pending_state", field="pending_msg",
                      value={"to": "", "text": "", "stage": "to"},
                      recipient_candidates=("İstanbul Ofis",))
        active = ctx(pending_references=(weather, message))
        result = self.call("İstanbul Ofis", active_context=active, candidates=(weather, message))
        self.assertEqual(result.pending_owner, "session.pending_msg.to")
        self.assertNotIn("MULTIPLE_PENDING_ANSWER_OWNERS", result.ambiguities)

    def test_unregistered_shape_does_not_strengthen_the_recipient_owner(self):
        weather = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        message = ref("pending_msg", "pending_state", field="pending_msg",
                      value={"to": "", "text": "", "stage": "to"},
                      recipient_candidates=("Ankara Ofis",))
        active = ctx(pending_references=(weather, message))
        result = self.call("İstanbul Ofis", active_context=active, candidates=(weather, message))
        self.assertIsNone(result.pending_owner)
        self.assertIn("MULTIPLE_PENDING_ANSWER_OWNERS", result.ambiguities)

    def test_message_pending_does_not_consume_new_requests_or_confirmations(self):
        text_pending = ref("pending_msg", "pending_state", field="pending_msg",
                           value={"to": "Ebru", "text": "", "stage": "text"})
        active = ctx(pending_references=(text_pending,))
        result = self.call("notlarımı göster", active_context=active, candidates=(text_pending,))
        self.assertNotEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.request_kind, RequestKind.CAPABILITY)

        confirm_pending = ref("pending_msg", "pending_state", field="pending_msg",
                              value={"to": "Ebru", "text": "Merhaba", "stage": "confirm"})
        active = ctx(pending_references=(confirm_pending,))
        result = self.call("başka bir şey", active_context=active, candidates=(confirm_pending,))
        self.assertNotEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_generic_pending_question_does_not_consume_unrelated_short_sentence(self):
        pending = ref(
            "pending_action",
            "pending_state",
            field="pending_action",
            value={"stage": "clarify", "command": "aç", "question": "Hangi dosyayı kastettin?",
                   "owner": OWNER, "expires": 9999999999},
        )
        active = ctx(pending_references=(pending,))
        result = self.call("yarın toplantım var", active_context=active, candidates=(pending,))
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_pending_exists_alone_is_not_answer_to_pending(self):
        pending = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        active = ctx(pending_references=(pending,))
        result = self.call("merhaba nasılsın", active_context=active, candidates=(pending,))
        self.assertNotEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_pending_presence_is_not_relation_authority(self):
        pending = ref(
            "pending_action",
            "pending_state",
            field="pending_action",
            value={"stage": "clarify", "command": "aç", "question": "Ne yapmak istersin?",
                   "owner": OWNER, "expires": 9999999999},
        )
        active = ctx(pending_references=(pending,))
        result = self.call("kuantum fiziği konuşalım", active_context=active, candidates=(pending,))
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_weather_pending_does_not_consume_unrelated_request(self):
        pending = ref("pending_weather_location", "pending_state", field="pending_weather_location")
        active = ctx(pending_references=(pending,))
        result = self.call("notlarımı göster", active_context=active, candidates=(pending,))
        self.assertNotEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.request_kind, RequestKind.CAPABILITY)

    def test_exact_yes_no_and_bounded_number_are_left_to_pr6(self):
        pending = ref("pending_choice", "pending_state", field="pending_choice")
        active = ctx(pending_references=(pending,))
        for text in ("evet", "hayır", "2"):
            with self.subTest(text=text):
                result = self.call(text, active_context=active, candidates=(pending,))
                self.assertNotEqual(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_continue_active_when_resolved_reference_is_active(self):
        task = ref("task-42", "task", text="Raporu bitir")
        active = ctx(active_task_references=(task,))
        result = self.call("ona devam et", active_context=active, candidates=(task,), references=(task,))
        self.assertEqual(result.conversation_relation, ConversationRelation.CONTINUE_ACTIVE)
        self.assertIs(result.references[0], task)

    def test_pdf_not_word_is_correction_without_durable_reset(self):
        result = self.call("PDF değil Word")
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIn(ContextAction.REPLACE_REFERENCE, result.context_actions)
        self.assertNotIn(ContextAction.RESET_SESSION_CONTEXT, result.context_actions)

    def test_onu_degil_otekini_is_reference_correction(self):
        one = ref("file-a", "file", name="a.pdf")
        two = ref("file-b", "file", name="b.pdf")
        result = self.call("onu değil ötekini", candidates=(one, two), references=(one, two))
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIn(ContextAction.REPLACE_REFERENCE, result.context_actions)

    def test_hayir_location_replacement_is_correction(self):
        result = self.call("hayır, Ankara değil İzmir")
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIn(ContextAction.REPLACE_REFERENCE, result.context_actions)

    def test_question_with_degil_is_not_automatically_correction(self):
        result = self.call("Python statik değil dinamik mi?")
        self.assertNotEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertNotIn(ContextAction.REPLACE_REFERENCE, result.context_actions)

    def test_bosver_is_context_control_but_not_completion(self):
        result = self.call("boşver")
        self.assertEqual(result.request_kind, RequestKind.CONTEXT_CONTROL)
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIn(ContextAction.DROP_TOPIC, result.context_actions)
        self.assertFalse(hasattr(result, "completed"))

    def test_bosver_prefix_drops_old_topic(self):
        result = self.call("boşver, hava nasıl?")
        self.assertEqual(result.request_kind, RequestKind.CONTEXT_CONTROL)
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIn(ContextAction.DROP_TOPIC, result.context_actions)
        self.assertNotIn(ContextAction.KEEP, result.context_actions)

    def test_baska_konu_is_topic_change(self):
        result = self.call("başka konu")
        self.assertEqual(result.request_kind, RequestKind.CONTEXT_CONTROL)
        self.assertEqual(result.conversation_relation, ConversationRelation.TOPIC_CHANGE)
        self.assertIn(ContextAction.DROP_TOPIC, result.context_actions)

    def test_konuyu_degistirmek_definition_is_not_topic_change(self):
        result = self.call("konuyu değiştirmek ne demek?")
        self.assertNotEqual(result.conversation_relation, ConversationRelation.TOPIC_CHANGE)
        self.assertNotIn(ContextAction.DROP_TOPIC, result.context_actions)

    def test_temporal_need_static(self):
        self.assertEqual(self.call("Python nedir?").temporal_need, TemporalNeed.STATIC)

    def test_temporal_need_current(self):
        self.assertEqual(self.call("şu an hava nasıl?").temporal_need, TemporalNeed.CURRENT)

    def test_temporal_need_recent(self):
        self.assertEqual(self.call("son günlerde teknoloji haberleri").temporal_need, TemporalNeed.RECENT)

    def test_temporal_need_historical(self):
        self.assertEqual(self.call("2020 yılında ne oldu?").temporal_need, TemporalNeed.HISTORICAL)

    def test_temporal_need_unsure(self):
        self.assertEqual(self.call("bunun hakkında konuşalım").temporal_need, TemporalNeed.UNSURE)

    def test_no_requires_current_data_parallel_field(self):
        result = self.call("şu an hava nasıl?")
        self.assertFalse(hasattr(result, "requires_current_data"))
        self.assertNotIn("requires_current_data", result.to_dict())

    def test_request_kind_chat(self):
        self.assertEqual(self.call("merhaba nasılsın").request_kind, RequestKind.CHAT)

    def test_request_kind_capability(self):
        result = self.call("notlarımı göster")
        self.assertEqual(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, "notes.read")

    def test_capability_command_tokens_do_not_match_inside_words(self):
        for text in ("araştırma nedir?", "bir bulut nedir?"):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CHAT)
                self.assertIsNone(result.capability_hint)

    def test_request_kind_context_control(self):
        self.assertEqual(self.call("başka konu").request_kind, RequestKind.CONTEXT_CONTROL)

    def test_singular_target_with_multiple_references_clarifies(self):
        one = ref(r"C:\A\rapor.pdf", "file", path=r"C:\A\rapor.pdf", name="rapor.pdf")
        two = ref(r"C:\B\rapor.pdf", "file", path=r"C:\B\rapor.pdf", name="rapor.pdf")
        result = self.call("rapor.pdf'i aç", candidates=(one, two), references=(one, two))
        self.assertEqual(result.request_kind, RequestKind.CLARIFY)
        self.assertTrue(result.needs_input)
        self.assertTrue(result.ambiguities)

    def test_clarify_always_needs_input(self):
        one = ref("a", "file", name="rapor.pdf")
        two = ref("b", "file", name="rapor.pdf")
        result = self.call("rapor.pdf'i aç", candidates=(one, two), references=(one, two))
        self.assertTrue(result.needs_input)
        self.assertEqual(result.request_kind, RequestKind.CLARIFY)

    def test_needs_input_is_never_emitted_without_real_reason(self):
        result = self.call("notlarımı göster")
        self.assertFalse(result.needs_input)
        self.assertFalse(result.ambiguities)

    def test_multiple_references_are_not_automatically_ambiguous(self):
        one = ref("f1", "file", name="a.pdf")
        two = ref("f2", "file", name="b.pdf")
        result = self.call("bu iki dosyayı karşılaştır", candidates=(one, two), references=(one, two))
        self.assertNotEqual(result.request_kind, RequestKind.CLARIFY)
        self.assertFalse(result.needs_input)
        self.assertEqual(result.references, (one, two))

    def test_no_candidate_never_creates_fake_reference(self):
        result = self.call("rapor.pdf'i aç")
        self.assertEqual(result.references, ())

    def test_reference_identity_is_preserved(self):
        candidate = ref("n1", "note", title="Notum")
        result = self.call("Notum", candidates=(candidate,), references=(candidate,))
        self.assertEqual(result.references, (candidate,))
        self.assertIs(result.references[0], candidate)

    def test_capability_hint_is_advisory_not_authority(self):
        result = self.call("notlarımı göster")
        self.assertEqual(result.capability_hint, "notes.read")
        self.assertFalse(authority_keys(result.arguments))
        for attr in ("allowed", "permission", "permission_granted", "authorized", "effect_allowed", "execute"):
            self.assertFalse(hasattr(result, attr))

    def test_reserved_authority_argument_keys_are_never_produced(self):
        samples = (
            "notlarımı göster",
            "rapor.pdf'i aç",
            "şu an hava nasıl?",
            "boşver",
            "PDF değil Word",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(authority_keys(self.call(text).arguments), set())

    def test_memory_approved_and_done_are_non_authority_provenance(self):
        approved = ref("m1", "memory", source="memory", approved=True, text="tercih")
        done = ref("m2", "memory", source="memory", done=True, text="eski iş")
        active = ctx(memory_references=(approved, done))
        result = self.call("yeni bir şey konuşalım", active_context=active, candidates=(approved, done))
        self.assertEqual(result.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(authority_keys(result.arguments), set())
        self.assertFalse(hasattr(result, "permission"))
        self.assertFalse(hasattr(result, "completed"))

    def test_context_actions_are_canonical_enum_only(self):
        for text in ("boşver", "başka konu", "PDF değil Word"):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertTrue(all(isinstance(action, ContextAction) for action in result.context_actions))

    def test_original_user_text_is_preserved_as_semantic_source(self):
        text = "  PDF değil Word  "
        result = self.call(text)
        self.assertEqual(result.arguments["original_text"], text)

    def test_reason_codes_are_safe_labels_not_chain_of_thought(self):
        result = self.call("PDF değil Word")
        self.assertTrue(result.reason_codes)
        for code in result.reason_codes:
            self.assertLessEqual(len(code), 64)
            self.assertRegex(code, r"^[A-Z0-9_]+$")
            self.assertNotIn("because", code.casefold())
            self.assertNotIn("çünkü", code.casefold())

    def test_deterministic_fallback(self):
        first = self.call("bunun hakkında konuşalım")
        second = self.call("bunun hakkında konuşalım")
        self.assertEqual(first, second)
        self.assertEqual(first.confidence, Confidence.MEDIUM)

    def test_malformed_inputs_fail_safe_without_model_repair(self):
        with self.assertRaises(ValueError):
            understand(owner=OWNER, request_id=RID, text=object(), active_context=ctx(), candidates=(), references=())
        with self.assertRaises(ValueError):
            understand(owner=OWNER, request_id=RID, text="x", active_context=ctx(), candidates=[], references=())
        with self.assertRaises(ValueError):
            understand(owner=OWNER, request_id=RID, text="x", active_context=ctx(), candidates=(), references=[])

    def test_provider_independent_public_surface(self):
        params = inspect.signature(understand).parameters
        self.assertEqual(
            tuple(params),
            ("owner", "request_id", "text", "active_context", "candidates", "references"),
        )
        for forbidden in ("model", "provider", "gemini", "groq", "ollama", "openai"):
            self.assertNotIn(forbidden, params)

    def test_no_permission_effect_worker_completion_or_durable_brain_state(self):
        import modules.brain_understanding as module

        source = inspect.getsource(module).casefold()
        forbidden = (
            "nxapi.allowed",
            "permission_granted",
            "effect_allowed",
            "worker.run",
            "task_workers",
            "goal_executor",
            "sessionstore(",
            "goalstate(",
            ".save(",
            ".write(",
            "json.dump",
            "completed=true",
            "done=true",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_no_second_sessionstore_or_goalstate_and_no_source_reads(self):
        import modules.brain_understanding as module

        source = inspect.getsource(module).casefold()
        forbidden = (
            "brain_context.build_active_context",
            "brain_candidates.build_candidates",
            "session_store",
            "goal_state",
            "history.read",
            "profile(",
            "nxapi.list_files",
            "open(",
            "requests.",
            "urllib",
            "socket",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_no_model_provider_invocation_or_semantic_output_repair_path(self):
        import modules.brain_understanding as module

        source = inspect.getsource(module).casefold()
        for token in ("openai", "gemini", "groq", "ollama", "modules.llm", "smart_router", "embedding", "model.generate"):
            self.assertNotIn(token, source)

    def test_production_wiring_is_not_in_understanding_module(self):
        import modules.brain_understanding as module

        source = inspect.getsource(module).casefold()
        for token in ("modules.main", "modules.engine", "web.py", "nx.js", "live.py", "brainfeedback"):
            self.assertNotIn(token, source)


class BrainUnderstandingReviewRegressionTests(BrainUnderstandingTests):
    def test_capability_domain_signals_are_bounded(self):
        cases = (
            ("noter göster", "notes.read"),
            ("havale göster", "weather.read"),
            ("keyword aç", "files.read"),
        )
        for text, forbidden_hint in cases:
            with self.subTest(text=text):
                result = self.call(text)
                self.assertNotEqual(result.capability_hint, forbidden_hint)

    def test_meta_language_command_words_are_chat_not_capability(self):
        for text in (
            "ara ne demek?",
            "bul ne demek?",
            "göster fiili ne demek?",
            "sil kelimesi ne anlama gelir?",
        ):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CHAT)
                self.assertIsNone(result.capability_hint)
                self.assertEqual(result.temporal_need, TemporalNeed.STATIC)

    def test_real_commands_still_propose_capability(self):
        cases = (
            ("internette ara", "research.search"),
            ("dosyayı bul", "files.read"),
            ("notlarımı göster", "notes.read"),
        )
        for text, hint in cases:
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(result.capability_hint, hint)

    def test_bosver_meta_language_is_not_context_control_or_correction(self):
        result = self.call("boşver kelimesi ne demek?")
        self.assertEqual(result.request_kind, RequestKind.CHAT)
        self.assertNotEqual(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertNotIn(ContextAction.DROP_TOPIC, result.context_actions)
        self.assertEqual(result.temporal_need, TemporalNeed.STATIC)

    def test_bosver_real_controls_still_drop_topic(self):
        for text in ("boşver", "boşver, hava nasıl?"):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CONTEXT_CONTROL)
                self.assertIn(ContextAction.DROP_TOPIC, result.context_actions)

    def test_temporal_meta_language_is_static(self):
        for text in (
            "bugün kelimesi ne demek?",
            "güncel sözcüğü ne demek?",
            "2020 sayısı nedir?",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.call(text).temporal_need, TemporalNeed.STATIC)

    def test_temporal_positive_cases_remain_semantic(self):
        cases = (
            ("bugünkü dolar kuru ne?", TemporalNeed.CURRENT),
            ("son bir haftadaki haberler", TemporalNeed.RECENT),
            ("2020 yılında ne oldu?", TemporalNeed.HISTORICAL),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.call(text).temporal_need, expected)


class BrainUnderstandingFinalCloseoutTests(BrainUnderstandingReviewRegressionTests):
    def test_weather_requests_are_capability_with_advisory_hint(self):
        cases = (
            ("şu an hava nasıl?", "weather.read.current", TemporalNeed.CURRENT),
            ("hava nasıl?", "weather.read", TemporalNeed.UNSURE),
            ("yarın hava nasıl?", "weather.read.current", TemporalNeed.CURRENT),
        )
        for text, hint, temporal in cases:
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(result.capability_hint, hint)
                self.assertEqual(result.temporal_need, temporal)
                self.assertEqual(authority_keys(result.arguments), set())

    def test_literal_weather_uses_are_chat_without_weather_hint(self):
        for text in (
            "hava yolu nedir?",
            "hava kuvvetleri nedir?",
            "“hava” kelimesi ne demek?",
        ):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CHAT)
                self.assertIsNone(result.capability_hint)
                self.assertEqual(result.temporal_need, TemporalNeed.STATIC)

    def test_temporal_clear_cases(self):
        cases = (
            ("son haber nedir?", TemporalNeed.RECENT),
            ("yarın hava nasıl?", TemporalNeed.CURRENT),
            ("dünkü hava nasıldı?", TemporalNeed.HISTORICAL),
            ("bugünkü dolar kuru ne?", TemporalNeed.CURRENT),
            ("son bir haftadaki haberler", TemporalNeed.RECENT),
            ("2020 yılında ne oldu?", TemporalNeed.HISTORICAL),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.call(text).temporal_need, expected)

    def test_meta_static_temporal_variants(self):
        for text in (
            "güncel sözcüğünü İngilizceye çevir",
            "2020 model ne demek?",
            "güncel olmayan yaklaşım ne demek?",
            "yakın zamanda ifadesi kaç günü anlatır?",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.call(text).temporal_need, TemporalNeed.STATIC)
        self.assertEqual(self.call("2020 model araba bugün kaç para?").temporal_need, TemporalNeed.CURRENT)

    def test_literal_command_words_are_not_action_proposals(self):
        for text in (
            "bu metinde “sil” yazıyor",
            "“göster” kelimesini yaz",
            "“ara” komutu ne anlama gelir?",
        ):
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CHAT)
                self.assertIsNone(result.capability_hint)

    def test_read_like_domain_commands_keep_read_hints(self):
        cases = (
            ("dosyayı bul", "files.read"),
            ("dosyayı aç", "files.read"),
            ("notlarımı göster", "notes.read"),
            ("internette ara", "research.search"),
        )
        for text, hint in cases:
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(result.capability_hint, hint)

    def test_destructive_domain_commands_do_not_claim_read_capability(self):
        cases = (
            ("dosyayı sil", "files.read"),
            ("notu sil", "notes.read"),
        )
        for text, forbidden_hint in cases:
            with self.subTest(text=text):
                result = self.call(text)
                self.assertEqual(result.request_kind, RequestKind.CAPABILITY)
                self.assertNotEqual(result.capability_hint, forbidden_hint)
                self.assertIsNone(result.capability_hint)

    def test_bosver_prefix_keeps_weather_semantics_while_dropping_topic(self):
        result = self.call("boşver, hava nasıl?")
        self.assertEqual(result.request_kind, RequestKind.CONTEXT_CONTROL)
        self.assertEqual(result.capability_hint, "weather.read")
        self.assertIn(ContextAction.DROP_TOPIC, result.context_actions)


class SequenceGrammarTests(unittest.TestCase):
    """Sıra grameri (BRAIN-MIG-017): tipli adım planının tek sahibi Understanding'dir.

    Eski sahibi `engine_sequence._split_steps` ham motor yüzeyinden emekli edildi; sözleşme
    olduğu gibi bu kata taşındı (sıra, kısa parça çiti, beş adım sınırı, geçersiz tip)."""

    def test_documented_sequence_forms_keep_their_order(self):
        for command in ('önce maili oku, sonra raporu yaz', 'maili oku ardından raporu yaz',
                        'maili oku akabinde raporu yaz', 'ÖNCE maili oku SONRA raporu yaz',
                        ' önce maili oku, ve daha sonra, raporu yaz. '):
            with self.subTest(command=command):
                self.assertEqual(sequence_steps(command), ('maili oku', 'raporu yaz'))

    def test_single_empty_or_unmarked_sentences_produce_no_plan(self):
        for command in ('', '   ', 'maili oku', 'önce maili oku', 'önce', 'sonra raporu yaz',
                        'maili oku ve raporu yaz', 'aç ardından x', 'önce abc sonra xy'):
            with self.subTest(command=command):
                self.assertEqual(sequence_steps(command), ())

    def test_short_parts_are_filtered_at_the_three_character_boundary(self):
        self.assertEqual(sequence_steps('önce ab sonra abc ardından def'), ('abc', 'def'))
        self.assertEqual(sequence_steps('önce abc sonra def'), ('abc', 'def'))

    def test_six_or_more_steps_are_capped_at_five(self):
        for count in (2, 5, 6, 100):
            with self.subTest(count=count):
                steps = [f'adım {index}' for index in range(count)]
                self.assertEqual(sequence_steps('önce ' + ' sonra '.join(steps)), tuple(steps[:5]))

    def test_a_long_step_is_passed_intact_without_truncation(self):
        long_step = 'ğ' * 100000
        self.assertEqual(sequence_steps('önce ' + long_step + ' sonra bitir'), (long_step, 'bitir'))

    def test_invalid_types_raise_before_any_step_exists(self):
        for command in (None, True, 12, b'abc', [], {}):
            with self.subTest(command=command), self.assertRaises(TypeError):
                sequence_steps(command)

    def test_the_marker_veto_is_wider_than_the_step_plan(self):
        # Tek adımlı 'önce …' bölünmez ama sıralı sayılır: canonical plan vetosu bu hükmü okur.
        self.assertTrue(is_sequenced('önce maili oku'))
        self.assertEqual(sequence_steps('önce maili oku'), ())
        self.assertFalse(is_sequenced('maili oku'))


    def test_canonical_understanding_propagates_model_request_cancellation(self):
        from modules import requests_state
        source = ref("file:rapor", "file", path="C:/Users/hamdi/Documents/rapor.pdf", name="rapor.pdf")
        with patch(
            "modules.brain_model_understanding.refine",
            side_effect=requests_state.Cancelled("cancelled"),
        ):
            with self.assertRaises(requests_state.Cancelled):
                self.call("rapor dosyasını özetle", candidates=(source,), references=(source,))

    def test_model_file_proposal_is_wired_into_canonical_understanding(self):
        from modules.brain_model_understanding import SemanticRefinement
        source = ref('file:rapor', 'file', path='C:/Users/hamdi/Documents/rapor.pdf', name='rapor.pdf')
        proposal = SemanticRefinement(RequestKind.CAPABILITY, ConversationRelation.NEW_REQUEST,
                                      TemporalNeed.UNSURE, 'files.read', Confidence.LOW,
                                      {'original_text': 'şu raporu bir incele', 'operation': 'analyze',
                                       'path': 'C:/Users/hamdi/Documents/rapor.pdf'})
        with patch('modules.brain_model_understanding.refine', return_value=proposal):
            result = self.call('şu raporu bir incele', candidates=(source,), references=(source,))
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, 'files.read')
        self.assertEqual(result.arguments['operation'], 'analyze')


if __name__ == "__main__":
    unittest.main()
