"""Sabit api/tryApi adları ile Bridge metotları arasındaki kaynak sözleşmesi.

Uygulama modülleri import edilmez, metot/dekoratör gövdeleri çalıştırılmaz.
Regex yalnız doğrudan, tek/çift tırnaklı ilk argümanı alır; api(name), koşullu
adlar, birleştirmeler, kaçışlı dizgeler ve şablon dizgeleri denetlenmez.
Tam JS ayrıştırıcısı değildir; argüman sayısı, sonuç biçimi ve gerçek UI ölçülmez.
"""
import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
IZINLI = {}  # Bilerek bulunmayan ad -> gerekçe. Gerçek eksik burada gizlenmez.
CALL = re.compile(r'''(?<![\w$.])(?:api|tryApi)\s*\(\s*(['"])([^'"\\\r\n]*)\1\s*(?=[,)])''')
PUBLIC_NAME = re.compile(r'[a-z][a-z0-9_]*')


def ui_sources(root=ROOT):
    return {p.relative_to(root).as_posix(): p.read_text(encoding='utf-8')
            for p in sorted((root / 'webui').rglob('*.js'))}


def api_calls(sources):
    return [(path, text.count('\n', 0, m.start()) + 1, m.group(2))
            for path, text in sorted(sources.items()) for m in CALL.finditer(text)]


def _method(*args, **kwargs):
    """Yalnız AST sınıf iskeletinin çağrılabilirlik işareti; çağrılmaz."""


def bridge_methods(sources):
    """Gerçek importları çöz, yan etkisiz sınıf iskeletleriyle Python MRO uygula.

    def/async def metotları işaretlenir; property ve veri alanları çağrılabilir
    sayılmaz. Gövde/dekoratör yürütme, dinamik setattr veya metot alias analizi yok.
    Bilinmeyen taban sessizce atlanmaz; test açık hata verir.
    """
    classes, imports, built = {}, {}, {}
    for path, source in sources.items():
        module = Path(path).stem
        imports[module] = {}
        for node in ast.parse(source, filename=path).body:
            if isinstance(node, ast.ClassDef):
                classes[module, node.name] = node
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imports[module][alias.asname or alias.name] = (node.module, alias.name)

    def build(key):
        if key in built:
            return built[key]
        module, name = key
        node = classes[key]
        bases = []
        for base in node.bases:
            if not isinstance(base, ast.Name):
                raise AssertionError(f'{module}.{name}: desteklenmeyen taban {ast.unparse(base)}')
            if base.id == 'object':
                bases.append(object)
            else:
                target = (module, base.id) if (module, base.id) in classes else imports[module].get(base.id)
                if target not in classes:
                    raise AssertionError(f'{module}.{name}: çözülemeyen taban {base.id}')
                bases.append(build(target))
        members = {}
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                property_like = any((isinstance(d, ast.Name) and d.id == 'property')
                                    or (isinstance(d, ast.Attribute) and d.attr in ('getter', 'setter', 'deleter'))
                                    for d in member.decorator_list)
                members[member.name] = None if property_like else _method
            elif isinstance(member, (ast.Assign, ast.AnnAssign)):
                targets = member.targets if isinstance(member, ast.Assign) else [member.target]
                if isinstance(member, ast.AnnAssign) and member.value is None:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        members[target.id] = None
        # Sadece kendi iskelet tabanlarımız kullanılır; uygulama sınıfı kurulmaz.
        built[key] = type(name, tuple(bases), members)
        return built[key]

    bridge = build(('web', 'Bridge'))
    names = {name for base in bridge.__mro__ for name in vars(base)}
    return {name for name in names if callable(getattr(bridge, name))}


def drift(calls, methods, allowed=IZINLI):
    problems = []
    for path, line, name in calls:
        if not PUBLIC_NAME.fullmatch(name):
            problems.append((path, line, name, 'sunucunun ad sınırına aykırı/özel'))
        elif name not in methods and name not in allowed:
            problems.append((path, line, name, 'Bridge üzerinde çağrılabilir metot yok'))
    return problems


class WebBridgeDriftTests(unittest.TestCase):
    def test_all_static_ui_calls_resolve_to_public_callable_bridge_methods(self):
        sources = ui_sources()
        calls = api_calls(sources)
        self.assertTrue(any(path == 'webui/nx.js' for path, _, _ in calls), 'nx.js taraması boş kalamaz')
        python = {p.name: p.read_text(encoding='utf-8')
                  for p in [ROOT / 'web.py', *sorted(ROOT.glob('web_*.py'))]}
        methods = bridge_methods(python)
        problems = drift(calls, methods)
        self.assertEqual(problems, [], 'Arayüz/köprü kayması: ' + '; '.join(
            f'{path}:{line} {name}: {reason}' for path, line, name, reason in problems))
        stale = set(IZINLI) - ({name for _, _, name in calls} - methods)
        self.assertEqual(stale, set(), f'Artık gerekmeyen IZINLI girdileri: {stale}')
        self.assertTrue(all(isinstance(reason, str) and reason.strip() for reason in IZINLI.values()))
        print(f'WEB_BRIDGE_DRIFT: {len(calls)} sabit çağrı, {len({n for _, _, n in calls})} ad, '
              f'{len({p for p, _, _ in calls})} JS dosyası; eksik yok.', file=sys.stderr)

    def test_extractor_covers_both_helpers_and_files_but_skips_dynamic_names(self):
        calls = api_calls({'webui/nx.js': "api('snapshot');\n tryApi(\"send\", 1); api(name); api('pre'+name);",
                           'webui/other.js': "tryApi('_private'); api(`snapshot`); notapi('ignored');"})
        self.assertEqual(calls, [('webui/nx.js', 1, 'snapshot'), ('webui/nx.js', 2, 'send'),
                                 ('webui/other.js', 1, '_private')])

    def test_detector_reports_typo_with_file_and_line(self):
        calls = api_calls({'webui/nx.js': "\napi('snapshott')"})
        self.assertEqual(drift(calls, {'snapshot'}), [
            ('webui/nx.js', 2, 'snapshott', 'Bridge üzerinde çağrılabilir metot yok')])

    def test_private_and_invalid_names_are_rejected_even_if_callable_or_allowed(self):
        calls = [('x.js', 1, name) for name in ('_secret', 'BadName', 'a/b')]
        self.assertEqual(len(drift(calls, {c[2] for c in calls}, {c[2]: 'gerekçe' for c in calls})), 3)

    def test_inheritance_aliases_properties_and_noncallable_overrides(self):
        sources = {'web_base.py': 'class Base:\n def inherited(self): pass\n def blocked(self): pass\n',
                   'web.py': 'from web_base import Base as Parent\nclass Bridge(Parent):\n blocked = None\n @property\n def value(self): pass\n def own(self): pass\n'}
        methods = bridge_methods(sources)
        self.assertIn('inherited', methods)
        self.assertIn('own', methods)
        self.assertNotIn('blocked', methods)
        self.assertNotIn('value', methods)


if __name__ == '__main__':
    unittest.main()
