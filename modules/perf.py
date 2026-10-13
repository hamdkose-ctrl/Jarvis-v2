"""Performans günlüğü: Jarvis'in kendi CPU/RAM kullanımını ve hangi iş parçacığının (thread) yorduğunu log'a yazar.

Her 5 dakikada bir tek satır: işlemci, bellek, iş parçacığı sayısı. İşlemci yüksekse (varsayılan %35) her dakika,
en çok çalışan 3 iş parçacığının adıyla birlikte yazar. Böylece "Jarvis yavaş" şikâyetinde log'dan neyin yorduğu görülür.
Davranışı değiştirmez; maliyeti dakikada bir kısa ölçümdür.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import logging
import os
import threading
import time

log = logging.getLogger("jarvis")

HIGH_CPU = 35.0        # % (tek çekirdek = 100): üstünde dakikada bir ayrıntı yazılır
CALM_EVERY = 300       # sn: sakin zamanlarda özet satırı aralığı
CHECK_EVERY = 60       # sn


def _names() -> dict[int, str]:
    return {t.native_id: t.name for t in threading.enumerate() if t.native_id}


def _loop(stop: threading.Event) -> None:
    try:
        import psutil
    except ImportError:
        return
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)
    last_threads = {t.id: t.user_time + t.system_time for t in proc.threads()}
    last_t = time.monotonic()
    last_calm = 0.0
    while not stop.wait(CHECK_EVERY):
        try:
            now = time.monotonic()
            cpu = proc.cpu_percent(None)
            rss = proc.memory_info().rss / 1048576
            threads = proc.threads()
            dt = max(now - last_t, 1.0)
            per = sorted(((t.user_time + t.system_time - last_threads.get(t.id, 0.0)) / dt * 100, t.id) for t in threads)
            last_threads = {t.id: t.user_time + t.system_time for t in threads}
            last_t = now
            if cpu >= HIGH_CPU:
                names = _names()
                top = ", ".join(f"{names.get(tid, 'tid%d' % tid)} %{pct:.0f}" for pct, tid in reversed(per[-3:]) if pct >= 1)
                log.info("Performans: CPU %%%.0f, RAM %.0f MB, %d iş parçacığı | en çok çalışan: %s",
                         cpu, rss, len(threads), top or "-")
                last_calm = now
            elif now - last_calm >= CALM_EVERY:
                log.info("Performans: CPU %%%.0f, RAM %.0f MB, %d iş parçacığı", cpu, rss, len(threads))
                last_calm = now
        except Exception:                       # noqa: BLE001  ölçüm hiçbir zaman Jarvis'i bozmasın
            _record_failure('modules/perf.py:_loop')


def start(stop: threading.Event) -> None:
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="performans-olcum").start()
