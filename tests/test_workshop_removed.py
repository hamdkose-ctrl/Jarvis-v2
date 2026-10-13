import ast
import tempfile
import unittest
from pathlib import Path
from scripts.kurulum_temizligi import remove

ROOT=Path(__file__).resolve().parents[1]


class WorkshopRemovalTests(unittest.TestCase):
    def test_no_workshop_routes_assets_or_module(self):
        web=ast.parse((ROOT/'web.py').read_text(encoding='utf-8'))
        bridge=next(n for n in web.body if isinstance(n,ast.ClassDef) and n.name=='Bridge')
        self.assertFalse(any(isinstance(n,ast.FunctionDef) and n.name.startswith('selfcoder_') for n in bridge.body))
        self.assertTrue(any(isinstance(n,ast.FunctionDef) and n.name=='github_publish' for n in bridge.body))
        self.assertFalse((ROOT/'modules/selfcoder').exists())
        ui=(ROOT/'webui/nx.js').read_text(encoding='utf-8')
        self.assertNotIn('selfcoder',ui.lower())
        self.assertNotIn('selfcoder_chat',(ROOT/'webui/nx.html').read_text())
        self.assertIn('ACT.mictoggle',ui)

    def test_overlay_cleanup_only_removes_obsolete_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'main.py').touch();(root/'web.py').touch()
            (root/'ATOLYEYI_KALDIR.bat').write_text('obsolete')
            (root/'scripts').mkdir();(root/'scripts/atolye_kalintilarini_kaldir.py').write_text('obsolete')
            old=root/'modules/selfcoder';old.mkdir(parents=True);(old/'engine.py').write_text('old')
            keep=root/'modules/git_publish.py';keep.write_text('keep')
            personal=root/'notes.json';personal.write_text('personal')
            remove(root)
            self.assertFalse(old.exists())
            self.assertFalse((root/'ATOLYEYI_KALDIR.bat').exists())
            self.assertFalse((root/'scripts/atolye_kalintilarini_kaldir.py').exists())
            self.assertEqual(keep.read_text(),'keep')
            self.assertEqual(personal.read_text(),'personal')
            self.assertEqual(remove(root),[])

    def test_wrong_directory_cannot_be_cleaned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'modules/selfcoder';old.mkdir(parents=True)
            with self.assertRaises(RuntimeError):remove(root)
            self.assertTrue(old.exists())
