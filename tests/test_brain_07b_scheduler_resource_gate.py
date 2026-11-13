"""BRAIN-07B read-only admission and exact pre-dispatch lease fencing.

All checks are isolated: no real worker, browser, keyboard, provider, or
permission grant. A ticket is not evidence of a completed task.
"""
from dataclasses import replace
import tempfile
import threading
from unittest.mock import Mock
from pathlib import Path
import unittest

from modules import (
    core_state_reducer, goal_plan_gate, goal_state, resource_leases,
    scheduler_resource_gate,
)

AdmissionError = scheduler_resource_gate.ReadOnlyAdmissionError


def node(name, cap="task.computer", deps=(), payload=None):
    return {
        "id": name, "depends_on": list(deps),
        "capability_id": cap,
        "input": payload if payload is not None else {
            "app": "notepad", "operation": "observe",
        },
        "expected_output": "verified metadata",
        "acceptance": "verified read-only worker receipt",
    }


def snapshot(owner="alice", job="job42", version=1, nodes=None):
    state = goal_state.new(
        owner=owner, job_id=job, goal="Observe open windows",
        authority="canonical",
    )
    chosen = nodes if nodes is not None else [node("observe")]
    return core_state_reducer.apply(state, {
        "op": "set_goal_plan", "plan": {
            "plan_version": version, "nodes": chosen,
        },
        "reason_code": "TEST_PLAN",
        "expected_version": state["version"],
    })


def candidate(state, ident="observe"):
    return goal_plan_gate.candidate(
        state, owner=state["owner"], job_id=state["job_id"], node_id=ident,
    )


class ReadOnlyLeaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.leases = resource_leases.LeaseTable(clock=lambda: self.now[0])

    def test_account_lease_renewal_cleanup_is_bounded_and_fail_closed(self):
        stop = Mock()
        thread = Mock()
        thread.is_alive.return_value = True
        leases = Mock()
        holder = [object()]
        held = scheduler_resource_gate._stop_renewal_without_voice_block(
            stop, thread, True, threading.RLock(), holder, leases,
        )
        self.assertFalse(held)
        stop.set.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=1.0)
        leases.release.assert_not_called()
        leases.validate.assert_not_called()

    def test_clean_heartbeat_exits_before_releasing_owned_ticket(self):
        stop = Mock()
        thread = Mock()
        thread.is_alive.return_value = False
        leases = Mock()
        leases.validate.return_value = True
        ticket = object()
        self.assertTrue(
            scheduler_resource_gate._stop_renewal_without_voice_block(
                stop, thread, True, threading.RLock(), [ticket], leases,
            ),
        )
        leases.release.assert_called_once_with(ticket)

    def test_existing_scheduler_table_gates_same_desktop_across_owners(self):
        first = snapshot(owner="alice")
        second = snapshot(owner="bob")
        old = scheduler_resource_gate.admit(
            self.leases, first, candidate(first), attempt=1,
        )
        self.assertEqual(old.keys, ("pc_desktop",))
        with self.assertRaises(resource_leases.LeaseConflict):
            scheduler_resource_gate.admit(
                self.leases, second, candidate(second), attempt=1,
            )
        self.assertEqual(
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, first, candidate(first), old, attempt=1,
            )["capability_id"], "task.computer",
        )
        self.leases.release(old)
        new = scheduler_resource_gate.admit(
            self.leases, second, candidate(second), attempt=1,
        )
        self.assertTrue(self.leases.validate(new))
        self.assertEqual(new.owner, "bob")

    def test_same_file_symlink_or_alias_yields_one_canonical_resource(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "document.txt"
            file.write_text("safe")
            canonical = snapshot(nodes=[
                node("read", "task.file", payload={
                    "path": str(file), "operation": "extract_obligations",
                }),
            ])
            selected = candidate(canonical, "read")
            lease = scheduler_resource_gate.admit(
                self.leases, canonical, selected, attempt=1,
            )
            self.assertEqual(len(lease.keys), 1)
            self.assertTrue(lease.keys[0].startswith("file:"))
            self.assertEqual(len(lease.keys[0].split(":", 1)[1]), 64)
            if hasattr(file, "symlink_to"):
                alias = Path(temp) / "alias.txt"
                try:
                    alias.symlink_to(file)
                except (OSError, NotImplementedError):
                    alias = file
                alternate = snapshot(owner="bob", nodes=[
                    node("read", "task.file", payload={
                        "path": str(alias), "operation": "extract_obligations",
                    }),
                ])
                with self.assertRaises(resource_leases.LeaseConflict):
                    scheduler_resource_gate.admit(
                        self.leases, alternate, candidate(alternate, "read"),
                        attempt=1,
                    )

    def test_different_files_do_not_block_one_another(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / "a.txt", Path(temp) / "b.txt"]
            for path in paths:
                path.write_text("different")
            states = [
                snapshot(owner=f"person{i}", nodes=[
                    node("read", "task.file", payload={
                        "path": str(path), "operation": "extract_obligations",
                    }),
                ])
                for i, path in enumerate(paths)
            ]
            tickets = [
                scheduler_resource_gate.admit(
                    self.leases, state, candidate(state, "read"), attempt=1,
                )
                for state in states
            ]
            self.assertNotEqual(tickets[0].keys, tickets[1].keys)
            self.assertTrue(all(self.leases.validate(t) for t in tickets))

    def test_email_account_key_serializes_distinct_owners_without_verified_subject(self):
        params = {"service": "gmail", "operation": "list_unread", "limit": 3}
        owner = snapshot(nodes=[
            node("read_mail", "task.account", payload=params),
        ])
        other = snapshot(owner="bob", nodes=[
            node("read_mail", "task.account", payload=params),
        ])
        ticket = scheduler_resource_gate.admit(
            self.leases, owner, candidate(owner, "read_mail"), attempt=1,
        )
        self.assertTrue(ticket.keys[0].startswith("gmail_account:"))
        self.assertEqual(ticket.keys, ("gmail_account:shared",))
        # The same physical external account can be connected to two Jarvis
        # profile names. An owner-derived hash must never be its sole fence.
        with self.assertRaises(resource_leases.LeaseConflict):
            scheduler_resource_gate.admit(
                self.leases, other, candidate(other, "read_mail"), attempt=1,
            )
        self.leases.release(ticket)
        other_ticket = scheduler_resource_gate.admit(
            self.leases, other, candidate(other, "read_mail"), attempt=1,
        )
        self.assertEqual(other_ticket.keys, ticket.keys)
        self.leases.release(other_ticket)

    def test_distinct_provider_services_have_independent_conservative_keys(self):
        gmail = scheduler_resource_gate._typed_resource_keys(
            {'capability_id': 'task.account',
             'input': {'service': 'gmail', 'operation': 'list_unread'}}, 'alice',
        )
        telegram = scheduler_resource_gate._typed_resource_keys(
            {'capability_id': 'task.account',
             'input': {'service': 'telegram', 'operation': 'list_updates'}}, 'bob',
        )
        self.assertNotEqual(gmail, telegram)
        self.assertEqual(gmail, ('gmail_account:shared',))
        self.assertEqual(telegram, ('provider:telegram-shared',))

    def test_stale_goalstate_version_or_revision_cannot_use_old_ticket(self):
        old_state = snapshot()
        selection = candidate(old_state)
        ticket = scheduler_resource_gate.admit(
            self.leases, old_state, selection, attempt=1,
        )
        revised = core_state_reducer.apply(old_state, {
            "op": "set_goal_plan", "plan": {
                "plan_version": 2, "nodes": [node("observe")],
            },
            "reason_code": "TEST_REVISED",
            "expected_version": old_state["version"],
        })
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, revised, selection, ticket, attempt=1,
            )
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            scheduler_resource_gate.admit(
                self.leases, revised, selection, attempt=1,
            )
        self.assertTrue(self.leases.validate(ticket))
        # Existing table ticket still needs lifecycle release: not permission.
        self.leases.release(ticket)

    def test_expiry_heartbeat_owner_and_attempt_are_fenced(self):
        state = snapshot()
        selected = candidate(state)
        lease = scheduler_resource_gate.admit(
            self.leases, state, selected, attempt=1, ttl=5,
        )
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, state, selected, lease, attempt=2,
            )
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, state, selected, replace(lease, owner="mallory"), attempt=1,
            )
        renewed = self.leases.heartbeat(lease, ttl=10)
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, state, selected, lease, attempt=1,
            )
        scheduler_resource_gate.validate_before_dispatch(
            self.leases, state, selected, renewed, attempt=1,
        )
        self.now[0] = 111
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.validate_before_dispatch(
                self.leases, state, selected, renewed, attempt=1,
            )

    def test_dependent_node_never_uses_lease_without_predecessor_proof(self):
        state = snapshot(nodes=[node("start"), node("later", deps=("start",))])
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.admit(
                self.leases, state, candidate(state, "later"), attempt=1,
            )
        self.assertFalse(self.leases.occupied("pc_desktop"))

    def test_reject_effectful_writer_browser_publish_and_unknown(self):
        for cap in ("task.writer", "task.browser", "task.publish", "task.unknown"):
            with self.subTest(cap=cap):
                state = snapshot(nodes=[node("bad", cap)])
                with self.assertRaises(AdmissionError):
                    scheduler_resource_gate.admit(
                        self.leases, state, candidate(state, "bad"), attempt=1,
                    )
        self.assertFalse(self.leases.occupied("pc_desktop"))

    def test_goal_observe_requires_its_existing_typed_input_schema(self):
        invalid = snapshot(nodes=[
            node("look", "goal.observe", payload={"resource_key": "pc_desktop"}),
        ])
        with self.assertRaises(ValueError):
            scheduler_resource_gate.admit(
                self.leases, invalid, candidate(invalid, "look"), attempt=1,
            )
        valid = snapshot(nodes=[
            node("look", "goal.observe", payload={
                "kind": "screen", "question": "What is on screen?",
            }),
        ])
        ticket = scheduler_resource_gate.admit(
            self.leases, valid, candidate(valid, "look"), attempt=1,
        )
        self.assertEqual(ticket.keys, ("pc_desktop",))
        self.assertTrue(self.leases.validate(ticket))

    def test_reject_model_supplied_resource_key_without_valid_capability_mapping(self):
        state = snapshot(nodes=[
            node("bad", "goal.document", payload={"resource_key": "pc_desktop"}),
        ])
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.admit(
                self.leases, state, candidate(state, "bad"), attempt=1,
            )

    def test_malformed_attempt_and_foreign_table_fail_closed(self):
        state = snapshot()
        chosen = candidate(state)
        for attempt in (True, 0, -1, 1000001, "1"):
            with self.subTest(attempt=attempt), self.assertRaises(AdmissionError):
                scheduler_resource_gate.admit(
                    self.leases, state, chosen, attempt=attempt,
                )
        with self.assertRaises(AdmissionError):
            scheduler_resource_gate.admit(
                None, state, chosen, attempt=1,
            )
        self.assertFalse(self.leases.occupied("pc_desktop"))


if __name__ == "__main__":
    unittest.main()
