"""Hoca çalışma alanı — domain sözleşmesi (1. adım) + ödev parçalama (4a).

Çoğunlukla veri modeli: ders, oturum, kaynak, hedef (ödev/deadline) ve ilerleme
kaydı/okuma. Tek istisna `decompose_assignment` (4a, 25 Ekim 2026): büyük bir
ödevi alt göreve bölmek için tek bir model çağrısı yapar. Dönem haritası/takvim
hesaplaması ve onaylı takvim değişikliği henüz yok — bunlar sonraki adımlar
(bkz. docs/agents/hoca.md).

Mevcut `modules/hoca.py` (ders/adım anlatımı, zayıf konu/tekrar) bu modüle sonraki
adımda bağlanacak; burada ona dokunulmadı, ikisi de `profile.data` üzerinde ayrı
anahtarlarla durur ("hoca" / "hoca_courses").

Hamdi'nin kararları (25 Ekim 2026, bkz. docs/agents/hoca.md):
- Ders = geniş kapsam (ör. "Matematik"); konu bunun altında (`modules/hoca.py`'nin
  ders planı/adımları). LGS'de de bu ayrım aynı.
- Her derste sınav takibi isteğe bağlı ve OTOMATİK: kullanıcı bir "çıkmış_soru"
  kaynağı eklerse kendiliğinden açılır; sorulmaz.
- Ders eklenirken seviye (LGS/lise/üniversite/genel) bir kez sorulur; kaynak yoksa
  anlatım bu seviyeye göre ayarlanır (bağlama `modules/hoca.py:start`'ın `level`
  parametresi üzerinden, sonraki adımda).
- Oturum hafızası: anlaşılmayan noktalar + çözülen sorular + sonraki adım.
  Tekrar aralığı (1-3-7 gün) `modules/studyexam.py` ile aynı kalıyor, değişmedi.
- Ders dosyaları (kitap/PDF/çıkmış soru) bu modülün kendi kaydıdır; Dosyalar
  ekranındaki genel dosyalarla hiç karışmaz (ayrı depo, ayrı liste).
"""
from __future__ import annotations

import json
import re
import time

from modules.diagnostics import record_failure as _record_failure

LEVELS = ("lgs", "lise", "üniversite", "genel")
SOURCE_TYPES = ("kitap", "pdf", "video", "web", "çıkmış_soru")
_EXAM_SOURCE_TYPES = {"çıkmış_soru"}

_NAME_MAX = 80
_LABEL_MAX = 160
_TOPIC_MAX = 120
_TEXT_MAX = 400
_LIST_MAX = 20  # oturum başına saklanan anlaşılmayan nokta/çözülen soru sayısı


class HocaWorkspaceError(Exception):
    """Kullanıcıya olduğu gibi gösterilebilen Türkçe hata."""


def _clip(value, limit) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _state(profile) -> list:
    if not isinstance(getattr(profile, "data", None), dict):
        profile.data = {}
    courses = profile.data.get("hoca_courses")
    if not isinstance(courses, list):
        courses = []
        profile.data["hoca_courses"] = courses
    return courses


def _next_id(courses: list) -> int:
    return 1 + max((int(c.get("id", 0)) for c in courses), default=0)


def add_course(profile, name: str, level: str = "genel") -> dict:
    name = _clip(name, _NAME_MAX)
    if not name:
        raise HocaWorkspaceError("Ders adı boş olamaz.")
    level = level if level in LEVELS else "genel"
    courses = _state(profile)
    if any(_clip(c.get("name"), _NAME_MAX).casefold() == name.casefold() for c in courses):
        raise HocaWorkspaceError(f"“{name}” adında bir ders zaten var.")
    course = {
        "id": _next_id(courses),
        "name": name,
        "level": level,
        "exam_enabled": False,
        "sources": [],
        "assignments": [],
        "sessions": {},
        "created": int(time.time()),
    }
    courses.append(course)
    profile.save()
    return course


def list_courses(profile) -> list:
    return list(_state(profile))


def get_course(profile, course_id: int) -> dict | None:
    for c in _state(profile):
        if int(c.get("id", -1)) == int(course_id):
            return c
    return None


def _require_course(profile, course_id: int) -> dict:
    course = get_course(profile, course_id)
    if not course:
        raise HocaWorkspaceError("Böyle bir ders bulunamadı.")
    return course


def add_source(profile, course_id: int, source_type: str, ref: str, label: str = "") -> dict:
    course = _require_course(profile, course_id)
    if source_type not in SOURCE_TYPES:
        raise HocaWorkspaceError(f"Bilinmeyen kaynak türü: {source_type}")
    ref = _clip(ref, 400)
    if not ref:
        raise HocaWorkspaceError("Kaynak boş olamaz.")
    source = {"type": source_type, "ref": ref, "label": _clip(label, _LABEL_MAX) or ref, "added": int(time.time())}
    course["sources"].append(source)
    if source_type in _EXAM_SOURCE_TYPES:
        course["exam_enabled"] = True  # otomatik: sorulmaz, kaynak türünden kendiliğinden açılır
    profile.save()
    return source


_ASSIGNMENT_ORIGINS = ("manual", "syllabus", "decomposed")


def add_assignment(profile, course_id: int, title: str, due: str = "", origin: str = "manual",
                    parent_id: int | None = None) -> dict:
    course = _require_course(profile, course_id)
    title = _clip(title, _LABEL_MAX)
    if not title:
        raise HocaWorkspaceError("Ödev/deadline başlığı boş olamaz.")
    assignment = {
        "id": _next_id(course["assignments"]),
        "title": title,
        "due": _clip(due, 40),  # serbest biçim (ör. "2026-11-03"); takvim bağlantısı sonraki adım
        "origin": origin if origin in _ASSIGNMENT_ORIGINS else "manual",
        "done": False,
        "created": int(time.time()),
    }
    if parent_id is not None:
        assignment["parent_id"] = parent_id  # yalnız "decomposed" alt görevlerinde dolu
    course["assignments"].append(assignment)
    profile.save()
    return assignment


_DECOMPOSE_MIN = 2
_DECOMPOSE_MAX = 6


def decompose_assignment(profile, course_id: int, title: str, due: str = "", context: str = "") -> dict:
    """Büyük bir ödevi/projeyi 2-6 küçük alt göreve böler (tek model çağrısı).
    Asıl ödev normal (`manual`) olarak eklenir; alt görevler `decomposed` kökenli,
    `parent_id`'si asıl ödeve işaret eden ayrı kayıtlardır — hiçbiri silinmez/birleştirilmez.
    Henüz takvime yazmaz (bkz. docs/agents/hoca.md, 5. adım: onaylı takvim değişikliği)."""
    from modules import llm
    course = _require_course(profile, course_id)
    parent = add_assignment(profile, course_id, title, due=due, origin="manual")
    prompt = f"Ödev/proje: {parent['title']}\nDers: {course['name']}\nTeslim: {due or 'belirtilmedi'}"
    if context:
        prompt += f"\nEk bilgi: {_clip(context, 1000)}"
    system = ("Sen bir çalışma planlayıcısısın. Verilen ödevi/projeyi 2-6 küçük, sıralı alt göreve böl. "
              "Yalnız JSON ver: {\"subtasks\":[{\"title\":\"kısa başlık\",\"due\":\"YYYY-MM-DD veya boş\"}]}. "
              "Teslim tarihi verildiyse alt görev tarihlerini ona göre geriye doğru makul aralıklarla dağıt; "
              "verilmediyse tarihleri boş bırak.")
    try:
        answer = llm.ask(prompt, system, 500)
    except Exception as exc:
        _record_failure('modules/hoca_workspace.py:decompose_assignment')
        raise HocaWorkspaceError(f"Ödev parçalanamadı ({type(exc).__name__}). Biraz sonra tekrar dene.")
    m = re.search(r"\{.*\}", str(answer or ""), re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    items = data.get("subtasks") if isinstance(data, dict) else None
    planned = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sub_title = _clip(it.get("title"), _LABEL_MAX)
        if not sub_title:
            continue
        planned.append((sub_title, _clip(it.get("due"), 40)))
        if len(planned) >= _DECOMPOSE_MAX:
            break
    if len(planned) < _DECOMPOSE_MIN:
        # Asıl ödev zaten eklendi (kullanıcı elle alt görev ekleyebilir); yarım-kayıt
        # bırakmamak için hiçbir alt görev yazılmadan açık hata verilir.
        raise HocaWorkspaceError("Ödev planı eksik geldi (en az 2 alt görev gerekir). Biraz sonra tekrar dene.")
    subtasks = [add_assignment(profile, course_id, sub_title, due=sub_due,
                                origin="decomposed", parent_id=parent["id"])
                for sub_title, sub_due in planned]
    return {"parent": parent, "subtasks": subtasks}


def list_assignments(profile, course_id: int | None = None) -> list:
    if course_id is not None:
        return list(_require_course(profile, course_id)["assignments"])
    out = []
    for c in _state(profile):
        out.extend(c["assignments"])
    return out


def record_session(profile, course_id: int, topic: str, *, unclear: str | None = None,
                    solved: str | None = None, next_step: str | None = None) -> dict:
    """Oturum hafızası: konu başına anlaşılmayan nokta + çözülen soru + sonraki adım.
    Her çağrı mevcut girdiye ekler (liste), `next_step` ise üzerine yazar (tek güncel durum)."""
    course = _require_course(profile, course_id)
    topic_key = _clip(topic, _TOPIC_MAX)
    if not topic_key:
        raise HocaWorkspaceError("Konu boş olamaz.")
    session = course["sessions"].get(topic_key)
    if not isinstance(session, dict):
        session = {"unclear": [], "solved": [], "next_step": ""}
        course["sessions"][topic_key] = session
    if unclear:
        session["unclear"] = (session["unclear"] + [_clip(unclear, _TEXT_MAX)])[-_LIST_MAX:]
    if solved:
        session["solved"] = (session["solved"] + [_clip(solved, _TEXT_MAX)])[-_LIST_MAX:]
    if next_step is not None:
        session["next_step"] = _clip(next_step, _TEXT_MAX)
    session["updated"] = int(time.time())
    profile.save()
    return session


def get_session(profile, course_id: int, topic: str) -> dict | None:
    course = _require_course(profile, course_id)
    return course["sessions"].get(_clip(topic, _TOPIC_MAX))


# ---- 2. adım: salt-okunur kaynak (kitap/pdf) ------------------------------
# İkinci bir dosya okuyucu kurulmadı: mevcut, test edilmiş `modules/file_worker.py`
# (salt-okunur, izin kapsamı `file_ops._roots()` ile aynı) kullanılıyor. Video
# kaynağı `modules/hoca_video.py`'de ayrı kalıyor (resmî YouTube/altyazı yolu);
# web kaynağı henüz yok (Tavily/Vikipedi paneli, metin bağlamı değil).

_READABLE_SOURCE_TYPES = ("kitap", "pdf")
DEFAULT_SOURCE_MAX_CHARS = 6000


def read_source_text(ref: str, max_chars: int = DEFAULT_SOURCE_MAX_CHARS) -> str:
    """Bilinen klasörler altındaki bir kitap/PDF'ten salt-okunur metin çıkarır.
    `file_worker.extract` izin dışı/desteklenmeyen/okunamayan dosyada açıkça
    `HocaWorkspaceError` fırlatır; sessiz boş sonuç üretmez."""
    from modules import file_worker
    try:
        obs = file_worker.extract(ref)
    except file_worker.FileWorkerError as exc:
        raise HocaWorkspaceError(str(exc)) from exc
    if obs.reason_code != "OK":
        raise HocaWorkspaceError(f"Kaynak okunamadı ({obs.reason_code}): {ref}")
    text = "\n".join(loc.text for loc in obs.locations if loc.text)
    if not text:
        raise HocaWorkspaceError(f"Kaynaktan okunabilir metin çıkmadı: {ref}")
    return text[:max_chars]


def course_context(course: dict, max_chars: int = DEFAULT_SOURCE_MAX_CHARS) -> dict | None:
    """Dersin kitap/pdf kaynaklarından ders anlatımı için bağlam metni üretir.
    Okunamayan tek tek kaynaklar sessizce atlanır (`warnings`'te görünür, işlemi
    durdurmaz); hiçbiri okunamazsa `None` döner — çağıran "kaynak yok" yoluna düşer."""
    parts, warnings = [], []
    for src in course.get("sources", []):
        if src.get("type") not in _READABLE_SOURCE_TYPES:
            continue
        label = src.get("label") or src.get("ref", "")
        try:
            text = read_source_text(src["ref"], max_chars=max_chars)
        except HocaWorkspaceError as exc:
            warnings.append(f"{label}: {exc}")
            continue
        parts.append(f"[{label}]\n{text}")
    if not parts:
        return None
    labels = [src.get("label") or src.get("ref", "") for src in course.get("sources", [])
              if src.get("type") in _READABLE_SOURCE_TYPES]
    return {"text": "\n\n".join(parts)[:max_chars], "label": "; ".join(labels), "full": True, "warnings": warnings}
