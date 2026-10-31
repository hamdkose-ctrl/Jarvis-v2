import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from modules import llm, smart_router as router

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {"docs", "tests", ".git", "__pycache__", "node_modules", ".claude"}
SCANNED = {".py", ".js", ".html", ".json", ".md", ".txt", ".bat", ".toml", ".yml", ".yaml", ".css"}


class OpenRouterRemovedTests(unittest.TestCase):
    def test_no_openrouter_reference_left_in_code_web_or_config(self):
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCANNED:
                continue
            rel = path.relative_to(ROOT)
            if rel.parts[0] in SKIP_DIRS or SKIP_DIRS & set(rel.parts):
                continue
            if "openrouter" in path.read_text(encoding="utf-8", errors="ignore").lower():
                offenders.append(str(rel))
        self.assertEqual(offenders, [])

    def test_set_provider_rejects_openrouter(self):
        with self.assertRaises(ValueError):
            llm.set_provider("openrouter")

    def test_stored_openrouter_choice_falls_back_to_the_router_policy(self):
        with patch.object(llm, "_choice", return_value={"provider": "openrouter"}), \
             patch.object(llm, "load_settings", return_value={"provider": "openrouter"}):
            self.assertEqual(llm._cfg()["provider"], "auto")

    def test_router_has_no_openrouter_surface(self):
        for name in ("openrouter", "api_key", "_free_emergency"):
            self.assertFalse(hasattr(router, name), name)
        self.assertNotIn("openrouter", router._CLOUD_PROVIDERS)
        with self.assertRaises(ValueError):
            router.set_free_tier_evidence(
                "alice", provider="openrouter", model="m", free_tier_verified=True, source="s", evidence_ref="r",
                verified_at=1.0, ttl_seconds=60, eligibility="eligible")


class LegacyStatePurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(router, "_STORE", pathlib.Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, state):
        path = router.owner_path("alice")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    def test_stored_key_model_and_evidence_are_deleted_from_disk(self):
        path = self.write({
            "cloud_free_confirmed": True, "key": "enc:sk-or-secret", "openrouter_model": "openrouter/free",
            "free_tier_evidence": {"openrouter": {"openrouter/free": {"provider": "openrouter"}},
                                   "groq": {"m": {"provider": "groq", "model": "m"}}},
        })
        state = router.settings("alice")
        self.assertTrue(state["cloud_free_confirmed"])
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("key", on_disk)
        self.assertNotIn("openrouter_model", on_disk)
        self.assertNotIn("openrouter", on_disk["free_tier_evidence"])
        self.assertIn("groq", on_disk["free_tier_evidence"])
        self.assertTrue(on_disk["cloud_free_confirmed"])
        self.assertNotIn("sk-or-secret", path.read_text(encoding="utf-8"))

    def test_clean_state_is_not_rewritten(self):
        path = self.write({"cloud_free_confirmed": False, "free_tier_evidence": {}})
        before = path.stat().st_mtime_ns
        router.settings("alice")
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_purge_failure_is_non_fatal(self):
        self.write({"cloud_free_confirmed": True, "key": "x"})
        with patch.object(router, "_save_state", side_effect=OSError("disk")):
            self.assertTrue(router.settings("alice")["cloud_free_confirmed"])

    def test_status_has_no_openrouter_row_or_key_field(self):
        with patch.object(router.privacy, "mode", return_value="normal"):
            status = router.status("alice")
        self.assertNotIn("openrouter", json.dumps(status).lower())
        self.assertNotIn("key", status)


if __name__ == "__main__":
    unittest.main()
