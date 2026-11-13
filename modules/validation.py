"""One mandatory, isolated release suite for developer, GitHub and local checks."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import release_guard as guard

JS_GROUPS = ('desktop_flows', 'files_in_chat_behavior', 'chat_drop_behavior', 'mobile_behavior', 'continuity_behavior', 'fieldnotes_behavior', 'desktop_auth_behavior', 'paid_provider_behavior', 'developer_behavior', 'router_behavior', 'study_behavior', 'navigation_start_behavior', 'local_stt_behavior', 'menu_security_behavior', 'hologram_behavior', 'ai_page_behavior', 'menu_dock_behavior', 'screen_files_panel_behavior', 'menu_subs_behavior', 'ses_boxes_behavior', 'files_search_behavior', 'mini_preview_behavior', 'menu_tap_behavior')
JS_GROUPS += ('team_center_behavior', 'seljuk_backdrop_behavior', 'hoca_behavior', 'activity_strip_behavior', 'task_summary_behavior', 'harita_behavior')
JS_GROUPS += ('harita_wizard_behavior', 'voice_speech_highlight_behavior')
SMOKE_GROUPS = ('headless_smoke', 'maintenance_smoke', 'voice_actions_smoke', 'paid_provider_smoke', 'developer_smoke', 'router_agents_smoke', 'stability_contracts')

def python_timeout():
    """Tüm Python testleri için üst sınır (sn). Linux ~70 sn, Windows runner'da 180 sn'ye yaklaşıp düşüyordu;
    sınır hız ölçütü değil, takılma koruması. JARVIS_VALIDATION_TIMEOUT ile değişir."""
    try:
        return max(60, int(os.environ.get('JARVIS_VALIDATION_TIMEOUT') or 600))
    except ValueError:
        return 600


def run_checks(root=None, *, python=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    executable = str(python or sys.executable)
    logs = []
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
        with guard.temporary_workspace('jarvis-validation-') as scratch:
            for index, (name, cmd) in enumerate(commands):
                env = os.environ.copy()
                env.pop('JARVIS_BOOT_MARKERS', None)
                env.pop('JARVIS_BOOT_ID', None)
                if python: env.pop('PYTHONPATH', None)
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
                        first_traces = '\n'.join(part[:2500] for part in details[:6])
                        return False, (headline + '\nFirst failure tracebacks:\n'
                                       + first_traces + '\nLast failure details:\n'
                                       + output[-12000:])
                    return False, '\n'.join(logs)[-16000:]
                if name == 'Python testleri':
                    count = re.search(r'Ran (\d+) tests?', output)
                    if not count or int(count[1]) == 0:
                        return False, 'Python testleri çalışmadı; doğrulama tamamlanmadı.\n' + output
        return True, '\n'.join(logs)[-16000:]
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
