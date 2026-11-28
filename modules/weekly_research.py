"""Haftalık araştırma turu: isteği kurup kuyruğa cron'lu iş olarak yazar (B4-3).

Araştırma isteği ve kanıt bağlamı `research_providers` içinde duruyordu ama hiçbir
çağıranı yoktu. Burada haftalık tur, tek bir yerde kurulup mevcut görev kuyruğuna
yazılıyor; ayrı zamanlayıcı uydurulmuyor.
"""
from __future__ import annotations

from modules import research_providers, task_queue

WEEKLY_CRON = '0 9 * * 1'
WEEKLY_LABEL = 'Her pazartesi 09:00'


def plan(topic: str) -> list[dict]:
    """Haftalık turun görev listesi: araştır, sonra rapora yaz."""
    istek = research_providers.weekly_research_request(topic)
    return [
        {'id': 'arastir', 'agent': 'research', 'input': {'query': istek['query']}},
        {'id': 'rapor', 'agent': 'writer', 'depends': ['arastir'],
         'input': {'instruction': 'Haftalık araştırma özeti: ' + topic,
                   'filename': 'haftalik-arastirma.md'}},
    ]


def schedule(owner: str, topic: str) -> dict:
    """Turu kuyruğa haftalık cron ile yazar; kimlik ve kadansı geri döndürür."""
    istek = research_providers.weekly_research_request(topic)
    kimlik = task_queue.enqueue(owner, plan(topic),
                                'Haftalık araştırma turu: ' + topic,
                                cron=WEEKLY_CRON)
    return {'id': kimlik, 'cron': WEEKLY_CRON, 'label': WEEKLY_LABEL,
            'window_days': istek['window_days'], 'topic': topic}
