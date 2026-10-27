"""Deterministic Stage 0-4 architecture guard.

This module protects the accepted Jarvis execution architecture without using a
model or network call. It scans production Python modules and reports:

- BLOCKER: a mechanically provable architecture boundary violation.
- WARNING: an accepted/deferred architecture gap that must stay visible.

The guard intentionally does not try to prove product behavior. Runtime and
acceptance tests remain authoritative for behavior.
"""
from __future__ import annotations

import ast
from pathlib import Path

SCOPE = 'stage-0-4'
ROADMAP_SOURCES = (
    'docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md',
    'docs/architecture/JARVIS_STAGE_0_4_GUARD.md',
    'docs/agents/gorev-cekirdegi.md',
)

_CAS_ALLOWLIST = {
    'modules/goal_state_compat.py',
    'modules/worker_result_commit.py',
    'modules/runtime_event_commit.py',
}

_CREATE_ALLOWLIST = {
    'modules/goal_state_compat.py',
}

_COMPENSATE_ALLOWLIST = {
    'modules/goal_state_save_hook.py',
    # Operator-authorized authority-promotion rollback uses the same guarded
    # CAS compensation primitive through the GoalState compatibility adapter.
    'modules/goal_state_compat.py',
}

_DIRECT_EXECUTE_ALLOWLIST = {
    'modules/specialist_orchestrator.py',
    'modules/worker_result_hook.py',
}

_DECISION_CONTEXT_KEYS = {
    'domain_invariant',
    'domain_authority',
    'user_authority',
    'job_authority',
    'effect_state',
}


def _call_name(node: ast.Call, module_alias: dict | None = None, func_alias: dict | None = None) -> str | None:
    module_alias = module_alias or {}
    func_alias = func_alias or {}
    fn = node.func
    if isinstance(fn, ast.Name):
        # Direct call through a `from X import Y as Z` function alias, e.g.
        # `from modules.goal_tools import execute as run_tool; run_tool(...)`.
        return func_alias.get(fn.id)
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        # Attribute call through a module alias, e.g.
        # `import modules.goal_tools as tools; tools.execute(...)`.
        base = module_alias.get(fn.value.id, fn.value.id)
        return f'{base}.{fn.attr}'
    return None


def _collect_aliases(tree: ast.AST) -> tuple[dict, dict]:
    """Resolve static import aliases that could otherwise hide a guarded call.

    Only `import X as Y` / `from X import Y as Z` forms are resolved (plain,
    non-aliased imports already match the existing attribute-call checks).
    Dynamic constructs (getattr, eval, import hooks, etc.) are intentionally
    left unresolved — the guard stays limited to what mechanical AST analysis
    can prove.
    """
    module_alias: dict[str, str] = {}
    func_alias: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.asname:
                    continue
                # `import modules.goal_tools as tools` -> tools -> goal_tools
                module_alias[alias.asname] = alias.name.rsplit('.', 1)[-1]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                if not alias.asname:
                    continue
                if module == 'modules' or module.endswith('.modules'):
                    # `from modules import goal_state_store as gss` -> submodule alias.
                    module_alias[alias.asname] = alias.name
                else:
                    # `from modules.goal_tools import execute as run_tool`.
                    short_module = module.rsplit('.', 1)[-1] if module else ''
                    func_alias[alias.asname] = f'{short_module}.{alias.name}'

    return module_alias, func_alias


def _issue(rule: str, severity: str, path: str, line: int, message: str) -> dict:
    return {
        'rule': rule,
        'severity': severity,
        'path': path,
        'line': line,
        'message': message,
    }


def _python_files(root: Path):
    modules = root / 'modules'
    if not modules.is_dir():
        return []
    return sorted(path for path in modules.rglob('*.py') if '__pycache__' not in path.parts)


def _has_explicit_decision_context(node: ast.Call) -> bool:
    supplied = {kw.arg for kw in node.keywords if kw.arg}
    if _DECISION_CONTEXT_KEYS <= supplied:
        return True
    for kw in node.keywords:
        value = kw.value
        if kw.arg is None and isinstance(value, ast.Call):
            fn = value.func
            if isinstance(fn, ast.Name) and fn.id == '_decision_context':
                return True
    return False


def _has_fixed_attempt_one(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant) and key.value == 'attempts'
                and isinstance(value, ast.Constant) and value.value == 1
            ):
                return True
    return False


def scan(root=None) -> dict:
    root = Path(root or Path(__file__).resolve().parents[1])
    blockers = []
    warnings = []
    runtime_event_producer_calls = 0
    fixed_attempt_one = False

    for path in _python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            blockers.append(_issue(
                'ARCH-000', 'BLOCKER', relative, getattr(exc, 'lineno', 0) or 0,
                f'Mimari denetim dosyayı güvenilir biçimde okuyamadı: {exc}',
            ))
            continue

        if relative == 'modules/goal_executor.py' and _has_fixed_attempt_one(tree):
            fixed_attempt_one = True

        module_alias, func_alias = _collect_aliases(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node, module_alias, func_alias)

            if name == 'goal_state_store.compare_and_swap' and relative not in _CAS_ALLOWLIST:
                blockers.append(_issue(
                    'ARCH-001', 'BLOCKER', relative, node.lineno,
                    'Canonical GoalState CAS yalnız onaylı Reducer/compat commit adaptörlerinden çağrılabilir.',
                ))

            if name == 'goal_state_store.create' and relative not in _CREATE_ALLOWLIST:
                blockers.append(_issue(
                    'ARCH-004', 'BLOCKER', relative, node.lineno,
                    'Canonical GoalState ilk projection yazımı yalnız goal_state_compat adaptöründe yapılabilir.',
                ))

            if name == 'goal_state_store.compensate' and relative not in _COMPENSATE_ALLOWLIST:
                blockers.append(_issue(
                    'ARCH-005', 'BLOCKER', relative, node.lineno,
                    'Canonical GoalState compensate yalnız goal_state_save_hook legacy write rollback yolunda kullanılabilir.',
                ))

            if name == 'runtime_execution_gate.plan_task' and not _has_explicit_decision_context(node):
                blockers.append(_issue(
                    'ARCH-002', 'BLOCKER', relative, node.lineno,
                    'Durable runtime gate explicit DecisionContext olmadan çağrıldı.',
                ))

            if name == 'goal_tools.execute' and relative not in _DIRECT_EXECUTE_ALLOWLIST:
                blockers.append(_issue(
                    'ARCH-003', 'BLOCKER', relative, node.lineno,
                    'Yeni doğrudan goal_tools.execute yolu ikinci execution boundary oluşturamaz; durable Core hattını kullan.',
                ))

            if name == 'runtime_event_commit.commit':
                runtime_event_producer_calls += 1

    if runtime_event_producer_calls == 0:
        warnings.append(_issue(
            'ARCH-W001', 'WARNING', 'modules/runtime_event_commit.py', 0,
            'RuntimeEvent production subscription/producer entegrasyonu henüz yok; durable subscription roadmap borcudur.',
        ))

    if fixed_attempt_one:
        warnings.append(_issue(
            'ARCH-W002', 'WARNING', 'modules/goal_executor.py', 0,
            'Durable execution attempt kimliği hâlâ sabit 1; gerçek retry sayacı backlogda tutulmalı.',
        ))

    return {
        'scope': SCOPE,
        'roadmap_sources': list(ROADMAP_SOURCES),
        'blockers': sorted(blockers, key=lambda row: (row['rule'], row['path'], row['line'])),
        'warnings': sorted(warnings, key=lambda row: (row['rule'], row['path'], row['line'])),
    }


def format_report(report: dict) -> str:
    lines = [f"Architecture Guard ({report['scope']})"]
    for bucket in ('blockers', 'warnings'):
        for row in report[bucket]:
            where = row['path'] + (f":{row['line']}" if row['line'] else '')
            lines.append(f"{row['severity']} {row['rule']} {where} — {row['message']}")
    if not report['blockers'] and not report['warnings']:
        lines.append('OK — mimari ihlal veya açık uyarı bulunmadı.')
    elif not report['blockers']:
        lines.append('PASS — blocker yok; warning backlog görünür durumda.')
    return '\n'.join(lines)


def main() -> int:
    report = scan()
    print(format_report(report))
    return 1 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
