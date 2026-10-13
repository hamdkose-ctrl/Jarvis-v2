"""Çıkmış soru kitapçıklarını (AÖL / MEB biçimi) ders ders ayrıştırır.

Kitapçıkta onlarca dersin soruları ve sonda cevap anahtarı birlikte durur. Eskiden metnin yalnız küçük bir
parçası yapay zekâya özetletiliyordu; sonuç yanlış dersleri karıştırıyordu. Burada her ders, her soru,
şıklar ve cevap anahtarı yapay zekâ kullanmadan, metinden doğrudan çıkarılır.
"""
from __future__ import annotations

import re
import threading
import uuid

_ANSWER_LOCK=threading.RLock()

_HDR = re.compile(r"^\s*\((\d{3})\)\s*(.*)$")
_NAME_END = re.compile(r"–\s*(\d+)(?:\s+\d+)?\s*$")          # "… – 1" (içindekilerde sonda sayfa no da olur)
_KEY_LINE = re.compile(r"^\s*(\d{1,2})\.\s+([A-E])\s*$")
_NOISE = re.compile(r"^\s*(?:\d+\.\s*OTURUM|\d{1,3}|TT\s*[\d.]+|[A-Z]\s*KİTAPÇIĞI.*)\s*$")
_LETTERS = "ABCDE"


def _clean(s: str) -> str:
    s = s.replace("\t", " ").replace("­", "")
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)               # satır sonu tirelemesi: "sürdürüle-\nbilirlik"
    s = re.sub(r"\b([A-ZÇĞİÖŞÜ]) (?=[a-zçğıöşü])", r"\1", s)    # "T arım" -> "Tarım" (PDF'in ayırdığı ilk harf)
    return re.sub(r"[  ]+", " ", s)


def _norm_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^SEÇ\.\s*", "SEÇMELİ ", name)
    m = _NAME_END.search(name)
    if m:
        name = name[:m.start()].strip() + " – " + m.group(1)
    return name


def _match_key(code: str, name: str) -> str:
    """Kitapçıktaki ad ile cevap anahtarındaki ad küçük farklar taşıyabilir ("SEÇ." / "SEÇMELİ")."""
    m = _NAME_END.search(name)
    num = m.group(1) if m else ""
    core = re.sub(r"SEÇMELİ|SEÇ\.|[^A-ZÇĞİÖŞÜ]", "", name.upper())[:6]
    return f"{code}|{num}|{core}"


def _headers(lines: list[str]):
    """(satır_no, kod, ad, ad_bittiği_satır) — ad birden çok satıra bölünmüş olabilir."""
    out, i = [], 0
    while i < len(lines):
        m = _HDR.match(lines[i])
        if m:
            name, j = m.group(2), i
            while not _NAME_END.search(name) and j + 1 < len(lines) and j - i < 2:
                j += 1
                name += " " + lines[j].strip()
            if _NAME_END.search(name):
                out.append((i, m.group(1), _norm_name(name), j))
                i = j + 1
                continue
        i += 1
    return out


def _split_options(body: str) -> tuple[str, dict]:
    parts = re.split(r"(?:(?<=\s)|^)([A-E])\)\s*", body)
    stem, opts = parts[0], {}
    for k in range(1, len(parts) - 1, 2):
        opts[parts[k]] = re.sub(r"\s+", " ", parts[k + 1]).strip()
    return re.sub(r"\s+", " ", stem).strip(), opts


def _questions(segment: str) -> list[dict]:
    lines = [ln for ln in segment.split("\n") if not _NOISE.match(ln)]
    text = "\n".join(lines)
    starts, want = [], 1
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\.\s+", text):
        if int(m.group(1)) == want:
            starts.append((want, m.start(), m.end()))
            want += 1
    qs = []
    for k, (n, _s, e) in enumerate(starts):
        end = starts[k + 1][1] if k + 1 < len(starts) else len(text)
        stem, opts = _split_options(text[e:end])
        if len(opts) >= 3:
            qs.append({"n": n, "text": stem, "options": opts})
    return qs


def parse(text: str) -> dict:
    """{ders_anahtarı: {"code","name","questions":[{n,text,options}], "answers":{n: harf}}}"""
    text = _clean(text or "")
    cut = text.find("CEVAP ANAHTARI")
    body, key = (text[:cut], text[cut:]) if cut >= 0 else (text, "")
    courses: dict[str, dict] = {}
    blines = body.split("\n")
    hdrs = _headers(blines)
    for k, (i, code, name, j) in enumerate(hdrs):
        end = hdrs[k + 1][0] if k + 1 < len(hdrs) else len(blines)
        qs = _questions("\n".join(blines[j + 1:end]))
        if len(qs) >= 3:                                         # içindekiler satırları soru içermez
            mk = _match_key(code, name)
            c = courses.setdefault(mk, {"code": code, "name": name, "questions": [], "answers": {}})
            existing = {q["n"] for q in c["questions"]}
            for q in qs:
                if q["n"] not in existing:
                    c["questions"].append(q)
                    existing.add(q["n"])
    if key:
        klines = key.split("\n")
        khdrs = _headers(klines)
        for k, (i, code, name, j) in enumerate(khdrs):
            end = khdrs[k + 1][0] if k + 1 < len(khdrs) else len(klines)
            ans = {}
            for ln in klines[j + 1:end]:
                m = _KEY_LINE.match(ln)
                if m:
                    ans[int(m.group(1))] = m.group(2)
            mk = _match_key(code, name)
            if mk in courses and ans:
                courses[mk]["answers"] = ans
    return courses


def course_label(c: dict) -> str:
    """Kullanıcıya gösterilen ad: "BİYOLOJİ – 1 (441)"."""
    return f"{c['name']} ({c['code']})"


# ============================================================ soru bankası, dersler, konu etiketi
import json as _json
import random as _random
import time as _time
from datetime import date as _date, datetime as _dt, timedelta as _td

_BANK_V = 1
from contextvars import ContextVar
from functools import wraps
_bank_snapshot = ContextVar('jarvis_exam_snapshot', default=None)


def _bank_operation(fn):
    @wraps(fn)
    def run(profile, *args, **kwargs):
        active = _bank_snapshot.get()
        if active is not None and active[0] is profile:
            return fn(profile, *args, **kwargs)
        snapshot = bank(profile)
        token = _bank_snapshot.set((profile, snapshot))
        try:
            return fn(profile, *args, **kwargs)
        finally:
            _bank_snapshot.reset(token)
    return run



def _study():
    from modules import study
    return study


def _exam_bank(profile, item) -> dict:
    """Bir çıkmış soru dosyasının ayrıştırılmış hali (önbellekli: <id>.exam.json)."""
    st = _study()
    f = st._dir(profile) / f"{item['id']}.exam.json"
    try:
        data = _json.loads(f.read_text(encoding="utf-8"))
        if data.get("v") == _BANK_V:
            return data["courses"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        text = (st._dir(profile) / f"{item['id']}.txt").read_text(encoding="utf-8")
    except OSError:
        return {}
    courses = parse(text)
    try:
        f.write_text(_json.dumps({"v": _BANK_V, "courses": courses}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return courses


def bank(profile) -> dict:
    """{ders_anahtarı: {"label","code","name","items":[{id, year, n, text, options, answer}]}} — son 3 yıl."""
    active = _bank_snapshot.get()
    if active is not None and active[0] is profile:
        return active[1]
    st = _study()
    s = st._state(profile)
    years = set(st._recent_exam_years(s))
    out: dict[str, dict] = {}
    for item in s.get("docs", []):
        if item.get("kind") != "exam" or int(item.get("year") or 0) not in years:
            continue
        y = int(item["year"])
        for mk, c in _exam_bank(profile, item).items():
            row = out.setdefault(mk, {"label": course_label(c), "code": c["code"], "name": c["name"], "items": []})
            for q in c.get("questions", []):
                # Aynı yılın birden fazla dönem/oturumunda aynı soru numarası olabilir. Kaynak belge kimliği qid'yi benzersiz tutar.
                row["items"].append({"id": f"{mk}#{item['id']}#{y}#{q['n']}", "legacy_id": f"{mk}#{y}#{q['n']}",
                                     "doc_id": int(item["id"]),
                                     "year": y, "period": str(item.get("period") or ""),
                                     "session": str(item.get("session") or ""), "n": q["n"], "text": q["text"],
                                     "options": q["options"], "answer": c.get("answers", {}).get(str(q["n"]))
                                     or c.get("answers", {}).get(q["n"])})
    for row in out.values():
        row["items"].sort(key=lambda q: (-q["year"], q["n"]))
    return out


@_bank_operation
def courses(profile) -> list[dict]:
    """Kitapçıklarda bulunan dersler (seçim listesi için)."""
    sel = set(_study()._state(profile).get("courses") or [])
    rows = [{"key": k, "label": v["label"], "count": len(v["items"]), "years": sorted({q["year"] for q in v["items"]}, reverse=True),
             "selected": k in sel} for k, v in bank(profile).items()]
    return sorted(rows, key=lambda r: (not r["selected"], r["label"]))


def set_courses(profile, keys) -> list[dict]:
    st = _study()
    valid = set(bank(profile))
    st._state(profile)["courses"] = [k for k in (keys or []) if k in valid][:8]
    st._state(profile).pop("exam_analysis", None)
    profile.save()
    return courses(profile)


def suggest_courses(profile) -> list[str]:
    """Hiç ders seçilmemişse: kitap adlarıyla eşleşen dersler (ör. "Biyoloji_1.pdf" -> BİYOLOJİ – 1)."""
    st = _study()
    books = [d["title"] for d in st._state(profile).get("docs", []) if d.get("kind") != "exam"]
    norm = lambda t: re.sub(r"[^a-zçğıöşü0-9]", "", t.replace("I", "ı").replace("İ", "i").lower())
    out = []
    for k, v in bank(profile).items():
        nm = norm(re.sub(r"SEÇMELİ|–.*$", "", v["name"]))
        num = (re.search(r"–\s*(\d+)", v["name"]) or [None, ""])[1]
        for b in books:
            nb = norm(b)
            if nm and nm in nb and (not num or re.search(rf"(?<!\d){num}(?!\d)", b)) and "seçmeli" not in v["name"].lower():
                out.append(k)
                break
    return out[:4]


@_bank_operation
def selected(profile) -> list[str]:
    st = _study()
    s = st._state(profile)
    b = bank(profile)
    sel = [k for k in (s.get("courses") or []) if k in b]
    if not sel:
        sel = suggest_courses(profile)
        if sel:
            s["courses"] = sel
            profile.save()
    return sel


def tag_topics(profile, mk: str, force: bool = False) -> dict:
    """Bir dersin bütün çıkmış sorularını tek yapay zekâ isteğiyle konulara ayırır (önbellekli)."""
    from modules import llm
    st = _study()
    s = st._state(profile)
    b = bank(profile).get(mk)
    if not b:
        return {}
    cache = s.setdefault("topics", {}).get(mk) or {}
    ids = [q["id"] for q in b["items"]]
    if not force and ids and all(i in cache for i in ids):
        return cache
    lines = []
    for q in b["items"]:
        opts = " | ".join(f"{k}) {v[:60]}" for k, v in q["options"].items())
        lines.append(f"[{q['id']}] {q['text'][:420]} || {opts}")
    prompt = ("Aşağıda '" + b["label"] + "' dersinin son yıllardaki sınav soruları var. Her soruyu dersin müfredatındaki "
              "TEK bir ana konuya ata. Konu adları kısa (1-4 kelime), Türkçe, ders kitabının ünite/konu başlıklarına benzer olsun; "
              "aynı konuya her yerde aynı adı ver ve toplamda en fazla 10 farklı konu kullan. YALNIZ JSON döndür: "
              '{"t": {"<soru kimliği>": "<konu>"}}\n\n' + "\n".join(lines))
    raw = llm.ask(prompt, system="Sınav sorularını konulara ayıran dikkatli bir öğretmensin. Yalnız JSON üret.", max_tokens=2500)
    data = st._json_object(raw) or {}
    tags = data.get("t") if isinstance(data.get("t"), dict) else data
    out = {i: str(tags.get(i) or "").strip()[:40] for i in ids if isinstance(tags, dict) and str(tags.get(i) or "").strip()}
    if out:
        s["topics"][mk] = out
        profile.save()
    return out


@_bank_operation
def course_analysis(profile, mk: str, tags: dict | None = None) -> dict:
    """Konu ağırlıkları (yüzde), yıl yıl sayılar ve yükselen konular — yapay zekâsız, etiketlerden hesaplanır."""
    b = bank(profile).get(mk) or {"items": [], "label": mk}
    tags = tags if tags is not None else (_study()._state(profile).get("topics", {}).get(mk) or {})
    years = sorted({q["year"] for q in b["items"]}, reverse=True)
    total, per_year = {}, {y: {} for y in years}
    for q in b["items"]:
        t = tags.get(q["id"]) or tags.get(q.get("legacy_id")) or "Diğer"
        total[t] = total.get(t, 0) + 1
        per_year[q["year"]][t] = per_year[q["year"]].get(t, 0) + 1
    n = sum(total.values()) or 1
    top = [{"name": t, "count": c, "pct": round(c * 100 / n, 1)} for t, c in sorted(total.items(), key=lambda kv: -kv[1])]
    rising = []
    if len(years) >= 2:
        new, old = per_year[years[0]], per_year[years[-1]]
        sn, so = sum(new.values()) or 1, sum(old.values()) or 1
        for t, c in new.items():
            d = c / sn - old.get(t, 0) / so
            if d >= .05:
                rising.append({"name": t, "delta_pct": round(d * 100, 1), "newest_count": c})
        rising.sort(key=lambda x: -x["delta_pct"])
    return {"key": mk, "label": b["label"], "years": years, "question_count": len(b["items"]), "top_topics": top,
            "rising_topics": rising[:5], "with_key": sum(1 for q in b["items"] if q.get("answer"))}


# ============================================================ soru çözme ve başarı
def _results(profile) -> list:
    return _study()._state(profile).setdefault("results", [])


@_bank_operation
def stats(profile) -> dict:
    """Ders ve konu bazında başarı: {ders: {"label", "topics":[{name, weight, asked, correct, pct}], "asked","correct"}}"""
    st = _study()
    s = st._state(profile)
    res = _results(profile)
    out = {}
    for mk in selected(profile):
        an = course_analysis(profile, mk)
        tags = s.get("topics", {}).get(mk) or {}
        rows = {t["name"]: {"name": t["name"], "weight": t["pct"], "asked": 0, "correct": 0} for t in an["top_topics"]}
        for r in res:
            if r.get("mk") != mk:
                continue
            t = r.get("topic") or tags.get(r.get("q")) or "Diğer"
            row = rows.setdefault(t, {"name": t, "weight": 0, "asked": 0, "correct": 0})
            row["asked"] += 1
            row["correct"] += 1 if r.get("ok") else 0
        topics = []
        for row in rows.values():
            row["pct"] = round(row["correct"] * 100 / row["asked"]) if row["asked"] else None
            topics.append(row)
        topics.sort(key=lambda r: -r["weight"])
        asked = sum(r["asked"] for r in topics)
        out[mk] = {"label": an["label"], "topics": topics, "asked": asked, "correct": sum(r["correct"] for r in topics),
                   "analysis": an}
    return out


@_bank_operation
def related_questions(profile, text: str, k: int = 5, mk: str | None = None, topic: str | None = None) -> list[dict]:
    """Seçili derslerin çıkmış sorularından metne en yakın olanlar (kelime eşleşmesi; yapay zekâ/kota kullanmaz).
    topic verilirse önce o konuya etiketlenmiş sorular gelir."""
    s = _study()._state(profile)
    words = {w[:6] for w in re.findall(r"\w{3,}", (text or "").replace("I", "ı").replace("İ", "i").lower())}
    out = []
    for key in ([mk] if mk else selected(profile)):
        b = bank(profile).get(key)
        if not b:
            continue
        tags = s.get("topics", {}).get(key) or {}
        for q in b["items"]:
            body = q["text"] + " " + " ".join(q["options"].values())
            qw = {w[:6] for w in re.findall(r"\w{3,}", body.replace("I", "ı").replace("İ", "i").lower())}
            qtopic = tags.get(q["id"]) or tags.get(q.get("legacy_id"))
            score = len(words & qw) + (10 if topic and qtopic == topic else 0)
            if score:
                opts = " ".join(f"{a}) {v}" for a, v in q["options"].items())
                meta = [str(q["year"])] + [x for x in (q.get("period"), q.get("session")) if x]
                out.append({"score": score, "title": b["label"], "kind": "exam", "year": q["year"],
                            "period": q.get("period", ""), "session": q.get("session", ""),
                            "exam_label": " · ".join(meta),
                            "chunk": f"{q['text']}\n{opts}" + (f"\n(Cevap: {q['answer']})" if q.get("answer") else "")})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


def _priority(row) -> float:
    """Sınavda sık çıkan + başarısı düşük ya da hiç çalışılmamış konu önce gelir."""
    succ = (row["correct"] / row["asked"]) if row["asked"] >= 2 else .5
    return (row["weight"] or 2) * (1.6 - succ) * (1.25 if row["asked"] == 0 else 1)


@_bank_operation
def focus(profile, limit: int = 3) -> list[dict]:
    rows = []
    for mk, c in stats(profile).items():
        for t in c["topics"]:
            if t["name"] == "Diğer":
                continue
            why = ("hiç çalışılmadı" if not t["asked"] else
                   f"başarı %{t['pct']}" if t["pct"] is not None else "az çalışıldı")
            rows.append({"course": c["label"], "mk": mk, "topic": t["name"], "weight": t["weight"], "why": why,
                         "score": _priority(t)})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


@_bank_operation
def quiz_next(profile, mk: str | None = None, topic: str | None = None) -> dict | None:
    s = _study()._state(profile)
    keys = [mk] if mk else selected(profile)
    b = bank(profile)
    recent_ok = {r["q"] for r in _results(profile)[-200:] if r.get("ok")}
    last = {r["q"] for r in _results(profile)[-15:]}
    st = stats(profile)
    pool, weights = [], []
    repeats, repeat_weights = [], []
    for k in keys:
        if k not in b:
            continue
        tags = s.get("topics", {}).get(k) or {}
        trow = {t["name"]: t for t in (st.get(k) or {}).get("topics", [])}
        for q in b[k]["items"]:
            if not q.get("answer") or q["answer"] not in q["options"]:
                continue
            t = tags.get(q["id"]) or tags.get(q.get("legacy_id")) or "Diğer"
            if topic and t != topic:
                continue
            w = _priority(trow[t]) if t in trow else 1.0
            if q["id"] in recent_ok:
                w *= .15                                      # doğru bildiğin soru seyrek tekrar gelir
            if q["id"] in last:
                repeats.append((k,q,t));repeat_weights.append(max(w,.05))
            else:
                pool.append((k,q,t));weights.append(max(w,.05))
    if not pool and repeats:
        latest=(_results(profile)[-1].get("q") if _results(profile) else None)
        eligible=[i for i,x in enumerate(repeats) if x[1]["id"]!=latest] or list(range(len(repeats)))
        pool=[repeats[i] for i in eligible];weights=[repeat_weights[i] for i in eligible]
    if not pool:
        return None
    k, q, t = _random.choices(pool, weights=weights, k=1)[0]
    attempt=uuid.uuid4().hex
    s["quiz_attempt"]={"id":attempt,"qid":q["id"]};profile.save()
    return {"attempt_id":attempt,"id": q["id"], "course": b[k]["label"], "mk": k, "year": q["year"],
            "period": q.get("period", ""), "session": q.get("session", ""),
            "n": q["n"], "text": q["text"], "options": q["options"], "topic": t}


def _find(profile, qid: str):
    mk = qid.split("#", 1)[0]
    items = (bank(profile).get(mk) or {}).get("items", [])
    for q in items:
        if q["id"] == qid:
            return mk, q
    legacy = [q for q in items if q.get("legacy_id") == qid]
    return (mk, legacy[0]) if len(legacy) == 1 else (mk, None)


@_bank_operation
def quiz_answer(profile, qid: str, choice: str, attempt_id: str = '') -> dict:
    with _ANSWER_LOCK:
        attempt=_study()._state(profile).get('quiz_attempt') or {}
        if attempt_id and (attempt.get('id')!=attempt_id or attempt.get('qid')!=qid):
            raise ValueError('Bu soru denemesi artık aktif değil; yeni soruyu cevapla.')
        if attempt.get('qid')==qid and attempt.get('result'):
            return dict(attempt['result'])
        result=_grade(profile,qid,choice)
        if attempt.get('qid')==qid:
            attempt['result']=result;profile.save()
        return result


def _grade(profile, qid: str, choice: str, question=None) -> dict:
    mk, q = _find(profile, qid) if question is None else (question['mk'],question)
    if not q or not q.get("answer"):
        raise ValueError("Bu sorunun cevap anahtarı bulunamadı.")
    choice = str(choice or "").strip().upper()
    if choice not in q["options"]:
        raise ValueError("Soruda bulunan şıklardan birini seç.")
    ok = choice == q["answer"]
    tags = _study()._state(profile).get("topics", {}).get(mk) or {}
    topic = q.get("topic") or tags.get(qid) or tags.get(q.get("legacy_id")) or "Diğer"
    res = _results(profile)
    res.append({"q": qid, "mk": mk, "topic": topic, "ok": ok, "choice": choice,
                "ts": _dt.now().strftime("%Y-%m-%d %H:%M")})
    del res[:-2000]
    profile.save()
    return {"ok": ok, "answer": q["answer"], "topic": topic}


@_bank_operation
def explain(profile, qid: str, choice: str = "") -> str:
    """Sorunun çözümünü kitaba dayanarak açıklar (yalnız istenince: kota harcamasın)."""
    mk, q = _find(profile, qid)
    if not q:
        raise ValueError("Soru bulunamadı.")
    opts = "\n".join(f"{k}) {v}" for k, v in q["options"].items())
    ask = (f"Şu sınav sorusunu açıkla. Doğru cevap (resmî cevap anahtarı): {q.get('answer') or 'bilinmiyor'}."
           + (f" Öğrencinin cevabı: {choice}." if choice else "")
           + " Neden doğru olduğunu ve diğer şıkların neden yanlış olduğunu kısa ve öğretici anlat; ilgili konuyu 2-3 cümleyle hatırlat.\n\n"
           + q["text"] + "\n" + opts)
    return _study().ask(profile, ask, "teacher")


@_bank_operation
def readiness(profile) -> int:
    """Seçili derslerde sınav ağırlığına göre ölçülmüş hazırlık yüzdesi. Çözülmemiş konu 0 kabul edilir."""
    num = den = 0.0
    for c in stats(profile).values():
        for t in c["topics"]:
            if t["name"] == "Diğer":
                continue
            w = float(t.get("weight") or 0)
            den += w
            num += w * float(t.get("pct") or 0)
    return round(num / den) if den else 0


@_bank_operation
def today(profile) -> dict:
    """Tek tuşluk bugünkü çalışma hedefi: en önemli zayıf konu + anlatım/soru adımı."""
    rows = focus(profile, 1)
    p = plan(profile, 1)
    target = rows[0] if rows else None
    if not target:
        return {"target": None, "readiness": readiness(profile), "days_left": p.get("days_left"),
                "note": "Önce dersini seçip son 3 yıl sorularını analiz et."}
    minutes = int(plan_cfg(profile).get("minutes") or 60)
    lesson_min = max(10, round(minutes * .45))
    question_count = max(5, round((minutes - lesson_min) / 3))
    return {"target": target, "readiness": readiness(profile), "days_left": p.get("days_left"),
            "lesson_minutes": lesson_min, "questions": question_count,
            "note": f"{lesson_min} dk konu anlatımı + {question_count} çıkmış soru"}


def _public_question(profile, qid: str) -> dict | None:
    mk, q = _find(profile, qid)
    if not q:
        return None
    b = bank(profile).get(mk) or {}
    tags = _study()._state(profile).get("topics", {}).get(mk) or {}
    topic = q.get("topic") or tags.get(qid) or tags.get(q.get("legacy_id")) or "Diğer"
    return {"id": q["id"], "course": b.get("label", mk), "mk": mk, "year": q["year"],
            "period": q.get("period", ""), "session": q.get("session", ""), "n": q["n"],
            "text": q["text"], "options": q["options"], "topic": topic}


@_bank_operation
def wrong_summary(profile) -> dict:
    """Yanlış defteri. Yanlıştan sonra 1 gün, ilk doğru tekrardan sonra 3 gün; iki doğru tekrar öğrenildi sayılır.

    Uzun süre tekrar edilmeyen aktif yanlışlar 7 günlük üst sınırla yeniden öne çıkar.
    """
    grouped: dict[str, list[dict]] = {}
    for r in _results(profile):
        grouped.setdefault(str(r.get("q") or ""), []).append(r)
    now = _dt.now()
    active, learned = [], 0
    for qid, rows in grouped.items():
        if not qid or not any(not r.get("ok") for r in rows):
            continue
        last_wrong = max(i for i, r in enumerate(rows) if not r.get("ok"))
        after = rows[last_wrong + 1:]
        correct_after = 0
        for r in after:
            if r.get("ok"):
                correct_after += 1
            else:
                correct_after = 0
        if correct_after >= 2:
            learned += 1
            continue
        base_row = after[-1] if after else rows[last_wrong]
        try:
            base_dt = _dt.strptime(str(base_row.get("ts") or ""), "%Y-%m-%d %H:%M")
        except ValueError:
            base_dt = now - _td(days=7)
        wait = 3 if correct_after == 1 else 1
        due = base_dt + _td(days=wait)
        # Hiç dönülmeyen yanlış 7 günü aşınca sürekli gecikmiş olarak önde kalır.
        q = _public_question(profile, qid)
        if not q:
            continue
        active.append({**q, "correct_after": correct_after, "due": due.strftime("%Y-%m-%d"),
                       "due_now": due <= now, "last": str(base_row.get("ts") or "")})
    active.sort(key=lambda x: (not x["due_now"], x["due"], x["course"], x["n"]))
    return {"active": active, "due": [x for x in active if x["due_now"]], "learned": learned}


@_bank_operation
def wrong_next(profile) -> dict | None:
    w = wrong_summary(profile)
    rows = w["due"] or w["active"]
    if not rows:return None
    q=dict(rows[0]);attempt=uuid.uuid4().hex
    _study()._state(profile)['quiz_attempt']={'id':attempt,'qid':q['id']};profile.save()
    q['attempt_id']=attempt;return q


@_bank_operation
def mock_start(profile, count: int = 10) -> dict:
    """Son 3 yılın gerçek soru havuzundan dağılımı koruyan 10/20/tam deneme başlatır."""
    pool = []
    snapshots = {}
    b = bank(profile)
    for mk in selected(profile):
        for q in (b.get(mk) or {}).get("items", []):
            if q.get("answer") and q["answer"] in q["options"]:
                pool.append(q["id"])
                tags = _study()._state(profile).get('topics', {}).get(mk) or {}
                topic = tags.get(q['id']) or tags.get(q.get('legacy_id')) or 'Diğer'
                snapshots[q['id']] = {**q, 'mk': mk, 'course': b[mk]['label'], 'topic': topic}
    if not pool:
        raise ValueError("Deneme için cevap anahtarı olan çıkmış soru bulunamadı.")
    _random.shuffle(pool)  # soru havuzunun kendisi geçmiş dağılımı taşıdığı için uniform seçim dağılımı korur
    count = int(count or 0)
    if count <= 0:
        chosen = pool
    else:
        chosen = pool[:min(max(1, count), len(pool))]
    sess = {"id": uuid.uuid4().hex, "qids": chosen, "answers": {},
            "started": _dt.now().strftime("%Y-%m-%d %H:%M"), "finished": "",
            "questions":{qid:snapshots[qid] for qid in chosen}}
    _study()._state(profile)["mock_session"] = sess
    profile.save()
    return mock_status(profile)


@_bank_operation
def mock_status(profile) -> dict:
    sess = _study()._state(profile).get("mock_session") or {}
    qids = list(sess.get("qids") or [])
    ans = dict(sess.get("answers") or {})
    if not qids:
        return {"active": False, "total": 0, "answered": 0, "correct": 0, "finished": False, "breakdown": []}
    current=None
    remaining=next((qid for qid in qids if qid not in ans),None)
    if remaining:
        stored=(sess.get('questions') or {}).get(remaining)
        current={k:v for k,v in stored.items() if k not in ('answer','legacy_id','doc_id')} if stored else _public_question(profile,remaining)
        if not current:raise ValueError('Denemenin kaynağı artık mevcut değil; yeni deneme başlat.')
    correct = sum(1 for x in ans.values() if x.get("ok"))
    finished = len(ans) >= len(qids)
    if finished and not sess.get("finished"):
        sess["finished"] = _dt.now().strftime("%Y-%m-%d %H:%M")
        profile.save()
    topics = {}
    for qid, a in ans.items():
        t = str(a.get("topic") or "Diğer")
        row = topics.setdefault(t, {"topic": t, "asked": 0, "correct": 0})
        row["asked"] += 1; row["correct"] += 1 if a.get("ok") else 0
    breakdown = sorted(({**r, "pct": round(r["correct"] * 100 / r["asked"])} for r in topics.values()),
                       key=lambda r: (r["pct"], -r["asked"], r["topic"]))
    return {"active": True, "id": sess.get("id"), "total": len(qids), "answered": len(ans), "correct": correct,
            "finished": finished, "current": current, "breakdown": breakdown, "started": sess.get("started", ""),
            "finished_at": sess.get("finished", "")}


@_bank_operation
def mock_answer(profile, qid: str, choice: str, session_id: str = '') -> dict:
    with _ANSWER_LOCK:
        return _mock_answer(profile,qid,choice,session_id)


def _mock_answer(profile, qid: str, choice: str, session_id: str = '') -> dict:
    sess = _study()._state(profile).get("mock_session") or {}
    if session_id and session_id!=sess.get('id'):
        raise ValueError('Bu deneme artık aktif değil; güncel denemeyi cevapla.')
    if qid not in (sess.get("qids") or []):
        raise ValueError("Bu soru aktif denemeye ait değil.")
    if qid in (sess.get("answers") or {}):
        return mock_status(profile)
    r = _grade(profile, qid, choice, (sess.get('questions') or {}).get(qid))
    sess.setdefault("answers", {})[qid] = {"choice": str(choice or "").upper()[:1], "ok": bool(r["ok"]),
                                             "answer": r["answer"], "topic": r["topic"]}
    profile.save()
    return {"result": r, "status": mock_status(profile)}


# ============================================================ ders programı
DAYS_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def plan_cfg(profile) -> dict:
    c = _study()._state(profile).setdefault("plan_cfg", {})
    c.setdefault("minutes", 60)
    c.setdefault("days", [0, 1, 2, 3, 4, 5])
    c.setdefault("time", "20:00")
    c.setdefault("exam_date", "")
    try:c['minutes']=max(15,min(480,int(c['minutes'])))
    except (ValueError,TypeError):c['minutes']=60
    raw_days=c.get('days')
    c['days']=sorted({d for d in raw_days if isinstance(d,int) and 0<=d<=6}) if isinstance(raw_days,list) else []
    if not c['days']:c['days']=[0,1,2,3,4]
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(c.get('time'))):c['time']='20:00'
    return c


def set_plan_cfg(profile, cfg: dict) -> dict:
    if "time" in cfg:
        from datetime import time as _time
        try:
            _time.fromisoformat(str(cfg["time"]).zfill(5))
        except ValueError:
            raise ValueError("Geçerli saat gir: 00:00–23:59")
    if cfg.get("exam_date"):
        _date.fromisoformat(str(cfg["exam_date"]))
    had_reminders = any(str(ev.get("title", "")).startswith("Çalışma: ") for ev in profile.data.get("events", []))
    c = plan_cfg(profile)
    if "minutes" in cfg:
        c["minutes"] = max(15, min(480, int(cfg["minutes"] or 60)))
    if "days" in cfg:
        c["days"] = sorted({int(d) for d in cfg["days"] if 0 <= int(d) <= 6}) or [0, 1, 2, 3, 4]
    if "time" in cfg and re.fullmatch(r"\d{1,2}:\d{2}", str(cfg["time"])):
        c["time"] = str(cfg["time"]).zfill(5)
    if "exam_date" in cfg:
        d = str(cfg["exam_date"] or "")
        c["exam_date"] = d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""
    profile.save()
    if had_reminders:
        set_reminders(profile)
    return plan(profile)


@_bank_operation
def plan(profile, days_ahead: int = 7) -> dict:
    """Haftalık program: sık çıkan ve zayıf konulara daha çok zaman. Yapay zekâ kullanmaz (anında, kotasız)."""
    cfg = plan_cfg(profile)
    rows = []
    for mk, c in stats(profile).items():
        for t in c["topics"]:
            if t["name"] != "Diğer":
                rows.append({"course": c["label"], "mk": mk, "topic": t["name"], "score": _priority(t)})
    today = _date.today()
    exam = None
    try:
        exam = _date.fromisoformat(cfg["exam_date"]) if cfg.get("exam_date") else None
    except ValueError:
        exam = None
    left = (exam - today).days if exam else None
    if not rows:
        return {"cfg": cfg, "days": [], "days_left": left, "note": "Program için önce Derslerim'den dersini seç ve soruları analiz et."}
    rows.sort(key=lambda r: -r["score"])
    tot = sum(r["score"] for r in rows) or 1
    # konuları puanlarıyla orantılı sıraya diz (en büyük kalan yöntemi), sonra günlere dağıt
    seq, acc = [], {r["topic"] + r["mk"]: 0.0 for r in rows}
    study_days = []
    d = today
    while len(study_days) < days_ahead and (not exam or d <= exam):
        if d.weekday() in cfg["days"]:
            study_days.append(d)
        d += _td(days=1)
    for _ in study_days:
        for r in rows:
            acc[r["topic"] + r["mk"]] += r["score"] / tot
        best = max(rows, key=lambda r: acc[r["topic"] + r["mk"]])
        acc[best["topic"] + best["mk"]] -= 1
        seq.append(best)
    m = cfg["minutes"]
    out = []
    for i, (day, main) in enumerate(zip(study_days, seq)):
        review = rows[(i + 1) % len(rows)] if len(rows) > 1 else main
        is_exam_eve = exam and (exam - day).days <= 2
        out.append({"date": day.isoformat(), "day": DAYS_TR[day.weekday()], "time": cfg["time"],
                    "blocks": ([{"kind": "deneme", "text": "Genel tekrar + karışık çıkmış soru denemesi", "minutes": m}]
                               if is_exam_eve else
                               [{"kind": "konu", "course": main["course"], "topic": main["topic"], "minutes": round(m * .6)},
                                {"kind": "soru", "course": review["course"], "topic": review["topic"], "minutes": m - round(m * .6),
                                 "questions": max(5, (m - round(m * .6)) // 3)}])})
    return {"cfg": cfg, "days": out, "days_left": left}


@_bank_operation
def set_reminders(profile) -> int:
    """Programdaki önümüzdeki günler için Jarvis hatırlatmaları kurar (bilgisayar + telefon bildirimi)."""
    p = plan(profile)
    for ev in list(profile.data.get("events", [])):
        if str(ev.get("title", "")).startswith("Çalışma: ") and ev.get("when", "") >= _date.today().isoformat():
            profile.delete_event(ev["id"])
    n = 0
    for d in p["days"]:
        txt = " + ".join(f"{b.get('topic') or b['text']} {b['minutes']} dk" for b in d["blocks"])
        profile.add_event("Çalışma: " + txt, f"{d['date']}T{d['time']}")
        n += 1
    return n
