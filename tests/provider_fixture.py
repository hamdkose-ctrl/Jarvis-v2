"""Test helper: keep the provider privacy bundle valid regardless of the real clock.

The production bundle expires (stale evidence fails closed). Tests of routing mechanics must not
depend on today's date, so they run against a copy whose expiry is far in the future. Tests of the
expiry itself (test_provider_privacy) use the real bundle with an explicit ``now``.
"""
from unittest.mock import patch
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from modules import provider_privacy

FAR_FUTURE = 4_000_000_000.0


def fresh_bundle(testcase):
    bundle = {name: dict(facts, expires_at=FAR_FUTURE) for name, facts in provider_privacy.PROVIDER_BUNDLE.items()}
    patcher = patch.object(provider_privacy, "PROVIDER_BUNDLE", bundle)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return bundle


@contextmanager
def routed_response(text):
    """Core/grammar fixture: real typed Router, real trace DB; fake provider boundary.

    The returned spy counts logical requests, not physical provider attempts.
    Candidate policy is explicitly injected; this is never a live role acceptance.
    """
    from modules import llm,smart_router
    plan=smart_router.RoutePlan(tuple(smart_router.ModelSpec('groq',name)
        for name in ('fixture-model-a','fixture-model-b')),(),2)
    with TemporaryDirectory() as folder,patch.object(smart_router,'_HEALTH',{}),patch.object(smart_router,'_STORE',Path(folder)),\
            patch.object(smart_router,'plan',return_value=plan),\
            patch.object(llm,'_send_provider',return_value=text),\
            patch.object(smart_router,'run_request',wraps=smart_router.run_request) as request:
        yield request


@contextmanager
def routed_plan(*, provider='groq', model='fixture-model', count=2):
    """Only eligibility is injected; transport/validator/budget/accounting stay real."""
    from modules import smart_router
    plan=smart_router.RoutePlan((smart_router.ModelSpec(provider,model),),(),count)
    with TemporaryDirectory() as folder,patch.object(smart_router,'_HEALTH',{}),patch.object(smart_router,'_STORE',Path(folder)),patch.object(smart_router,'plan',return_value=plan):
        yield
