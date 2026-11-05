"""Görsel üretim yürütücüsü ve prompt kurucusu.

Sohbet türü seçimi canonical Brain'de yapılır: Understanding typed
visual.create + kapalı kind önerir, Core doğrular. Bu modül yalnız prompt'u
kurar, mevcut image_gen sağlayıcısını çağırır ve PNG'yi Jarvis Dosyaları'na
kaydeder. detect_type* yardımcıları geriye dönük uyumluluk içindir; normal
chat production path bunları çağırmaz.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from modules import image_gen
from modules.diagnostics import record_failure as _record_failure
from modules.visual_types import LABELS, TYPES, match_type

# ------------------------------------------------------------------ tür tespiti

def _norm(text: str) -> str:
    # Model output normalization; the user-turn type vocabulary is shared with Brain.
    return (text or "").replace("İ", "i").replace("I", "i").lower()


def detect_type_by_keyword(text: str) -> str | None:
    """Compatibility helper; production chat selection belongs to canonical Brain."""
    return match_type(text)


_MODEL_PROMPT = (
    "Aşağıdaki cümle bir görsel üretim isteği mi, ve öyleyse şu 7 türden "
    "hangisi: mindmap, flowchart, infographic, timeline, handwritten, "
    "blueprint, visualize. Yalnız bu 8 kelimeden birini yaz (7 tür adı veya "
    "'hicbiri'), başka hiçbir şey yazma.\n\nCümle: {text}"
)


def detect_type_via_model(text: str, *, _ask=None) -> str | None:
    """Kalıp eşleşmediğinde modele bir kez sorar. `_ask` yalnız testler için."""
    try:
        ask = _ask
        if ask is None:
            from modules import llm
            ask = llm.ask
        answer = ask(_MODEL_PROMPT.format(text=text.strip()), max_tokens=20)
    except Exception:
        _record_failure('modules/visual_commands.py:detect_type_via_model')
        return None
    answer = _norm(answer).strip()
    for kind in TYPES:
        if kind in answer:
            return kind
    return None


def detect_type(text: str, *, _ask=None) -> str | None:
    """Hibrit tespit: önce ücretsiz kalıp, uymazsa (nadiren) modele sor."""
    kind = detect_type_by_keyword(text)
    if kind:
        return kind
    return detect_type_via_model(text, _ask=_ask)


# ------------------------------------------------------------------ istem (prompt) kurma
_PROMPT_TEMPLATES = {
    "mindmap": "A clean, colorful mind map diagram. Central topic branching into labeled nodes. Content: {content}",
    "flowchart": "A clear flowchart diagram with labeled boxes and directional arrows showing a process. Content: {content}",
    "infographic": "A modern, colorful infographic with icons, short labels and simple charts. Content: {content}",
    "timeline": "A horizontal timeline diagram with labeled dated milestones in order. Content: {content}",
    "handwritten": "A photo-realistic handwritten note on paper, neat cursive handwriting, slightly textured paper. Content: {content}",
    "blueprint": "A technical blueprint-style line drawing on a blue grid background, labeled parts. Content: {content}",
    "visualize": "A clear, simple explanatory illustration summarizing the following. Content: {content}",
}


def build_prompt(kind: str, content: str) -> str:
    if kind not in _PROMPT_TEMPLATES:
        raise ValueError(f"Bilinmeyen görsel türü: {kind}")
    content = (content or "").strip()
    if not content:
        raise ValueError("İçerik boş olamaz.")
    return _PROMPT_TEMPLATES[kind].format(content=content[:1500])


# ------------------------------------------------------------------ üretim + kayıt
@dataclass
class VisualResult:
    kind: str
    label: str
    path: str


def _destination(kind: str) -> Path:
    from modules import nxapi
    folder = nxapi.FILES_DIR / "Görseller"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = folder / f"{kind}_{stamp}.png"
    n = 1
    while dest.exists():
        dest = folder / f"{kind}_{stamp}_{n}.png"
        n += 1
    return dest


def create_visual(text: str, content: str, *, slug: str, kind: str | None = None, _ask=None) -> VisualResult:
    """Tetikleme cümlesinden türü bulur (gerekirse), görseli üretir ve
    "Dosyalar" ekranının zaten taradığı `Jarvis Dosyaları/Görseller`
    klasörüne kaydeder. `kind` dışarıdan biliniyorsa (örn. Dosyalar
    ekranındaki bir butondan) tespit adımı atlanır.
    """
    resolved_kind = kind or detect_type(text, _ask=_ask)
    if not resolved_kind:
        raise ValueError("Bu bir görsel üretim isteği gibi görünmüyor.")
    prompt = build_prompt(resolved_kind, content)
    data = image_gen.generate_image(prompt, slug=slug)
    dest = _destination(resolved_kind)
    dest.write_bytes(data)
    return VisualResult(kind=resolved_kind, label=LABELS[resolved_kind], path=str(dest))
