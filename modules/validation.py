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
JS_GROUPS += ('harita_wizard_behavior',)
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
        commands = [('Python testleri', [executable, '-X', 'utf8', '-W', 'ignore::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests', '-q'])]
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
                cp = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=python_timeout() if index == 0 else 90)
                output = cp.stdout + cp.stderr
                logs.append(name + '\n' + output)
                if cp.returncode:
                    return False, '\n'.join(logs)[-16000:]
                if index == 0:
                    count = re.search(r'Ran (\d+) tests?', output)
                    if not count or int(count[1]) == 0:
                        return False, 'Python testleri çalışmadı; doğrulama tamamlanmadı.\n' + output
        return True, '\n'.join(logs)[-16000:]
    except (OSError, SyntaxError, subprocess.TimeoutExpired) as exc:
        return False, '\n'.join(logs)[-12000:] + '\nDoğrulama tamamlanmadı: ' + str(exc)

if __name__ == '__main__':
    ok, log = run_checks()
    print(log)
    print('Tüm test grupları başarılı.' if ok else 'Doğrulama başarısız veya eksik.')
    sys.exit(0 if ok else 1)

