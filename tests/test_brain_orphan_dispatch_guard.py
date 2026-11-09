"""Structural guard: every ``engine_intents.dispatch`` case must have a living canonical producer.

The legacy dispatcher is a pure consumer. Its only allowed intent vocabulary is what the
audited Brain call sites can actually hand to it: the ``brain_core_map.CORE_INTENTS``
targets plus the literal projections produced at those call sites. A case outside that
vocabulary is a zombie: no surface can reach it, so it can rot silently and can be
re-introduced as a fake second semantic authority.

The guard is deliberately structural (AST), not a list of banned strings: the case set, the
producer set and the call-site inventory are re-derived from source on every run, so adding
a producer-less case - or a new caller that bypasses the canonical gate - breaks the test
instead of passing an inspection.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"
INTENTS_FILE = MODULES / "engine_intents.py"

# The only production files allowed to call engine_intents.dispatch, and therefore the only
# places a dispatch intent can be produced. Anything else is a second semantic authority.
AUDITED_CALL_SITES = frozenset({"modules/brain_entry.py", "modules/engine_commands.py",
                                "modules/command_manager.py"})
DISPATCH_ARITY = 5  # dispatch(runtime, intent, a, command, cmd_lower)

# Physical-removal evidence for the cleanup PR: none of these may exist as a dispatch case or
# as a Core intent again. The orphan test below is what stops a NEW producer-less case.
REMOVED_LEGACY_INTENTS = frozenset({
    "open_app", "close_app", "open_url", "mail", "media", "note", "handoff", "work",
    "pc_control", "screenshot", "status", "volume", "brightness", "send_phone",
    "desktop_task", "code", "feedback",
})


def _production_sources() -> dict[str, str]:
    files = sorted(MODULES.glob("*.py")) + [ROOT / "main.py"] + sorted(ROOT.glob("web*.py"))
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8", errors="replace")
            for path in files if path.is_file()}


def _is_engine_intents_dispatch(node: ast.Call) -> bool:
    """True for a call to the legacy dispatcher, not for command_manager.dispatch."""
    if len(node.args) != DISPATCH_ARITY:
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "dispatch":
        return True
    return (isinstance(func, ast.Attribute) and func.attr == "dispatch"
            and isinstance(func.value, ast.Name) and func.value.id == "engine_intents")


def _imports_dispatch(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("engine_intents"):
            if any(alias.name == "dispatch" for alias in node.names):
                return True
    return False


def dispatch_case_names(source: str) -> set[str]:
    """Every string case label of the ``match intent:`` block inside engine_intents.dispatch."""
    names: set[str] = set()
    for function in [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "dispatch"]:
        for node in ast.walk(function):
            if not (isinstance(node, ast.Match) and isinstance(node.subject, ast.Name)
                    and node.subject.id == "intent"):
                continue
            for case in node.cases:
                pattern = case.pattern
                if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Constant):
                    if isinstance(pattern.value.value, str):
                        names.add(pattern.value.value)
    return names


def _dict_table_intents(source: str, constant_name: str) -> set[str]:
    """Intent names of a ``{hint: (intent, ...)}`` Core mapping table in brain_core_map."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == constant_name for t in targets):
            continue
        if not isinstance(value, ast.Dict):
            continue
        for item in value.values:
            if isinstance(item, ast.Tuple) and item.elts and isinstance(item.elts[0], ast.Constant):
                if isinstance(item.elts[0].value, str):
                    found.add(item.elts[0].value)
    return found


def core_intent_targets(source: str) -> set[str]:
    """The intent names brain_core_map.CORE_INTENTS can hand to dispatch."""
    return _dict_table_intents(source, "CORE_INTENTS")


def fast_intent_targets(source: str) -> set[str]:
    """Intent names of the Fast Gate table: the protocol sentence never re-selects them."""
    return _dict_table_intents(source, "FAST_INTENTS")


def literal_intents_in(source: str) -> set[str]:
    """Intent names a call-site file can produce: ``{"intent": "..."}`` payloads plus literal
    intent arguments passed straight to ``dispatch(...)``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "intent" \
                        and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
        if isinstance(node, ast.Call) and _is_engine_intents_dispatch(node):
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
    return found


def dispatch_call_sites(sources: dict[str, str]) -> dict[str, list[str]]:
    """Map every production file that calls the legacy dispatcher to its intent arguments."""
    inventory: dict[str, list[str]] = {}
    for name, source in sources.items():
        if not _imports_dispatch(source):
            continue
        expressions = [ast.get_source_segment(source, node.args[1]) or "?"
                       for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.Call) and _is_engine_intents_dispatch(node)]
        if expressions:
            inventory[name] = sorted(expressions)
    return inventory


def producer_intents(sources: dict[str, str]) -> set[str]:
    """The complete living vocabulary dispatch may receive, derived from audited call sites only."""
    core_map = sources["modules/brain_core_map.py"]
    producers = core_intent_targets(core_map) | fast_intent_targets(core_map)
    for file_name in sorted(AUDITED_CALL_SITES):
        producers |= literal_intents_in(sources[file_name])
    producers.add("chat")  # engine_commands fallback when the projection carries no intent
    return producers


def orphan_case_names(sources: dict[str, str]) -> set[str]:
    return dispatch_case_names(sources["modules/engine_intents.py"]) - producer_intents(sources)


class ProducerAndCaseExtractionTests(unittest.TestCase):
    """Non-vacuity: the guard must actually see both sides, or an empty set would pass silently."""

    def setUp(self):
        self.sources = _production_sources()

    def test_dispatch_case_set_is_extractable(self):
        cases = dispatch_case_names(self.sources["modules/engine_intents.py"])
        self.assertGreaterEqual(len(cases), 10)
        for known_live in {"file_action", "weather", "level_set", "notes_read", "notes_write",
                           "reminder", "translate", "app_action", "screen_analyze", "task", "clarify"}:
            self.assertIn(known_live, cases, known_live)

    def test_canonical_producer_set_is_extractable(self):
        producers = producer_intents(self.sources)
        for known_produced in {"level_set", "weather", "file_action", "reminder", "notes_read",
                               "notes_write", "task", "translate", "screen_analyze", "app_action",
                               "audio_action", "media_action", "screen_capture", "shutdown_request",
                               "shutdown_cancel", "fast_time", "fast_date", "fast_system_status",
                               "fast_speech_stop", "clarify", "chat"}:
            self.assertIn(known_produced, producers, known_produced)

    def test_producer_set_is_exactly_the_canonical_vocabulary(self):
        core_map = self.sources["modules/brain_core_map.py"]
        self.assertEqual(
            producer_intents(self.sources),
            core_intent_targets(core_map) | fast_intent_targets(core_map)
            | literal_intents_in(self.sources["modules/brain_entry.py"])
            | literal_intents_in(self.sources["modules/engine_commands.py"])
            | literal_intents_in(self.sources["modules/command_manager.py"])
            | {"chat"},
        )

    def test_case_set_is_source_driven_not_hardcoded(self):
        self.assertEqual(dispatch_case_names("def dispatch(runtime, intent, a, command, cmd_lower):\n    return ''\n"), set())


class DispatchCallSiteAuthorityTests(unittest.TestCase):
    """Only the audited canonical call sites may hand work to the legacy dispatcher."""

    def setUp(self):
        self.sources = _production_sources()

    def test_only_audited_producers_call_dispatch(self):
        self.assertEqual(set(dispatch_call_sites(self.sources)), set(AUDITED_CALL_SITES))

    def test_dispatch_intent_arguments_are_canonical_shapes(self):
        # "intent" = legacy projection, "plan[0]" = validated Core plan, "lane_plan[0]" = the bounded
        # State/Fast protocol answer mapped in brain_core_map; '"chat"' is the no-intent fallback.
        allowed = {"intent", "plan[0]", "lane_plan[0]", '"chat"'}
        for file_name, expressions in dispatch_call_sites(self.sources).items():
            for expression in expressions:
                self.assertIn(expression, allowed,
                                f"{file_name}: beklenmeyen dispatch niyeti {expression!r}")

    def test_engine_commands_takes_the_intent_from_the_canonical_route(self):
        source = self.sources["modules/engine_commands.py"]
        self.assertIn("route_command", source)
        self.assertNotIn("router.classify", source)


class OrphanDispatchCaseTests(unittest.TestCase):
    def setUp(self):
        self.sources = _production_sources()

    def test_orphan_set_is_empty(self):
        orphans = orphan_case_names(self.sources)
        self.assertEqual(
            orphans, set(),
            "Bu dispatch case'lerinin canonical producer'ı yok: " + ", ".join(sorted(orphans)),
        )

    def test_guard_has_no_exception_allowlist(self):
        # The empty orphan set is the unconditional contract: no tolerated-exception constant,
        # in this file or in any other test, may be subtracted from the measured orphan set.
        for path in sorted(ROOT.glob("tests/test_brain_*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, ast.AnnAssign) else [])
                self.assertFalse(any(isinstance(t, ast.Name) and t.id == "KNOWN_UNMIGRATED" for t in targets),
                                 f"{path.name}: istisna allowlist'i geri geldi")
        self.assertNotIn("KNOWN_UNMIGRATED", globals())

    def test_guard_breaks_for_a_future_producer_less_case(self):
        # Mutation proof: a case no canonical producer can emit must be reported as orphan.
        source = self.sources["modules/engine_intents.py"]
        anchor = '        case "weather":\n'
        self.assertIn(anchor, source)
        mutated = source.replace(
            anchor,
            '        case "brand_new_zombie_capability":\n            return "zombie"\n' + anchor,
            1,
        )
        mutated_cases = dispatch_case_names(mutated)
        self.assertIn("brand_new_zombie_capability", mutated_cases)
        self.assertEqual(mutated_cases - producer_intents(self.sources),
                         {"brand_new_zombie_capability"})

    def test_guard_breaks_for_a_new_dispatch_caller(self):
        sources = dict(self.sources)
        sources["modules/rogue_router.py"] = (
            "from modules.engine_intents import dispatch\n\n\n"
            "def run(runtime, command, args):\n"
            "    return dispatch(runtime, 'volume', args, command, command.casefold())\n"
        )
        self.assertIn("modules/rogue_router.py", dispatch_call_sites(sources))


class RemovedLegacyIntentTests(unittest.TestCase):
    """Physical removal evidence: the zombie vocabulary is gone from consumer and allowlist alike."""

    def test_removed_intents_are_not_dispatch_cases(self):
        cases = dispatch_case_names(INTENTS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(cases & set(REMOVED_LEGACY_INTENTS), set(),
                         "Hâlâ dispatch case olan yetim niyetler: "
                         + ", ".join(sorted(cases & set(REMOVED_LEGACY_INTENTS))))

    def test_removed_intents_are_not_core_targets(self):
        sources = _production_sources()
        self.assertEqual(core_intent_targets(sources["modules/brain_core_map.py"]) & set(REMOVED_LEGACY_INTENTS), set())

    def test_living_producers_are_still_dispatchable(self):
        sources = _production_sources()
        cases = dispatch_case_names(sources["modules/engine_intents.py"])
        self.assertTrue(producer_intents(sources) <= cases | {"chat"},
                        "Producer bir niyet üretiyor ama dispatch onu karşılamıyor")


if __name__ == "__main__":
    unittest.main()
