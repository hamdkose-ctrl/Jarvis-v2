"""The Home weather cache publishes only the active request generation."""

import ast
import threading
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class HomeWeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "web.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sampler = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "Sampler")
        # Loading only Sampler keeps the tests independent of the desktop runtime.
        cls.code = compile(ast.Module(body=[sampler], type_ignores=[]), str(path), "exec")

    def setUp(self):
        self.pending = []
        self.source = Mock()
        self.clock = 10_000
        scope = {
            "deque": deque,
            "threading": SimpleNamespace(Lock=threading.Lock, Thread=self.defer_thread),
            "time": SimpleNamespace(time=lambda: self.clock),
            "weather_struct": self.source,
        }
        exec(self.code, scope)
        self.sampler = scope["Sampler"]()

    def defer_thread(self, *, target, args, daemon):
        self.assertTrue(daemon)
        return SimpleNamespace(start=lambda: self.pending.append((target, args)))

    def refresh(self, owner, city, elapsed=0):
        self.clock += elapsed
        self.sampler._refresh_weather(owner, city, self.clock)

    def complete(self, snapshot, index=0):
        self.source.return_value = snapshot
        target, args = self.pending.pop(index)
        target(*args)

    def test_cache_is_invalidated_immediately_on_city_change(self):
        self.refresh("alice", "İzmir")
        izmir = {"city": "İzmir", "temp": 21}
        self.complete(izmir)
        self.assertEqual(self.sampler.weather_for("alice", "İzmir"), izmir)
        self.assertIsNone(self.sampler.weather_for("alice", "Ankara"))
        self.assertIsNone(self.sampler.weather_for("bob", "İzmir"))

        # Within the normal TTL, the new city still gets its own request.
        self.refresh("alice", "Ankara", elapsed=1)
        self.assertIsNone(self.sampler.weather_for("alice", "İzmir"))
        self.assertIsNone(self.sampler.weather_for("alice", "Ankara"))
        ankara = {"city": "Ankara", "temp": 13}
        self.complete(ankara)
        self.assertEqual(self.sampler.weather_for("alice", "Ankara"), ankara)

    def test_late_result_for_previous_owner_cannot_replace_current_weather(self):
        self.refresh("alice", "İzmir")
        self.refresh("bob", "İzmir", elapsed=1)
        current = {"city": "İzmir", "temp": 22}
        self.complete(current, index=1)
        self.complete({"city": "İzmir", "temp": 19})
        self.assertEqual(self.sampler.weather_for("bob", "İzmir"), current)
        self.assertIsNone(self.sampler.weather_for("alice", "İzmir"))

    def test_invalidation_discards_inflight_result_even_for_the_same_key(self):
        self.refresh("alice", "İzmir")
        self.sampler.invalidate_weather()
        self.refresh("alice", "İzmir", elapsed=1)
        self.complete({"city": "İzmir", "temp": 18})
        self.assertIsNone(self.sampler.weather_for("alice", "İzmir"))

        current = {"city": "İzmir", "temp": 20}
        self.complete(current)
        self.assertEqual(self.sampler.weather_for("alice", "İzmir"), current)

    def test_current_failure_can_retry_after_short_delay(self):
        self.refresh("alice", "İzmir")
        self.complete(None)
        self.assertIsNone(self.sampler.weather_for("alice", "İzmir"))
        self.refresh("alice", "İzmir", elapsed=30)
        self.assertEqual(len(self.pending), 0)
        self.refresh("alice", "İzmir", elapsed=31)
        self.assertEqual(len(self.pending), 1)
        current = {"city": "İzmir", "temp": 18}
        self.complete(current)
        self.assertEqual(self.sampler.weather_for("alice", "İzmir"), current)


if __name__ == "__main__":
    unittest.main()
