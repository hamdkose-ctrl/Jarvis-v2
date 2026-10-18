"""Hoca modu: konu bazlı, adım adım ders kaydı.

Ders = konu + 3-8 adımlık plan (tek model çağrısı). Plan ve ilerleme kullanıcı profilinde
(`profile.data["hoca"]`) durur; bu modül kendi başına başka model çağrısı yapmaz. Plan bozuk
gelirse sessizce düşülmez, açık hata verilir ve hiçbir şey kaydedilmez.
"""
from __future__ import annotations

import json
import re
import time

from modules import llm
from modules.diagnostics import record_failure as _record_failure

MAX_STEPS = 8
MIN_STEPS = 2
_TOPIC_MAX = 120
_TITLE_MAX = 120
_GOAL_MAX = 240


class HocaError(Exception):
    """Kullanıcıya olduğu gibi gösterilebilen Türkçe hata."""


def _state(profile) -> dict:
    s = profile.data.setdefault("hoca", {})
    if not isinstance(s.get("lesson"), (dict, type(None))):
        s["lesson"] = None
    s.setdefault("lesson", None)
    return s


def _clip(value, limit) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse_plan(text: str) -> list[dict]:
    raw = str(text or "")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise HocaError("Ders planı anlaşılamadı (model JSON vermedi). Biraz sonra tekrar dene.")
    try:
        data = json.loads(m.group(0))
        items = data.get("steps") if isinstance(data, dict) else None
    except ValueError:
        raise HocaError("Ders planı anlaşılamadı (JSON bozuk). Biraz sonra tekrar dene.")
    steps = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        title, goal = _clip(it.get("title"), _TITLE_MAX), _clip(it.get("goal"), _GOAL_MAX)
        if title and goal:
            steps.append({"title": title, "goal": goal})
    if len(steps) < MIN_STEPS:
        raise HocaError("Ders planı eksik geldi (en az 2 adım gerekir). Biraz sonra tekrar dene.")
    return steps[:MAX_STEPS]


_SYSTEM = ("Sen sabırlı bir hocasın. Verilen konu için sırayla öğrenilecek adımlardan oluşan kısa bir ders planı yaz. "
           "Yalnız JSON ver: {\"steps\":[{\"title\":\"kısa başlık\",\"goal\":\"bu adımda öğrenilecek şey\"}]}. "
           "3 ile 7 adım olsun, her adım bir öncekine dayansın, konudan sapma.")


def start(profile, topic: str, level: str = "") -> dict:
    topic = _clip(topic, _TOPIC_MAX)
    if not topic:
        raise HocaError("Hangi konuyu çalışmak istediğini söyler misin?")
    level = _clip(level, 40)
    prompt = f"Konu: {topic}\nSeviye: {level or 'belirtilmedi'}"
    try:
        answer = llm.ask(prompt, _SYSTEM, 900)
    except Exception as exc:
        _record_failure('modules/hoca.py:start')
        raise HocaError(f"Ders planı şu an hazırlanamadı ({type(exc).__name__}). Biraz sonra tekrar dene.")
    steps = parse_plan(answer)
    lesson = {"topic": topic, "level": level, "steps": steps, "active": 0, "done": False,
              "started": int(time.time())}
    _state(profile)["lesson"] = lesson
    profile.save()
    return lesson


def active(profile) -> dict | None:
    lesson = _state(profile).get("lesson")
    if not lesson or lesson.get("done"):
        return None
    return lesson


def current_step(profile) -> dict | None:
    lesson = active(profile)
    if not lesson:
        return None
    i = lesson.get("active", 0)
    steps = lesson.get("steps") or []
    return steps[i] if 0 <= i < len(steps) else None


def advance(profile) -> dict | None:
    """Sonraki adıma geçer; son adımdan sonra ders biter. Yeni adımı (bittiyse None) döndürür."""
    lesson = active(profile)
    if not lesson:
        return None
    lesson["active"] = lesson.get("active", 0) + 1
    if lesson["active"] >= len(lesson.get("steps") or []):
        lesson["done"] = True
    profile.save()
    return current_step(profile)
