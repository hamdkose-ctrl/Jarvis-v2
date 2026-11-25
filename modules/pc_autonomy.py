"""Sınırlı otonomi: çok adımlı işi **kendi başına** yürütür, sonunda hesap verir.

Neden "sınırlı": kullanıcı uyurken değil, görev verildiğinde çalışır. Kurallar
kullanıcı politikasıyla aynı, ama artık **yazılı**:

- Bütçe: en çok `MAX_STEPS` adım, `MAX_SECONDS` saniye, adım başına en çok `MAX_TRIES`
  deneme. Bütçe biterse "bitti" denmez; **nerede kaldığı** söylenir.
- Riskli adım (silme/ödeme/gönderme) gelirse otonomi **durur**: onay istenir, kalan
  adımlar çalışmaz. Onay yoksa iş yarım kalır — bu bir kusur değil, tasarımdır.
- Her çalışma **rapor** üretir: adım adım ne yapıldı, hangi kademe çözdü (UIA/klavye/
  OCR), ne kadar sürdü, nerede durdu. Rapor `~/.jarvis/autonomy/` altına yazılır.
- `abort` (Esc) her adımda kontrol edilir.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from modules import pc_task
from modules.diagnostics import record_failure as _record_failure

MAX_STEPS = 6
MAX_SECONDS = 120.0
MAX_TRIES = 2
REPORT_DIR = Path.home() / ".jarvis" / "autonomy"
BUDGET_MSG = "{limit} sınırına ulaştım; {done} adım tamamlandı, kalanı yapmadım."
ASK_MSG = "“{step}” adımı onay istiyor; otonomiyi durdurdum. Onay verirsen devam ederim."


def execute(command: str, *, abort=None, budget: "Budget" = None) -> dict:
    """Komutu sınırlı otonomiyle yürütür ve rapor döndürür."""
    plan = pc_task.plan(command)
    if plan["status"] != "ok":
        return _finish({"status": plan["status"], "text": plan["text"], "steps": [], "command": command})
    budget = budget or Budget()
    steps, started = [], time.time()
    for text, intent, args in plan["steps"]:
        if abort is not None and abort.is_set():
            return _finish({"status": "stopped", "text": "Durduruldu.", "steps": steps, "command": command})
        if not budget.can_step() or time.time() - started > MAX_SECONDS:
            return _finish({"status": "budget",
                            "text": BUDGET_MSG.format(limit=f"{int(MAX_SECONDS)} sn / {MAX_STEPS} adım",
                                                      done=len(steps)),
                            "steps": steps, "command": command})
        tick = time.time()
        result = pc_task.pc_hands.attempt(lambda: pc_task._RUNNERS[intent](args),
                                          window=str(args.get("window") or ""), abort=abort)
        status = result.get("status")
        steps.append({"step": text, "intent": intent, "status": status,
                      "ms": int((time.time() - tick) * 1000), "text": result.get("text", "")[:160]})
        if status == "needs_confirmation":
            return _finish({"status": "paused", "text": ASK_MSG.format(step=text), "steps": steps,
                            "command": command})
        if status != "done":
            return _finish({"status": "stop", "text": result.get("text", ""), "steps": steps,
                            "command": command})
    return _finish({"status": "done", "text": f"{len(steps)} adım tamamlandı.", "steps": steps,
                    "command": command})


class Budget:
    """Adım bütçesi: kaç adım kaldı."""

    def __init__(self, remaining: int = MAX_STEPS):
        self.remaining = remaining

    def can_step(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _finish(report: dict) -> dict:
    report.setdefault("finished_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    path = None
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S") + ".json"
        path = REPORT_DIR / name
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        _record_failure("modules/pc_autonomy.py:_finish")
    report["report"] = str(path) if path else ""
    return report
