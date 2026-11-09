"""Record an explicitly user-attested Groq Free plan against reviewed official model facts.

No account/plan API claim is made. No secret is printed or copied. Default is a
plan only; --confirm-free-no-payment records the current owner's current model.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
REVIEWED_MODELS = frozenset({'openai/gpt-oss-120b','openai/gpt-oss-20b','qwen/qwen3.8-27b'})
RATE_SOURCE = 'https://console.groq.com/docs/rate-limits'
BILLING_SOURCE = 'https://console.groq.com/docs/billing-faqs'
# Reviewed 2026-11-08: Free model table; exceeding limits returns429; paid upgrade requires payment method.
FACTS_EXPIRE = datetime(2026,11,15,tzinfo=timezone.utc).timestamp()


def confirm(*, free_no_payment_confirmed: bool):
    if free_no_payment_confirmed is not True:
        raise ValueError('Explicit Groq Free/no-payment user attestation is required.')
    now=time.time()
    if now >= FACTS_EXPIRE:
        raise ValueError('Official model facts expired; review them before recording new evidence.')
    from modules import llm, smart_router
    owner=llm.current_user()
    model=llm.groq_model()
    if not owner or not llm.user_groq_key(owner):
        raise ValueError('The current Jarvis profile has no configured Groq key.')
    if not smart_router.settings(owner).get('cloud_free_confirmed'):
        raise ValueError('The current profile has not enabled its free cloud accounts.')
    if model not in REVIEWED_MODELS:
        raise ValueError('The selected Groq model is not in the reviewed Free model table: '+model)
    old=smart_router.free_tier_evidence(owner,'groq',model) or {}
    if (old.get('verification_status')=='rejected' or old.get('eligibility')=='not_eligible'
            or old.get('quota_state')=='exhausted' or old.get('quota_remaining')==0):
        raise ValueError('Existing negative/quota evidence is preserved; resolve that finding first.')
    result=smart_router.set_free_tier_evidence(owner,provider='groq',model=model,
        free_tier_verified=True,source='user-attested Free/no-payment + reviewed Groq official model facts',
        evidence_ref=RATE_SOURCE+' ; '+BILLING_SOURCE,verified_at=now,
        ttl_seconds=min(7*86400,FACTS_EXPIRE-now),eligibility='eligible',
        quota_state='not_reported',quota_remaining=None,hard_stop_guaranteed=True,
        verification_status='verified',
        reason='User explicitly attested Free plan without payment method; official model/429 and billing policy reviewed. Not an account API verification.')
    return {'model':model,'source':result['source'],'expires_at':result['expires_at']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--confirm-free-no-payment',action='store_true')
    args=p.parse_args(argv)
    if not args.confirm_free_no_payment:
        print('Plan only. Record evidence only after the user explicitly confirms their Groq Free plan and no payment method.')
        return 0
    try:
        result=confirm(free_no_payment_confirmed=True)
    except ValueError as exc:
        print(str(exc));return 2
    print('Groq model evidence recorded:',result['model'],'(quota not invented; reviewed facts expire 2026-11-15)')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
