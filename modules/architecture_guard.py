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
    'docs/architecture/JARVIS_UI_CORE_BOUNDARY.md',
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

# worker_result_hook.execute() is itself an execution adapter around
# goal_tools.execute(). Only the durable specialist orchestrator may enter that
# wrapper; otherwise a caller could bypass the DecisionContext/runtime gate and
# create a second execution boundary without calling goal_tools.execute itself.
_WORKER_RESULT_EXECUTE_ALLOWLIST = {
    'modules/specialist_orchestrator.py',
}

_DECISION_CONTEXT_KEYS = {
    'domain_invariant',
    'domain_authority',
    'user_authority',
    'job_authority',
    'effect_state',
}

# UI files may call presentation/query/configuration services, but must not gain
# a second business/execution authority by importing Core authority internals.
# This is deliberately an import/dependency boundary, not a keyword/name scan.
_UI_AUTHORITY_MODULES = frozenset({
    'modules.core_brain_adapter',
    'modules.canonical_goal_control',
    'modules.canonical_plan_revision',
    'modules.canonical_planning_queue',
    'modules.capability_decision',
    'modules.completion_policy',
    'modules.core_state_reducer',
    'modules.execution_record',
    'modules.goal_executor',
    'modules.goal_state_store',
    'modules.goal_tools',
    'modules.permission_classify',
    'modules.permission_gate',
    'modules.permission_policy',
    'modules.runtime_event_commit',
    'modules.runtime_execution_gate',
    'modules.task_agents',
    'modules.task_results',
    'modules.worker_result_commit',
})

# Paid-down UI/Core authority debt must not be reintroduced. The baseline is
# intentionally empty; any future UI dependency on the modules above is ARCH-006.
_UI_AUTHORITY_BASELINE = {}

# BRAIN-03 dilim 2 (§7): bu iki etki kullanıcının KENDİ cümlesinin anlamıdır; karar sahibi
# bounded model zarfıdır. Ham cümleden yetenek seçen bir yüzey (regex/kelime listesi) ya da
# modelden bu yeteneği yasaklayan bir küme ikinci bir semantic authority'dir.
#
# Kural yetenek ADİNİ değil SAHİBİNİ ve SÖZLEŞME TABLOSUNU denetler: ad yalnız aşağıdaki
# kapalı sözleşme tablolarının içinde taşınabilir (sabitin tanımı, Core'un niyet tablosu,
# zarfın dayanak tablosu, bu guardın ihlal kümesi). Bir fonksiyonun içinde, bir yasak
# kümesinde, kıyaslamada veya bu adların dışında bırakılmış bir tabloda görünmesi blocker'dır.
# Bu yüzden ihlali başka bir dosyaya taşımak, tanıyıcıyı/sabiti yeniden adlandırmak veya
# literal yerine kanonik sabiti import etmek denetimi kapatmaz: her yol ya sahibisiz bir
# literal ya da sözleşme tablosu dışında bir kanonik ad üretir.
#
# Denetim yetenek KİMLİĞİNE bakar, biçim/güvenlik denetimlerine (numara regex'i, kapalı enum,
# tip sınırı) dokunmaz: onlar bir yetenek adı taşımadığı için hiç ele alınmaz.
_SEMANTIC_MODEL_CAPABILITIES = {
    'message.send': 'MESSAGE_SEND_CAPABILITY',
    'contacts.manage': 'CONTACTS_MANAGE_CAPABILITY',
}
# Dosya → yetenek adının meşren görünebileceği modül-düzeyi sözleşme tabloları.
_SEMANTIC_CAPABILITY_CONTRACT_TABLES = {
    'modules/brain_understanding.py': ('MESSAGE_SEND_CAPABILITY', 'CONTACTS_MANAGE_CAPABILITY'),
    'modules/brain_core_map.py': ('CORE_INTENTS',),
    'modules/brain_model_understanding.py': ('_USER_OWNED_ARGUMENT_SLOTS', '_BASE_ARGUMENT_SHAPES'),
    'modules/architecture_guard.py': ('_SEMANTIC_MODEL_CAPABILITIES',),
}


def _assignment_target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Assign):
        return tuple(target.id for target in node.targets if isinstance(target, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return (node.target.id,)
    return ()


def _authorized_semantic_nodes(tree: ast.AST, relative: str) -> set[int]:
    """Yalnız kapalı sözleşme tablolarının düğümleri: başka hiçbir konum meşru değildir."""
    tables = _SEMANTIC_CAPABILITY_CONTRACT_TABLES.get(relative, ())
    if not tables:
        return set()
    literals = set(_SEMANTIC_MODEL_CAPABILITIES)
    constants = set(_SEMANTIC_MODEL_CAPABILITIES.values())
    nodes: set[int] = set()
    for node in tree.body:
        names = set(_assignment_target_names(node))
        if not names & set(tables):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Constant) and inner.value in literals) or (
                    isinstance(inner, ast.Name) and inner.id in constants):
                nodes.add(id(inner))
    return nodes


def _semantic_authority_issues(tree: ast.AST, relative: str) -> list[dict]:
    literals = set(_SEMANTIC_MODEL_CAPABILITIES)
    constants = set(_SEMANTIC_MODEL_CAPABILITIES.values())
    if not any((isinstance(node, ast.Constant) and node.value in literals)
               or (isinstance(node, ast.Name) and node.id in constants)
               for node in ast.walk(tree)):
        return []
    authorized = _authorized_semantic_nodes(tree, relative)
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in literals:
            if id(node) in authorized:
                continue
            issues.append(_issue(
                'ARCH-008', 'BLOCKER', relative, node.lineno,
                f'Yetenek adı {node.value!r} kapalı sözleşme tablosu dışında kullanıldı: ham '
                'cümleden yetenek seçilemez ve modelden yasaklanamaz; karar bounded model zarfınındır.',
            ))
        elif isinstance(node, ast.Name) and node.id in constants:
            if id(node) in authorized:
                continue
            issues.append(_issue(
                'ARCH-008', 'BLOCKER', relative, node.lineno,
                f'Kanonik yetenek sabiti {node.id} kapalı sözleşme tablosu dışında taşındı: '
                'yeniden adlandırma veya dosya taşıma semantik yetkiyi geri vermez.',
            ))
    return issues


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


def _module_dependencies(tree: ast.AST) -> set[str]:
    """Return statically declared `modules.*` dependency edges.

    The UI/Core boundary is about dependency direction: a UI adapter may call a
    canonical facade/service, but it must not import Core authority internals to
    make lifecycle/permission/execution decisions itself. Import aliases do not
    change the dependency edge and therefore do not bypass this check.
    """
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('modules.'):
                    dependencies.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module == 'modules':
                for alias in node.names:
                    if alias.name != '*':
                        dependencies.add(f'modules.{alias.name}')
            elif module.startswith('modules.'):
                dependencies.add(module)
    return dependencies


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


def _ui_python_files(root: Path):
    """Python UI/bridge shells whose dependency direction is guarded."""
    candidates = [root / 'web.py', root / 'gui.py', root / 'launcher.py']
    candidates.extend(sorted(root.glob('web_*.py')))
    unique = {path.resolve(): path for path in candidates if path.is_file()}
    return sorted(unique.values(), key=lambda path: path.relative_to(root).as_posix())


def _parse(path: Path, relative: str, blockers: list[dict]) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding='utf-8'), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        blockers.append(_issue(
            'ARCH-000', 'BLOCKER', relative, getattr(exc, 'lineno', 0) or 0,
            f'Mimari denetim dosyayı güvenilir biçimde okuyamadı: {exc}',
        ))
        return None


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
        tree = _parse(path, relative, blockers)
        if tree is None:
            continue

        if relative == 'modules/goal_executor.py' and _has_fixed_attempt_one(tree):
            fixed_attempt_one = True

        module_alias, func_alias = _collect_aliases(tree)

        blockers.extend(_semantic_authority_issues(tree, relative))

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

            if name == 'worker_result_hook.execute' and relative not in _WORKER_RESULT_EXECUTE_ALLOWLIST:
                blockers.append(_issue(
                    'ARCH-007', 'BLOCKER', relative, node.lineno,
                    'worker_result_hook.execute yalnız durable specialist orchestrator içinden çağrılabilir; DecisionContext/runtime gate bypass edilemez.',
                ))

            if name == 'runtime_event_commit.commit':
                runtime_event_producer_calls += 1

    for path in _ui_python_files(root):
        relative = path.relative_to(root).as_posix()
        tree = _parse(path, relative, blockers)
        if tree is None:
            continue
        baseline = _UI_AUTHORITY_BASELINE.get(relative, frozenset())
        for dependency in sorted(_module_dependencies(tree) & _UI_AUTHORITY_MODULES):
            if dependency in baseline:
                warnings.append(_issue(
                    'ARCH-W003', 'WARNING', relative, 0,
                    f'Mevcut UI/Core authority borcu baseline: {dependency}. Bu bağımlılık büyütülemez; canonical backend facade/service üzerinden taşınmalı.',
                ))
            else:
                blockers.append(_issue(
                    'ARCH-006', 'BLOCKER', relative, 0,
                    f'UI katmanı Core business-authority modülüne doğrudan bağımlı olamaz: {dependency}. Canonical backend facade/service çağırılmalı.',
                ))

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
        'warnings': sorted(warnings, key=lambda row: (row['rule'], row['path'], row['line'], row['message'])),
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

