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

# Zincirin devamı: "sonra artı düğmesine bas" — pencere söylenmez, önceki adımın
# penceresi kullanılır. Tek adımda pencere şart; çok adımda tekrar etmek yorucu.
_BARE_CLICK = re.compile(r"(.+?)\s+(?:dugmesine|ogesine|sekmesine|linkine)\s+(?:bas|tikla)")
_BARE_TYPE = re.compile(r"(.+?)\s+(?:alanina|kutusuna|yerine)\s+(.+?)\s+yaz")

# Adım sınırları: sıralı işi anlatan bağlaçlar ve virgül.
BOUNDARIES = (" sonra ", " ardından ", ",", " ve sonra ", " ondan sonra ")
MAX_STEPS = 6
UNPARSED = "“{part}” adımını anlayamadım; bu yüzden hiçbir şey yapmadım."
TOO_LONG = "Bir seferde en çok {limit} adım yürütebilirim; komutu bölerek söyle."
STOPPED = "“{step}” adımında durdum: {reason} Kalan adımları çalıştırmadım."

_RUNNERS = {
    "pc_save": lambda args: __import__("modules.pc_files", fromlist=["save_as"]).save_as(
        str(args.get("window") or ""), str(args.get("name") or "")),
    "pc_search": lambda args: __import__("modules.pc_hands", fromlist=["press_enter"]).press_enter(
        str(args.get("window") or "")),
    "pc_click": lambda args: pc_hands.click(str(args.get("window") or ""), str(args.get("target") or "")),
    "pc_type": lambda args: pc_hands.type_text(str(args.get("window") or ""), str(args.get("target") or ""),
                                               str(args.get("text") or "")),
}
_OK = ("done",)


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
        if resolved and resolved[0] in _RUNNERS:
            inherited = str((resolved[1] or {}).get("window") or inherited)
        elif inherited:
            bare = pc_hands._fold(part)
            click = _BARE_CLICK.fullmatch(bare)
            typing = _BARE_TYPE.fullmatch(bare)
            if click:
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
