"""BRAIN-02 — üretim yüzey paritesi: photo turu ve kota, birincil zarfın dışında kalamaz.

İki dikiş birlikte ölçülür: (1) AST ile üretim çağrı sitelerinin kendisi (yüzey gerçekten
bayrağı geçiyor mu), (2) gerçek `EngineContext` + canonical photo artifact üzerinden davranış
(zarf çalıştığında photo kararı ve yetkisi bozuluyor mu). Zarf taşıması `smart_router.run`
düzeyinde taklit edilir; anlamlandırma, çitler, `core_plan` ve photo executor gerçektir.
"""
from __future__ import annotations
from modules import core_brain_adapter
from provider_fixture import routed_response, routed_plan

import ast
import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fixtures  # noqa: F401  (import ordering fixtures)
from test_brain_photo_core_cutover import PHOTO, EVIL, _PhotoHarness

from modules import brain_entry, engine_live_brain, engine_loop, requests_state
from modules import brain_model_understanding as model
from modules import failure_policy
from modules.brain_contracts import (
    Confidence, ContextReference, ConversationRelation, RequestKind, TemporalNeed,
    UnderstandingResult,
)
from modules.brain_model_understanding import SCHEMA_VERSION
from modules.brain_understanding import PHOTO_CAPABILITY

REPO = Path(__file__).resolve().parents[1]

ENVELOPE_KEYS = ("schema_version", "operation", "conversation_relation", "temporal_need",
                 "target_goal_ids", "goal", "actions", "clarification", "confidence")


def photo_envelope(operation="chat", *, actions=(), confidence="LOW", **changes) -> str:
    """Photo turunun karar alanları: artifact devamı CONTINUE_ACTIVE, confidence HIGH doğar."""
    changes.setdefault("conversation_relation", "CONTINUE_ACTIVE")
    changes.setdefault("temporal_need", "UNSURE")
    return envelope(operation, actions=actions, confidence=confidence, **changes)


def envelope(operation="chat", *, actions=(), confidence="LOW", **changes) -> str:
    values = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "UNSURE",
        "target_goal_ids": [],
        "goal": None,
        "actions": list(actions),
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": confidence,
    }
    assert set(changes) <= set(ENVELOPE_KEYS)
    values.update(changes)
    return json.dumps(values)


def photo_action(arguments: dict, *, action_id="a1") -> dict:
    return {
        "action_id": action_id,
        "capability_id": PHOTO_CAPABILITY,
        "arguments": arguments,
        "reference_slots": [],
        "depends_on": [],
    }


def _prepare_calls(tree: ast.AST, *, bare_names_in: str | None = None) -> list[ast.Call]:
    """All canonical Brain entry sites: prepare or JSON-only prepare_json.

    The JSON boundary must not silently bypass semantic admission by merely
    renaming the original preparation call.
    """
    rows = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in {"prepare", "prepare_json"}:
            holder = func.value
            name = holder.id if isinstance(holder, ast.Name) else getattr(holder, "attr", "")
            if name == "brain_entry":
                rows.append(call)
        elif bare_names_in and isinstance(func, ast.Name) and func.id in {"prepare", "prepare_json"}:
            rows.append(call)
    return rows


def _enabled(call: ast.Call) -> bool:
    """Bayrak ya sabit True ya da photo turundaki tek meşru koşulu: kullanıcı sorusu var mı."""
    for keyword in call.keywords:
        if keyword.arg != "model_understanding":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant):
            return value.value is True
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "bool" and len(value.args) == 1
                and isinstance(value.args[0], ast.Name) and value.args[0].id == "question"):
            return True
    return False


class ProductionPrepareSiteTests(unittest.TestCase):
    """Yüzey boşluğu burada doğar: bir üretim çağrısı bayrağı pas geçerse zarf hiç çalışmaz."""

    def test_photo_turn_in_the_production_loop_enables_the_envelope(self):
        tree = ast.parse(inspect.getsource(engine_loop.main))
        calls = _prepare_calls(tree)
        self.assertEqual(len(calls), 2, "düz metin turu + photo turu bekleniyordu")
        self.assertTrue(all(_enabled(call) for call in calls),
                        "engine_loop.main içinde birincil zarfı çalıştırmayan bir prepare çağrısı var")

    def test_questionless_photo_placeholder_turn_spends_no_model_call(self):
        """Soru olmayan photo turunda yüzey zaten 'ne yapayım?' sorusunu yazıyor: uydurma
        'Fotoğraf' metnini modele göndermek kota harcamasıdır, semantik karar değildir."""
        tree = ast.parse(inspect.getsource(engine_loop.main))
        photo_call = next(call for call in _prepare_calls(tree)
                          if any(keyword.arg == "artifact" for keyword in call.keywords))
        value = next(keyword.value for keyword in photo_call.keywords
                     if keyword.arg == "model_understanding")
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(getattr(value.func, "id", ""), "bool")
        self.assertEqual(getattr(value.args[0], "id", ""), "question")

    def test_live_and_nested_step_sites_stay_wired(self):
        live = _prepare_calls(ast.parse(inspect.getsource(engine_live_brain._live_command)))
        step = _prepare_calls(ast.parse(inspect.getsource(core_brain_adapter.run_step)),
                              bare_names_in="core_brain_adapter.py")
        self.assertTrue(live and all(_enabled(call) for call in live))
        self.assertTrue(step and all(_enabled(call) for call in step))

    def test_only_the_documented_acceptance_harness_keeps_the_envelope_off(self):
        unwired = []
        sources = (sorted((REPO / "modules").rglob("*.py")) + sorted(REPO.glob("*.py"))
                   + [REPO / "scripts" / "brain_acceptance.py"])
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            bare = "brain_entry.py" if path.name == "brain_entry.py" else None
            for call in _prepare_calls(tree, bare_names_in=bare):
                if not _enabled(call):
                    unwired.append(str(path.relative_to(REPO)).replace("\\", "/"))
        self.assertEqual(unwired, ["scripts/brain_acceptance.py"],
                         "production dışında bilinçli kapalı tek yüzey kalmalı: çok turlu kabul harness'i")


class PhotoTurnEnvelopeTests(_PhotoHarness):
    """Photo turu zarfla birlikte de aynı canonical kararı ve aynı yetki sınırlarını taşır."""

    def free_route(self):
        return (
            patch("modules.llm.current_user", return_value=self.owner),
            patch("modules.llm.provider", return_value="groq"),
            patch("modules.llm.privacy.mode", return_value="normal"),
            patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
        )

    def prepare_photo(self, text: str, *, transport=None, exc: BaseException | None = None):
        rid = self._rid("model")
        self.assertTrue(requests_state.register(self.owner, rid))
        artifact = brain_entry.photo_artifact(owner=self.owner, request_id=rid, path=PHOTO)
        p1, p2, p3, p4 = self.free_route()
        run = ({"side_effect": exc} if exc is not None else {"return_value": transport})
        with p1, p2, p3, p4, routed_plan(count=1), patch("modules.llm.dispatch", **run), \
                requests_state.activate(self.owner, rid, complete=False):
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid, text=text,
                source="telefon", artifact=artifact, model_understanding=True,
            )
        return entry, rid

    def test_model_chat_does_not_launch_a_photo_effect(self):
        entry, _rid = self.prepare_photo("Bunu analiz et", transport=photo_envelope())
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.executor.assert_not_called()

    def test_model_selected_photo_action_binds_owner_artifact_and_executes_once(self):
        raw = photo_envelope(
            "direct_action", confidence="HIGH",
            actions=[photo_action({"operation": "analyze"})])
        entry, _rid = self.prepare_photo("Bunu analiz et", transport=raw)
        plan = brain_entry.core_plan(entry)
        self.assertEqual(plan[0], "photo_action")
        self.assertEqual(plan[1]["photo"], PHOTO)
        output, result, job_id = self.run_core(entry)
        self.assertEqual(output, "PHOTO OK")
        self.assertIsNone(job_id)
        self.executor.assert_called_once()
        self.assertEqual(self.executor.call_args.args[1:3], (PHOTO, "analyze"))
        self.assertEqual(result.result_status, "handled")

    def test_model_cannot_point_a_photo_operation_at_another_file(self):
        raw = photo_envelope(
            "direct_action", confidence="HIGH",
            actions=[photo_action({"operation": "analyze", "photo": EVIL})])
        entry, _rid = self.prepare_photo("Bunu analiz et", transport=raw)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.executor.assert_not_called()
        self.assertIn("MODEL_PROPOSAL_REJECTED", entry.understanding.reason_codes)

    def test_photo_action_without_operation_cannot_inherit_old_regex_guess(self):
        raw = photo_envelope(
            "direct_action", confidence="HIGH", actions=[photo_action({})])
        entry, _rid = self.prepare_photo("Bunu analiz et", transport=raw)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.executor.assert_not_called()
        self.assertIn("MODEL_PROPOSAL_REJECTED", entry.understanding.reason_codes)

    def test_quota_exhaustion_fails_closed_without_photo_execution(self):
        error = failure_policy.ProviderExhaustedError(
            "Uygun ücretsiz model yanıt vermedi. HTTP 429 kota. Ücretli modele geçilmedi.")
        entry, _rid = self.prepare_photo("Bunu analiz et", exc=error)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("MODEL_UNAVAILABLE", entry.understanding.reason_codes)
        self.executor.assert_not_called()

    def test_user_cancellation_in_the_photo_envelope_is_not_becoming_chat(self):
        with self.assertRaises(requests_state.Cancelled):
            self.prepare_photo("Bunu analiz et", exc=requests_state.Cancelled("iptal"))
        self.assertEqual(self.executor.call_count, 0)

    def test_no_free_route_means_the_photo_turn_never_calls_a_model(self):
        rid = self._rid("noroute")
        self.assertTrue(requests_state.register(self.owner, rid))
        artifact = brain_entry.photo_artifact(owner=self.owner, request_id=rid, path=PHOTO)
        p1, p2, _p3, p4 = self.free_route()
        with p1, p2, p4, patch("modules.smart_router.selection",
                               return_value={"candidates": ["ollama"]}), \
                patch("modules.llm.dispatch") as run, \
                requests_state.activate(self.owner, rid, complete=False):
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid, text="Bunu analiz et",
                source="telefon", artifact=artifact, model_understanding=True,
            )
        run.assert_not_called()
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("MODEL_UNAVAILABLE", entry.understanding.reason_codes)
        self.executor.assert_not_called()


class PhotoEnvelopeAuthorityTests(unittest.TestCase):
    """Zarf dikişi: photo argümanı modelin yazabileceği bir alan değildir, devam kararı bozulamaz."""

    OWNER = "hamdi"
    RID = "req-photo-authority"

    def photo_result(self):
        return UnderstandingResult(
            owner=self.OWNER,
            request_id=self.RID,
            request_kind=RequestKind.CAPABILITY,
            capability_hint=PHOTO_CAPABILITY,
            arguments={"operation": "analyze", "photo": PHOTO, "question": "",
                       "original_text": "Bunu analiz et"},
            references=(ContextReference(id="photo:" + PHOTO, kind="photo",
                                         source="engine_queue.photo", owner=self.OWNER,
                                         provenance={"path": PHOTO,
                                                     "origin_request_id": self.RID}),),
            conversation_relation=ConversationRelation.CONTINUE_ACTIVE,
            temporal_need=TemporalNeed.UNSURE,
            confidence=Confidence.HIGH,
            needs_input=False,
            ambiguities=(),
        )

    def ask(self, raw, *, text="Bunu analiz et", photo_path=PHOTO):
        p1, p2, p3, p4 = (
            patch("modules.llm.current_user", return_value=self.OWNER),
            patch("modules.llm.provider", return_value="groq"),
            patch("modules.llm.privacy.mode", return_value="normal"),
            patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
        )
        with p1, p2, p3, p4, routed_response(raw):
            return model.propose(owner=self.OWNER, text=text,
                                 current=self.photo_result(),
                                 arguments=self.photo_result().arguments,
                                 protected_relation=True,
                                 photo_path=photo_path)

    def test_a_model_supplied_photo_target_is_not_a_valid_proposal(self):
        self.assertIsNone(self.ask(photo_envelope(
            "direct_action", confidence="HIGH",
            actions=[photo_action({"operation": "analyze", "photo": EVIL})])))

    def test_model_action_binds_the_canonical_photo_without_a_model_path(self):
        proposal = self.ask(photo_envelope(
            "direct_action", confidence="HIGH",
            actions=[photo_action({"operation": "analyze"})]))
        self.assertIsNotNone(proposal)
        self.assertEqual(dict(proposal.actions[0].arguments)["photo"], PHOTO)
        self.assertEqual(dict(proposal.actions[0].arguments)["operation"], "analyze")

    def test_photo_note_text_is_grounded_in_user_utterance(self):
        utterance = "bunu not et: garanti belgesi"
        note = photo_action({"operation": "note", "note_text": "garanti belgesi"})
        raw = photo_envelope("direct_action", confidence="HIGH", actions=[note])
        self.assertIsNone(self.ask(raw, text=utterance),
                          "Ungrounded note text may never be saved.")
        note["argument_sources"] = {"note_text": "garanti belgesi"}
        chosen = self.ask(photo_envelope(
            "direct_action", confidence="HIGH", actions=[note]), text=utterance)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.actions[0].arguments["note_text"], "garanti belgesi")
        self.assertEqual(chosen.actions[0].arguments["photo"], PHOTO)

    def test_photo_action_without_bound_owner_artifact_cannot_run(self):
        raw = photo_envelope("direct_action", confidence="HIGH",
                             actions=[photo_action({"operation": "analyze"})])
        self.assertIsNone(self.ask(raw, photo_path=None))

    def test_chat_is_non_executing_and_does_not_reclassify_an_image(self):
        proposal = self.ask(photo_envelope("chat", confidence="HIGH"))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.operation, "chat")
        self.assertEqual(proposal.actions, ())


if __name__ == "__main__":
    unittest.main()
