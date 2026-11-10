"""BRAIN-05: Goal Resolver ve çoklu GoalState bağlamı.

Ölçülen şey zincirin kendisidir: kullanıcının kendi açık hedef kayıtlarının gözlemi
(`goal_executor.open_jobs` → `ActiveContext.goal_candidates`), model zarfının kapalı taşıyıcısı
ve `prepare → handoff → goal_resolver → goal_executor` geçişinin kalıcı kayda dokunması.

Model zarfı TAKLİTTİR. Bu dosya gerçek bir Türkçe cümlenin model tarafından doğru
sınıflandırıldığını iddia etmez; o ayrı bir canlı Brain kabulüdür. Burada iddia edilen,
yanlış/uydurma/belirsiz bir önerinin zincirin hiçbir halkasında başka bir hedefe efekt
üretmemesidir.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as fixtures
from modules import brain_context, brain_entry, goal_executor, goal_resolver, requests_state
from modules import brain_model_understanding as envelope
from modules.brain_contracts import (ActiveContext, Confidence, ContextReference, GoalOperation,
                                     RequestKind, UnderstandingResult)
from modules.brain_understanding import understand

OWNER = "hamdi"
RID = "brain-05-unit"
CARD = "a" * 16
OTHER = "b" * 16


def card(ident: str, *, title: str = "hedef", state: str = "running",
         priority: int | None = None, owner: str = OWNER) -> ContextReference:
    provenance = {"state": state, "title": title, "updated": time.time(), "created": time.time()}
    if priority is not None:
        provenance["priority"] = priority
    return ContextReference(id=ident, kind="goal", source="goal_state", owner=owner,
                            provenance=provenance)


def goal_entry(*cards, operation, targets=(), text="şu hedefi duraklat", goal_card=None,
               owner: str = OWNER) -> SimpleNamespace:
    """Resolver'ın okuduğu alanlarla sınırlı, deterministik bir hedef turu gözlemi."""
    active = ActiveContext(owner=owner, request_id=RID, goal_candidates=tuple(cards))
    understanding = UnderstandingResult(
        owner=owner, request_id=RID, request_kind=RequestKind.GOAL_CONTROL,
        goal_operation=operation, goal_target_ids=tuple(targets), goal_card=goal_card)
    return SimpleNamespace(owner=owner, text=text, active_context=active,
                           understanding=understanding)


def job_row(request: str, owner: str = OWNER, *, state: str = "running") -> dict:
    return {"id": uuid.uuid4().hex[:16], "owner": owner, "request": request,
            "created": time.time(), "state": state, "goals": [], "steps": [], "outputs": {}}


class GoalCandidateObservationTests(unittest.TestCase):
    """Madde 1: modele yalnız kullanıcıya ait aktif hedeflerin sınırlı kartları gider."""

    def context(self, rows, *, standing=None, is_open=lambda row: True):
        return brain_context.build_active_context(
            owner=OWNER, request_id=RID, session_store=None, profile=None,
            history_reader=lambda owner, limit=12: [],
            goal_reader=lambda owner: standing,
            goal_candidate_reader=rows if callable(rows) else (lambda owner: rows),
            goal_is_open=is_open)

    def test_every_open_goal_of_this_owner_becomes_a_card(self):
        first = dict(job_row("raporu toparla"), state="paused",
                     steps=[{"id": "s1", "state": "done"}, {"id": "s2", "state": "pending"}])
        second = job_row("mailleri tara")
        active = self.context([first, second])
        self.assertEqual([ref.id for ref in active.goal_candidates], [first["id"], second["id"]])
        provenance = active.goal_candidates[0].provenance
        self.assertEqual((provenance["title"], provenance["state"], provenance["progress"]),
                         ("raporu toparla", "paused", "1/2"))

    def test_closed_and_foreign_rows_are_never_offered(self):
        active = self.context([job_row("x")], is_open=lambda row: False)
        self.assertEqual(active.goal_candidates, ())
        with self.assertRaises(ValueError):
            self.context([job_row("x", "baskasi")])

    def test_the_card_set_is_bounded_by_the_envelope_limit(self):
        rows = [dict(job_row("h"), id=format(index, "016x")) for index in range(30)]
        active = self.context(rows)
        self.assertEqual(len(active.goal_candidates), brain_context._MAX_GOAL_CARDS)
        # İki ayrı üst sınır zamana karşı ayrışmasın: gözlem, zarfın sayısını aşamaz.
        self.assertLessEqual(len(active.goal_candidates), envelope.MAX_TARGET_GOALS)

    def test_the_standing_control_card_is_unchanged_by_the_multi_goal_observation(self):
        # Çıplak kontrollerin duran hedefi `latest.json` kartıdır. BRAIN-05 çoklu bağlamı aynı
        # alana yazamaz: geçitler iki hedefi birden görüp eski akışı belirsizliğe düşürür.
        standing = job_row("duran hedef", state="paused")
        other = job_row("yeni hedef")
        active = self.context([standing, other], standing=standing)
        self.assertEqual([ref.id for ref in active.active_goal_references], [standing["id"]])
        self.assertEqual([ref.id for ref in active.goal_candidates], [standing["id"], other["id"]])

    def test_a_reader_failure_is_a_bounded_observation_not_a_crash(self):
        def boom(owner):
            raise RuntimeError("store erişilemez")

        with patch.object(brain_context, "_record_failure") as recorded:
            active = self.context(boom)
        self.assertEqual(active.goal_candidates, ())
        recorded.assert_called_with("modules/brain_context.py:goal_candidate_read")
        statuses = {ref.provenance["reason_code"] for ref in active.recent_references
                    if ref.source == "goal_state" and ref.kind == "source_status"}
        self.assertEqual(statuses, {"GOAL_CANDIDATE_READ"})

    def test_a_bare_mapping_is_a_shape_violation(self):
        # Listelenen gözlem sözleşmesidir: tek kayıt dönen bir okuyucu sessizce yutulmaz.
        with patch.object(brain_context, "_record_failure") as recorded:
            active = self.context([job_row("x")][0])
        self.assertEqual(active.goal_candidates, ())
        recorded.assert_called_with("modules/brain_context.py:goal_candidate_shape")


class GoalCarrierContractTests(unittest.TestCase):
    """Madde 2: hedef işlemi kapalı bir taşıyıcıdır; biçimsiz kombinasyon üretilemez."""

    def result(self, **changes):
        row = {"owner": OWNER, "request_id": RID, "request_kind": RequestKind.GOAL_CONTROL}
        row.update(changes)
        return UnderstandingResult(**row)

    def test_an_operation_without_its_own_shape_is_rejected(self):
        # Kind'ın kendisi "bu bir hedef turu" der; işlem net değilse taşıyıcı açıktır ve
        # resolver efekt yerine soru üretir (`GOAL_OPERATION_MISSING`).
        self.assertIsNone(self.result().goal_operation)
        with self.assertRaises(ValueError):
            self.result(request_kind=RequestKind.CAPABILITY,
                        goal_operation=GoalOperation.PAUSE, goal_target_ids=(CARD,))
        with self.assertRaises(ValueError):
            self.result(goal_target_ids=(CARD,))  # işlem olmadan kimlik taşıyamaz
        with self.assertRaises(ValueError):
            self.result(goal_card={"kind": "goal", "title": "x"})  # işlem olmadan kart da

    def test_create_carries_a_card_and_no_identity(self):
        row = self.result(goal_operation=GoalOperation.CREATE,
                          goal_card={"kind": "goal", "title": "yeni hedef"})
        self.assertEqual(row.goal_target_ids, ())
        with self.assertRaises(ValueError):
            self.result(goal_operation=GoalOperation.CREATE)
        with self.assertRaises(ValueError):
            self.result(goal_operation=GoalOperation.CREATE,
                        goal_card={"kind": "goal", "title": "x"}, goal_target_ids=(CARD,))

    def test_every_other_operation_carries_identities_and_no_card(self):
        for operation in GoalOperation:
            if operation is GoalOperation.CREATE:
                continue
            self.result(goal_operation=operation, goal_target_ids=(CARD,))
            with self.assertRaises(ValueError, msg=operation.value):
                self.result(goal_operation=operation, goal_target_ids=(CARD,),
                            goal_card={"kind": "goal", "title": "x"})
            with self.assertRaises(ValueError, msg=operation.value):
                self.result(goal_operation=operation)

    def test_card_shape_and_identity_uniqueness_are_enforced(self):
        with self.assertRaises(ValueError):
            self.result(goal_operation=GoalOperation.CREATE,
                        goal_card={"kind": "goal", "title": "x", "allowed": True})
        with self.assertRaises(ValueError):
            self.result(goal_operation=GoalOperation.CREATE, goal_card={"kind": "goal", "title": "  "})
        with self.assertRaises(ValueError):
            self.result(goal_operation=GoalOperation.PAUSE, goal_target_ids=(CARD, CARD))


class GoalEnvelopeFenceTests(unittest.TestCase):
    """Madde 3: anlamı ve hedefi model önerir; uydurduğu kimlik tüm öneriyi düşürür.

    Zarf buradan taklit edilir ve taşıyıcı sağlayıcı hiç aranmaz: ölçülen, zarfın
    `_build` kapılarıdır."""

    def current(self, text: str):
        return understand(owner=OWNER, request_id=RID, text=text,
                          active_context=ActiveContext(owner=OWNER, request_id=RID),
                          candidates=(), references=())

    def envelope(self, *, operation, targets=(), goal=None, actions=(), confidence="HIGH",
                 relation="NEW_REQUEST"):
        clarify = operation == "clarify"
        return {
            "schema_version": envelope.SCHEMA_VERSION, "operation": operation,
            "conversation_relation": relation, "temporal_need": "STATIC",
            "target_goal_ids": list(targets), "goal": goal, "actions": list(actions),
            "clarification": {"required": clarify,
                              "question": "Hangisi?" if clarify else None,
                              "reason_code": "TARGET_MISSING" if clarify else None},
            "confidence": confidence,
        }

    def ask(self, row, *, cards=(), text="ikinci hedefi duraklat", current=None, **changes):
        base = self.current(text) if current is None else current
        with patch("modules.llm.current_user", return_value=OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", return_value=json.dumps(row)) as transport:
            proposal = envelope.propose(owner=OWNER, text=text, current=base,
                                        arguments=dict(base.arguments),
                                        goal_candidates=tuple(cards), **changes)
        # Bu testler ağı hiç kullanamaz; çağrı tek ve taklitlidir.
        transport.assert_called_once()
        return proposal

    def test_an_ungrounded_goal_identity_travels_to_the_resolver_instead_of_the_planner(self):
        # Sunulmamış kimlik öneriyi düşürürse cümle legacy kapıya kalır ve yeni bir GoalState
        # açılır. Hedef işleminde kimlik yürütücüye taşınır; orada efekt değil soru ürer.
        proposal = self.ask(self.envelope(operation="pause_goal", targets=(CARD,)))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.operation, "pause_goal")
        self.assertEqual(proposal.target_goal_ids, (CARD,))
        # Sunulmuş bir kimlik aynı zarfla yine geçerlidir.
        offered = self.ask(self.envelope(operation="pause_goal", targets=(CARD,)),
                           cards=(card(CARD),))
        self.assertEqual(offered.target_goal_ids, (CARD,))

    def test_a_goal_identity_on_a_non_goal_operation_is_rejected(self):
        # Hedef işlemi olmayan bir önerinin kimlik taşıması başlı başına uydurmadır.
        self.assertIsNone(self.ask(self.envelope(operation="chat", targets=(CARD,))))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "GOAL_TARGET_NOT_OFFERED")

    def test_a_goal_operation_never_carries_actions(self):
        action = {"action_id": "a1", "capability_id": "pc.level.set",
                  "arguments": {"property": "volume", "level": 10},
                  "reference_slots": [], "depends_on": []}
        self.assertIsNone(self.ask(self.envelope(operation="pause_goal", targets=(CARD,),
                                                 actions=[action]),
                                   cards=(card(CARD),)))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "ACTION_COUNT_MISMATCH")

    def test_create_is_adopted_only_with_a_card_and_without_identities(self):
        proposal = self.ask(self.envelope(operation="create_goal",
                                          goal={"kind": "goal", "title": "yeni hedef"}),
                            text="yarınki sunumu hazırla")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.goal["title"], "yeni hedef")
        self.assertIsNone(self.ask(self.envelope(operation="create_goal"),
                                   text="yarınki sunumu hazırla"))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "ACTION_COUNT_MISMATCH")

    def test_a_goal_card_shape_is_closed(self):
        # Kart yapısı kapalıdır: yetki alanı da dahil hiçbir fazla alan ilk biçim denetiminde
        # düşer. Yetki taramasının ikinci durağı yok — taşıyıcıda doğrudan kurulursa
        # `brain_contracts._check_goal_carrier` aynı alanı reddeder.
        self.assertIsNone(self.ask(self.envelope(operation="create_goal",
                                                 goal={"kind": "goal", "title": "x",
                                                       "effect_allowed": True}),
                                   text="yarınki sunumu hazırla"))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "GOAL_CARD_INVALID")

    def test_goal_operation_is_distinct_from_conversation_continuation(self):
        offered = (card(CARD), card(OTHER))
        text = "sunum taslağı hedefinden devam et"
        correct = self.envelope(operation="continue_goal", targets=(CARD,),
                                relation="NEW_REQUEST")
        self.assertEqual(self.ask(correct, cards=offered, text=text).target_goal_ids, (CARD,))
        # Only deterministic context may establish CONTINUE_ACTIVE. A model
        # cannot claim to own an active turn merely from the word "devam".
        forged = self.envelope(operation="continue_goal", targets=(CARD,),
                               relation="CONTINUE_ACTIVE")
        self.assertIsNone(self.ask(forged, cards=offered, text=text))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "RELATION_NOT_CURRENT")

    def test_revise_and_add_task_require_an_id_and_no_model_card(self):
        offered = (card(CARD), card(OTHER))
        for operation in ("revise_goal", "add_task"):
            with self.subTest(operation=operation):
                good = self.envelope(operation=operation, targets=(CARD,))
                self.assertEqual(self.ask(good, cards=offered).target_goal_ids, (CARD,))
                wrong = self.envelope(operation=operation, targets=(CARD,),
                                      goal={"kind":"goal","title":"model-written title"})
                self.assertIsNone(self.ask(wrong, cards=offered))
                detail = envelope.proposal_diagnostic()
                self.assertEqual(detail["reason_code"], "ACTION_COUNT_MISMATCH")
                self.assertTrue(detail["goal_card_present"])
                self.assertEqual(detail["target_goal_count"], 1)

    def test_the_model_may_raise_confidence_for_a_goal_operation(self):
        # Deterministik katmanın hedef anlamı hakkında kararı yoktur; LOW tahmini modeli
        # susturmaz. Dayanak yine sunulmuş kimliktir.
        low = dataclasses.replace(self.current("ikinci hedefi duraklat"), confidence=Confidence.LOW)
        proposal = self.ask(self.envelope(operation="pause_goal", targets=(CARD,)),
                            cards=(card(CARD),), current=low)
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.operation, "pause_goal")

    def test_a_pending_owner_is_not_a_goal_operation(self):
        from modules.brain_contracts import ConversationRelation, PendingOwner
        pending = dataclasses.replace(
            self.current("evet"), pending_owner=PendingOwner.APP_CLARIFY,
            conversation_relation=ConversationRelation.ANSWER_TO_PENDING, needs_input=False,
            ambiguities=())
        # İlişki yerinde kalmalı ki kapı PROTECTED_RELATION'dan değil, sahiplikten düşsün.
        row = self.envelope(operation="pause_goal", targets=(CARD,), relation="ANSWER_TO_PENDING")
        self.assertIsNone(self.ask(row, cards=(card(CARD),), text="evet", current=pending,
                                   protected_relation=True))
        self.assertEqual(envelope.proposal_diagnostic()["reason_code"], "PROTECTED_PENDING_OWNER")


class GoalResolverTests(unittest.TestCase):
    """Madde 4-5: belirsizde soru, doğrulanamayan kimlikte efekt yok, hedefler yalıtılır."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(goal_executor, "STORE", Path(self.temp.name) / "goals")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))

    def seed(self, request: str, *, state: str = "running", owner: str = OWNER,
             move_pointer: bool = False) -> str:
        row = job_row(request, owner, state=state)
        goal_executor._save(row, move_pointer=move_pointer)
        return row["id"]

    def resolve(self, operation, targets, *, cards=None, text="şu hedefi duraklat"):
        cards = cards if cards is not None else tuple(card(ident) for ident in targets)
        # Real offered cards carry a version and an execution snapshot.
        enriched = []
        for ref in cards:
            try:
                job = goal_executor.read_job(OWNER, ref.id)
            except ValueError:
                job = None
            if job:
                actual = brain_context._goal_card(OWNER, job)
                ref = dataclasses.replace(ref, provenance={**dict(ref.provenance), **dict(actual.provenance)})
            enriched.append(ref)
        cards = tuple(enriched)
        goal_card = ({"kind": "goal", "title": text}
                     if operation is GoalOperation.CREATE else None)
        return goal_resolver.resolve(self.runtime,
                                     goal_entry(*cards, operation=operation, targets=targets,
                                                text=text, goal_card=goal_card))

    def test_pause_preserves_pending_and_review_records(self):
        for state in ("question", "approval", "review"):
            with self.subTest(state=state):
                ident = self.seed("bekleyen hedef", state=state)
                root = goal_executor.STORE / OWNER
                paths = (root / (ident + ".goalstate.json"), root / (ident + ".execution.json"))
                before = [path.read_bytes() for path in paths]
                result = self.resolve(GoalOperation.PAUSE, (ident,))
                self.assertEqual(result.result_status, "failed")
                self.assertEqual(before, [path.read_bytes() for path in paths])
                self.assertEqual(goal_executor.read_job(OWNER, ident)["state"], state)

    def test_pause_addresses_the_selected_goal_only(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef", state="interrupted")
        before = goal_executor.read_job(OWNER, first)
        result = self.resolve(GoalOperation.PAUSE, (second,),
                              cards=(card(first, title="ilk hedef"),
                                     card(second, title="ikinci hedef")))
        self.assertEqual(result.result_status, "handled")
        self.assertEqual(result.job_id, second)
        self.assertEqual(goal_executor.read_job(OWNER, second)["state"], "paused")
        self.assertEqual(goal_executor.read_job(OWNER, first), before)

    def test_explicit_cancel_negation_blocks_model_proposed_effect(self):
        ident = self.seed("planlama hedefi")
        before = goal_executor.read_job(OWNER, ident)
        for words in (
            "Planlama hedefini iptal etme, sadece anlamını anlat.",
            "Planlama hedefini iptal etmeyin; ne anlama geliyor?",
            "Planlama hedefi iptal edilmesin, bunu açıkla.",
        ):
            with self.subTest(words=words):
                result = self.resolve(GoalOperation.CANCEL, (ident,), text=words)
                self.assertEqual(result.result_status, "needs_input")
                self.assertEqual(result.reason_code, "GOAL_CANCELLATION_NEGATED")
                self.assertEqual(goal_executor.read_job(OWNER, ident), before)

    def test_positive_cancellation_still_works(self):
        ident = self.seed("planlama hedefi")
        result = self.resolve(GoalOperation.CANCEL, (ident,),
                              text="Planlama hedefini iptal et.")
        self.assertEqual(result.result_status, "handled")
        self.assertEqual(goal_executor.read_job(OWNER, ident)["state"], "cancelled")

    def test_ambiguity_between_two_goals_asks_and_changes_nothing(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef")
        snapshot = {ident: goal_executor.read_job(OWNER, ident) for ident in (first, second)}
        cards = (card(first, title="ilk hedef"), card(second, title="ikinci hedef"))
        result = self.resolve(GoalOperation.CONTINUE, (first, second), cards=cards)
        self.assertEqual(result.reason_code, "GOAL_TARGET_AMBIGUOUS")
        self.assertEqual(result.result_status, "needs_input")
        self.assertIn("ilk hedef", result.message)
        self.assertIn("ikinci hedef", result.message)
        self.assertEqual({ident: goal_executor.read_job(OWNER, ident) for ident in snapshot},
                         snapshot)

    def test_a_goal_that_was_never_offered_is_refused(self):
        standing = self.seed("duran hedef")
        result = self.resolve(GoalOperation.CANCEL, ("f" * 16,), cards=(card(standing),))
        self.assertEqual(result.reason_code, "GOAL_TARGET_NOT_OFFERED")
        self.assertEqual(goal_executor.read_job(OWNER, standing)["state"], "running")
        self.assertIn("başka hedefe işlem uygulanmadı", result.message)

    def test_a_goal_that_closed_since_the_snapshot_is_refused(self):
        # Kart sunulduktan sonra kayıt kapanmış olabilir: açıklık koşeli işlem anında yeniden
        # denetlenir, yoksa `pause_job` hiçbir şey yapmadan "yaptım" derdi.
        ident = self.seed("kapanmış hedef", state="done")
        result = self.resolve(GoalOperation.PAUSE, (ident,))
        self.assertEqual(result.reason_code, "GOAL_TARGET_STALE")
        self.assertEqual(goal_executor.read_job(OWNER, ident)["state"], "done")

    def test_an_identity_that_is_not_a_goal_id_is_refused(self):
        result = self.resolve(GoalOperation.PAUSE, ("kısa-id",))
        self.assertEqual((result.result_status, result.reason_code),
                         ("failed", "GOAL_TARGET_NOT_ADDRESSABLE"))

    def test_a_foreign_goal_record_raises_instead_of_touching_it(self):
        ident = self.seed("kendi hedefim")
        # Owner'ı bozulmuş bir kayıt (ör. başka namespace'ten taşınmış dosya) sessizce
        # işlenmez: `execution_record.load` sahipliği okumada doğrular ve yürütücüye
        # ulaşmadan hata yükselir.
        record = goal_executor.STORE / OWNER / (ident + ".execution.json")
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload["job"]["owner"] = "baskasi"
        record.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.resolve(GoalOperation.PAUSE, (ident,))
        self.assertEqual(json.loads(record.read_text(encoding="utf-8"))["job"]["state"], "running")

    def test_a_foreign_owner_entry_is_refused_before_any_read(self):
        # Taşıyıcının owner'ı ile istek sahibi ayrışırsa hiçbir kayıt okunmadan durur.
        ident = self.seed("kendi hedefim")
        entry = goal_entry(card(ident, owner="baskasi"), operation=GoalOperation.PAUSE,
                           targets=(ident,), owner="baskasi")
        with self.assertRaises(ValueError):
            goal_resolver.resolve(self.runtime, entry)
        self.assertEqual(goal_executor.read_job(OWNER, ident)["state"], "running")

    def test_add_task_uses_the_users_own_words_as_the_new_result(self):
        ident = self.seed("rapor hedefi", state="interrupted")
        text = "rapora kaynakçayı da ekle"
        result = self.resolve(GoalOperation.ADD_TASK, (ident,), text=text)
        self.assertEqual(result.result_status, "handled")
        job = goal_executor.read_job(OWNER, ident)
        self.assertEqual([goal["text"] for goal in job["goals"]], ["rapor hedefi", text])
        self.assertEqual(job["request"], "rapor hedefi")
        self.assertIn(text, result.message)

    def test_prioritize_orders_cards_without_changing_lifecycle_state(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef", state="paused")
        self.resolve(GoalOperation.PRIORITIZE, (second,))
        titles = [row["request"] for row in goal_executor.open_jobs(OWNER, limit=8)]
        self.assertEqual(titles[0], "ikinci hedef")
        self.assertEqual(goal_executor.read_job(OWNER, second)["state"], "paused")

    def test_cancel_closes_the_selected_goal_and_keeps_the_other_open(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef")
        self.resolve(GoalOperation.CANCEL, (second,))
        self.assertEqual(goal_executor.read_job(OWNER, second)["state"], "cancelled")
        self.assertEqual(goal_executor.read_job(OWNER, first)["state"], "running")

    def test_bare_controls_do_not_move_the_standing_target_pointer(self):
        standing = self.seed("duran hedef", move_pointer=True)
        other = self.seed("diğer hedef")
        self.resolve(GoalOperation.PAUSE, (other,))
        self.assertEqual(goal_executor.latest(OWNER)["id"], standing)

    def test_continue_uses_runner_and_revise_commits_canonical_intent(self):
        ident = self.seed("sürdürülecek hedef", state="interrupted")
        with patch.object(goal_executor, "run", return_value="sürüyor") as runner:
            self.resolve(GoalOperation.CONTINUE, (ident,))
            self.resolve(GoalOperation.REVISE, (ident,), text="şunu da ekleyerek sürdür")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[1], "hedef devam")
        state = goal_executor.goal_job_control.canonical(goal_executor.STORE / OWNER, OWNER, ident)
        self.assertEqual(state['goal_intent']['revision'], "şunu da ekleyerek sürdür")
        self.assertGreater(state['version'], 0)

    def test_create_never_addresses_an_identity(self):
        calls = []

        def fake_run(runtime, request, **options):
            calls.append((request, options))
            return "açıldı"

        with patch.object(goal_executor, "run", fake_run):
            result = self.resolve(GoalOperation.CREATE, (), cards=(),
                                  text="yarınki sunumu hazırla")
        self.assertEqual(calls, [("yarınki sunumu hazırla", {})])
        self.assertEqual(result.reason_code, "GOAL_CREATE")

    def test_a_core_refusal_is_reported_not_reinterpreted(self):
        ident = self.seed("çalışan hedef")
        with patch.object(goal_executor, "_ACTIVE", {OWNER}), \
                patch.object(goal_executor, "_ACTIVE_JOBS", {OWNER: "başka-kimlik"}):
            result = self.resolve(GoalOperation.PAUSE, (ident,))
        self.assertEqual((result.result_status, result.reason_code),
                         ("failed", "GOAL_LIFECYCLE_REFUSED"))
        self.assertEqual(goal_executor.read_job(OWNER, ident)["state"], "running")

    def test_a_carrier_without_an_operation_asks_instead_of_guessing(self):
        active = ActiveContext(owner=OWNER, request_id=RID, goal_candidates=(card(CARD),))
        understanding = UnderstandingResult(owner=OWNER, request_id=RID,
                                            request_kind=RequestKind.GOAL_CONTROL)
        entry = SimpleNamespace(owner=OWNER, text="hedef", active_context=active,
                                understanding=understanding)
        result = goal_resolver.resolve(self.runtime, entry)
        self.assertEqual((result.result_status, result.reason_code),
                         ("needs_input", "GOAL_OPERATION_MISSING"))


class GoalProductionSeamTests(fixtures._CanonicalAuthorityHarness):
    """Gerçek üretim dikişi: prepare(model_understanding=True) → handoff → Core lifecycle.

    Zarf taklit; zincirin kendisi hedef okuması, taşıyıcı, precedences, resolver ve kalıcı
    kayıt açısından gerçektir."""

    def setUp(self):
        super().setUp()
        for target, value in (
            ("modules.llm.current_user", lambda: self.owner),
            ("modules.llm.provider", lambda: "groq"),
            ("modules.llm.privacy.mode", lambda: "normal"),
            ("modules.smart_router.selection", lambda *a, **k: {"candidates": ["groq"]}),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, request: str, *, state: str = "running") -> str:
        row = job_row(request, self.owner, state=state)
        goal_executor._save(row, move_pointer=False)
        return row["id"]

    def envelope(self, operation, *, targets=(), goal=None, actions=(), confidence="HIGH"):
        clarify = operation == "clarify"
        return json.dumps({
            "schema_version": envelope.SCHEMA_VERSION, "operation": operation,
            "conversation_relation": "NEW_REQUEST", "temporal_need": "STATIC",
            "target_goal_ids": list(targets), "goal": goal, "actions": list(actions),
            "clarification": {"required": clarify, "question": "Hangisi?" if clarify else None,
                              "reason_code": "TARGET_MISSING" if clarify else None},
            "confidence": confidence,
        })

    def turn(self, text, raw):
        """Paylaşılan harness turu; farkı provider'ın taklitli zarfı ve `handoff`'ın üçüncü
        değeri olan hedef kimliğidir. Legacy handler Mock'tur: çağrılmadığı kanıtlanır."""
        rid = "b5-" + uuid.uuid4().hex[:8]
        handler = Mock(return_value="HANDLER")
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            with patch("modules.smart_router.run", return_value=raw):
                entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text,
                                            source="yazı", model_understanding=True)
                out, feedback, job_id = brain_entry.handoff(self.ctx, entry, handler, text)
        return entry, out, handler, feedback, job_id

    def test_a_goal_operation_reaches_the_store_through_the_real_seam(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef", state="interrupted")
        entry, out, handle, feedback, job_id = self.turn(
            "ikinci hedefi duraklat", self.envelope("pause_goal", targets=(second,)))
        self.assertIs(entry.understanding.request_kind, RequestKind.GOAL_CONTROL)
        self.assertIs(entry.understanding.goal_operation, GoalOperation.PAUSE)
        self.assertEqual(entry.understanding.goal_target_ids, (second,))
        self.assertEqual(feedback.result_status, "handled")
        self.assertEqual(feedback.reason_code, "GOAL_PAUSE")
        self.assertEqual(job_id, second)
        # Kullanıcıya dönen söz resolver'ın Core doğrulamasından geçen gözlemidir.
        self.assertIn("duraklattı", out)
        self.assertEqual(goal_executor.read_job(self.owner, second)["state"], "paused")
        self.assertEqual(goal_executor.read_job(self.owner, first)["state"], "running")
        handle.assert_not_called()

    def test_the_legacy_planner_never_sees_a_goal_operation_sentence(self):
        # BRAIN-MIG-098: hedef işlemi front gate zincirine düşmez; `_planner_command` ve
        # `brain_precedence.claim` bu cümleyi ikinci kez yorumlayamaz.
        ident = self.seed("tek hedef", state="interrupted")
        for attribute in ("_planner_command", "_extra_commands", "_user_command",
                          "_macro_run", "_macro_manage"):
            setattr(self.ctx, attribute, Mock(return_value=None))
        self.turn("tek hedefi duraklat", self.envelope("pause_goal", targets=(ident,)))
        for attribute in ("_planner_command", "_extra_commands", "_user_command"):
            self.assertEqual(getattr(self.ctx, attribute).call_count, 0, attribute)
        self.assertEqual(goal_executor.read_job(self.owner, ident)["state"], "paused")

    def test_an_unoffered_identity_asks_and_invents_no_goal(self):
        first = self.seed("duran hedef")
        entry, out, handle, feedback, job_id = self.turn(
            "önceki hedefi duraklat", self.envelope("pause_goal", targets=("f" * 16,)))
        # Kimlik yürütücüye taşınır; Core onu owner'ın açık kayıtlarında bulamaz ve efekt
        # başlamaz. Cümle legacy kapıya düşmediği için yeni bir GoalState de açılmaz.
        self.assertIs(entry.understanding.request_kind, RequestKind.GOAL_CONTROL)
        self.assertIs(entry.understanding.goal_operation, GoalOperation.PAUSE)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertEqual(feedback.reason_code, "GOAL_TARGET_NOT_OFFERED")
        self.assertIsNone(job_id)
        self.assertIn("bulamadım", out)
        handle.assert_not_called()
        self.assertEqual(goal_executor.read_job(self.owner, first)["state"], "running")
        self.assertEqual(goal_executor.open_jobs(self.owner, limit=8), [
            goal_executor.read_job(self.owner, first)])

    def test_an_ambiguous_goal_operation_keeps_the_existing_clarify_path(self):
        first, second = self.seed("ilk hedef"), self.seed("ikinci hedef")
        entry, out, handle, feedback, _ = self.turn(
            "ikisini de duraklat", self.envelope("clarify", confidence="HIGH"))
        self.assertIs(entry.understanding.request_kind, RequestKind.CLARIFY)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertIn("Hangisi?", out)
        for ident in (first, second):
            self.assertEqual(goal_executor.read_job(self.owner, ident)["state"], "running")
        handle.assert_not_called()

    def test_a_goal_operation_never_reopens_the_legacy_task_door(self):
        # Bir hedef turu `task` üretirse ikinci bir GoalState açılır (hedef uydurma).
        entry = self.turn("ikinci hedefi duraklat",
                          self.envelope("pause_goal", targets=(CARD,)))[0]
        understanding = dataclasses.replace(entry.understanding, request_kind=RequestKind.GOAL_CONTROL,
                                            goal_operation=GoalOperation.PAUSE,
                                            goal_target_ids=(CARD,), needs_input=False,
                                            ambiguities=())
        projection = brain_entry._legacy_route_projection(dataclasses.replace(entry,
                                                                             understanding=understanding))
        self.assertEqual(projection["intent"], "clarify")
        self.assertEqual(projection["args"]["question"], brain_entry._GOAL_CONTROL_DOOR_QUESTION)

    def test_a_model_chat_turn_does_not_touch_the_goal_store(self):
        ident = self.seed("dokunulmayacak hedef")
        before = goal_executor.read_job(self.owner, ident)
        self.turn("bugün hava nasıl", self.envelope("chat", confidence="HIGH"))
        self.assertEqual(goal_executor.read_job(self.owner, ident), before)

    def test_a_direct_action_turn_does_not_become_a_goal_operation(self):
        ident = self.seed("dokunulmayacak hedef")
        entry, _out, _handle, _feedback, job_id = self.turn(
            "sesi yirmi yap", self.envelope("direct_action", confidence="HIGH", actions=[
                {"action_id": "a1", "capability_id": "pc.level.set",
                 "arguments": {"property": "volume", "level": 20, "original_text": "sesi yirmi yap"},
                 "reference_slots": [], "depends_on": []}]))
        self.assertIsNone(entry.understanding.goal_operation)
        self.assertEqual(entry.understanding.goal_target_ids, ())
        # Hedef olmayan tur GoalState'e bağlanamaz: kimlik uydurulmaz.
        self.assertIsNone(job_id)
        self.assertEqual(goal_executor.read_job(self.owner, ident)["state"], "running")


if __name__ == "__main__":
    unittest.main()
