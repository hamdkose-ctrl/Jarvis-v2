"""Read-only Finance CSV income/expense analysis."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
from pathlib import Path

from modules import requests_state, service_store, task_results


def _amount(value, separator='.'):
    if not isinstance(value, str) or separator not in ('.', ','):
        raise ValueError('Sayı biçimi geçersiz.')
    value = value.strip().replace(' ', '')
    if separator == ',':
        value = value.replace('.', '').replace(',', '.')
    elif ',' in value:
        raise ValueError('Ondalık virgüllü veri için decimal="," belirt.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Geçersiz sayısal hücre.') from None
    if not number.is_finite() or abs(number) > Decimal('1e18'):
        raise ValueError('Sayısal hücre sınır dışında.')
    return number


def csv_summary(owner, path, columns, decimal='.'):
    """Summarize a user-approved finance CSV without changing it."""
    service_store.identity(owner)
    from modules import nxapi
    original = Path(path)
    source = nxapi.allowed(path)
    if (not source or not source.is_file() or source.suffix.lower() != '.csv'
            or original.is_symlink() or any(parent.is_symlink() for parent in original.parents)
            or source.stat().st_size > 5_000_000):
        raise ValueError('Analiz için izinli kullanıcı alanında en fazla 5 MB CSV gerekli.')
    if not isinstance(columns, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                for key, value in columns.items()):
        raise ValueError('Sütun eşleştirmesi gerekli.')
    required, optional = {'amount', 'kind'}, {'date'}
    if not required.issubset(columns) or set(columns) - required - optional:
        raise ValueError('Analiz sütunları geçersiz.')
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('CSV UTF-8 olmalı; kodlama tahmin edilmedi.') from None
    first = text.splitlines()[0] if text.splitlines() else ''
    delimiter = ';' if first.count(';') > first.count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames or not set(columns.values()).issubset(reader.fieldnames):
        raise ValueError('Belirtilen sütun CSV başlığında yok.')
    income = expense = Decimal(0)
    count = 0
    for index, row in enumerate(reader, 2):
        requests_state.check()
        count += 1
        if count > 20_000:
            raise ValueError('CSV 20.000 satır sınırını aşıyor.')
        if None in row or any(row.get(name) is None for name in columns.values()):
            raise ValueError('CSV satırında eksik/fazla hücre: ' + str(index))
        try:
            amount = _amount(row[columns['amount']], decimal)
            if amount < 0:
                raise ValueError('Gelir/gider tutarı negatif olamaz; tür ayrı sütundadır.')
            label = row[columns['kind']].strip().casefold()
            if label in ('gelir', 'income'):
                income += amount
            elif label in ('gider', 'expense'):
                expense += amount
            else:
                raise ValueError('İşlem türü gelir/income veya gider/expense olmalı.')
        except ValueError as exc:
            raise ValueError('CSV satırı ' + str(index) + ': ' + str(exc)) from None
    if not count:
        raise ValueError('CSV veri satırı içermiyor.')
    if task_results.file_digest(source) != digest:
        raise ValueError('CSV analiz sırasında değişti.')
    return {'kind': 'finance', 'rows': count,
            'result': {'income': str(income), 'expense': str(expense), 'net': str(income - expense)},
            'columns': columns, 'decimal': decimal, 'source_file': str(source),
            'source_sha256': digest, 'source_unchanged': True,
            'scope': 'Yalnız sağlanan CSV; canlı banka/mağaza bağlantısı veya stok/sipariş değişikliği yapılmadı.'}
