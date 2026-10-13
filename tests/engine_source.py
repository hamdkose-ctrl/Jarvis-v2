"""Adapt existing isolated branch tests to the real explicit-context modules.

No legacy engine copy is kept: nodes are read from the current production files.
Integration tests exercise the actual context binding and facade separately.
"""
import ast
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source():
    return '\n'.join(path.read_text(encoding='utf-8').replace('runtime.', '').replace('voice_session.', '').replace('self.', '')
                     for path in sorted((ROOT / 'modules').glob('engine_*.py')))


class Isolated(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id in ('runtime', 'self', 'voice_session'):
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.args.args and node.args.args[0].arg in ('runtime', 'self'):
            node.args.args.pop(0)
        # Preserve the global-write contract in a deliberately isolated namespace.
        writes = set()
        def collect(item):
            if isinstance(item, (ast.FunctionDef, ast.Lambda, ast.ClassDef)): return
            if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) and item.value.id == 'runtime' and isinstance(item.ctx, ast.Store):
                writes.add(item.attr)
            for child in ast.iter_child_nodes(item): collect(child)
        for item in node.body: collect(item)
        node.body = [item for item in node.body if not (isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'runtime' for t in item.targets))]
        node = self.generic_visit(node)
        if writes: node.body.insert(0, ast.Global(names=sorted(writes)))
        return node


def tree():
    functions, voice_methods, startup = [], [], []
    for path in sorted((ROOT / 'modules').glob('engine_*.py')):
        parsed = ast.parse(path.read_text(encoding='utf-8'))
        for node in parsed.body:
            if isinstance(node, ast.FunctionDef) and node.name != '_initialize':
                functions.append(Isolated().visit(copy.deepcopy(node)))
            elif isinstance(node, ast.ClassDef) and node.name == 'VoiceSession':
                for method in node.body:
                    if not isinstance(method, ast.FunctionDef): continue
                    converted = Isolated().visit(copy.deepcopy(method))
                    if method.name == '__init__':
                        startup = [item for item in converted.body if not (isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'runtime' for t in item.targets))]
                    else: voice_methods.append(converted)
    # Expand the production dispatcher only for isolated branch tests.
    # Integration tests still call the actual cross-module function.
    handler = next(node for node in functions if node.name == 'handle')
    dispatcher = next(node for node in functions if node.name == 'dispatch')
    handler.body = handler.body[:-2] + copy.deepcopy(dispatcher.body)
    main = next(node for node in functions if node.name == 'main')
    main.body = [node for node in main.body if not (isinstance(node, ast.ImportFrom) and node.module == 'modules.engine_voice')
                 and not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'voice_session' for t in node.targets))]
    background = [copy.deepcopy(n) for n in functions if n.name in ('_handoff_notice', '_learning_notice', '_google_health')]
    main.body = startup + voice_methods + background + main.body
    return ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
