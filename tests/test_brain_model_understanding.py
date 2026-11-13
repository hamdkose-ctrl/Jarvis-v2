"""BRAIN-01: birincil model zarfının sınırları (ücretsiz rota, tek çağrı, Core yeniden doğrulama).

Zarf biçimi ``brain-understanding.v2``dir; eski "yalnız tipli alan cilalama" sözleşmesi
BRAIN-01'de kaldırıldığı için bu dosyadaki beklentiler modelin karar üretebildiğini,
yetkinin ise Core'da kaldığını birlikte doğrular.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.brain_contracts import (
    Confidence, ContextReference, ConversationRelation, RequestKind, TemporalNeed, UnderstandingResult,
)
from modules import brain_model_understanding as model


OWNER = "hamdi"


def current(**changes):
    values = dict(
        owner=OWNER,
        request_id="req-model-1",
        request_kind=RequestKind.CAPABILITY,
        capability_hint="files.read",
        arguments={"operation": "summarize", "path": "C:/Users/hamdi/Documents/rapor.pdf"},
        conversation_relation=ConversationRelation.NEW_REQUEST,
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.MEDIUM,
    )
    values.update(changes)
    return UnderstandingResult(**values)


def action(capability_id, arguments=None, slots=None, *, action_id="a1"):
    return {
        "action_id": action_id,
        "capability_id": capability_id,
        "arguments": arguments or {},
        "reference_slots": slots or [],
        "depends_on": [],
    }


def answer(**changes):
    values = {
        "schema_version": model.SCHEMA_VERSION,
        "operation": "chat",
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "STATIC",
        "target_goal_ids": [],
        "goal": None,
        "actions": [],
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": "LOW",
    }
    values.update(changes)
    return json.dumps(values)


def direct(capability_id, arguments=None, slots=None, **changes):
    changes.setdefault("confidence", "MEDIUM")
    return answer(operation="direct_action",
                  actions=[action(capability_id, arguments, slots)], **changes)


class BrainModelUnderstandingTests(unittest.TestCase):
    def setUp(self):
        owner_patch = patch("modules.llm.current_user", return_value=OWNER)
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def eligible(self):
        return (
            patch("modules.llm.provider", return_value="groq"),
            patch("modules.llm.privacy.mode", return_value="normal"),
            patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
        )

    def ask(self, raw, text="rapor dosyasını özetle", *, active=None, args=None, **kwargs):
        active = current() if active is None else active
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            return model.propose(owner=OWNER, text=text, current=active,
                                 arguments=(active.arguments if args is None else args), **kwargs)

    def payload(self, text="Metni ileride okuyabilmek için saklamak istiyorum.", *, active=None, **kwargs):
        """Modelin gerçekten gördüğü yükü yakalar: sözleşme metni burada denetlenir."""
        captured = {}

        def run(owner, combined, callback, **router):
            captured["payload"], _ = json.JSONDecoder().raw_decode(combined)
            self.model_input = combined
            return answer()

        active = current() if active is None else active
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=run):
            model.propose(owner=OWNER, text=text, current=active,
                          arguments=active.arguments, **kwargs)
        return captured["payload"]

    def test_prompt_states_whether_a_session_output_actually_exists(self):
        present = self.payload(session_artifacts=({"slot": "last_doc", "label": "rapor"},))
        self.assertIs(present["current"]["current_output"]["available"], True)
        self.assertEqual(present["current"]["current_output"]["slot"], "last_doc")
        absent = self.payload(session_artifacts=())
        self.assertIs(absent["current"]["current_output"]["available"], False)
        self.assertIsNone(absent["current"]["current_output"]["slot"])
        self.assertIsNone(absent["current"]["current_output"]["label"])
        # Core yalnız tek bir çıktıyı bağlayabilir: iki kayıt belirsizdir, uydurma hedef değildir.
        two = self.payload(session_artifacts=({"slot": "last_doc", "label": "rapor"},
                                              {"slot": "older_doc", "label": "önceki"}))
        self.assertIs(two["current"]["current_output"]["available"], False)

    def test_an_unrecognised_slot_is_never_a_session_output(self):
        # Tanınmış last_doc dışı bir tek kayıt çıktı sayılmaz; hükmün kaynağı Core'un
        # bağlayabildiği attır, herhangi bir slotun varlığı değil.
        only_other = self.payload(session_artifacts=({"slot": "older_doc", "label": "önceki"},))
        self.assertIs(only_other["current"]["current_output"]["available"], False)
        self.assertIsNone(only_other["current"]["current_output"]["slot"])

    def test_absent_output_still_leaves_named_file_candidates_intact(self):
        # current_output.available false yalnız üretilmiş oturum çıktısını anlatır;
        # dosya adaylarının yokluğu değildir ve netleştirmeyi engellemez.
        named = current(references=(
            ContextReference(id="file_0", kind="file", source="scan", owner=OWNER,
                             provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf"}),
            ContextReference(id="file_1", kind="file", source="scan", owner=OWNER,
                             provenance={"path": "C:/Users/hamdi/Documents/ozet.docx"})))
        payload = self.payload(active=named, session_artifacts=())
        self.assertIs(payload["current"]["current_output"]["available"], False)
        self.assertEqual([row["slot"] for row in payload["file_candidates"]], ["file_0", "file_1"])
        self.assertIn("file_candidates", payload["current"]["current_output"]["meaning"])
        adopted = self.ask(answer(operation="clarify", confidence="HIGH",
                                  clarification={"required": True,
                                                 "question": "Hangi dosyayı saklayayım?",
                                                 "reason_code": "TARGET_MISSING"}),
                          active=current(needs_input=True, references=named.references),
                          session_artifacts=())
        self.assertIsNotNone(adopted)
        self.assertEqual(adopted.clarification_reason_code, "TARGET_MISSING")

    def test_present_output_describes_a_chosen_target_by_the_capability_not_a_question(self):
        # Çıktı varken hüküm "başka hedef gösterilirse sor" demek değildir: kullanıcının aday
        # listelerinden açıkça seçtiği hedef, o yeteneğin kendi sözleşmesiyle yargılanır.
        rows = ({"slot": "last_doc", "label": "rapor"},)
        payload = self.payload(session_artifacts=rows)
        self.assertIs(payload["current"]["current_output"]["available"], True)
        meaning = payload["current"]["current_output"]["meaning"]
        self.assertIn("reference_slots", meaning)
        self.assertIn("genuinely cannot be decided", meaning)
        self.assertIn("is judged by the selected capability's own contract", self.model_input)
        self.assertIn("rather than turning into a question", meaning)
        # Kaldırılan aşırı hüküm: rakip hedef gösterildi diye seçimi soruya zorlamak.
        self.assertNotIn("competing target", self.model_input)
        self.assertNotIn("must not be asked for again unless", self.model_input)

    def test_present_output_leaves_clarify_open_for_a_genuinely_undecided_target(self):
        # Hedef gerçekten bağlanamıyorsa soru yolu açıktır: çıktıların varlığı netleştirmeyi kapatmaz.
        rows = ({"slot": "last_doc", "label": "rapor"},)
        named = current(needs_input=True, references=(
            ContextReference(id="last_doc", kind="artifact", source="session_state", owner=OWNER),
            ContextReference(id="file_0", kind="file", source="scan", owner=OWNER,
                             provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf"}),
            ContextReference(id="file_1", kind="file", source="scan", owner=OWNER,
                             provenance={"path": "C:/Users/hamdi/Documents/ozet.docx"})))
        self.assertIsNotNone(self.ask(answer(operation="clarify", confidence="HIGH",
                                            clarification={"required": True,
                                                           "question": "Hangisini saklayayım?",
                                                           "reason_code": "TARGET_MISSING"}),
                                      active=named, session_artifacts=rows))

    def test_prompt_never_carries_document_content_or_fingerprint(self):
        payload = json.dumps(self.payload(
            session_artifacts=({"slot": "last_doc", "label": "rapor"},)), ensure_ascii=False)
        self.assertNotIn("document_digest", payload)
        self.assertNotIn("Rapor içeriği", payload)

    def test_prompt_advertises_capability_purposes_without_an_answer_table(self):
        schema = self.payload()["allowed"]["argument_schema"]
        for capability in ("documents.export", "notes.write", "files.mutate", "system.diagnose"):
            self.assertIn("purpose", schema[capability])
            self.assertIn("precondition", schema[capability])
        corpus = json.loads((Path(__file__).resolve().parents[1]
                             / "tests/data/brain_output_diagnose_holdout.json").read_text(encoding="utf-8"))
        serialized = json.dumps(self.payload(), ensure_ascii=False).casefold()
        for case in corpus["cases"]:
            self.assertNotIn(case["text"].casefold(), serialized)

    def test_model_can_conservatively_downgrade_false_capability_to_chat(self):
        result = self.ask(answer())
        self.assertIsNotNone(result)
        self.assertEqual(result.operation, "chat")
        self.assertIs(result.temporal_need, TemporalNeed.STATIC)

    def test_owner_mismatch_never_uses_another_profiles_provider_key(self):
        with patch("modules.llm.current_user", return_value="other"), \
                patch("modules.smart_router.run") as run:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        run.assert_not_called()

    def test_paid_provider_is_never_used_by_brain_understanding(self):
        with patch("modules.llm.provider", return_value="openai"), patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_local_ollama_is_not_silently_started_or_selected(self):
        with patch("modules.llm.provider", return_value="ollama"), patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_no_verified_free_provider_means_no_model_call(self):
        p1, p2, _ = self.eligible()
        with p1, p2, patch("modules.smart_router.selection", return_value={"candidates": ["ollama"]}), \
                patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_unknown_capability_is_rejected(self):
        self.assertIsNone(self.ask(direct("shell.execute", {"cmd": "dir"})))

    def test_capability_requires_independent_core_argument_validation(self):
        self.assertIsNone(self.ask(direct("files.read"), args={"execute": True}))

    def test_independent_model_chat_preserves_pending_owner_without_consume(self):
        # Protected relation is not a universal veto of NEW_REQUEST chat.
        # It must leave the old pending owner untouched and perform no action.
        self.assertIsNotNone(self.ask(answer(confidence="HIGH")))
        pending = current(conversation_relation=ConversationRelation.ANSWER_TO_PENDING)
        proposal = self.ask(answer(conversation_relation="NEW_REQUEST"),
                            active=pending, args=pending.arguments,
                            protected_relation=True)
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.operation, "chat")
        self.assertEqual(proposal.actions, ())
        self.assertEqual(pending.conversation_relation,
                         ConversationRelation.ANSWER_TO_PENDING)

    def test_malformed_json_fails_closed(self):
        self.assertIsNone(self.ask("not json"))

    def test_protocol_still_rejects_named_wrapper_and_wrong_version(self):
        with self.assertRaises(ValueError):
            model._decode(json.dumps({model.SCHEMA_VERSION:json.loads(answer())}))
        with self.assertRaises(ValueError):
            model._decode(answer(schema_version='invented-version'))

    def test_request_cancellation_propagates_instead_of_becoming_chat_fallback(self):
        from modules import requests_state
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run",
                               side_effect=requests_state.Cancelled("cancelled")):
            with self.assertRaises(requests_state.Cancelled):
                model.propose(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)

    def test_model_timeout_fails_closed_without_changing_existing_proposal(self):
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=TimeoutError("late")):
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)

    def test_model_cannot_create_a_clarification_without_a_typed_reason(self):
        raw = answer(operation="clarify", confidence="MEDIUM",
                     clarification={"required": True, "question": "Hangisini?", "reason_code": None})
        self.assertIsNone(self.ask(raw))

    def test_model_maps_file_operation_only_through_supplied_reference_slot(self):
        from modules.brain_contracts import ContextReference
        from modules.brain_core_map import core_plan
        file_ref = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        active = current(
            request_kind=RequestKind.CHAT,
            capability_hint=None,
            arguments={"original_text": "şu raporu bir incele"},
            references=(file_ref,),
        )
        raw = direct("files.read", {"operation": "analyze"}, ["file_0"])
        with patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            result = self.ask(raw, text="şu raporu bir incele", active=active)
            self.assertIsNotNone(result)
            self.assertEqual(result.actions[0].capability_id, "files.read")
            self.assertEqual(dict(result.actions[0].arguments), {
                "original_text": "şu raporu bir incele",
                "operation": "analyze",
                "path": "C:/Users/hamdi/Documents/rapor.pdf",
            })
            self.assertEqual(
                core_plan(result.actions[0].capability_id, result.actions[0].arguments),
                ("file_action", {"operation": "analyze",
                                 "path": "C:/Users/hamdi/Documents/rapor.pdf"}))

    def test_model_cannot_invent_file_slot_or_path(self):
        from modules.brain_contracts import ContextReference
        file_ref = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        active = current(request_kind=RequestKind.CHAT, capability_hint=None,
                         arguments={"original_text": "şu raporu incele"}, references=(file_ref,))
        self.assertIsNone(self.ask(direct("files.read", {"operation": "analyze"}, ["file_9"]),
                                   text="şu raporu incele", active=active))
        self.assertIsNone(self.ask(
            direct("files.read", {"operation": "analyze", "path": "C:/secret.txt"}, ["file_0"]),
            text="şu raporu incele", active=active))

    def test_model_can_move_an_established_capability_to_another_domain(self):
        """BRAIN-01: `current.capability_hint` öneri ön koşulu değildir; Core argümanı doğrular."""
        active = current(capability_hint="notes.read", arguments={"original_text": "notları göster"})
        result = self.ask(direct("pc.level.set", {"property": "volume", "level": 40}),
                          text="notları göster", active=active)
        self.assertIsNotNone(result)
        self.assertEqual(result.actions[0].capability_id, "pc.level.set")

    def test_model_cannot_change_deterministic_file_operation_or_target(self):
        from modules.brain_contracts import ContextReference
        first = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        second = ContextReference(
            id="file-ref-2", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/butce.pdf", "name": "butce.pdf"},
        )
        active = current(
            capability_hint="files.read",
            arguments={"original_text": "rapor dosyasını özetle", "operation": "summarize",
                       "path": "C:/Users/hamdi/Documents/rapor.pdf"},
            references=(first, second),
        )
        self.assertIsNone(self.ask(direct("files.read", {"operation": "analyze"}, ["file_0"]),
                                   active=active))
        self.assertIsNone(self.ask(direct("files.read", {"operation": "summarize"}, ["file_1"]),
                                   active=active))

    def test_model_understanding_token_limit_is_separate_from_time_budget(self):
        from modules import requests_state
        raw = answer(confidence="MEDIUM")

        def through_router(owner, prompt, callback, **kwargs):
            return callback("groq")
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=through_router), \
                patch.object(requests_state, "budget", wraps=requests_state.budget) as budget, \
                patch("modules.llm._send_provider", return_value=raw) as send:
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        self.assertIs(type(send.call_args.args[3]), int)
        self.assertEqual(send.call_args.args[3], 2048)
        budget.assert_called_once_with(model._MODEL_BUDGET_SECONDS)
        self.assertEqual(model._MODEL_BUDGET_SECONDS, 30.0)

    def test_a_provider_answer_late_to_the_local_budget_is_never_adopted(self):
        # Yerel bütçe dolmuşsa biçimi doğru bir yanıt bile benimsenmez ve işlem başlatmaz;
        # tanı da "sağlayıcı yanıt vermedi" değil kendi kök nedenini taşır.
        from modules import requests_state
        raw = direct("documents.export", confidence="HIGH")

        def late_run(owner, prompt, callback, **kwargs):
            time.sleep(.08)
            return raw

        p1, p2, p3 = self.eligible()
        with requests_state.budget(.02), p1, p2, p3, \
                patch("modules.smart_router.run", side_effect=late_run):
            result = model.propose(owner=OWNER, text="sonucu belge olarak sakla",
                                   current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        self.assertEqual(model.proposal_diagnostic()["reason_code"], "LOCAL_DEADLINE_EXCEEDED")

    def test_a_valid_answer_at_thirteen_seconds_is_adopted_by_the_shared_thirty_second_policy(self):
        # Ortak süre politikası 30 sn: 13 sn'de gelen geçerli yanıt eski 12 sn duvarına çarpıp
        # düşmez. Saat ileri sarılır, ağ beklenmez; ölçülen yalnız sürenin kendisidir.
        from modules import requests_state
        clock = {'t': 1000.0}
        stub = SimpleNamespace(monotonic=lambda: clock['t'])

        def slow_run(owner, prompt, callback, **kwargs):
            raw = callback('groq')
            clock['t'] += 13.0
            return raw

        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch.object(requests_state, 'time', stub), patch.object(model, 'time', stub), \
                patch("modules.smart_router.run", side_effect=slow_run), \
                patch("modules.llm._send_provider", return_value=answer(confidence="HIGH")):
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        self.assertEqual(model.proposal_diagnostic()['status'], 'accepted')

    def test_a_shorter_outer_budget_still_bounds_the_thirty_second_policy(self):
        # İç içe bütçe en sıkı olanı korur: 6 sn'lik dış bütçe varken 30 sn'lik politikaya
        # çıkılmaz; 8 sn'de dönen yanıt uygulanmaz ve kendi kök nedenini yazar.
        from modules import requests_state
        clock = {'t': 1000.0}
        stub = SimpleNamespace(monotonic=lambda: clock['t'])

        def slow_run(owner, prompt, callback, **kwargs):
            raw = callback('groq')
            clock['t'] += 8.0
            return raw

        p1, p2, p3 = self.eligible()
        with p1, p2, p3, \
                patch.object(requests_state, 'time', stub), patch.object(model, 'time', stub), \
                patch("modules.smart_router.run", side_effect=slow_run), \
                patch("modules.llm._send_provider", return_value=answer(confidence="HIGH")), \
                requests_state.budget(6):
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        self.assertEqual(model.proposal_diagnostic()["reason_code"], "LOCAL_DEADLINE_EXCEEDED")

    def test_brain_routes_decided_model_and_validates_within_attempt_budget(self):
        from modules import smart_router
        plan = smart_router.RoutePlan((smart_router.ModelSpec('gemini', 'verified-gemini'),
                                       smart_router.ModelSpec('groq', 'verified-groq')), (), 2)
        calls = []
        def transport(provider, prompt, system, max_tokens, history, *, model):
            calls.append((provider, model))
            return 'invalid-json' if len(calls) == 1 else answer(confidence='HIGH')
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch.object(smart_router, 'plan', return_value=plan), \
                patch('modules.llm._send_provider', side_effect=transport):
            result = model.propose(owner=OWNER, text='rapor dosyasını özetle',
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        self.assertEqual(calls, [('gemini', 'verified-gemini'), ('groq', 'verified-groq')])

    def test_bad_brain_response_does_not_disable_provider_for_next_turn(self):
        from modules import cloudflare_chat, smart_router, usage_meter
        import tempfile

        for bad in ('invalid-json', answer(operation='invented-operation')):
            with self.subTest(response=bad), tempfile.TemporaryDirectory() as temp:
                responses = iter((bad, answer(confidence='HIGH'), answer(confidence='HIGH')))
                calls = []
                def transport(provider, prompt, system, max_tokens, history, *, model):
                    calls.append(provider)
                    return next(responses)
                with patch.object(smart_router, '_STORE', Path(temp)), \
                        patch.object(smart_router, '_HEALTH', {}), patch.object(smart_router, '_LAST', {}), \
                        patch.object(smart_router, 'settings', return_value={'cloud_free_confirmed': True}), \
                        patch.object(smart_router, '_evidence_gate', return_value={'ok': True}), \
                        patch.object(usage_meter, 'observed_exhaustion', return_value=None), \
                        patch('modules.llm.provider', return_value='groq'), \
                        patch('modules.llm.privacy.mode', return_value='normal'), \
                        patch('modules.llm.user_groq_key', return_value='test'), \
                        patch.object(cloudflare_chat, 'configured', return_value=True), \
                        patch('modules.llm._send_provider', side_effect=transport):
                    first = model.propose(owner=OWNER, text='merhaba', current=current(), arguments=current().arguments)
                    trace = smart_router._LAST[OWNER]['attempts']
                    self.assertIsNotNone(first)
                    self.assertEqual(trace[0]['kind'], 'response_validation')
                    self.assertNotIn((OWNER, 'groq'), smart_router._HEALTH)
                    self.assertIn('groq', smart_router.selection(OWNER, 'text')['candidates'])
                    second = model.propose(owner=OWNER, text='merhaba', current=current(), arguments=current().arguments)
                self.assertIsNotNone(second)
                self.assertEqual(calls, ['groq', 'cloudflare', 'groq'])

    def test_production_groq_http_payload_accepts_brain_token_limit(self):
        raw = answer(confidence="MEDIUM")
        response = SimpleNamespace(status_code=200, headers={},
            json=lambda: {"choices": [{"message": {"content": raw}}]})

        def through_router(owner, prompt, callback, **kwargs):
            return callback("groq")

        def accept_request(url, **kwargs):
            body = kwargs['json']
            self.assertIs(type(body['max_tokens']), int)
            self.assertEqual(body['max_tokens'], 2048)
            prompt=json.loads(body['messages'][-1]['content'])
            schema=prompt['response_schema']
            self.assertEqual(set(schema['required']),model.ENVELOPE_KEYS)
            self.assertEqual(set(schema['properties']),model.ENVELOPE_KEYS)
            self.assertEqual(schema['properties']['schema_version'],{'const':model.SCHEMA_VERSION})
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(set(schema['properties']['actions']['items']['required']),model.ACTION_KEYS)
            self.assertIn('without a named wrapper',body['messages'][0]['content'])
            self.assertIn('For capabilities whose allowed.argument_schema lists argument_sources',body['messages'][0]['content'])
            return response

        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=through_router), \
                patch("modules.llm.user_groq_key", return_value="test-only"), \
                patch("modules.llm.groq_model", return_value="openai/gpt-oss-120b"), \
                patch("modules.smart_router.settings", return_value={}), \
                patch("modules.llm._fallback_states", {}), \
                patch("modules.llm._limited", return_value=None), \
                patch("modules.llm._timed", side_effect=lambda name, fn: fn()), \
                patch("modules.usage_meter.record"), patch("modules.usage_meter.observe_limits"), \
                patch("modules.llm.requests.post", side_effect=accept_request) as post:
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
