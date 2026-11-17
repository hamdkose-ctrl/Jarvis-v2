"""Offline checks for the live measurement, never call an account/provider."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('d4_holdout',ROOT/'scripts/brain_output_diagnose_holdout.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def proposal(operation='chat', capability=None):
    return SimpleNamespace(operation=operation,actions=() if capability is None else (SimpleNamespace(capability_id=capability),))


class LiveHoldoutRunnerTests(unittest.TestCase):
    def setUp(self):
        from modules import smart_router
        p=patch.object(smart_router,'qualification_candidate',return_value=smart_router.ModelSpec('groq','test-model'))
        p.start();self.addCleanup(p.stop)

    def _versioned_repository_path(self, rel):
        """Kabul kısayol betiği ve iş akımı yalnız kaynak checkout'unun geliştirme ürünüdür:
        publish_policy `.ps1` (istisna yalnız modules/desktop_uia.ps1) ve `.github/` yollarını
        yayın paketinin içine taşımaz, bu yüzden kurulu PC kopyasında dosya yoktur. Kaynak
        checkout'unda (CI, PC watcher, geliştirme dalı) eksik dosya normal FAIL ile yakalanır."""
        from modules.publish_policy import is_publishable_path
        path = ROOT / rel
        if not path.exists() and not is_publishable_path(rel) and not (ROOT / '.git').exists():
            self.skipTest(f'{rel}: yayın paketi bu yolu taşımıyor (publish_policy); yalnız kaynak deposu denetimi.')
        return path

    def _source_sha(self, sha='f'*40):
        """Rapor kaynağın exact SHA'sını taşımak zorundadır; üretim kodu bunu git'ten ister ve
        kanıt yoksa uydurmaz. Ölçüm sözleşmesi (durum/exit kodu/kabul iddiası) her ağaçta
        koşsun diye SHA kanıtı burada deterministik verilir; doğrulama gevşetilmez."""
        return patch.object(runner, 'subprocess', SimpleNamespace(
            check_output=lambda cmd, *a, **k: sha + '\n', CalledProcessError=subprocess.CalledProcessError))

    def test_response_metadata_does_not_retain_unknown_keys_or_values(self):
        from modules.brain_model_understanding import SCHEMA_VERSION
        data=runner.response_shape(json.dumps({SCHEMA_VERSION:{'SECRET_KEY':'SECRET_TEXT'}}))
        self.assertTrue(data['named_wrapper']);self.assertFalse(data['version_matches'])
        self.assertEqual(data['extra_field_count'],1)
        self.assertNotIn('SECRET',repr(data))
        self.assertEqual(runner.response_shape('not json SECRET'),{'json_object':False})

    def test_a_rejected_raw_wrong_action_is_still_a_critical_proposal(self):
        from modules import llm, brain_model_understanding as model
        def rejected(*args):
            llm.dispatch(None,None,'synthetic','synthetic')
            model._proposal_diagnostic.set({'status':'rejected','reason_code':'CORE_ARGUMENTS_INVALID',
                'operation':'direct_action','capabilities':['documents.export']})
            return None
        with patch('modules.llm.dispatch',return_value='{}'),patch.object(runner,'ask',side_effect=rejected):
            result=runner.measure('owner',[self.case(['chat'])])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['incorrect_action_proposals'],1)

    def case(self, expected, output=True):
        return {'id':'c1','group':'test','text':'synthetic','expected':expected,'has_output':output}

    def test_default_mode_never_accesses_an_account_or_model(self):
        with patch.object(runner,'preflight') as pre, patch.object(runner,'measure') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main([]),0)
        pre.assert_not_called(); run.assert_not_called()

    def test_missing_route_is_unmeasured_and_never_success(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            with self._source_sha(), patch.object(runner,'preflight',return_value=('owner',False,'no route')), patch.object(runner,'measure') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--run','--json',str(report)]),2)
            data=json.loads(report.read_text())
        self.assertEqual(data['state'],'unmeasured');run.assert_not_called()
        self.assertNotIn('owner',data)
        self.assertEqual(data['head'],'f'*40)

    def test_connection_probe_spends_one_case_without_claiming_semantic_acceptance(self):
        measured=runner.verdict([runner.judge(self.case(['chat']),proposal('direct_action','system.diagnose'))],0)
        measured.update(provider_requests=1,provider_responses=1,
                        results=[runner.judge(self.case(['chat']),proposal('direct_action','system.diagnose'))])
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            with self._source_sha(), patch.object(runner,'preflight',return_value=('owner',True,'ready')), patch.object(runner,'measure',return_value=measured) as run, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--run','--connection-only','--json',str(report)]),0)
            data=json.loads(report.read_text())
        self.assertEqual(len(run.call_args.args[1]),1)
        self.assertEqual(data['scope'],'connection');self.assertTrue(data['connection_ok'])
        self.assertFalse(data['semantic_acceptance'])
        self.assertNotIn('accuracy',data);self.assertNotIn('correct',data['results'][0])

    def test_zip_install_without_git_provenances_by_fingerprint_and_never_invents_a_sha(self):
        # Kaynak SHA uydurulmaz: .git olmayan ZIP kurulumunda kanıt, ölçülen içerığın
        # parmak izidir (install:<fp12>, head_source=fingerprint). Kapı zaten yalnız
        # fingerprint/binding/süreye bakar; head alanı tek başına yetki vermez.
        def no_head(cmd,*a,**k):
            raise subprocess.CalledProcessError(128,cmd)
        from modules import smart_router
        expected='install:'+smart_router._role_fingerprint()[:12]
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            with patch.object(runner,'subprocess',SimpleNamespace(check_output=no_head)), patch.object(runner,'preflight',return_value=('owner',False,'no route')), patch.object(runner,'measure') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--run','--json',str(report)]),2)
            data=json.loads(report.read_text())
        self.assertEqual(data['head'],expected)
        self.assertEqual(data['head_source'],'fingerprint')
        self.assertEqual(data['state'],'unmeasured')
        run.assert_not_called()

    def test_local_deadline_and_a_silent_provider_get_different_stop_reasons(self):
        # Aynı 'yanıt yok' görünümü iki ayrı kök nedeni saklamaz: kendi süremiz dolduysa
        # ölçüm local_deadline_exceeded ile durur, sağlayıcı susmuşsa provider_no_response.
        from modules import brain_model_understanding as model
        for code, expected in [('LOCAL_DEADLINE_EXCEEDED','local_deadline_exceeded'),
                               ('MODEL_CALL_OR_VALIDATION_ERROR','provider_no_response')]:
            with self.subTest(reason_code=code):
                def expired(*args):
                    model._proposal_diagnostic.set({'status':'rejected','reason_code':code})
                    return None
                with patch.object(runner,'ask',side_effect=expired):
                    report=runner.measure('owner',[self.case(['chat'])]*20,interval_seconds=0)
                self.assertEqual(report['stop_reason'],expected)
                self.assertEqual(report['state'],'unmeasured')
                self.assertIsNone(report['accuracy'])
                self.assertEqual(report['incorrect_action_proposals'],0)
                self.assertEqual(report['attempted_effects'],0)

    def test_invalid_first_real_response_stops_the_full_run_as_failed(self):
        from modules import llm
        def invalid(*args):
            llm.dispatch(None,None,'synthetic','synthetic')
            return None
        with patch('modules.llm.dispatch',return_value='invalid JSON'), patch.object(runner,'ask',side_effect=invalid) as ask:
            report=runner.measure('owner',[self.case(['chat'])]*20,interval_seconds=0)
        ask.assert_called_once()
        self.assertEqual(report['state'],'failed');self.assertIsNone(report['accuracy'])
        self.assertEqual(report['stop_reason'],'model_response_invalid')
        self.assertEqual(report['planned_cases'],20)

    def test_connection_probe_distinguishes_no_response_from_invalid_response(self):
        for responded, expected in [(False,'unmeasured'),(True,'failed')]:
            row=runner.judge(self.case(['chat']),None,response_received=responded)
            measured=runner.verdict([row],0)
            measured.update(provider_requests=1,provider_responses=int(responded),results=[row])
            with self.subTest(responded=responded), tempfile.TemporaryDirectory() as td:
                report=Path(td)/'report.json'
                with self._source_sha(), patch.object(runner,'preflight',return_value=('owner',True,'ready')), patch.object(runner,'measure',return_value=measured), redirect_stdout(io.StringIO()):
                    exit_code=runner.main(['--run','--connection-only','--json',str(report)])
                data=json.loads(report.read_text())
                self.assertEqual(data['state'],expected)
                self.assertEqual(exit_code,2 if not responded else 1)
                self.assertFalse(data['connection_ok']);self.assertFalse(data['semantic_acceptance'])

    def test_raw_model_proposal_is_required_for_a_score(self):
        row=runner.judge(self.case(['chat']),None)
        report=runner.verdict([row],0)
        self.assertEqual(report['state'],'unmeasured');self.assertIsNone(report['accuracy'])

    def test_an_ironic_comment_must_not_become_an_action(self):
        row=runner.judge(self.case(['chat','needs_input']),proposal('direct_action','system.diagnose'))
        report=runner.verdict([row],0)
        self.assertEqual(report['state'],'failed');self.assertEqual(report['incorrect_action_proposals'],1)

    def test_missing_output_requires_model_clarification_not_assumed_target(self):
        row=runner.judge(self.case(['needs_input'],False),proposal('direct_action','documents.export'))
        self.assertFalse(row['correct']);self.assertEqual(row['outcome'],'documents.export')

    def test_a_model_export_on_a_real_output_is_scored_as_an_action(self):
        row=runner.judge(self.case(['documents.export']),proposal('direct_action','documents.export'))
        self.assertEqual(runner.verdict([row],0)['state'],'passed')

    def test_an_attempted_effect_always_fails_the_measurement(self):
        row=runner.judge(self.case(['chat']),proposal())
        self.assertEqual(runner.verdict([row],1)['state'],'failed')

    def test_a_partial_set_cannot_claim_a_success_rate(self):
        rows=[runner.judge(self.case(['chat']),proposal()),runner.judge(self.case(['chat']),None)]
        r=runner.verdict(rows,0)
        self.assertIsNone(r['accuracy']);self.assertEqual(r['model_responses'],1)

    def test_a_received_but_invalid_model_response_is_failure_not_missing_access(self):
        row=runner.judge(self.case(['chat']),None,response_received=True)
        r=runner.verdict([row],0)
        self.assertEqual(r['state'],'failed');self.assertEqual(r['accuracy'],0)
        self.assertFalse(row['valid_proposal'])

    def test_measurement_intercepts_an_accidental_dispatch(self):
        from modules import engine_intents
        def attempt(*args):
            engine_intents.dispatch(None, 'document_export', {}, '', '')
        with patch.object(runner,'ask',side_effect=attempt):
            result=runner.measure('owner',[self.case(['chat'])])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['attempted_effects'],1)
        self.assertEqual(result['provider_requests'],0)

    def test_expected_answers_are_not_sent_to_the_model_or_used_as_a_fallback(self):
        from modules.brain_contracts import ConversationRelation
        current=SimpleNamespace(arguments={},pending_owner=None,conversation_relation=ConversationRelation.NEW_REQUEST)
        with patch('modules.brain_understanding.understand',return_value=current), patch('modules.brain_model_understanding.propose',return_value=None) as model:
            self.assertIsNone(runner.ask('owner',self.case(['SECRET_EXPECTATION']),0))
        self.assertNotIn('SECRET_EXPECTATION',repr(model.call_args))
        self.assertEqual(model.call_args.kwargs['text'],'synthetic')

    def test_provider_reset_header_is_a_duration_not_an_utterance_rule(self):
        self.assertEqual(runner.reset_seconds('1m2.5s'),62.5)
        self.assertEqual(runner.reset_seconds('500ms'),.5)
        self.assertIsNone(runner.reset_seconds('unknown'))
        self.assertIsNone(runner.reset_seconds('-1s'))

    def test_real_response_observation_and_token_reset_spacing(self):
        from modules import llm
        def fake_response(*args):
            llm.dispatch(None,None,'synthetic','synthetic')
            return proposal()
        with patch('modules.llm.dispatch',return_value='{}'), patch.object(runner,'ask',side_effect=fake_response), patch('modules.usage_meter.limits',return_value={'groq':{'test-model':{'tok_reset':'1m'}}}), patch('modules.llm.groq_model',return_value='test-model'), patch.object(runner.time,'sleep') as sleep:
            r=runner.measure('owner',[self.case(['chat']),self.case(['chat'])])
        self.assertEqual(r['state'],'passed');self.assertEqual(r['provider_responses'],2)
        sleep.assert_called_once_with(61)

    def test_quota_stop_keeps_the_planned_count_without_a_success_rate(self):
        from modules import llm
        def response(owner,case,index):
            if index==0:
                llm.dispatch(None,None,'synthetic','synthetic')
                return proposal()
            return None
        with patch('modules.llm.dispatch',return_value='{}'), patch.object(runner,'ask',side_effect=response):
            r=runner.measure('owner',[self.case(['chat'])]*3,interval_seconds=0)
        self.assertEqual(r['state'],'unmeasured');self.assertIsNone(r['accuracy'])
        self.assertEqual(r['cases'],2);self.assertEqual(r['planned_cases'],3)

    def test_corpus_is_twenty_distinct_synthetic_eval_cases(self):
        rows=json.loads(runner.CORPUS.read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(rows),20);self.assertEqual(len({r['id'] for r in rows}),20)
        self.assertEqual({r['group'] for r in rows},{'export','diagnose','negation','explanation_or_quote','irony','missing_output'})

    def test_windows_workflow_declares_live_acceptance_instead_of_measuring_it(self):
        # CI iş akımı publish_policy'nin kaynağıdır (.yml) ve güncellemeyle de taşınır;
        # kurulu PC kopyasında da denetlenir, bu yüzden burada koşulma kapısı yoktur.
        source=(ROOT/'.github/workflows/testler-windows.yml').read_text(encoding='utf-8')
        # Bu iş makinesinde canlı ölçüm hiç yapılmaz: otomatik çağrı, exit kodu eşlemesi ve
        # CI'da üretilmiş rapor artifact'ı yok. exit2'yi yeşile çevirmek ayrım değil,
        # aynı kanıtı iki kez saymaktır.
        self.assertNotIn('utf8 scripts/brain_output_diagnose_holdout.py',source)
        self.assertNotIn('--run --json',source)
        self.assertNotIn('$Exit',source)
        self.assertNotIn('brain-d4-',source)
        self.assertNotIn('upload-artifact',source)
        self.assertNotIn('continue-on-error',source)
        # Kalan beyan: kapanış için aynı SHA'nın gerçek kullanıcı Full raporu ayrıca gerekir.
        self.assertIn('GITHUB_STEP_SUMMARY',source)
        self.assertIn('state=passed',source)
        self.assertIn('Run-BrainCheck.ps1',source)

    def test_the_accepted_runner_never_widens_the_model_budget(self):
        # Kabul ölçümü üretim bütçesiyle koşılır; bütçe genişletmek yalnız tanıdır ve
        # kabul sonucu sayılmaz. Koşar bunu yaparsa aynı kanıt iki kez sayılmış olur.
        source=(ROOT/'scripts/brain_output_diagnose_holdout.py').read_text(encoding='utf-8')
        self.assertNotIn('_MODEL_BUDGET_SECONDS',source)
        self.assertNotIn('transport_timeouts',source)

    def _powershell(self, script):
        import shutil, subprocess
        if shutil.which('powershell') is None:
            self.skipTest('powershell yok; kısayol temizliği bu koşumda çalıştırılamaz.')
        return subprocess.run(['powershell', '-NoProfile', '-Command', script],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')

    def _cleanup_script(self):
        # Test edilen kod, çalışan kısayolun kendi içindeki blok olmalı: kopya bir betik yazılmıyor.
        source = self._versioned_repository_path('scripts/Run-BrainCheck.ps1').read_text(encoding='utf-8')
        block = source.split('# BEGIN-CLONE-CLEANUP')[1].split('# END-CLONE-CLEANUP')[0]
        self.assertIn('function Remove-BrainCheckClone', block)
        folder = tempfile.mkdtemp(prefix='jarvis-brain-cleanup-')
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, 'cleanup.ps1')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(block)
        return path

    def _build_clone(self, purpose):
        # Sabit ad kullanılamaz: CI ve PC watcher aynı anda koşarsa ikinci süreç
        # ilkinin klasörünü siler ve birbirinin kanıtını yok eder.
        root = tempfile.mkdtemp(prefix='jarvis-brain-cleanup-%s-' % purpose)
        os.makedirs(os.path.join(root, 'alt'))
        with open(os.path.join(root, 'alt', 'dosya.txt'), 'w', encoding='utf-8') as handle:
            handle.write('x')
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_clone_cleanup_deletes_the_clone_on_both_path_forms(self):
        cleanup = self._cleanup_script()
        for form in ('long', 'short'):
            root = self._build_clone(form)
            if form == 'short':
                got = self._powershell(
                    "(New-Object -ComObject Scripting.FileSystemObject).GetFolder('%s').ShortPath" % root)
                root = got.stdout.strip()
                if '~' not in root:
                    continue  # kısa ad bu koşumda üretilemiyorsa uzun yol yine de doğrulanmış sayılır.
            run = self._powershell(". '%s'; $w=$null; $ok=Remove-BrainCheckClone -Path '%s' "
                                   "-WarningVariable w -WarningAction SilentlyContinue; "
                                   "'ok=' + $ok + ' warned=' + [bool]($w)" % (cleanup, root))
            self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
            self.assertIn('ok=True warned=False', run.stdout)
            self.assertFalse(os.path.exists(root), 'Klon silinmeden kaldı: %s' % root)

    def test_clone_cleanup_warns_and_keeps_the_path_visible_when_delete_fails(self):
        cleanup = self._cleanup_script()
        root = self._build_clone('locked')
        locked = os.path.join(root, 'alt', 'dosya.txt')
        # Tutamak bir değişkende kalmalı: Out-Null nesneyi bırakıyor, sonlandırıcı
        # (finalizer) kilidi test ortasında açabilirdi. Dispose ancak finally'de,
        # yani silme denemesi ve çıktı üretildikten sonra yapılır.
        run = self._powershell(
            "$fs=[IO.File]::Open('%s','Open','ReadWrite','None'); try { . '%s'; $w=$null; "
            "$ok=Remove-BrainCheckClone -Path '%s' -WarningVariable w -WarningAction SilentlyContinue; "
            "'ok=' + $ok + ' warned=' + [bool]($w) + ' path=' + $w } "
            "finally { $fs.Dispose() }" % (locked, cleanup, root))
        self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
        self.assertIn('ok=False warned=True', run.stdout)
        self.assertIn(root, run.stdout, 'Uyarı silinemeyen klasör yolını göstermeli.')

    def test_launcher_wires_the_cleanup_and_never_swallows_a_leak(self):
        source = self._versioned_repository_path('scripts/Run-BrainCheck.ps1').read_text(encoding='utf-8')
        finally_block = source.split('} finally {')[1].split('}')[0]
        self.assertIn('Remove-BrainCheckClone -Path $RunDir', finally_block)
        self.assertNotIn('Remove-Item -LiteralPath $RunDir', source)
        self.assertIn('Write-Warning', source.split('# BEGIN-CLONE-CLEANUP')[1])

    def test_provider_pin_is_passed_as_the_exact_free_cloud_target(self):
        # Sabitleme yalnız adayı seçmez: ölçüm o exact bulut modelinin rapor hedefiyle
        # koşülur. Eşikler, bütçe ve kabul koşulları bu baytın varlığıyla değişmez.
        from modules import smart_router
        seen = {}
        def candidate(owner, **kwargs):
            seen.update(kwargs)
            return smart_router.ModelSpec('groq', 'test-model')
        with self._source_sha(), patch.object(runner, 'preflight', return_value=('owner', True, 'ready')), \
                patch.object(smart_router, 'qualification_candidate', side_effect=candidate), \
                patch.object(runner, 'measure', return_value={'state': 'failed'}) as run, \
                redirect_stdout(io.StringIO()):
            exit_code = runner.main(['--run', '--qualify-provider', 'groq'])
        self.assertEqual(seen, {'connection_id': None, 'local': False, 'provider': 'groq'})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(exit_code, 1)

    def test_provider_pin_refuses_local_and_custom_modes_before_any_preflight(self):
        # --qualify-provider yalnız ücretsiz bulut sırasını sabitler; yerel/özel hedefin
        # kendi sabitlemesi vardır. Çakışma ilk model çağrısından önce reddedilir.
        for other in ('--qualify-local', '--qualify-connection'):
            argv = ['--run', '--qualify-provider', 'groq', other]
            if other == '--qualify-connection':
                argv += ['conn-1', '--accept-paid']
            with self.subTest(other=other), patch.object(runner, 'preflight') as pre, \
                    patch.object(runner, 'measure') as run, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as got:
                    runner.main(argv)
            self.assertEqual(got.exception.code, 2)
            pre.assert_not_called()
            run.assert_not_called()

    def test_provider_pin_only_accepts_the_three_free_cloud_providers(self):
        # Yerel/özel sağlayıcılar kendi sabitleme bayraklarıyla ölçülür; serbest metin
        # uydurma hedefe ilk çağrıyı gönderemez.
        for name in ('ollama', 'custom', 'GROQ'):
            with self.subTest(name=name), patch.object(runner, 'preflight') as pre, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as got:
                    runner.main(['--run', '--qualify-provider', name])
            self.assertEqual(got.exception.code, 2)
            pre.assert_not_called()


class QualificationCandidateTargetTests(unittest.TestCase):
    def test_provider_filter_pins_the_first_matching_free_candidate(self):
        from modules import smart_router
        specs = (smart_router.ModelSpec('gemini', 'g-1'),
                 smart_router.ModelSpec('groq', 'q-1'),
                 smart_router.ModelSpec('groq', 'q-2'))
        with patch.object(smart_router, 'plan', return_value=smart_router.RoutePlan(specs, (), 1)):
            self.assertEqual(smart_router.qualification_candidate('owner').model, 'g-1')
            self.assertEqual(smart_router.qualification_candidate('owner', provider='groq').model, 'q-1')
            with self.assertRaises(ValueError):
                smart_router.qualification_candidate('owner', provider='cloudflare')

    def test_routed_free_candidates_carry_the_original_order_when_unpinned(self):
        # Sabitleme yoksa sözleşme eskisi gibi: ilk uygun ücretsiz bulut adayı döner.
        from modules import smart_router
        specs = (smart_router.ModelSpec('groq', 'q-1'), smart_router.ModelSpec('gemini', 'g-1'))
        with patch.object(smart_router, 'plan', return_value=smart_router.RoutePlan(specs, (), 1)):
            self.assertEqual(smart_router.qualification_candidate('owner').model, 'q-1')
            self.assertEqual(smart_router.qualification_candidate('owner', provider='gemini').model, 'g-1')


class CaptureHeadTests(unittest.TestCase):
    def test_git_checkout_reports_the_commit_and_is_marked_as_git(self):
        with patch('subprocess.check_output', return_value='abc123def\n') as out:
            head, source = runner._capture_head(Path('.'))
        self.assertEqual((head, source), ('abc123def', 'git'))
        out.assert_called_once()

    def test_non_git_zip_install_falls_back_to_the_fingerprint_marker(self):
        from modules import smart_router
        failure = subprocess.CalledProcessError(128, ['git', 'rev-parse', 'HEAD'])
        with patch('subprocess.check_output', side_effect=failure):
            head, source = runner._capture_head(Path('.'))
        self.assertEqual(source, 'fingerprint')
        self.assertEqual(head, 'install:' + smart_router._role_fingerprint()[:12])

    def test_head_is_provenance_only_and_the_gate_never_reads_it(self):
        import inspect
        from modules import router_quota, smart_router
        gate = inspect.getsource(router_quota.role_qualified)
        self.assertNotIn('head', gate)
        self.assertIn('_role_fingerprint()', inspect.getsource(smart_router._brain_role_allowed))
