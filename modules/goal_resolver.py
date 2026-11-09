"""BRAIN-05 Goal Resolver: modelin hedef işlemi önerisini kullanıcının kendi kayıtlarında doğrular.

Bu modül hedef otoritesi DEĞİLDİR ve ikinci bir hedef deposu taşımaz. Tek işi, Brain'in
ÖNERDİĞİ (``UnderstandingResult.goal_operation`` + ``goal_target_ids``) yaşam döngüsü adımını
kullanıcının kendi kalıcı kayıtları üzerinde yeniden doğrulamaktır: sahip, kimlik biçimi,
kaydın varlığı ve sahipliği, kartın gerçekten sunulmuş olması. Geçişin kendisi mevcut
``goal_executor`` ilkelleriyle yapılır; her kayıt yazımı ``goal_state_save_hook`` üzerinden
canonical GoalState'ı Reducer/CAS ile ilerletir, burada doğrudan GoalState yazılmaz.

İki kural bu modülün tamamını biçimlendirir:
  • Belirsizse işlem yapılmaz, soru sorulur (mevcut clarify yolu).
  • Bir hedefe yapılan işlem diğerinin kaydına dokunmaz; doğrulanamayan kimlik için
    hiçbir kayıt yazılmaz ve bu kullanıcıya açıkça söylenir.
Hedefin metni asla modelden alınmaz: yeni eklenen sonuç ve düzeltme kullanıcının kendi
cümlesidir, salt sürdürme ise ``hedef devam`` protokol sözüyle gider (cevap kanalına
kontrol cümlesi yazılmaz).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.brain_contracts import GoalOperation

#: Bu işlemler tek bir hedef üzerinde yürür; birden fazla kimlik seçilirse soru sorulur.
#: `create_goal` hiç kimlik taşımaz, o yüzden bu kümede değil (yukarıda ayrı yürür).
_SINGLE_TARGET = frozenset({
    GoalOperation.CONTINUE, GoalOperation.RESUME, GoalOperation.PRIORITIZE,
})
#: Salt sürdürme: `goal_executor.RESUME_COMMANDS` içinde olduğu için cevap kanalını kirletmez.
_CONTINUE_TOKEN = "hedef devam"
_CARD_TITLE_MAX = 80


@dataclass(frozen=True)
class Resolution:
    """Bir hedef işlemi turunun Core doğrulamalı sonucu: söylenecek metin, durum ve kimlik."""

    message: str
    result_status: str
    reason_code: str
    job_id: str | None = None


def _cards(entry: Any) -> dict[str, str]:
    """Sunulan açık hedef kartları: kimlik → kullanıcının kendi hedef cümlesinden başlık.

    Modelin adresleyebildiği kümeyle doğrulanan küme aynı ActiveContext alanından gelir; iki
    ayrı okuma zamanla ayrışmasın diye tek kaynak budur."""
    cards = {}
    for reference in getattr(entry.active_context, "goal_candidates", ()):
        if reference.source != "goal_state":
            continue
        title = str((reference.provenance or {}).get("title") or "").strip()
        cards[str(reference.id)] = title[:_CARD_TITLE_MAX]
    return cards


def _listing(cards: dict[str, str]) -> str:
    titles = [title or ident[:8] for ident, title in cards.items()]
    return "; ".join(titles) if titles else "kayıtlı açık hedefin yok"


def _question(message: str, reason_code: str) -> Resolution:
    return Resolution(message=message, result_status="needs_input", reason_code=reason_code)


def _titles_for(targets: tuple[str, ...], cards: dict[str, str]) -> str:
    return _listing({ident: cards.get(ident, "") for ident in targets})


def resolve(runtime: Any, entry: Any) -> Resolution:
    """One goal-control turn, validated against the owner's own durable records."""
    from modules import goal_executor

    understanding = getattr(entry, "understanding", None)
    operation = getattr(understanding, "goal_operation", None)
    if not isinstance(operation, GoalOperation):
        # Taşıyıcıda işlem yoksa bu kanal hiç devreye girmemeliydi: efekt yok, soru var.
        return _question("Hangi hedefle ne yapmamı istediğini netleştiremedim; işlem yapılmadı.",
                         "GOAL_OPERATION_MISSING")
    owner = runtime.profile.slug
    if owner != entry.owner:
        raise ValueError("Hedef işlemi owner'ı istek sahibiyle eşleşmiyor.")
    targets = tuple(getattr(understanding, "goal_target_ids", ()) or ())
    cards = _cards(entry)
    text = str(entry.text or "").strip()

    if operation is GoalOperation.CREATE:
        # Kart modelin "yeni hedef" niyetinin taşıyıcısıdır; kalıcı hedef cümlesi ise
        # kullanıcının kendi sözüdür. Boş bir cümleyi burada yeniden yorumlamayız:
        # `goal_executor._run` "Somut hedef gerekli." ile kendisi refusal verir.
        return _single(lambda: goal_executor.run(runtime, text), _reason(operation))

    unknown = [ident for ident in targets if ident not in cards]
    if unknown:
        # Zarf yalnız sunulmuş kimlikleri geçirir; buraya ulaşmaları önerinin bu turda
        # sunulmuş bir hedefe bağlı olmadığını gösterir. Efekt yok, başka hedefe dokunma yok.
        return _question(
            "Bu hedefi sana ait açık bir hedef kaydında bulamadım; başka hedefe işlem uygulanmadı. "
            f"Açık hedeflerin: {_listing(cards)}.", "GOAL_TARGET_NOT_OFFERED")
    if operation in _SINGLE_TARGET and len(targets) != 1:
        return _question(
            "Bu işlemi bir hedef üzerinde yapabilirim. Hangisini kastettin: "
            f"{_titles_for(targets, cards)}?", "GOAL_TARGET_AMBIGUOUS")

    applied: list[Resolution] = []
    for ident in targets:
        applied.append(_apply_one(runtime, goal_executor, owner, operation, ident, text))
    refused = [row for row in applied if row.result_status != "handled"]
    if refused:
        message = "\n".join(row.message for row in applied)
        return Resolution(message=message,
                          result_status="handled" if len(refused) < len(applied) else "failed",
                          reason_code=refused[0].reason_code,
                          job_id=None if len(applied) > 1 else applied[0].job_id)
    if len(applied) == 1:
        return applied[0]
    return Resolution(message="\n".join(row.message for row in applied),
                      result_status="handled", reason_code="GOAL_OPERATIONS_APPLIED", job_id=None)


def _apply_one(runtime: Any, goal_executor: Any, owner: str, operation: GoalOperation,
               ident: str, text: str) -> Resolution:
    """One identity, re-read from the durable store, through the existing lifecycle primitive."""
    try:
        job = goal_executor.read_job(owner, ident)
    except ValueError:
        return _question("Bu hedef kimliği kalıcı bir hedef kaydına uymuyor; işlem yapılmadı.",
                         "GOAL_TARGET_NOT_ADDRESSABLE")
    if not job:
        return _question(
            "Bu hedef artık kayıtlı değil; tamamlanmış ya da kapanmış olabilir. Başka hedefe "
            "işlem uygulanmadı.", "GOAL_TARGET_STALE")
    # Kartın sunulduğu açıklık koşeli işlem anında yeniden denetlenir: kayıt sunulduktan
    # sonra kapanmış ya da bayatlamış olabilir. `execution_record.load` sahipliği zaten
    # doğrular, burada ikinci bir owner kontrolü yoktur.
    if not goal_executor.is_open(job):
        return _question(
            "Bu hedef artık açık değil; tamamlanmış, kapanmış ya da bayatlamış olabilir. "
            "Başka hedefe işlem uygulanmadı.", "GOAL_TARGET_STALE")
    return _single(
        lambda: _dispatch(runtime, goal_executor, owner, operation, ident, text),
        _reason(operation), ident)


def _reason(operation: GoalOperation) -> str:
    """Kart üzerindeki işlem adı, kaydı hangi ilkelin yürüttüğünün tanısıdır."""
    return "GOAL_" + operation.name.upper()


def _single(call: Any, reason_code: str, ident: str | None = None) -> Resolution:
    """Run one Core lifecycle call; its own refusal is reported, not re-interpreted here."""
    try:
        message = call()
    except ValueError as exc:
        # İlkellerin ValueError metni kullanıcıya söylenmek üzere yazılmıştır (ör.
        # "Başka bir hedef çalışıyor."). Cancelled ve PermissionError ValueError değildir,
        # onlar buradan geçmez: iptal yukarı gider, sahiplik hatası canlı yükselir.
        return Resolution(message=str(exc), result_status="failed",
                          reason_code="GOAL_LIFECYCLE_REFUSED", job_id=ident)
    return Resolution(message=str(message), result_status="handled", reason_code=reason_code,
                      job_id=ident)


def _dispatch(runtime: Any, goal_executor: Any, owner: str, operation: GoalOperation,
              ident: str, text: str) -> str:
    # `create_goal` buraya hiç ulaşmaz: yeni kaydın hedeflenecek bir kimliği yoktur ve o
    # geçiş `resolve` kendi dalından yürür. Buradaki her kol mevcut bir kayıttadır.
    if operation in {GoalOperation.CONTINUE, GoalOperation.RESUME}:
        return goal_executor.run(runtime, _CONTINUE_TOKEN, resume=True, job_id=ident)
    if operation is GoalOperation.REVISE:
        # Düzeltme kullanıcının kendi cümlesidir ve cevap kanalından yürür; `request`
        # (canonical kimlik alanı) değiştirilmez.
        return goal_executor.run(runtime, text, resume=True, job_id=ident)
    if operation is GoalOperation.ADD_TASK:
        return goal_executor.append_goal_task(owner, ident, text)
    if operation is GoalOperation.PAUSE:
        return goal_executor.pause_job(owner, ident)
    if operation is GoalOperation.CANCEL:
        return goal_executor.cancel_job(owner, ident)
    return goal_executor.prioritize_job(owner, ident)
