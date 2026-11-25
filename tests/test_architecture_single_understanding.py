"""Mimari bekçi: tek anlama sahibi.

25 Kasım dersi: mevcut Brain (`brain_model_understanding`) dururken `capability_*`
diye paralel bir anlama yolu eklendi ve iki beyin doğdu. Bu test, aynı hatanın
sessizce tekrarlanmasını engeller:

- `modules/` içinde `capability_*` adlı anlama modülü olamaz.
- `fast_commands.resolve` yalnız tek yerden (engine_loop) çağrılır; başka modül
  kendi karar noktasını kurup hızlı yolu ikinci kez yorumlayamaz.
"""
import ast
import unittest
from pathlib import Path

MODULES = Path(__file__).resolve().parents[1] / "modules"
# `pc_task` çok adımlı görevi adımlara böler; karar sahibi değil, var olan
# yürütücüyü (engine_intents) kullanır. Yeni bir çağıran eklemek bu listeye
# bilinçli kayıt gerektirir — sessizce ikinci karar noktası doğamaz.
ALLOWED_RESOLVE_CALLERS = {"engine_loop.py", "pc_task.py"}
FORBIDDEN_PARALLEL_BRAINS = {
    "capability_brain.py", "capability_llm.py", "capability_router.py",
    "capability_catalog.py", "capability_understand.py",
}


def _py_files():
    return sorted(path for path in MODULES.glob("*.py") if path.name != "__init__.py")


class SingleUnderstandingOwner(unittest.TestCase):
    def test_no_parallel_capability_brain(self):
        present = {path.name for path in _py_files()}
        offenders = sorted(present & FORBIDDEN_PARALLEL_BRAINS)
        self.assertEqual(offenders, [], f"paralel anlama modülü: {offenders}")

    def test_fast_path_is_read_from_one_place(self):
        callers = []
        for path in _py_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "resolve"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "fast_commands"):
                    callers.append(path.name)
        self.assertEqual(sorted(set(callers)), sorted(ALLOWED_RESOLVE_CALLERS))


if __name__ == "__main__":
    unittest.main()
