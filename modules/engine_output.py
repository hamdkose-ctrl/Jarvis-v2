"""engine output; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def emit(runtime, kind: str, text: str = "", extra: str = "") -> None:
    """Arayüze olay gönderir (user, assistant, state, system, quit) ve konuşmaları günlüğe yazar."""
    pass  # Shared fields are held by the explicit engine context.
    metadata = None
    owner = runtime.pc_profile() if extra == "ses" else runtime.profile
    if kind in ("user", "assistant"):
        with runtime._event_lock:
            if kind == 'assistant':
                from modules import requests_state
                requests_state.check()
            runtime._log_id += 1
            row = runtime.history.append(owner.slug, kind, text, extra) or {}
            runtime.event_log.append({"id": runtime._log_id, "kind": kind, "text": text, "source": extra,
                              "user": owner.name, "rid": runtime._cur_rid, "hid": row.get("id")})
            del runtime.event_log[:-200]
            metadata = {'user': owner.slug, 'mid': row.get('id'), 'rid': runtime._cur_rid}
            if kind == 'assistant' and getattr(runtime, 'response_waiters', None) is not None:
                runtime.response_waiters.publish(owner.slug, runtime._cur_rid, text)
        if kind == "user":
            try:
                from modules import learning
                learning.observe(owner, text)
            except Exception:
                runtime._record_failure('main.py:emit')
        if runtime._guest is not None and owner.slug != runtime.pc_profile().slug:
            return       # başka kullanıcının (telefondaki) konuşması bilgisayar ekranında görünmez
    elif kind == "step":
        metadata = {'user': owner.slug, 'rid': runtime._cur_rid}
        if runtime._guest is not None and owner.slug != runtime.pc_profile().slug:
            return
    if runtime._ui is not None:
        try:
            if getattr(runtime._ui, 'event_metadata', False) is True:
                runtime._ui(kind, text, extra, metadata=metadata)
            else:
                runtime._ui(kind, text, extra)
        except Exception:
            runtime._record_failure('main.py:emit')

def _emit_route(runtime) -> None:
    """Shows which model answered (and any fallback) as step lines on this request's card."""
    try:
        notes = runtime._llm.take_route()
    except Exception:
        runtime._record_failure('main.py:_emit_route')
        return
    for i, (text, ok) in enumerate(notes, 1):
        runtime.emit("step", text, ("done" if ok else "error") + f"|m{i}|")


def set_share(runtime, which: str | None) -> str:
    """Ekran paylaşımı / kamera: 'screen', 'camera' ya da None (kapat). Arayüze 'share' olayı gönderir."""
    if which and (msg := runtime.privacy.blocked("screen" if which == "screen" else "camera")):
        return msg
    was = runtime.vision.mode()
    try:
        if which:
            runtime.vision.start(which)
        else:
            runtime.vision.stop()
    except Exception as exc:
        runtime._record_failure('main.py:set_share')
        runtime.emit("share", runtime.vision.mode() or "")
        return f"Paylaşım {'başlatılamadı' if which else 'kapatılamadı'}: {exc}"
    # Arayüz olayı ve denetim kaydı istenen durumdan değil, işlem sonrası gerçek durumdan üretilir.
    now = runtime.vision.mode()
    runtime.emit("share", now or "")
    if which and now != which:
        return "Paylaşım başlatılamadı."
    if not which and now:
        return "Paylaşımı kapatamadım; hâlâ açık görünüyor."
    runtime.privacy.audit("paylaşım", now or "kapatıldı")
    if now == "screen":
        return "Ekranını paylaşıyorsun. Sorularını ekrana bakarak yanıtlarım."
    if now == "camera":
        return "Kamera açık. Sorularını kameranın gördüğüne bakarak yanıtlarım."
    return "Paylaşımı kapattım." if was else "Açık bir ekran ya da kamera paylaşımı yoktu; paylaşım kapalı."

def set_sleep(runtime, on: bool, announce: bool = True) -> str:
    """Hazırda bekle: Jarvis açık kalır (telefon/Siri, hatırlatmalar çalışır) ama yalnızca '<ad> uyan' sözünü dinler."""
    runtime.flags["sleep"] = bool(on)
    runtime.emit("sleep", "1" if on else "")
    msg = (f"Hazırda bekliyorum. Uyandırmak için “{runtime.WAKE_WORD} uyan” de." if on else "Buradayım.")
    if announce:
        runtime.events.put(("say", msg))
    return msg

def _short_for_speech(runtime, text: str, limit: int = 400) -> str:
    """Uzun yanıtı cümle sınırından keser, sesli okuma yarım cümlede bitmesin."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
    return cut[: idx + 1] if idx > 100 else cut

def _finalize(runtime, out: str) -> str:
    """LaTeX işaretlerini okunur düz metne çevirir (kod blokları hariç); son analiz kaydını da eşler."""
    cleaned = runtime.richtext.clean_math(out)
    if cleaned != out:
        if runtime._session().last_doc is not None and out.startswith(runtime._session().last_doc[0][:50]):
            runtime._session().last_doc = (runtime.richtext.clean_math(runtime._session().last_doc[0]),) + tuple(runtime._session().last_doc[1:])
        out = cleaned
    return out

def _doc_ready_line(runtime, kind: str, text: str = "") -> str:
    """Uzun analiz/özet ekrana yazılır; sesli olarak bir giriş cümlesi + belgenin özünü anlatan kısa bir kısım söylenir."""
    head = {"ozet": "Özeti ekrana yazdım.", "ceviri": "Çeviri hazır, ekrana yazdım.",
            "gorsel_analiz": "Görseli inceledim, sonucu ekrana yazdım."}.get(kind, "Analizi ekrana yazdım.")
    if kind == "ceviri" or not text:
        return head
    gist = []
    for line in text.splitlines():
        t = runtime.re.sub(r"[*#>`_|]+", "", line).strip(" -•\t")
        t = runtime.re.sub(r"^\d+[.)]\s*", "", t)
        if len(t) < 40 or t.endswith(":") or runtime.re.match(r"(?i)(sunulan|aşağıda|işte|bu belge(?:ye| için) dayan)", t):
            continue
        gist.append(t)
        if sum(len(g) for g in gist) > 260:
            break
    return head + (" Kısaca: " + " ".join(gist)[:420] if gist else "")

def _table_chat(runtime) -> str:
    """Önceki Jarvis yanıtını dosya üretmeden sohbet içinde tabloya çevirir."""
    from modules import conversation_reset
    rows = conversation_reset.recent(runtime.profile.slug, runtime.history.read(runtime.profile.slug, "", 80))
    source = next((str(r.get("text", "")).strip() for r in reversed(rows)
                   if r.get("role") == "assistant" and str(r.get("text", "")).strip()), "")
    if not source:
        return "Tabloya dönüştüreceğim bir önceki yanıtı bulamadım."
    result = runtime.ask("Aşağıdaki önceki yanıtı sohbet ekranında Markdown tablo olarak düzenle. "
               "Dosya oluşturma, kaydetme veya yetki hakkında konuşma. Yalnızca tabloyu ve gerekirse tek cümlelik başlığı ver; "
               "bilgileri eksiltme.\n\nÖNCEKİ YANIT:\n" + source).strip()
    runtime._session().last_doc = (result, "", "tablo")
    return result

def _copy_text(runtime, text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        runtime._record_failure('main.py:_copy_text')
        try:
            runtime.subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                           input=text.encode("utf-8"), timeout=10,
                           creationflags=getattr(runtime.subprocess, "CREATE_NO_WINDOW", 0), check=True)
            return True
        except Exception:
            runtime._record_failure('main.py:_copy_text')
            return False
