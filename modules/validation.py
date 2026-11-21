"""One mandatory, isolated release suite for developer, GitHub and local checks."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import release_guard as guard

JS_GROUPS = ('desktop_flows', 'files_in_chat_behavior', 'chat_drop_behavior', 'mobile_behavior', 'continuity_behavior', 'fieldnotes_behavior', 'desktop_auth_behavior', 'paid_provider_behavior', 'developer_behavior', 'router_behavior', 'study_behavior', 'navigation_start_behavior', 'local_stt_behavior', 'ai_page_behavior', 'screen_files_panel_behavior', 'ses_boxes_behavior', 'files_search_behavior', 'mini_preview_behavior')
JS_GROUPS += ('desktop_workspace_behavior', 'team_center_behavior', 'hoca_behavior', 'activity_strip_behavior', 'task_summary_behavior', 'harita_behavior')
JS_GROUPS += ('harita_wizard_behavior', 'voice_speech_highlight_behavior')
JS_GROUPS += ('persona_preferences_behavior',)
SMOKE_GROUPS = ('headless_smoke', 'maintenance_smoke', 'voice_actions_smoke', 'paid_provider_smoke', 'developer_smoke', 'router_agents_smoke', 'stability_contracts')

def python_timeout():
    """Tam Python testleri için fail-closed üst sınır (sn).

    Windows'taki ~6.5k test geçici olarak eski 600 saniyelik tavana
    takılabiliyor; 900 sn sadece tamamlanma payıdır, PASS sayılmaz.
    JARVIS_VALIDATION_TIMEOUT ile aynı CI/gerçek PC watcher akışı yönetilir.
    """
    try:
        return max(60, int(os.environ.get('JARVIS_VALIDATION_TIMEOUT') or 900))
    except ValueError:
        return 900


def _record_failure(location):
    """This module's broad catches are recovery paths; each must leave a trace."""
    from modules import diagnostics
    diagnostics.record_failure(location)


def run_checks(root=None, *, python=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    executable = str(python or sys.executable)
    logs = []
    # TWO callers reach this suite on one PC: the updater installing a version and
    # the PC acceptance watcher testing an open PR. Both used to run at once and
    # fight over the speaker, microphone, resource claims and CPU, so a healthy
    # tree came back as a failure (issue 679). One machine-wide claim plus a
    # remembered PASS for the identical tree keeps the suite honest:
    #   * a tree that already passed does not sit the same exam again;
    #   * a second caller waits, and when it still cannot own the machine it says
    #     that no verdict exists instead of publishing a wrong one.
    # Failures are never remembered, so a red result is always re-earned.
    from modules import validation_lock
    key = None
    try:
        key = validation_lock.tree_digest(root, executable)
        remembered = validation_lock.cached_verdict(key)
    except Exception:            # noqa: BLE001 - cache is never a precondition to test
        _record_failure('modules/validation.py:cache_lookup')
        remembered = None
    if remembered is not None:
        return True, remembered + '\nAynı kaynak ağacı bu bilgisayarda daha önce doğrulandı; sınav tekrarlanmadı.'
    node = shutil.which('node')
    if not node:
        candidate = Path(os.environ.get('CODEX_PRIMARY_RUNTIME_NODE') or Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        node = str(candidate) if candidate.is_file() else None
    if not node:
        return False, 'Node.js bulunamadı. JavaScript kontrolleri zorunlu; doğrulama tamamlanmadı.'
    try:
        for folder in (root, root / 'modules', root / 'tests', root / 'scripts'):
            for file in sorted(folder.glob('*.py')):
                compile(file.read_bytes(), str(file), 'exec')
        required = [root / 'tests' / (n + '.js') for n in JS_GROUPS]
        required += [root / 'tests' / (n + '.py') for n in SMOKE_GROUPS]
        if not (root / 'tests').is_dir() or any(not f.is_file() for f in required):
            return False, 'Zorunlu test dosyaları eksik; doğrulama tamamlanmadı.'
        commands = [
            ('Architecture Guard', [executable, '-X', 'utf8', '-m', 'modules.architecture_guard']),
            ('Python testleri', [executable, '-X', 'utf8', '-W', 'ignore::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
        ]
        commands += [(str(f.relative_to(root)), [node, '--check', str(f)]) for f in sorted((root / 'webui').rglob('*.js'))]
        commands += [(n, [node, 'tests/' + n + '.js']) for n in JS_GROUPS]
        commands += [(n, [executable, '-X', 'utf8', 'tests/' + n + '.py']) for n in SMOKE_GROUPS]
        with validation_lock.only_one_run('release-suite', wait_seconds=900) as owned:
            if not owned:
                return False, ('Bu bilgisayarda başka bir doğrulama koşumu sürüyor; bu koşum için sonuç '
                               'üretilmedi (INCONCLUSIVE). Kod kusuru değildir.')
            return _run_commands(root, commands, executable, logs, key, bool(python))
    except (OSError, SyntaxError, subprocess.TimeoutExpired) as exc:
        return False, '\n'.join(logs)[-12000:] + '\nDoğrulama tamamlanmadı: ' + str(exc)


def _run_commands(root, commands, executable, logs, key, drop_pythonpath):
    try:
        with guard.temporary_workspace('jarvis-validation-') as scratch:
            for index, (name, cmd) in enumerate(commands):
                env = os.environ.copy()
                env.pop('JARVIS_BOOT_MARKERS', None)
                env.pop('JARVIS_BOOT_ID', None)
                if drop_pythonpath: env.pop('PYTHONPATH', None)
                env['PYTHONUTF8'] = '1'
                env['PYTHONIOENCODING'] = 'utf-8'
                env['JARVIS_DATA_DIR'] = str(Path(scratch) / str(index))
                env['JARVIS_TEST_PYTHON'] = executable
                timeout = python_timeout() if name == 'Python testleri' else 90
                cp = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
                output = cp.stdout + cp.stderr
                logs.append(name + '\n' + output)
                if cp.returncode:
                    if name == 'Python testleri':
                        # Keep error names even when the test suite output is too long
                        # for the standard validation log tail.
                        from collections import Counter
                        failures = re.findall(r'^(?:FAIL|ERROR): (.+)$', output, re.MULTILINE)
                        modules = Counter()
                        for item in failures:
                            match = re.search(r'\((test_[A-Za-z0-9_]+)\.', item)
                            modules[match.group(1) if match else 'unclassified'] += 1
                        index = '\n'.join(
                            f'  {module}: {count}' for module, count in modules.most_common()
                        )
                        headline = (f'CI failure index: {len(failures)} cases in {len(modules)} test modules.\n'
                                    + index + '\nFirst failures:\n'
                                    + '\n'.join(failures[:20]))
                        # The first failure often identifies a shared root cause;
                        # include its traceback instead of only its name.
                        details = re.findall(
                            r'(?ms)^(?:FAIL|ERROR): .+?(?=^={10,}$|^Ran [0-9]+ tests|\Z)',
                            output,
                        )
                        examples = {}
                        for part in details:
                            match = re.search(r'\((test_[A-Za-z0-9_]+)\.', part)
                            key = match.group(1) if match else 'unclassified'
                            examples.setdefault(key, part)
                        # One representative traceback per failure-heavy module
                        # is much more useful than six copies of one broken
                        # legacy test fixture. The full suite still fails.
                        selected = [module for module, _count in modules.most_common(15)]
                        first_traces = '\n'.join(
                            examples[module][:1900] for module in selected
                            if module in examples
                        )
                        return False, (headline + '\nRepresentative failure tracebacks:\n'
                                       + first_traces + '\nLast failure details:\n'
                                       + output[-12000:])
                    return False, '\n'.join(logs)[-16000:]
                if name == 'Python testleri':
                    count = re.search(r'Ran (\d+) tests?', output)
                    if not count or int(count[1]) == 0:
                        return False, 'Python testleri çalışmadı; doğrulama tamamlanmadı.\n' + output
        passed = '\n'.join(logs)[-16000:]
        if key is not None:
            # Only a real PASS is remembered; an identical tree cannot contain a new
            # regression, so re-running the same exam on this PC adds no evidence.
            try:
                validation_lock.remember_verdict(key, True, passed)
            except Exception:     # noqa: BLE001 - caching never decides the verdict
                _record_failure('modules/validation.py:cache_store')
        return True, passed
    except subprocess.TimeoutExpired as exc:
        # The old -q + discarded captured output concealed the offending test:
        # CI showed only "timed out after 600 seconds". Verbose unittest names
        # and the last printed test are diagnostic evidence, not a test PASS.
        def decoded(value):
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return value or ""
        partial = decoded(exc.stdout) + decoded(exc.stderr)
        return False, ('\n'.join(logs)[-3500:] + "\nLast test output before timeout:\n"
                       + partial[-10000:] + "\nDoğrulama tamamlanmadı: " + str(exc))
    except (OSError, SyntaxError) as exc:
        return False, '\n'.join(logs)[-12000:] + '\nDoğrulama tamamlanmadı: ' + str(exc)

if __name__ == '__main__':
    ok, log = run_checks()
    print(log)
    print('Tüm test grupları başarılı.' if ok else 'Doğrulama başarısız veya eksik.')
    sys.exit(0 if ok else 1)
