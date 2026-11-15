"""Regression fence: Brain proposes serializable decisions; Core owns effects."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from modules import brain_entry, core_brain_adapter
from modules.brain_contracts import ActiveContext
from modules.brain_gates import GateObservation


ROOT = Path(__file__).resolve().parents[1] / "modules"
EXECUTION_METHODS = {
    "handoff", "_batch_handoff", "run_step", "_active_request_id",
    "_photo_lifecycle", "_drop_stale_clarify", "_open_core_pending",
    "_correlated_job_id", "_install_job_guard", "_install_goal_save_guard",
    "_install_engine_control_guard", "_install_core_guards",
}


class BrainRouterBoundaryTests(unittest.TestCase):
    def test_brain_has_no_execution_entrypoints_or_core_state_writes(self):
        tree = ast.parse((ROOT / "brain_entry.py").read_text(encoding="utf-8"))
        functions = {node.name for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertFalse(functions & EXECUTION_METHODS)
        writes = []
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in {
                    "pending_action", "pending_event_title", "route", "_save",
                    "engine_control",
                }:
                    writes.append((target.attr, node.lineno))
        self.assertEqual(writes, [])

    def test_existing_core_adapter_is_the_only_effect_handoff(self):
        self.assertTrue(callable(core_brain_adapter.handoff))
        self.assertTrue(callable(core_brain_adapter.run_step))
        self.assertTrue(callable(core_brain_adapter._batch_handoff))
        for module in ("engine_loop", "engine_live_brain"):
            source = (ROOT / f"{module}.py").read_text(encoding="utf-8")
            self.assertIn("core_brain_adapter.handoff", source)
            self.assertNotIn("brain_entry.handoff", source)
        for module in ("engine_sequence", "main_planner"):
            source = (ROOT / f"{module}.py").read_text(encoding="utf-8")
            self.assertIn("from modules.core_brain_adapter import run_step", source)

    def test_router_proposal_is_json_serializable_without_authority(self):
        owner, rid = "fixture-owner", "rid-json-router"
        entry = brain_entry.EntryResult(
            owner=owner, request_id=rid, source="yazı", text="merhaba",
            active_context=ActiveContext(owner=owner, request_id=rid),
            state_gate=GateObservation(owner, rid, "state", False, "NO_PENDING"),
        )
        envelope = json.loads(json.dumps(entry.to_dict(), ensure_ascii=False))
        proposal = json.loads(json.dumps(brain_entry.core_proposal(entry), ensure_ascii=False))
        self.assertEqual((envelope["owner"], envelope["request_id"]), (owner, rid))
        self.assertEqual(proposal["request_kind"], None)
        forbidden = {"execute", "allowed", "approved", "completed", "effect_allowed"}
        self.assertFalse(forbidden.intersection(envelope))
        self.assertFalse(forbidden.intersection(proposal))


if __name__ == "__main__":
    unittest.main()
