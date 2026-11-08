"""Finans kaynaklarını canlı dener: her kaynağa bir istek, model çağrısı ve yazma yok.

Kullanım (Jarvis klasöründe): .venv\\Scripts\\python.exe -X utf8 scripts\\finans_kaynak_testi.py
Çıktı her kaynak için GEÇTİ/BAŞARISIZ ve okunan değeri gösterir; sonucu Claude'a yapıştırmak yeterli.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import finance  # noqa: E402

CHECKS = (
    ('TCMB today.xml (USD)', lambda: _tcmb()),
    ('Frankfurter (USD/TRY)', lambda: '{} TL, {}'.format(*finance._frankfurter('USD'))),
    ('BtcTurk BTC/TRY', lambda: _market('BTCTRY')),
    ('BtcTurk PAXG/TRY (gram altın)', lambda: _market('PAXGTRY')),
    ('CoinGecko BTC/TRY (yedek)', lambda: _market('BTCTRY', finance._coingecko)),
    ('CoinGecko PAXG/TRY (yedek)', lambda: _market('PAXGTRY', finance._coingecko)),
    ('Yahoo Finance THYAO.IS', lambda: _bist('THYAO')),
    ('Yahoo Finance XU100.IS', lambda: _bist('XU100')),
)
SAMPLE_REQUESTS = (
    ('USD/TRY', {'kind': 'rate', 'source': 'USD', 'target': 'TRY'}),
    ('EUR/TRY amount 100', {'kind': 'rate', 'amount': '100', 'source': 'EUR', 'target': 'TRY'}),
    ('BTC/TRY', {'kind': 'asset', 'asset': 'BTC', 'target': 'TRY'}),
    ('Gold gram/TRY', {'kind': 'asset', 'asset': 'GOLD', 'gold_kind': 'gram', 'target': 'TRY'}),
    ('THYAO', {'kind': 'stock', 'stock': 'THYAO'}),
    ('XU100', {'kind': 'stock', 'stock': 'XU100'}),
)


def _tcmb():
    table, label = finance._tcmb()
    return f'{table["USD"]} TL, {len(table)} para birimi, {label}'


def _market(pair, source=None):
    row = (source or finance._btcturk)(pair)
    return f'son {row["last"]}, günlük %{row["daily"]}, zaman {row["when"]}'


def _bist(code):
    row = finance._yahoo(code)
    return f'son {row["last"]} TRY, günlük %{row["daily"]}, zaman {row["when"]}'


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        try:
            print(f'GEÇTİ      {label}: {check()}')
        except Exception as exc:  # Kaynak hatası türü ve kısa nedeni teşhis için gösterilir.
            failed += 1
            print(f'BAŞARISIZ  {label}: {type(exc).__name__}: {str(exc)[:160]}')
    finance._CACHE.clear()
    for label, arguments in SAMPLE_REQUESTS:
        request = finance.request_from_slots(arguments)
        print(f'\n> {label}\n{finance.answer_request(request)}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
