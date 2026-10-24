import unittest


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self):
        from modules import crash_recovery, effect_journal
        self.recovery = crash_recovery
        self.journal = effect_journal.Journal()

    def intent(self):
        return {'schema':'effect_intent.v1','effect_id':'e1','owner':'alice','job_id':'job-1',
                'command_id':'cmd-1','capability_id':'mail.send','capability_version':'1',
                'input_digest':'a'*64}

    def test_no_intent_is_not_started_and_cannot_retry_implicitly(self):
        out=self.recovery.decide(self.journal,'e1')
        self.assertEqual(out, {'state':'not_started','action':'policy_required','reason_code':'EFFECT_INTENT_MISSING'})

    def test_intent_without_receipt_is_unknown_read_only_reconcile(self):
        self.journal.record_intent(self.intent())
        out=self.recovery.decide(self.journal,'e1')
        self.assertEqual(out['state'],'unknown'); self.assertEqual(out['action'],'read_only_reconcile')
        self.assertEqual(out['reason_code'],'RECEIPT_MISSING_NO_BLIND_RETRY')

    def test_verified_receipt_is_succeeded_and_never_retries(self):
        self.journal.record_intent(self.intent())
        self.journal.record_receipt({'schema':'effect_receipt.v1','effect_id':'e1','provider_receipt_ref':'r1','verified':True})
        self.assertEqual(self.recovery.decide(self.journal,'e1')['action'],'no_retry')


class RequiredFollowsManifestPolicyTests(unittest.TestCase):
    """required() must mirror the manifest's replay/reconciliation policy for
    every task capability, not just 'publish': journal coverage is manifest-
    driven, and a read-only capability must never enter the journal path."""

    def setUp(self):
        from modules import capability_manifest, effect_recovery_runtime, task_tools
        self.manifest = capability_manifest
        self.runtime = effect_recovery_runtime
        self.task_tools = task_tools

    def test_every_task_capability_matches_its_manifest_replay_reconciliation_policy(self):
        checked = []
        for kind in self.task_tools.CATALOG:
            row = self.manifest.from_task_tool(kind)
            expects_journal = row['replay'] == 'conditional' and row['reconciliation'] == 'required'
            self.assertEqual(
                self.runtime.required(kind), expects_journal,
                f"{kind}: manifest replay={row['replay']!r} reconciliation={row['reconciliation']!r} "
                f"but required()={self.runtime.required(kind)!r}",
            )
            checked.append(kind)
        # Sanity: both a journal-required and a journal-exempt capability exist,
        # otherwise this loop could pass vacuously.
        self.assertTrue(any(self.runtime.required(kind) for kind in checked))
        self.assertTrue(any(not self.runtime.required(kind) for kind in checked))

    def test_read_only_capability_is_never_journal_required(self):
        for kind in ('research', 'account', 'verify'):
            row = self.manifest.from_task_tool(kind)
            self.assertEqual(row['effect_policy'], 'read_only')
            self.assertFalse(self.runtime.required(kind))

    def test_external_write_capability_is_journal_required(self):
        row = self.manifest.from_task_tool('publish')
        self.assertEqual(row['effect_policy'], 'external_write')
        self.assertTrue(self.runtime.required('publish'))
