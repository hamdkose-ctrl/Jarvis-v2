"""Windows UI Automation adapter: visible native controls, never guessed coordinates."""
from __future__ import annotations
import atexit
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from modules import requests_state

SCRIPT = Path(__file__).with_name('desktop_uia.ps1')
NEWLINE = bytes([10])


class NotSent(ValueError):
    """The adapter can prove that no interaction was attempted."""


class WindowMissing(NotSent):
    pass


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class _Worker:
    """Tek bir uzun ömürlü PowerShell süreci: her istek bir satır JSON, her yanıt bir satır JSON.
    Süreç ve UIA derlemeleri her okumada yeniden yüklenmez; zaman aşımı, iptal veya hata olursa süreç öldürülür."""

    def __init__(self):
        self.lines = queue.Queue()
        self.process = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SCRIPT.read_text(encoding='utf-8')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def alive(self):
        return self.process.poll() is None

    def kill(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(2)
        except (OSError, subprocess.TimeoutExpired):
            pass   # süreç zaten kapanmış ya da kapanmıyor; yenisi başlatılacak


_worker = None
_lock = threading.Lock()


def shutdown():
    global _worker
    with _lock:
        if _worker:
            _worker.kill()
        _worker = None


atexit.register(shutdown)


def _call(payload):
    global _worker
    if os.name != 'nt':
        raise ValueError('Masaüstü görevleri Windows üzerinde çalışır.')
    requests_state.check()
    request = json.dumps(payload, ensure_ascii=False).encode('utf-8') + NEWLINE   # json.dumps satır sonlarını kaçırır; istek tek satırdır
    with _lock:
        if not _worker or not _worker.alive():
            _worker = _Worker()
        worker = _worker
        try:
            worker.process.stdin.write(request); worker.process.stdin.flush()
            deadline = time.monotonic() + 20
            while True:
                requests_state.check()
                if time.monotonic() >= deadline:
                    raise ValueError('Windows kontrol okuması süre sınırını aştı; işlem sonucu belirsiz.')
                try:
                    output = worker.lines.get(timeout=.2)
                    break
                except queue.Empty:
                    continue
        except BaseException:
            worker.kill(); _worker = None   # yanıtı belirsiz süreç yeniden kullanılmaz
            raise
        if output is None:
            _worker = None
    requests_state.check()
    try:
        data = json.loads((output or b'').decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise ValueError('Windows kontrollerini okuyamadım; işlem doğrulanmadı.') from None
    if not isinstance(data, dict):
        raise ValueError('Windows kontrol yanıtı geçersiz.')
    if not data.get('ok'):
        error = NotSent if data.get('sent') is False else ValueError
        raise error(str(data.get('message') or 'Windows işlemi tamamlanamadı.')[:500])
    return data


class DesktopUI:
    def observe(self, target, hwnd=None):
        from modules import system_control as pc
        windows = pc._app_windows()
        matches = [w for w in windows if w[0] == hwnd] if hwnd else pc._select_window(target, windows)
        if not matches:
            raise WindowMissing('Hedef pencere açık değil: ' + target)
        matches = list({w[0]: w for w in matches}.values())
        if len(matches) > 1 and hwnd is None:
            foreground = pc._window_api().GetForegroundWindow()
            active = [w for w in matches if w[0] == foreground]
            if len(active) == 1:
                matches = active
        if len(matches) != 1:
            choices = '; '.join(title for _, title, _ in matches[:8])
            raise ValueError('Birden fazla hedef pencere var. Kullanmak istediğini öne getirip “PC görevi devam” de.' + (' Seçenekler: '+choices if choices else ''))
        handle, title, app = matches[0]
        result = _call({'op': 'observe', 'hwnd': handle})
        return {'hwnd': handle, 'title': title, 'app': result.get('app', app), 'pid': result['pid'],
                'app_pid': result.get('app_pid', result['pid']), 'controls': result['controls']}

    def act(self, snapshot, action):
        # Native UIA patterns address an element directly; no global input is sent.
        # Foreground activation is neither necessary nor reliable under Windows.
        fresh = self.observe(snapshot['title'], snapshot['hwnd'])
        if digest(fresh) != digest(snapshot):
            raise NotSent('Pencere veya kontroller değişti; eski hedefte işlem yapmadım.')
        target = next((c for c in fresh['controls'] if c['id'] == action['control']), None)
        if not target:
            raise NotSent('İşlem hedefi artık görünür değil.')
        result = _call({'op': action['op'], 'hwnd': fresh['hwnd'], 'pid': fresh['pid'],
                        'app': fresh['app'], 'app_pid': fresh.get('app_pid', fresh['pid']), 'target': target,
                        'value': action.get('value', '')})
        return result
