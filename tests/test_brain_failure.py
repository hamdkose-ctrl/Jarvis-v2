import inspect
import tempfile
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import Mock, patch

from modules import brain_failure, engine_loop, engine_voice, failure_policy, requests_state
from modules.brain_contracts import BrainFeedback

SECRETS = ("sk-SECRETKEY1234567890", "https://api.evil.test/v1?key=ABCDEF123456", r"C:\Users\hamdi\gizli\sifre.txt",
           "/home/hamdi/.ssh/id_rsa", "Bearer abcdef0123456789abcdef0123456789abcdef")


def leaky(cls, *extra):
    return cls(" ".join(SECRETS), *extra)


class _Http(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.status_code = code


def feedback(status="failed", **kw):
    return BrainFeedback(owner="hamdi", request_id="r1", result_status=status, **kw)


class SynthesizeLeakTests(unittest.TestCase):
    def cases(self):
        yield leaky(requests_state.Cancelled)
        yield leaky(FileNotFoundError)
        yield leaky(ValueError)
        yield leaky(TypeError)
        yield leaky(PermissionError)
        yield leaky(RuntimeError)
        yield leaky(KeyError)
        yield leaky(ConnectionError)
        yield leaky(TimeoutError)
        yield leaky(ModuleNotFoundError)
        yield leaky(failure_policy.ProviderExhaustedError)
        yield _Http(429, " ".join(SECRETS) + " PerDay")
        yield _Http(401, " ".join(SECRETS))
        yield _Http(503, " ".join(SECRETS))

    def test_no_branch_leaks_raw_exception_text(self):
        for exc in self.cases():
            for fb in (None, feedback(), feedback("cancelled"), feedback("needs_input", needs_input=True)):
                with self.subTest(exc=type(exc).__name__, fb=getattr(fb, "result_status", None)):
                    text = brain_failure.synthesize(fb, exc)
                    self.assertTrue(text.strip())
                    for secret in SECRETS:
                        self.assertNotIn(secret, text)
                    for needle in ("SECRETKEY", "evil.test", "gizli", "id_rsa", "abcdef0123456789"):
                        self.assertNotIn(needle, text)

    def test_fixed_sentences_per_kind(self):
        self.assertEqual(brain_failure.synthesize(None, requests_state.Cancelled("x")), brain_failure.CANCELLED_TEXT)
        self.assertEqual(brain_failure.synthesize(feedback("cancelled"), RuntimeError("x")), brain_failure.CANCELLED_TEXT)
        self.assertEqual(brain_failure.synthesize(None, FileNotFoundError("x")), brain_failure.FILE_TEXT)
        self.assertEqual(brain_failure.synthesize(None, ValueError("x")), brain_failure.VALIDATION_TEXT)
        self.assertEqual(brain_failure.synthesize(feedback("needs_input", needs_input=True), ValueError("x")),
                         brain_failure.NEEDS_INPUT_TEXT)
        self.assertEqual(brain_failure.synthesize(None, KeyError("x")), brain_failure.GENERIC_TEXT)

    def test_provider_failures_use_policy_text_and_keep_recovery_class(self):
        exc = _Http(429, "PerDay quota")
        text = brain_failure.synthesize(feedback(recovery_class="fallback_possible"), exc)
        self.assertEqual(text, brain_failure.scrub(failure_policy.explain(exc)))
        self.assertNotIn("429", text)
        self.assertEqual(failure_policy.recovery_class(exc), failure_policy.structured_outcome(exc)["recovery_class"])

    def test_scrub_and_never_raises(self):
        text = brain_failure.scrub("hata " + " ".join(SECRETS))
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        with patch.object(failure_policy, "classify", side_effect=RuntimeError("boom")):
            self.assertEqual(brain_failure.synthesize(None, RuntimeError("x")), brain_failure.GENERIC_TEXT)


class BindingTests(unittest.TestCase):
    def test_no_raw_exception_branch_remains_in_engine_loop_and_voice(self):
        for fn in (engine_loop.main, engine_voice._live_command if hasattr(engine_voice, "_live_command") else engine_voice):
            source = inspect.getsource(fn)
            self.assertNotIn("diagnose.explain", source)
            self.assertNotIn("out = str(exc)", source)
            self.assertNotIn("return str(exc)", source)

    def test_voice_module_has_no_raw_exception_to_user(self):
        source = inspect.getsource(engine_voice)
        self.assertNotIn("diagnose.explain", source)
        self.assertNotIn("out = str(exc)", source)
        self.assertNotIn("return str(exc)", source)
        self.assertNotIn("Google yöntemiyle devam: {exc}", source)


class LiveCommandBranchLeakTests(unittest.TestCase):
    """engine_voice._live_command: every failure branch of the real orchestration, no raw text out."""

    def setUp(self):
        import test_engine_modular as fixtures
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        for name, value in [('_journal', Path(folder.name) / 'requests.json'), ('_records', {}),
                            ('_current', ContextVar('failure_request', default=None))]:
            p = patch.object(requests_state, name, value); p.start(); self.addCleanup(p.stop)
        self.runtime = fixtures.ModularEngineTests.context(self)
        self.runtime.requests_state = requests_state
        self.runtime.emit = Mock()

    def run_with(self, exc):
        def handle(text):
            raise exc
        self.runtime.handle = handle
        return str(self.runtime._live_command('işlem yap'))

    def assert_clean(self, text):
        self.assertTrue(text.strip())
        for needle in ("SECRETKEY", "evil.test", "gizli", "id_rsa", "abcdef0123456789", "Traceback"):
            self.assertNotIn(needle, text)

    def test_each_branch_is_synthesized(self):
        for exc in (leaky(ValueError), leaky(FileNotFoundError), leaky(RuntimeError), leaky(KeyError),
                    leaky(PermissionError), _Http(429, " ".join(SECRETS)), leaky(failure_policy.ProviderExhaustedError)):
            with self.subTest(exc=type(exc).__name__):
                self.assert_clean(self.run_with(exc))

    def test_cancel_branch_outside_handle(self):
        def handle(text):
            raise leaky(requests_state.Cancelled)
        self.runtime.handle = handle
        text = str(self.runtime._live_command('işlem yap'))
        self.assert_clean(text)
        self.assertIn('iptal', text)


if __name__ == "__main__":
    unittest.main()
