from __future__ import annotations

import importlib
import inspect
import time
import unittest

from modules.brain_contracts import ActiveContext, ContextReference
from modules.confirmation import decision


OWNER = "hamdi"
RID = "req-gates-1"
_RESERVED = {
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
}


def ref(
    ident: str,
    *,
    kind: str = "pending_state",
    source: str = "session_state",
    owner: str = OWNER,
    **provenance,
) -> ContextReference:
    return ContextReference(id=ident, kind=kind, source=source, owner=owner, provenance=provenance)


def ctx(*, owner: str = OWNER, request_id: str = RID, pending=(), goals=(), tasks=()) -> ActiveContext:
    return ActiveContext(
        owner=owner,
        request_id=request_id,
        pending_references=tuple(pending),
        active_goal_references=tuple(goals),
        active_task_references=tuple(tasks),
    )


class GateTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("modules.brain_gates")
        except ModuleNotFoundError:
            self.fail("modules.brain_gates foundation henüz yok")

    def state(self, text: str, *, active_context: ActiveContext | None = None, refs=()):
        return self.module().exact_state_gate(
            owner=OWNER,
            request_id=RID,
            text=text,
            active_context=active_context or ctx(),
            state_references=tuple(refs),
        )

    def fast(self, text: str, *, sleeping: bool = False, source: str = "yazı", active_context: ActiveContext | None = None):
        return self.module().deterministic_fast_gate(
            owner=OWNER,
            request_id=RID,
            text=text,
            active_context=active_context or ctx(),
            sleeping=sleeping,
            source=source,
        )

    def test_state_exists_is_not_consume_authority(self):
        pending = ref("pending_confirm", value="shutdown")
        result = self.state("yarın toplantım var", active_context=ctx(pending=(pending,)))
        self.assertFalse(result.matched)
        self.assertEqual(result.reason_code, "NO_BOUNDED_STATE_MATCH")

    def test_two_matching_bounded_states_fail_closed(self):
        confirm = ref("pending_confirm", value="shutdown")
        organize = ref("pending_organize", value={"plan": [], "label": "Belgeler"})
        result = self.state("evet", active_context=ctx(pending=(confirm, organize)))
        self.assertFalse(result.matched)
        self.assertEqual(result.reason_code, "MULTIPLE_BOUNDED_STATE_MATCHES")

    def test_confirmation_yes_no_and_explicit_veto_are_bounded(self):
        confirm = ref("pending_confirm", value="shutdown")
        for text, selection in (("evet", "yes"), ("hayır", "no"), ("iptal", "no")):
            with self.subTest(text=text):
                result = self.state(text, active_context=ctx(pending=(confirm,)))
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, "session.pending_confirm.confirm")
                self.assertEqual(result.selection, selection)

        msg = ref("pending_msg", value={"to": "Ebru", "text": "Merhaba", "stage": "confirm"})
        result = self.state("evet ama gönderme", active_context=ctx(pending=(msg,)))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "session.pending_msg.confirm")
        self.assertEqual(result.selection, "no")

    def test_confirmation_false_deny_sentence_is_not_match(self):
        text = "Gönderme kelimesini neden kullandın?"
        self.assertIsNone(decision(text))
        msg = ref("pending_msg", value={"to": "Ebru", "text": "Merhaba", "stage": "confirm"})
        result = self.state(text, active_context=ctx(pending=(msg,)))
        self.assertFalse(result.matched)

    def test_goal_resume_approval_and_cancel_are_exact_state_protocols(self):
        paused = ref("goal-1", kind="goal", source="goal_state", state="paused")
        approval = ref("goal-2", kind="goal", source="goal_state", state="approval")
        cases = (
            ("devam", paused, "goal.resume", "resume"),
            ("hedef devam", paused, "goal.resume", "resume"),
            ("evet", approval, "goal.approval", "yes"),
            ("hedef onayla", approval, "goal.approval", "yes"),
            ("iptal", paused, "goal.cancel", "cancel"),
        )
        for text, goal, protocol, selection in cases:
            with self.subTest(text=text):
                result = self.state(text, active_context=ctx(goals=(goal,)))
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, protocol)
                self.assertEqual(result.selection, selection)

    def test_closed_goal_is_read_only_status_not_resumable_state(self):
        done = ref("goal-1", kind="goal", source="goal_state", state="done")
        result = self.state("devam", active_context=ctx(goals=(done,)))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, 'goal.closed_resume')
        self.assertEqual(result.selection, done.id)

    def test_job_resume_ignores_unrelated_weather_pending(self):
        weather = ref("pending_weather_location", value=True)
        job = ref("job-1", kind="task_job", source="task_agents", state="incomplete")
        result = self.state("devam", active_context=ctx(pending=(weather,)), refs=(job,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "job.resume")
        self.assertEqual(result.selection, "resume")

    def test_job_closed_or_goal_owned_resume_does_not_steal(self):
        done_job = ref("job-1", kind="task_job", source="task_agents", state="done")
        self.assertFalse(self.state("devam", refs=(done_job,)).matched)
        stale_job = ref("job-stale", kind="task_job", source="task_agents", state="incomplete", stale=True)
        self.assertFalse(self.state("devam", refs=(stale_job,)).matched)
        goal = ref("goal-1", kind="goal", source="goal_state", state="paused")
        job = ref("job-2", kind="task_job", source="task_agents", state="incomplete")
        result = self.state("devam", active_context=ctx(goals=(goal,)), refs=(job,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "goal.resume")

    def test_pending_app_selection_is_exact_numeric_name_or_cancel(self):
        app = ref("pending_app", value={"choices": ["Chrome", "Word"], "at": 10.0})
        active = ctx(pending=(app,))
        for text, selection in (("2", "Word"), ("1 numara", "Chrome"), ("word", "Word"), ("iptal", "cancel")):
            with self.subTest(text=text):
                result = self.state(text, active_context=active)
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, "session.pending_app.select" if selection != "cancel" else "session.pending_app.cancel")
                self.assertEqual(result.selection, selection)
        self.assertFalse(self.state("Word hakkında konuşalım", active_context=active).matched)
        self.assertFalse(self.state("9", active_context=active).matched)
        self.assertFalse(self.state("2").matched)

    def test_pending_action_only_confirmation_stage_is_bounded(self):
        confirm = ref("pending_action", value={"action": "note_delete", "owner": OWNER, "expires": 9999999999})
        result = self.state("evet", active_context=ctx(pending=(confirm,)))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "session.pending_action.confirm")

        clarify = ref("pending_action", value={"stage": "clarify", "owner": OWNER, "expires": 9999999999})
        self.assertFalse(self.state("evet", active_context=ctx(pending=(clarify,))).matched)

    def test_final_confirmation_state_families_are_bounded(self):
        rows = (
            (ref("pending_organize", value={"plan": [], "label": "Belgeler"}), "session.pending_organize.confirm"),
            (ref("pending_event_title", value={"confirm": ["Toplantı", "2026-11-01T10:00", None]}), "session.pending_event_title.confirm"),
        )
        for pending, protocol in rows:
            with self.subTest(protocol=protocol):
                result = self.state("hayır", active_context=ctx(pending=(pending,)))
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, protocol)
                self.assertEqual(result.selection, "no")

    def test_open_ended_pending_states_are_left_to_understanding(self):
        rows = (
            ref("pending_weather_location", value=True),
            ref("pending_action", value={"stage": "clarify", "command": "aç", "question": "Hangi dosya?",
                                         "owner": OWNER, "expires": 9999999999}),
            ref("pending_msg", value={"to": "", "text": "", "stage": "to"}),
            ref("pending_msg", value={"to": "Ebru", "text": "", "stage": "text"}),
        )
        for pending in rows:
            with self.subTest(state=pending.id):
                self.assertFalse(self.state("İstanbul", active_context=ctx(pending=(pending,))).matched)
                self.assertFalse(self.state("başka konu", active_context=ctx(pending=(pending,))).matched)
                self.assertFalse(self.state("PDF değil Word", active_context=ctx(pending=(pending,))).matched)
                self.assertFalse(self.state("notlarımı göster", active_context=ctx(pending=(pending,))).matched)

    def test_level_visual_and_voice_choices_require_exact_option(self):
        level = ref("pending_level", value=70)
        self.assertEqual(self.state("ses", active_context=ctx(pending=(level,))).selection, "volume")
        self.assertEqual(self.state("parlaklık", active_context=ctx(pending=(level,))).selection, "brightness")
        self.assertFalse(self.state("ses hakkında konuşalım", active_context=ctx(pending=(level,))).matched)

        visual = ref("pending_visual", value={"stage": "source", "text": "x", "kind": "diagram"})
        self.assertEqual(self.state("dosya", active_context=ctx(pending=(visual,))).selection, "file")
        self.assertEqual(self.state("sohbet", active_context=ctx(pending=(visual,))).selection, "chat")
        self.assertFalse(self.state("dosya hakkında konuşalım", active_context=ctx(pending=(visual,))).matched)

        voice = ref("pending_voice", value="sor")
        self.assertEqual(self.state("Kerem", active_context=ctx(pending=(voice,))).selection, "kerem")
        self.assertFalse(self.state("Kerem hakkında konuşalım", active_context=ctx(pending=(voice,))).matched)

    def test_learning_approval_is_explicit_and_bounded(self):
        learning = ref("pending_facts", source="learning", value=["A", "B"])
        cases = (
            ("öğrendiklerini kaydet", "approve:all"),
            ("öğrendiklerini kaydetme", "reject:all"),
            ("öğrendiğin 2 bilgiyi kaydet", "approve:2"),
            ("öğrendiğin 1 bilgiyi unut", "reject:1"),
        )
        for text, selection in cases:
            with self.subTest(text=text):
                result = self.state(text, refs=(learning,))
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, "learning.pending_facts.select")
                self.assertEqual(result.selection, selection)
        self.assertFalse(self.state("öğrendiklerin ilginçmiş", refs=(learning,)).matched)

    def test_hoca_naked_answer_is_not_state_gate_but_explicit_control_is(self):
        hoca = ref("lesson.pending", source="profile.hoca", question="S?", step=0)
        self.assertFalse(self.state("mitokondri enerji üretir", refs=(hoca,)).matched)
        result = self.state("sonraki adım", refs=(hoca,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "hoca.lesson.control")
        self.assertEqual(result.selection, "next")

    def test_desktop_consent_requires_explicit_domain_consent_state(self):
        session_only = ref("pending_desktop", value=True)
        self.assertFalse(self.state("evet", active_context=ctx(pending=(session_only,))).matched)
        consent = ref("consent", source="desktop_agent", status="consent")
        result = self.state("izin veriyorum", refs=(consent,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "desktop.consent")
        self.assertEqual(result.selection, "yes")
        self.assertFalse(self.state("belki", refs=(consent,)).matched)

    def test_phone_photo_only_exact_cancel_is_state_gate(self):
        photo = ref("pending_photo", source="engine_commands", path="C:/photo.jpg", t=1.0)
        result = self.state("iptal", refs=(photo,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "phone_photo.cancel")
        self.assertFalse(self.state("buna bak", refs=(photo,)).matched)
        self.assertFalse(self.state("bu fotoğrafta ne var", refs=(photo,)).matched)

    def test_one_bounded_state_carried_by_both_lists_is_a_single_protocol_hit(self):
        """Production shape: ActiveContext and the observed refs can describe the same state."""
        photo = ref("pending_photo", source="engine_commands", path="C:/photo.jpg", t=1.0)
        cases = (
            ("iptal", (photo,), ctx(pending=(photo,)), "phone_photo.cancel", "BOUNDED_PHOTO_CANCEL"),
            ("devam", (ref("job-1", kind="task_job", source="task_agents", state="incomplete"),),
             ctx(tasks=(ref("job-1", kind="task_job", source="task_agents", state="incomplete"),)),
             "job.resume", "BOUNDED_JOB_RESUME"),
        )
        for text, refs, active, protocol, reason in cases:
            with self.subTest(text=text):
                result = self.state(text, active_context=active, refs=refs)
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, protocol)
                self.assertEqual(result.reason_code, reason)

    def test_foreground_photo_cancel_outranks_background_job(self):
        photo = ref("pending_photo", source="engine_commands", path="C:/photo.jpg", t=1.0)
        job = ref("job-1", kind="task_job", source="task_agents", state="incomplete")
        result = self.state("iptal", active_context=ctx(pending=(photo,)), refs=(photo, job))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "phone_photo.cancel")

    def test_active_clarify_cancel_outranks_long_lived_goal(self):
        clarify = ref("pending_action", value={
            "stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
            "owner": OWNER, "expires": time.time() + 90, "proposal": {"kind": "app.open"},
        })
        goal = ref("goal-1", kind="goal", source="goal_state", state="running")
        result = self.state("iptal", active_context=ctx(pending=(clarify,), goals=(goal,)))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "session.pending_action.clarify_cancel")
        self.assertEqual(result.selection, "cancel")

    def test_explicit_goal_control_outranks_foreground_clarify(self):
        clarify = ref("pending_action", value={
            "stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
            "owner": OWNER, "expires": time.time() + 90, "proposal": {"kind": "app.open"},
        })
        goal = ref("goal-1", kind="goal", source="goal_state", state="running")
        result = self.state("hedef iptal", active_context=ctx(pending=(clarify,), goals=(goal,)))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "goal.cancel")

    def test_foreground_desktop_consent_outranks_goal_approval(self):
        consent = ref("consent", source="desktop_agent", status="consent")
        goal = ref("goal-1", kind="goal", source="goal_state", state="approval")
        result = self.state("evet", active_context=ctx(goals=(goal,)), refs=(consent,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "desktop.consent")

    def test_open_ended_foreground_cancel_is_left_to_understanding(self):
        weather = ref("pending_weather_location", value=True)
        goal = ref("goal-1", kind="goal", source="goal_state", state="running")
        result = self.state("boşver", active_context=ctx(pending=(weather,), goals=(goal,)))
        self.assertFalse(result.matched)
        self.assertEqual(result.reason_code, "FOREGROUND_STATE_REQUIRES_UNDERSTANDING")

    def test_exact_foreground_cancel_outranks_goal(self):
        goal = ref("goal-1", kind="goal", source="goal_state", state="running")
        rows = (
            (ref("pending_msg", value={"to": "Ebru", "text": "", "stage": "text"}),
             "session.pending_msg.cancel"),
            (ref("pending_event_title", value="Toplantı"),
             "session.pending_event_title.cancel"),
        )
        for pending, protocol in rows:
            with self.subTest(protocol=protocol):
                result = self.state("iptal", active_context=ctx(pending=(pending,), goals=(goal,)))
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, protocol)
                self.assertEqual(result.selection, "cancel")

    def test_equal_rank_foreground_states_stay_fail_closed(self):
        confirm = ref("pending_confirm", value={"action": "close_app", "name": "Chrome"})
        message = ref("pending_msg", value={"to": "Ali", "text": "Selam", "stage": "confirm"})
        result = self.state("evet", active_context=ctx(pending=(confirm, message)))
        self.assertFalse(result.matched)
        self.assertEqual(result.reason_code, "MULTIPLE_BOUNDED_STATE_MATCHES")

    def test_deduping_one_state_from_both_carriers_stays_a_single_protocol_hit(self):
        photo = ref("pending_photo", source="engine_commands", path="C:/photo.jpg", t=1.0)
        result = self.state("iptal", active_context=ctx(pending=(photo,)), refs=(photo,))
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "phone_photo.cancel")

    def test_owner_and_request_fences_fail_closed(self):
        module = self.module()
        with self.assertRaises(ValueError):
            module.exact_state_gate(owner=OWNER, request_id=RID, text="evet", active_context=ctx(owner="other"))
        with self.assertRaises(ValueError):
            module.exact_state_gate(owner=OWNER, request_id=RID, text="evet", active_context=ctx(request_id="other"))
        foreign = ref("pending_confirm", owner="other", value="shutdown")
        with self.assertRaises(ValueError):
            self.state("evet", refs=(foreign,))
        wrong_request = ref("pending_confirm", value="shutdown", request_id="other")
        with self.assertRaises(ValueError):
            self.state("evet", refs=(wrong_request,))

    def test_gate_observation_has_no_authority_fields(self):
        pending = ref("pending_confirm", value="shutdown")
        result = self.state("evet", active_context=ctx(pending=(pending,)))
        data = result.to_dict()
        self.assertFalse(_RESERVED.intersection(data))
        self.assertEqual(data["selection"], "yes")
        self.assertNotIn("capability_hint", data)

    def test_fast_gate_exact_engine_controls(self):
        cases = (
            ("Jarvis'i kapat", False, "fast.engine.close", "close"),
            ("uyu", False, "fast.engine.sleep", "sleep"),
            ("uyan", True, "fast.engine.wake", "wake"),
            ("mikrofonu kapat", False, "fast.mic.toggle", "mic_off"),
            ("mikrofonu aç", False, "fast.mic.toggle", "mic_on"),
            ("konuşmayı durdur", False, "fast.speech.stop", "stop_speaking"),
            ("saat kaç", False, "fast.time.read", "time"),
            ("bugünün tarihi", False, "fast.date.read", "date"),
            ("sistem durumu", False, "fast.system.status", "status"),
        )
        for text, sleeping, protocol, selection in cases:
            with self.subTest(text=text):
                result = self.fast(text, sleeping=sleeping)
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, protocol)
                self.assertEqual(result.selection, selection)

    def test_fast_gate_self_close_rejects_suffix_broadening(self):
        for text in (
            "Jarvis'i kapatma",
            "Jarvis'i kapatmak",
            "Jarvis kapanma",
            "uygulamayı kapatma",
            "kendini kapatma",
            "Jarvis'i çıkma",
            "Jarvis'i sonlandırma",
        ):
            with self.subTest(text=text):
                result = self.fast(text)
                self.assertFalse(result.matched)
                self.assertNotEqual(result.protocol, "fast.engine.close")

    def test_fast_gate_is_context_bounded_and_not_second_router(self):
        self.assertFalse(self.fast("uyan", sleeping=False).matched)
        self.assertFalse(self.fast("Jarvis'i kapat", source="telefon").matched)
        for text in (
            "bilgisayarı kapat",
            "onu aç",
            "diğerini sil",
            "rapor.pdf aç",
            "hava nasıl?",
            "bugünkü dolar kuru ne?",
            "notlarımı göster",
            "Chrome'u aç",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.fast(text).matched)

    def test_fast_gate_source_has_no_model_router_or_permission_path(self):
        source = inspect.getsource(self.module()).casefold()
        for forbidden in (
            "smart_router", "modules.router", "modules.llm", "llm.ask", "openai", "gemini", "groq", "ollama",
            "permission_granted", "effect_allowed", "worker.run", "goal_executor.run",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
