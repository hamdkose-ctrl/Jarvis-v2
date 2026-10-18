"""engine_runtime drift testi (18 Ekim 2026): `runtime.<ad>` kullanımı ile `engine_runtime` bağlamı arasında sessiz kopma olmasın.

`EngineContext` adları elle tutulan iki listeyle (`_DEPENDENCIES`, `_HANDLERS`) ve `_initialize` içindeki atamalarla kurar.
Bir `engine_*.py` dosyası listeye eklenmemiş bir `runtime.X` okursa hata ancak o komut gerçekten çalışınca, derinde patlar.
Bu test hepsini KAYNAK METİN olarak (ast; hiçbir modül import edilmez, ağ/Windows/ekran gerekmez) okur ve kopmayı dosya adı +
satır + eksik adla bildirir.
"""
import ast
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / 'modules'
RUNTIME_FILE = MODULES / 'engine_runtime.py'

# Bilerek bağlamda tanımlanmayan ama `runtime.X` biçiminde OKUNAN adlar: ad -> neden. Bugün boş; eklenirse nedeni yazılmalı.
IZINLI: dict = {}


def _tree(path):
    return ast.parse(Path(path).read_text(encoding='utf-8'), filename=str(path))


def _literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{RUNTIME_FILE.name} içinde {name} bulunamadı (sabit bir liste/sözlük olmalı)')


def _module_names(tree):
    """Modül düzeyinde tanımlı adlar: def, class, atama, import."""
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out |= {t.id for t in targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).split('.')[0] for a in node.names}
        elif isinstance(node, (ast.Try, ast.If)):                 # try: import ... / if ...: tanımları da say
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    out.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    out |= {(a.asname or a.name).split('.')[0] for a in sub.names}
                elif isinstance(sub, ast.Assign):
                    out |= {t.id for t in sub.targets if isinstance(t, ast.Name)}
    return out


def runtime_uses(tree, filename='<kaynak>'):
    """(okunan adlar {ad: [(dosya, satır)]}, atanan adlar {ad}) -- yalnız `runtime.<ad>` erişimleri."""
    loads, stores = defaultdict(list), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'runtime':
            if isinstance(node.ctx, ast.Load):
                loads[node.attr].append((filename, node.lineno))
            else:
                stores.add(node.attr)
    return loads, stores


def context_names():
    """EngineContext'in kuruluşta kazandığı adlar: _DEPENDENCIES + _HANDLERS + sınıf üyeleri/self atamaları + _initialize atamaları."""
    tree = _tree(RUNTIME_FILE)
    names = set(_literal(tree, '_DEPENDENCIES'))
    for handler_names in _literal(tree, '_HANDLERS').values():
        names |= set(handler_names)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'EngineContext':
            for member in node.body:
                if isinstance(member, ast.FunctionDef):
                    names.add(member.name)
                elif isinstance(member, ast.Assign):
                    names |= {t.id for t in member.targets if isinstance(t, ast.Name)}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == 'self' \
                        and isinstance(sub.ctx, ast.Store):
                    names.add(sub.attr)
    names |= runtime_uses(tree)[1]                                  # _initialize içindeki `runtime.X = ...`
    return names


def drift(sources: dict, known: set, allowed=IZINLI) -> list:
    """sources: {dosya adı: ast ağacı}. Bağlamda çözülmeyen `runtime.X` okumaları: [(dosya, satır, ad)]."""
    out = []
    for name, tree in sources.items():
        for attr, places in runtime_uses(tree, name)[0].items():
            if attr not in known and attr not in allowed:
                out += [(f, line, attr) for f, line in places]
    return sorted(out)


class EngineRuntimeDriftTests(unittest.TestCase):
    def test_every_runtime_attribute_read_resolves(self):
        known = context_names()
        sources = {p.name: _tree(p) for p in sorted(MODULES.glob('engine_*.py'))}
        self.assertGreater(len(sources), 5)
        missing = drift(sources, known)
        self.assertEqual(missing, [], 'bağlamda çözülmeyen runtime.X: ' + '; '.join(f'{f}:{n} runtime.{a}' for f, n, a in missing)
                         + ' (engine_runtime._DEPENDENCIES/_HANDLERS ya da _initialize\'a ekle, ya da IZINLI\'ya nedeniyle yaz)')

    def test_dependencies_exist_in_engine_runtime_namespace(self):
        tree = _tree(RUNTIME_FILE)
        defined = _module_names(tree)
        missing = [n for n in _literal(tree, '_DEPENDENCIES') if n not in defined]
        self.assertEqual(missing, [], f'_DEPENDENCIES içinde olup engine_runtime.py\'de tanımsız (globals()[ad] KeyError verir): {missing}')

    def test_handlers_exist_in_their_modules(self):
        problems = []
        for module, names in _literal(_tree(RUNTIME_FILE), '_HANDLERS').items():
            path = MODULES / f'{module}.py'
            if not path.exists():
                problems.append(f'{module}.py yok')
                continue
            defined = _module_names(_tree(path))
            problems += [f'{module}.{n}' for n in names if n not in defined]
        self.assertEqual(problems, [], f'_HANDLERS içinde olup modülde tanımsız: {problems}')

    def test_no_name_is_set_twice_by_both_lists(self):
        tree = _tree(RUNTIME_FILE)
        handlers = [n for names in _literal(tree, '_HANDLERS').values() for n in names]
        both = sorted(set(handlers) & set(_literal(tree, '_DEPENDENCIES')))
        self.assertEqual(both, [], f'hem _DEPENDENCIES hem _HANDLERS içinde (biri ötekini sessizce ezer): {both}')
        dup = sorted({n for n in handlers if handlers.count(n) > 1})
        self.assertEqual(dup, [], f'_HANDLERS içinde birden çok modülde aynı ad: {dup}')

    def test_detector_flags_unknown_name_and_ignores_known(self):
        """Dedektörün kendisi: bilinmeyen runtime.X yakalanır, bilinenler, atamalar ve başka nesneler yakalanmaz."""
        src = ast.parse("def f(runtime, other):\n    runtime.bilinen()\n    runtime.yok_ad\n    other.baska\n    runtime.atanan = 1\n")
        self.assertEqual(drift({'x.py': src}, {'bilinen'}), [('x.py', 3, 'yok_ad')])
        self.assertEqual(drift({'x.py': src}, {'bilinen'}, allowed={'yok_ad': 'test'}), [])
        self.assertEqual(drift({'x.py': src}, {'bilinen', 'yok_ad'}), [])

    def test_known_names_are_not_trivially_empty(self):
        known = context_names()
        for name in ('handle', 'emit', 'profile', 'google_api', 'datetime', '_planner_command'):
            self.assertIn(name, known)


if __name__ == '__main__':
    unittest.main()
