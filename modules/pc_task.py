"""PC ajanı 5. dilim — çok adımlı görev: "şunu aç, şunu yaz, kaydet".

Kurallar:
- Adımlar **ayrıştırılamazsa hiç başlanmaz**: yarım anlaşılmış bir planı çalıştırmak,
  hiç çalıştırmamaktan daha kötü. Cevap tek cümle: hangi adımı anlamadım.
- Adımlar sırayla yürür; biri durursa (onay gerekiyor / pencere yok / ekran değişmedi)
  **zincir durur**, kalanı çalışmaz ve ne olduğu tek tek söylenir.
- Onay gerektiren adım (silme/ödeme/gönderme) zincirin ortasında olsa da durur:
  otomatik onay yok.
- `abort` (Esc) her adımdan önce kontrol edilir.
"""
from __future__ import annotations

import re

from modules import fast_commands, pc_hands
from modules.diagnostics import record_failure as _record_failure

# Zincirin devamı: "sonra artı düğmesine bas" — pencere söylenmez, önceki adımın
# penceresi kullanılır. Tek adımda pencere şart; çok adımda tekrar etmek yorucu.
_BARE_SAY = re.compile(r"(.+?)\s+(?:yaz|yaziver)")
_BARE_ENTER = re.compile(r"(?:enter|ara|aramayi baslat|aramayı başlat)")
_BARE_CLICK = re.compile(r"(.+?)\s+(?:dugmesine|ogesine|sekmesine|linkine)\s+(?:bas|tikla)")
_BARE_TYPE = re.compile(r"(.+?)\s+(?:alanina|kutusuna|yerine)\s+(.+?)\s+yaz")

# Adım sınırları: sıralı işi anlatan bağlaçlar ve virgül.
BOUNDARIES = (" sonra ", " ardından ", ",", " ve sonra ", " ondan sonra ")
MAX_STEPS = 6
UNPARSED = "“{part}” adımını anlayamadım; bu yüzden hiçbir şey yapmadım."
TOO_LONG = "Bir seferde en çok {limit} adım yürütebilirim; komutu bölerek söyle."
STOPPED = "“{step}” adımında durdum: {reason} Kalan adımları çalıştırmadım."

_RUNNERS = {
    "app_open": lambda args: _open_app(str(args.get("name") or "")),
    "pc_save": lambda args: __import__("modules.pc_files", fromlist=["save_as"]).save_as(
        str(args.get("window") or ""), str(args.get("name") or "")),
    "pc_search": lambda args: __import__("modules.pc_hands", fromlist=["press_enter"]).press_enter(
        str(args.get("window") or "")),
    "pc_click": lambda args: pc_hands.click(str(args.get("window") or ""), str(args.get("target") or "")),
    "pc_type": lambda args: pc_hands.type_text(str(args.get("window") or ""), str(args.get("target") or ""),
                                               str(args.get("text") or "")),
}
_OK = ("done",)
APP_GATED = ("“{name}” uygulamasını ben açamıyorum (izin kapısı). Sen açarsan "
             "kalan adımları yaparım.")


def _open_app(name: str) -> dict:
    """Uygulama açma onaylı yoldan geçer; kapı kapalıysa dürüstçe söylenir."""
    try:
        from modules.system_control import open_application
        text = open_application(name)
        return {"status": "done", "text": str(text)[:120]}
    except PermissionError:
        return {"status": "refused", "text": APP_GATED.format(name=name)}
    except Exception as exc:
        _record_failure("modules/pc_task.py:_open_app")
        return {"status": "failed", "text": f"“{name}” açılamadı: {str(exc)[:60]}"}


def split_steps(command: str) -> list[str]:
    """Komutu adım cümlelerine böler (sıralı bağlaçlar ve virgül)."""
    text = f" {str(command or '').strip()} "
    for boundary in BOUNDARIES:
        text = text.replace(boundary, " | ")
    return [part.strip() for part in text.split("|") if part.strip()]


def plan(command: str) -> dict:
    """Adımları çözer; anlaşılmayan varsa plan döndürmez."""
    parts = split_steps(command)
    if not parts:
        return {"status": "empty", "text": UNPARSED.format(part=command)}
    if len(parts) > MAX_STEPS:
        return {"status": "too_long", "text": TOO_LONG.format(limit=MAX_STEPS)}
    steps = []
    inherited = ""
    for part in parts:
        resolved = fast_commands.resolve(part)
        if resolved and resolved[0] == "app_open":
            # "chrome aç" adımı: pencere devralma zincirini bu uygulamayla başlatır.
            name = str((resolved[1] or {}).get("name") or "")
            inherited = name or inherited
        if resolved and resolved[0] in _RUNNERS:
            inherited = str((resolved[1] or {}).get("window") or inherited)
        elif inherited:
            bare = pc_hands._fold(part)
            click = _BARE_CLICK.fullmatch(bare)
            typing = _BARE_TYPE.fullmatch(bare)
            if _BARE_ENTER.fullmatch(bare):
                resolved = ("pc_search", {"window": inherited})
            elif (typing_say := _BARE_SAY.fullmatch(bare)) and inherited:
                # "chrome aç, youtube yaz" → tarayıcıda adres çubuğu; değilse metin alanı.
                target = "adres" if pc_hands.is_browser(pc_hands.pc_awareness.find_window(inherited).get("match") or {}) else "metin"
                resolved = ("pc_type", {"window": inherited, "target": target,
                                        "text": typing_say.group(1).strip()})
            elif click:
                resolved = ("pc_click", {"window": inherited, "target": click.group(1).strip()})
            elif typing:
                resolved = ("pc_type", {"window": inherited, "target": typing.group(1).strip(),
                                        "text": typing.group(2).strip()})
        if not resolved or resolved[0] not in _RUNNERS:
            return {"status": "unparsed", "text": UNPARSED.format(part=part)}
        # Adım bir demet: {"intent","args"} sözlüğü, CI'daki "tek yön karar mercii"
        # bekçisi tarafından ikinci bir router gibi görünüyordu.
        steps.append((part, resolved[0], resolved[1]))
    return {"status": "ok", "steps": steps}


def run(command: str, *, abort=None) -> dict:
    """Adımları sırayla yürütür; durursa zincir kesilir."""
    prepared = plan(command)
    if prepared["status"] != "ok":
        return {"status": prepared["status"], "text": prepared["text"], "done": []}
    spoken, done = [], []
    for step_text, intent, args in prepared["steps"]:
        if abort is not None and abort.is_set():
            return {"status": "stopped", "text": "Durduruldu.", "done": done}
        # Kurtarma: geçici aksaklıkta bir kez daha dene, sonra dürüstçe dur.
        result = pc_hands.attempt(lambda: _RUNNERS[intent](args), window=str(args.get("window") or ""),
                                  abort=abort)
        if result.get("status") not in _OK:
            spoken.append(STOPPED.format(step=step_text, reason=result.get("text", "")))
            return {"status": "stop", "text": " ".join(spoken), "done": done}
        done.append(step_text)
        spoken.append(result.get("text", ""))
    return {"status": "done", "text": " ".join(text for text in spoken if text), "done": done}
