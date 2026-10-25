"""Sohbetten tetiklenen görsel komutlarını `modules/visual_commands.py`'ye
bağlayan ince katman. `command_manager.dispatch` içinden çağrılır, tıpkı
`desktop_agent`/`task_agents` gibi — None dönerse normal akış sürer.

Hamdi ile netleşen tasarım (bkz. `docs/agents/gorsel-komutlar.md`):
- Dosyalar ekranındaysa (bu modülün dışında, `main_documents._file_command`
  üzerinden) içerik otomatik alınır, soru sorulmaz.
- Sohbetteyse "sohbetten mi, dosyadan mı?" sorulur: "sohbet" son konuşma
  geçmişini kullanır; "dosya" kullanıcıyı Dosyalar ekranındaki ilgili
  düğmeye yönlendirir (dosya adı çözümleme burada tekrar kurulmaz —
  tek bir yerde, Dosyalar ekranında yapılır).
- Kötü sonuçta "yeniden dene" aynı içerikle tekrar üretir.
"""
from __future__ import annotations

import re

from modules import visual_commands
from modules.diagnostics import record_failure as _record_failure
from modules.image_gen import ImageGenError

_SOURCE_SOHBET = re.compile(r"\bsohbet(?:ten|i)?\b|\bkonu[sş]ma(?:dan)?\b|\bge[cç]mi[sş](?:ten)?\b")
_SOURCE_DOSYA = re.compile(r"\bdosya(?:dan)?\b|\bbelge(?:den)?\b")
_RETRY = re.compile(r"\byeniden\s+dene\w*\b|\btekrar\s+dene\w*\b|\bbir\s+daha\s+dene\w*\b")

_HISTORY_LIMIT = 40


def _history_text(context, owner: str) -> str:
    try:
        rows = context.history_read(owner, "", _HISTORY_LIMIT) or []
    except Exception:
        _record_failure("modules/visual_chat.py:_history_text")
        return ""
    parts = [str(r.get("text", "")).strip() for r in rows if isinstance(r, dict) and r.get("text")]
    return "\n".join(p for p in parts if p)


def _generate(context, owner: str, text: str, content: str, kind: str) -> str:
    if not (content or "").strip():
        return "Görsel için kullanılacak bir içerik bulamadım; henüz bir şey konuşmadık."
    try:
        result = visual_commands.create_visual(text, content, slug=owner, kind=kind)
    except ImageGenError as exc:
        return f"Görsel üretilemedi ({exc.reason_code}). Cloudflare hesap/anahtar ayarını kontrol et."
    except ValueError as exc:
        return str(exc)
    context.session.last_visual = {"text": text, "content": content, "kind": kind}
    return (f"{result.label.capitalize()} hazır, Dosyalar sayfasına kaydettim: {result.path}\n"
            'Beğenmezsen "yeniden dene" diyebilirsin.')


def handle(context, command: str, normalized: str) -> str | None:
    owner, session = context.profile.slug, context.session

    # `session` bazı testlerde hafif bir SimpleNamespace olabilir (yalnız o
    # testin kullandığı alanlarla); bu alanlar orada hiç yoksa normal akışa
    # düşülmeli, AttributeError ile patlamamalı.
    pending = getattr(session, "pending_visual", None)
    if pending is not None:
        if pending.get("stage") == "source":
            if _SOURCE_SOHBET.search(normalized):
                session.pending_visual = None
                return _generate(context, owner, pending["text"], _history_text(context, owner), pending["kind"])
            if _SOURCE_DOSYA.search(normalized):
                session.pending_visual = None
                return ('Dosyalar sayfasında ilgili dosyayı seç, sonra o dosyanın yanındaki '
                        '"Görselleştir" düğmesine bas — içerik oradan otomatik alınır.')
            return 'Sohbetten mi, dosyadan mı? "sohbet" veya "dosya" yazabilirsin.'
        session.pending_visual = None   # tanınmayan aşama: kilitlenmesin, normal akışa düşsün

    last_visual = getattr(session, "last_visual", None)
    if _RETRY.search(normalized) and last_visual:
        return _generate(context, owner, last_visual["text"], last_visual["content"], last_visual["kind"])

    kind = visual_commands.detect_type(command)
    if kind is None:
        return None
    session.pending_visual = {"text": command, "kind": kind, "stage": "source"}
    return f"{visual_commands.LABELS[kind].capitalize()} için içerik nereden gelsin: sohbetten mi, dosyadan mı?"
