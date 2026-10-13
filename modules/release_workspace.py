"""Build/test a candidate without mutating the installed sources or environment."""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import release_guard as guard

DEPENDENCY_FILES = {'requirements.txt', 'requirements.lock.txt', 'requirements-browser.txt', 'requirements-bundle.txt'}


def changed_environment(root, changed, project):
    changed_names = {Path(name).as_posix().casefold() for name in changed}
    if not DEPENDENCY_FILES.intersection(changed_names): return None
    # A fresh venv is installed from the complete candidate lock; original .venv is untouched.
    lock = root / 'requirements.lock.txt'
    if not lock.is_file(): raise ValueError('Bağımlılık değişikliğinde tam requirements.lock.txt gerekli.')
    if 'requirements.txt' in changed_names and 'requirements.lock.txt' not in changed_names:
        raise ValueError('requirements.txt değişikliğiyle birlikte sürüm kilidini de güncelle.')
    folder = guard.store(project) / 'environments' / uuid.uuid4().hex
    python = guard.environment_python(folder)
    try:
        subprocess.run([sys.executable, '-m', 'venv', str(folder)], check=True, capture_output=True, timeout=120)
        command = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(lock)]
        if (root / 'requirements.txt').is_file():
            command += ['-r', str(root / 'requirements.txt')]
        if (root / 'requirements-bundle.txt').is_file():
            command += ['-r', str(root / 'requirements-bundle.txt')]
        elif (root / 'requirements-browser.txt').is_file():
            command += ['-r', str(root / 'requirements-browser.txt')]
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=600)
        if result.returncode: raise RuntimeError('Yeni bağımlılıklar kurulamadı; mevcut ortam değiştirilmedi.')
        return str(python)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@contextmanager
def candidate(project, changes, *, allow_protected=False):
    with guard.temporary_workspace('jarvis-candidate-') as folder:
        root = Path(folder) / 'project'
        guard.copy_source(project, root)
        for name, content in changes.items():
            if guard.protected_source(name) and not allow_protected:
                raise ValueError('Kurtarma/test altyapısı otomatik geliştirmede değiştirilemez: ' + name)
            path = guard.safe_path(root, name)
            if content is None: path.unlink(missing_ok=True)
            else: guard.atomic(path, content)
        yield root


def validate(root, project, python=None):
    from modules.validation import run_checks
    root, project = Path(root), Path(project)
    def run(target):
        return run_checks(target, python=python) if python else run_checks(target)
    # Test edits cannot silently remove the current regression coverage.
    with guard.temporary_workspace('jarvis-trusted-tests-') as temporary:
        baseline = Path(temporary) / 'project'
        guard.copy_source(root, baseline)
        shutil.rmtree(baseline / 'tests', ignore_errors=True)
        if (project / 'tests').is_dir():
            shutil.copytree(project / 'tests', baseline / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
        ok, log = run(baseline)
        if not ok: return False, log
    def manifest(folder):
        return {p.relative_to(folder).as_posix(): guard.digest(p.read_bytes())
                for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if manifest(root / 'tests') != manifest(project / 'tests'):
        return run(root)
    return True, log


def discard_environment(project, python):
    if not python: return
    folder = Path(python).parent.parent
    expected = (guard.store(project) / 'environments').resolve()
    if folder.parent.resolve() == expected:
        shutil.rmtree(folder, ignore_errors=True)
