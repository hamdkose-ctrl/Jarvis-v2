"""Offline Router fixtures for Core and Brain tests."""
from unittest.mock import patch
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


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
