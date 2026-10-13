"""Independent startup supervisor. Run this instead of gui.py for automatic recovery."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import release_guard as guard
from release_guard import _record_failure

ROOT = Path(__file__).resolve().parent
BOOT_TIMEOUT = 120
STABLE_SECONDS = 5
DEPENDENCY_TIMEOUT = 30
# Read-only import check; run_tests.bat reuses it without recovery or cleanup.
DEPENDENCY_IMPORTS = 'import psutil; from google import genai; import speech_recognition, sounddevice, requests'


def check_installation(project=ROOT, fallback=None):
    """Recover before dependency imports; keep Windows automatic repair support."""
    project = Path(project).resolve()
    guard.recover(project)
    if guard.pending(project):
        # A candidate must be supervised/rolled back, never repaired in place.
        return 0
    executable = guard.current_python(project, fallback or sys.executable)
    try:
        result = subprocess.run([executable, '-c', DEPENDENCY_IMPORTS],
            cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=DEPENDENCY_TIMEOUT)
    except subprocess.TimeoutExpired:
        _record_failure('launcher.py:dependency_timeout')
        print('Bağımlılık kontrolü süre sınırını aştı; açılış durduruldu.')
        return 2
    if result.returncode:
        return 2
    return subprocess.call([executable, str(project / 'scripts' / 'kurulum_temizligi.py')], cwd=project)


def _markers_ready(markers, ident):
    try:
        return all((Path(markers) / name).read_text(encoding="utf-8") == ident for name in ('engine', 'web'))
    except OSError:
        # The engine may remove its marker between readiness and a read.
        return False


def _stop_child(child):
    """Do not leave a candidate writing files when shutdown is interrupted."""
    if child.poll() is not None:
        return
    try:
        child.terminate()
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        child.wait(timeout=10)


def supervise(project=ROOT, fallback=None, *, timeout=BOOT_TIMEOUT, stable=STABLE_SECONDS):
    project = Path(project).resolve()
    guard.recover(project)
    item = guard.pending(project)
    executable = guard.current_python(project, fallback or sys.executable)
    if not item:
        return subprocess.call([executable, str(project / 'gui.py')], cwd=project)
    if item['status'] != 'awaiting_start':
        raise RuntimeError('Geliştirme işlemi tamamlanmamış; yedek korunuyor.')
    with tempfile.TemporaryDirectory(prefix='jarvis-boot-') as markers:
        env = os.environ.copy()
        env.update(JARVIS_BOOT_MARKERS=markers, JARVIS_BOOT_ID=item['id'])
        try:
            child = subprocess.Popen([executable, str(project / 'gui.py'), '--guncellemesiz'], cwd=project, env=env)
        except OSError:
            _record_failure('launcher.py:candidate_start')
            child = None
        if child is not None:
            deadline = time.monotonic() + timeout
            healthy_since = None
            try:
                while child.poll() is None and time.monotonic() < deadline:
                    healthy = _markers_ready(markers, item['id'])
                    if healthy:
                        healthy_since = healthy_since or time.monotonic()
                        if time.monotonic() - healthy_since >= stable:
                            guard.confirm(project, item)
                            return child.wait()
                    else: healthy_since = None
                    time.sleep(0.1)
                if child.poll() is None:
                    _stop_child(child)
            except BaseException:
                _stop_child(child)
                raise
    guard.restore(project, item)
    print('Yeni sürüm sağlıklı açılmadı; önceki kaynaklar ve Python ortamı geri yüklendi.')
    executable = guard.current_python(project, fallback or sys.executable)
    return subprocess.call([executable, str(project / 'gui.py'), '--guncellemesiz'], cwd=project)


if __name__ == '__main__':
    try:
        sys.exit(check_installation() if '--check-installation' in sys.argv[1:] else supervise())
    except Exception as exc:
        _record_failure('launcher.py:startup')
        print('Güvenli başlatma durduruldu; yedek korundu:', type(exc).__name__, str(exc))
        sys.exit(1)
