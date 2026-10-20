"""Saf araç sözleşmesi doğrulama, keşif ve JSON-uyumlu açıklama yardımcıları."""
from __future__ import annotations

import copy
import importlib
import pkgutil
import re

from modules.diagnostics import record_failure as _record_failure
from modules.permission_gate import CLASSES

_ID = re.compile(r"[a-z0-9_-]{1,40}\Z")
_PARAM_TYPES = frozenset({'str', 'int', 'float', 'bool'})
_STATUS_STATES = frozenset({'ready', 'not_connected', 'running', 'error'})
_MAX_TEXT = 200


def _error(errors: list[str], message: str) -> None:
    if len(errors) < 100:
        errors.append(message[:_MAX_TEXT])


def _text_limits(value, path: str, errors: list[str], seen: set[int]) -> None:
    """Sözleşmedeki metin değer/anahtarlarını döngüye girmeden sınırlar."""
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            _error(errors, f'{path} metni 200 karakteri geçemez.')
        return
    if callable(value) or value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, (dict, list, tuple)):
        ident = id(value)
        if ident in seen:
            _error(errors, f'{path} döngüsel yapı içeremez.')
            return
        seen.add(ident)
        try:
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(key, str) and len(key) > _MAX_TEXT:
                        _error(errors, f'{path} anahtarı 200 karakteri geçemez.')
                    _text_limits(item, f'{path}.{key}', errors, seen)
            else:
                for index, item in enumerate(value):
                    _text_limits(item, f'{path}[{index}]', errors, seen)
        finally:
            seen.remove(ident)


def validate(contract) -> list[str]:
    """CONTRACT sözlüğünü doğrular; hiçbir bozuk girdide istisna dışarı taşımaz."""
    errors: list[str] = []
    try:
        if not isinstance(contract, dict):
            return ['Sözleşme sözlük olmalı.']

        ident = contract.get('id')
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            _error(errors, 'id yalnız küçük harf, rakam, _ ve - içeren en fazla 40 karakter olmalı.')

        name = contract.get('name')
        if not isinstance(name, str) or not name.strip():
            _error(errors, 'name boş olmayan metin olmalı.')

        actions = contract.get('actions')
        if not isinstance(actions, list) or not actions:
            _error(errors, 'actions en az bir eylem içeren liste olmalı.')
        else:
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    _error(errors, f'actions[{index}] sözlük olmalı.')
                    continue
                action_class = action.get('class')
                if action_class not in CLASSES:
                    _error(errors, f'actions[{index}].class izin verilen sınıflardan biri olmalı.')
                params = action.get('params')
                if not isinstance(params, dict):
                    _error(errors, f'actions[{index}].params sözlük olmalı.')
                else:
                    for key, kind in params.items():
                        if not isinstance(key, str) or not key:
                            _error(errors, f'actions[{index}].params anahtarları boş olmayan metin olmalı.')
                        if kind not in _PARAM_TYPES:
                            _error(errors, f'actions[{index}].params yalnız str|int|float|bool kullanabilir.')

        if not callable(contract.get('status')):
            _error(errors, 'status çağrılabilir olmalı.')
        if not callable(contract.get('cancel')):
            _error(errors, 'cancel çağrılabilir olmalı.')

        _text_limits(contract, 'contract', errors, set())
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
        _error(errors, 'Sözleşme doğrulanamadı.')
    return errors


def _failure(context: str, reason: str) -> None:
    """record_failure'ın güvenli neden yakalaması için nedeni aktif istisna içinde kaydeder."""
    try:
        raise ValueError(reason[:1000])
    except ValueError:
        _record_failure(context)


def load_all(package: str = 'modules', prefix: str = 'tool_') -> dict[str, dict]:
    """Paket altındaki tool_* modüllerini yükler; bozuk araçlar diğerlerini etkilemez."""
    if not isinstance(package, str) or not package.strip() or not isinstance(prefix, str) or not prefix:
        return {}
    try:
        root = importlib.import_module(package)
        paths = getattr(root, '__path__', None)
        if paths is None:
            raise ValueError('Araç paketi dizin paketi değil.')
    except Exception as exc:
        _record_failure('modules/tool_contract.py:load_all:package')
        return {}

    grouped: dict[str, list[tuple[str, dict]]] = {}
    own_name = __name__.rsplit('.', 1)[-1]
    try:
        discovered = sorted(pkgutil.iter_modules(paths), key=lambda item: item.name)
    except Exception as exc:
        _record_failure('modules/tool_contract.py:load_all:discover')
        return {}

    for info in discovered:
        short = info.name
        if not short.startswith(prefix):
            continue
        if package == __package__ and short in (own_name, 'tool_map', 'tool_wizard'):
            continue
        module_name = f'{package}.{short}'
        try:
            module = importlib.import_module(module_name)
            contract = getattr(module, 'CONTRACT')
            errors = validate(contract)
            if errors:
                raise ValueError('; '.join(errors))
            grouped.setdefault(contract['id'], []).append((module_name, contract))
        except Exception as exc:
            _record_failure(f'modules/tool_contract.py:load_all:{short}')

    if package == __package__ and prefix == 'tool_':
        try:
            from modules import llm, tool_wizard
            owner = llm._key_context.get()
            if owner:
                generated = tool_wizard.contracts(owner)
                for ident, contract in generated.items():
                    errors = validate(contract)
                    if errors or ident != contract['id']:
                        raise ValueError('Kullanıcı araç sözleşmesi geçersiz.')
                for ident, contract in generated.items():
                    grouped.setdefault(ident, []).append(('modules.tool_wizard', contract))
        except Exception:
            _record_failure('modules/tool_contract.py:load_all:wizard')

    loaded: dict[str, dict] = {}
    for ident, rows in grouped.items():
        if len(rows) != 1:
            for module_name, _contract in rows:
                short = module_name.rsplit('.', 1)[-1]
                _failure(f'modules/tool_contract.py:load_all:{short}', f'Aynı araç id birden fazla dosyada kullanılmış: {ident}')
            continue
        loaded[ident] = rows[0][1]
    return loaded


def _safe_status(status_callable) -> dict:
    try:
        result = status_callable()
        if (not isinstance(result, dict)
                or result.get('state') not in _STATUS_STATES
                or not isinstance(result.get('detail'), str)
                or len(result['detail']) > _MAX_TEXT):
            raise ValueError('Geçersiz araç durumu.')
        return {'state': result['state'], 'detail': result['detail']}
    except Exception:
        _record_failure('modules/tool_contract.py:status')
        return {'state': 'error', 'detail': 'Araç durumu alınamadı.'}


def describe(contract) -> dict:
    """Çağrılabilir alanları çıkartıp status sonucunu ekleyen JSON-uyumlu kopya üretir."""
    errors = validate(contract)
    if errors:
        raise ValueError('; '.join(errors))
    result = {}
    for key, value in contract.items():
        if key in {'status', 'cancel'}:
            continue
        result[key] = copy.deepcopy(value)
    result['status'] = _safe_status(contract['status'])
    return result
