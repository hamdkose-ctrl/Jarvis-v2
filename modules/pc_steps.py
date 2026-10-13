"""Visible PC-control steps: wraps system_control so every real action is reported to the chat.

Only the listed actions are reported; every other attribute passes through unchanged.
A reporting failure never blocks or changes the action itself.
"""
from __future__ import annotations
import itertools
from modules.diagnostics import record_failure as _record_failure
import threading

_IDS = itertools.count(1)
_IDS_LOCK = threading.Lock()


def _media(action):
    return {'next': 'Sonraki parçaya geçiliyor', 'prev': 'Önceki parçaya dönülüyor'}.get(str(action), 'Medya oynat/duraklat gönderiliyor')


# name -> (label(args), success(result))
_ACTIONS = {
    'set_volume': (lambda level: f'Ses yüzde {max(0, min(100, int(level)))} yapılıyor', bool),
    'change_volume_by_delta': (lambda delta: 'Ses ' + ('artırılıyor' if int(delta) > 0 else 'kısılıyor'), lambda r: r is not None),
    'set_mute': (lambda on: 'Bilgisayarın sesi kapatılıyor' if on else 'Bilgisayarın sesi açılıyor', bool),
    'set_brightness': (lambda level: f'Ekran parlaklığı yüzde {max(0, min(100, int(level)))} yapılıyor', bool),
    'media_control': (_media, lambda r: r is not False),
    'open_application': (lambda name: f'“{name}” açılıyor', lambda r: getattr(r, 'ok', False) is True),
    'close_application': (lambda name: f'“{name}” kapatılıyor', lambda r: getattr(r, 'ok', False) is True),
    'shutdown_pc': (lambda: 'Bilgisayar 60 saniye sonra kapanacak şekilde zamanlanıyor', lambda r: True),
    'cancel_shutdown': (lambda: 'Zamanlanmış kapatma iptal ediliyor', lambda r: True),
    'window_action': (lambda target, action: f'“{target}” penceresi: {action}', lambda r: bool(isinstance(r, dict) and r.get('ok'))),
}


def _detail(result):
    if isinstance(result, dict):
        return str(result.get('message') or '')
    if isinstance(result, str):
        return result
    return ''


class ReportedControl:
    """system_control proxy; report(text, status, step_id, detail) publishes one step line."""

    def __init__(self, module, report):
        self._module = module
        self._report = report

    def _send(self, *args):
        try:
            self._report(*args)
        except Exception:  # noqa: BLE001 - the action must not depend on the screen
            _record_failure('modules/pc_steps.py:report')

    def __getattr__(self, name):
        target = getattr(self._module, name)
        spec = _ACTIONS.get(name)
        if spec is None or not callable(target):
            return target
        label_of, ok_of = spec

        def reported(*args, **kwargs):
            try:
                label = label_of(*args, **kwargs)
            except Exception:  # noqa: BLE001 - unusual arguments still run the real action
                _record_failure('modules/pc_steps.py:label')
                label = name
            with _IDS_LOCK:
                step_id = f's{next(_IDS)}'
            self._send(label, 'working', step_id, '')
            try:
                result = target(*args, **kwargs)
            except Exception:
                _record_failure('modules/pc_steps.py:action')
                self._send(label, 'error', step_id, 'İşlem hata verdi.')
                raise
            self._send(label, 'done' if ok_of(result) else 'error', step_id, _detail(result)[:300])
            return result

        return reported
