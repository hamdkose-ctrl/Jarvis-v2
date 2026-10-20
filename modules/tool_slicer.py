"""Yerel PrusaSlicer adaptörü; indirme, kabuk veya sessiz yedek yol yoktur."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import threading

from modules import llm, permission_audit, permission_gate, permission_policy, service_store
from modules.diagnostics import record_failure as _diagnostic_failure


def _record_failure(context):
    try:
        raise RuntimeError('Yerel araç işlemi tamamlanamadı.') from None
    except RuntimeError:
        _diagnostic_failure(context)


class _LocalTool:
    """Sabit CLI seçenekleri; her örneğin çalışan işleri kullanıcıya özeldir."""
    def __init__(self, ident, name, programs, inputs, output, arguments):
        self.ident, self.name, self.programs = ident, name, programs
        self.inputs, self.output, self.arguments = inputs, output, arguments
        self.jobs = {}
        self.lock = threading.RLock()

    def executable(self):
        return next((path for name in self.programs if (path := shutil.which(name))), None)

    def status(self):
        owner = llm._key_context.get()
        if not owner:
            return {'state': 'not_connected', 'detail': 'Kullanıcı seçilmedi.'}
        try:
            service_store.identity(owner)
            with self.lock:
                if owner in self.jobs:
                    return {'state': 'running', 'detail': self.name + ' yerel işi sürüyor.'}
            if not self.executable():
                return {'state': 'not_connected', 'detail': self.name + ' kurulu değil.'}
            return {'state': 'ready', 'detail': self.name + ' komutu mevcut; gerçek PC sınanmadı.'}
        except Exception:
            _record_failure('modules/tool_slicer.py:status')
            return {'state': 'error', 'detail': 'Yerel araç durumu okunamadı.'}

    def decision(self, owner, action_class, target):
        service_store.identity(owner)
        result = permission_gate.decide({'class': action_class, 'via': 'file', 'target': target})
        decision, reason = permission_policy.apply(owner, self.ident, action_class, result['decision'], result['reason'])
        if decision not in ('allow', 'ask', 'deny'):
            raise ValueError('Geçersiz izin kararı.')
        permission_audit.record(owner, decision, action_class, self.ident, 'file', reason)
        return decision

    def run(self, owner, source, destination, *, approve=False):
        process = None
        try:
            if not isinstance(approve, bool):
                raise ValueError('Geçersiz onay.')
            decision = self.decision(owner, 'local_destructive', self.ident)
            if decision == 'deny':
                return {'state': 'blocked', 'detail': 'Politika bu yerel işlemi engelliyor.'}
            executable = self.executable()
            if not executable:
                return {'state': 'not_connected', 'detail': self.name + ' kurulu değil.'}
            if decision == 'ask' and not approve:
                return {'state': 'approval', 'detail': 'Seçilen dosyadan yeni çıktı üretmek için onay gerekli.'}
            if not isinstance(source, str) or not isinstance(destination, str):
                raise ValueError('Açık kaynak ve çıktı yolları gerekli.')
            source, destination = Path(source).absolute(), Path(destination).absolute()
            for path in (source, destination):
                if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
                    raise ValueError('Dosya yolu sembolik bağ olamaz.')
            if (not source.is_file() or source.suffix.lower() not in self.inputs
                    or destination.suffix.lower() != self.output or destination.exists()
                    or not destination.parent.is_dir()):
                raise ValueError('Kaynak/çıktı geçersiz veya çıktı zaten mevcut.')
            with tempfile.TemporaryDirectory(prefix='.jarvis-tool-', dir=destination.parent) as temporary:
                output = Path(temporary) / ('output' + self.output)
                argv = [executable, *self.arguments(str(source), str(output))]
                with self.lock:
                    if owner in self.jobs:
                        raise ValueError('Bu kullanıcının aracı zaten çalışıyor.')
                    process = subprocess.Popen(argv, shell=False, cwd=temporary, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.jobs[owner] = process
                try:
                    process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
                    return {'state': 'error', 'detail': 'Yerel araç zaman aşımında durduruldu; çıktı yayımlanmadı.'}
                if process.returncode != 0:
                    return {'state': 'error', 'detail': 'Yerel araç başarı bildirmedi; çıktı yayımlanmadı.'}
                if not output.is_file() or output.is_symlink() or not 0 < output.stat().st_size <= 100_000_000:
                    raise ValueError('Yerel araç geçerli çıktı üretmedi.')
                # Atomic no-clobber publication; a concurrently created target survives.
                os.link(output, destination)
            return {'state': 'done', 'detail': 'Yerel komut sıfır koduyla bitti ve yeni çıktı dosyası doğrulandı.'}
        except Exception:
            _record_failure('modules/tool_slicer.py:run')
            try:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
            except Exception:
                _record_failure('modules/tool_slicer.py:cleanup')
            return {'state': 'blocked', 'detail': 'Yerel işlem tamamlanamadı; mevcut dosyaların üzerine yazılmadı.'}
        finally:
            if process is not None:
                with self.lock:
                    if self.jobs.get(owner) is process:
                        self.jobs.pop(owner)

    def cancel(self):
        owner = llm._key_context.get()
        try:
            if self.decision(owner, 'local_reversible', self.ident) != 'allow':
                return {'cancelled': False, 'detail': 'İptal izni verilmedi.'}
            with self.lock:
                process = self.jobs.get(owner)
                if process is None or process.poll() is not None:
                    return {'cancelled': False, 'detail': 'Bu kullanıcı için çalışan yerel iş yok.'}
                process.terminate()
            return {'cancelled': True, 'detail': 'Yerel sürece durdurma iletildi; çıkış henüz doğrulanmadı.'}
        except Exception:
            _record_failure('modules/tool_slicer.py:cancel')
            return {'cancelled': False, 'detail': 'Yerel işin iptali doğrulanamadı.'}

    def contract(self, icon):
        return {'id': self.ident, 'name': self.name, 'area': 'cihaz', 'icon': icon,
                'actions': [{'id': 'run', 'name': 'Yeni çıktı üret', 'desc': 'Seçilen yerel dosyadan yeni dosya üretir; üzerine yazmaz.',
                             'class': 'local_destructive', 'params': {'source': 'str', 'destination': 'str'}},
                            {'id': 'cancel', 'name': 'Yerel işi iptal et', 'desc': 'Yalnız bu kullanıcının çalışan yerel sürecine durdurma iletir.',
                             'class': 'local_reversible', 'params': {}}],
                'status': self.status, 'cancel': self.cancel}


_TOOL = _LocalTool('slicer', 'PrusaSlicer', ('prusa-slicer', 'PrusaSlicer'), {'.stl', '.3mf', '.obj'}, '.gcode',
                   lambda source, output: ['--export-gcode', '--output', output, source])
run, status, cancel = _TOOL.run, _TOOL.status, _TOOL.cancel
CONTRACT = _TOOL.contract('layers')
