"""Facade import does not start the engine; concurrent consumers share one."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock,patch

class LazyFacadeTests(unittest.TestCase):
    def test_import_is_lazy_and_concurrent_runtime_access_constructs_once(self):
        module=ModuleType('lazy_facade_test')
        context=SimpleNamespace()
        constructor=Mock(return_value=context)
        dependency=ModuleType('modules.engine_runtime');dependency.EngineContext=constructor
        with patch.dict(sys.modules,{'lazy_facade_test':module,'modules.engine_runtime':dependency}):
            exec(compile((Path(__file__).resolve().parents[1]/'main.py').read_bytes(),'main.py','exec'),module.__dict__)
            constructor.assert_not_called()
            self.assertFalse(hasattr(module,'__path__'));constructor.assert_not_called()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda _:module._runtime,range(16)))
            self.assertTrue(all(value is context for value in results))
            constructor.assert_called_once()
