"""User attestation plus official facts; no real provider, key or profile writes."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('confirm_groq',ROOT/'scripts/confirm_groq_free_plan.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


class ConfirmGroqFreePlanTests(unittest.TestCase):
    def setUp(self):
        from modules import smart_router
        self.router=smart_router
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.model='openai/gpt-oss-120b'
        for target,value in (
            ('modules.smart_router._STORE',Path(self.temp.name)),
            ('modules.llm.current_user',lambda:'test-owner'),
            ('modules.llm.groq_model',lambda:self.model),
            ('modules.llm.user_groq_key',lambda owner:'test-only'),
            ('time.time',lambda:setup.FACTS_EXPIRE-3600),
        ):
            p=patch(target,value);p.start();self.addCleanup(p.stop)
        self.router.configure('test-owner',cloud_free_confirmed=True)

    def test_default_plan_does_not_record_evidence(self):
        with patch.object(setup,'confirm') as write,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup.main([]),0)
        write.assert_not_called()

    def test_explicit_free_attestation_records_only_the_current_owner_model(self):
        setup.confirm(free_no_payment_confirmed=True)
        row=self.router.free_tier_evidence('test-owner','groq',self.model)
        self.assertEqual(row['expires_at'],setup.FACTS_EXPIRE)
        self.assertEqual(row['quota_state'],'not_reported');self.assertIsNone(row['quota_remaining'])
        self.assertIn('user-attested',row['source']);self.assertIn(setup.RATE_SOURCE,row['evidence_ref'])
        self.assertIn('Not an account API verification',row['reason'])
        self.assertIsNone(self.router.free_tier_evidence('another-owner','groq',self.model))
        self.assertTrue(self.router._evidence_gate('test-owner','groq',self.model)['ok'])

    def test_no_user_attestation_never_writes_a_record(self):
        with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=False)
        self.assertIsNone(self.router.free_tier_evidence('test-owner','groq',self.model))

    def test_unknown_model_is_not_assumed_to_be_free(self):
        self.model='unreviewed-model'
        with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=True)

    def test_expired_official_facts_do_not_renew_themselves(self):
        with patch('time.time',return_value=setup.FACTS_EXPIRE+1):
            with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=True)

    def test_missing_key_or_disabled_cloud_is_not_bypassed(self):
        with patch('modules.llm.user_groq_key',return_value=''):
            with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=True)
        self.router.configure('test-owner',cloud_free_confirmed=False)
        with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=True)

    def test_existing_negative_or_exhausted_evidence_is_preserved(self):
        for field,value in [('verification_status','rejected'),('eligibility','not_eligible'),('quota_state','exhausted'),('quota_remaining',0)]:
            with self.subTest(field=field):
                state=self.router.settings('test-owner')
                state['free_tier_evidence']={'groq':{self.model:{field:value}}}
                self.router._save_state('test-owner',state)
                with self.assertRaises(ValueError):setup.confirm(free_no_payment_confirmed=True)
                self.assertEqual(self.router.free_tier_evidence('test-owner','groq',self.model),{field:value})
