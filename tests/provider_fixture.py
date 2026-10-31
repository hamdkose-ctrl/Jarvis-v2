"""Test helper: keep the provider privacy bundle valid regardless of the real clock.

The production bundle expires (stale evidence fails closed). Tests of routing mechanics must not
depend on today's date, so they run against a copy whose expiry is far in the future. Tests of the
expiry itself (test_provider_privacy) use the real bundle with an explicit ``now``.
"""
from unittest.mock import patch

from modules import provider_privacy

FAR_FUTURE = 4_000_000_000.0


def fresh_bundle(testcase):
    bundle = {name: dict(facts, expires_at=FAR_FUTURE) for name, facts in provider_privacy.PROVIDER_BUNDLE.items()}
    patcher = patch.object(provider_privacy, "PROVIDER_BUNDLE", bundle)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return bundle
