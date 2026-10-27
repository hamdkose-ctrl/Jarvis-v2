import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import failure_policy, image_gen, model_health


class _StatusError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f'HTTP {status_code}')
        self.status_code = status_code


class _Models:
    def list(self, config=None):
        raise _StatusError(429)


class _Client:
    def __init__(self):
        self.models = _Models()
    def close(self):
        pass


class FailurePolicyConsumerTests(unittest.TestCase):
    def test_model_health_uses_common_status_classification(self):
        model_health._cache.clear()
        result = model_health.check('hamdi', 'key', ['gemini-x'], lambda **_: _Client(), force=True)
        self.assertEqual(result['state'], 'quota_error')

    def test_model_health_has_no_private_http_code_classifier(self):
        source = inspect.getsource(model_health.check)
        self.assertIn('failure_policy.classify', source)
        self.assertNotIn("code in (401,403)", source.replace(' ', ''))
        self.assertNotIn('code==429', source.replace(' ', ''))

    def test_image_gen_delegates_http_failure_classification(self):
        source = inspect.getsource(image_gen.generate_image)
        self.assertIn('failure_policy.classify', source)
        compact = source.replace(' ', '')
        self.assertNotIn('resp.status_code==429', compact)
        self.assertNotIn('resp.status_code==401', compact)

    def test_common_policy_classifies_http_shapes(self):
        self.assertEqual(failure_policy.classify(_StatusError(429)), failure_policy.RATE_LIMIT)
        auth = RuntimeError('forbidden')
        auth.response = SimpleNamespace(status_code=403)
        self.assertEqual(failure_policy.classify(auth), failure_policy.AUTH)


if __name__ == '__main__':
    unittest.main()
