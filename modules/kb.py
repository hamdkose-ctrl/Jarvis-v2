"""Bilgi tabanı: kullanıcının yüklediği belgelerden soru yanıtlama ("kira bedeli hangi dosyadaydı?").

Belge metni ~/.jarvis/kb/<kullanıcı>/<id>.txt olarak saklanır ve aynı klasördeki arama.sqlite (SQLite FTS5) içinde
sayfa/slayt/Excel sayfası bilgisiyle parçalara bölünüp dizinlenir. Yalnız kullanıcının yüklediği dosyalar girer
(Bilgi tabanı sayfası ve sohbete eklenen dosyalar); disk taranmaz. Belge listesi profil verisinde ('kb') durur.
"""
from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path

from config import DATA_DIR
from modules import docs
from modules.diagnostics import record_failure as _record_failure
from modules import llm
from modules.llm import ask

ROOT = DATA_DIR / "kb"
_TEXT_EXT = {".txt", ".md", ".csv", ".html", ".htm"}
_CHUNK = 1500


def _dir(profile) -> Path:
    d = ROOT / profile.slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _docs(profile) -> list[dict]:
    return profile.data.setdefault("kb", [])


def list_docs(profile) -> list[dict]:
    return list(_docs(profile))


def _signature(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def add(profile, path: str) -> dict:
    """Belgeyi okuyup bilgi tabanına ekler. Hata olursa ValueError/FileNotFoundError fırlatır.

    Aynı dosya değişmeden tekrar eklenirse mevcut kayıt döner; değişmişse eski kaydın yerine geçer.
    """
    p = Path(path)
    sig = _signature(p)
    for d in list(_docs(profile)):
        if d.get("path") == str(p):
            # Kodlama düzeltmesinden önce eklenen metin dosyaları (cp1254 harfleri silinmiş olabilir) yeniden okunur.
            if d.get("sig") == sig and (d.get("v") == 2 or p.suffix.lower() not in _TEXT_EXT):
                return d
            remove(profile, d["id"])
    text = docs.read_document(path, keep_pages=True, cache=True).strip()
    if not text:
        raise ValueError(docs.no_text_message(path))
    entry = {"id": profile._new_id(), "title": p.name, "path": str(p), "chars": len(text), "sig": sig, "v": 2,
             "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
    (_dir(profile) / f"{entry['id']}.txt").write_text(text, encoding="utf-8")
    _docs(profile).append(entry)
    profile.save()
    _index(profile, entry, text)
    return entry


def remember(profile, path: str) -> dict | None:
    """Sohbete eklenen dosyayı sessizce aranabilir yapar; okunamazsa sohbeti bozmaz."""
    if Path(path).suffix.lower() not in docs.SUPPORTED:
        return None
    try:
        return add(profile, path)
    except (ValueError, OSError, RuntimeError):
        _record_failure('modules/kb.py:remember')
        return None


def remove(profile, doc_id: int) -> None:
    profile.data["kb"] = [d for d in _docs(profile) if d["id"] != doc_id]
    try:
        (_dir(profile) / f"{doc_id}.txt").unlink(missing_ok=True)
        (_dir(profile) / f"{doc_id}.emb.json").unlink(missing_ok=True)
    except OSError:
        pass
    con = _db(profile)
    if con is not None:
        with con:
            con.execute("DELETE FROM parca WHERE doc = ?", (doc_id,))
        con.close()
    profile.save()


def clear(profile) -> None:
    profile.data["kb"] = []
    shutil.rmtree(_dir(profile), ignore_errors=True)
    profile.save()


def _norm(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


# Konum işaretleri: PDF sayfa sonu (\f), MarkItDown slayt/Excel başlıkları ve yerleşik okuyucu etiketleri.
_MARK = re.compile(r"\f|<!-- Slide number: (\d+) -->|^\[Slayt (\d+)\]$|^\[Sayfa: (.+)\]$|^## (.+)$", re.M)


def _sections(text: str, ext: str) -> list[tuple[str, str]]:
    """(konum, metin) parçaları: 'sayfa 3', 'slayt 7', 'sayfa "Özet"' (Excel) veya başlık."""
    loc = "sayfa 1" if ext == ".pdf" else ""
    page, pos, out = 1, 0, []
    for m in _MARK.finditer(text):
        out.append((loc, text[pos:m.start()]))
        if m.group(0) == "\f":
            page += 1
            loc = f"sayfa {page}"
        elif m.group(1) or m.group(2):
            loc = f"slayt {m.group(1) or m.group(2)}"
        elif m.group(3) or ext in (".xlsx", ".xlsm"):
            loc = f'sayfa "{(m.group(3) or m.group(4)).strip()}"'
        else:
            loc = f'bölüm "{m.group(4).strip()[:60]}"'
        pos = m.end()
    out.append((loc, text[pos:]))
    return [(loc, part) for loc, part in out if part.strip()]


def _db(profile):
    """Kullanıcının arama dizini; SQLite'ta FTS5 yoksa None (eski anahtar kelime taramasına düşülür)."""
    import sqlite3
    try:
        con = sqlite3.connect(_dir(profile) / "arama.sqlite", timeout=10)
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS parca USING fts5("
                    "metin, doc UNINDEXED, baslik UNINDEXED, konum UNINDEXED, ham UNINDEXED, tokenize='unicode61')")
        return con
    except sqlite3.Error:
        _record_failure('modules/kb.py:_db')
        return None


def _index(profile, d: dict, text: str, con=None) -> None:
    own = con is None
    con = con or _db(profile)
    if con is None:
        return
    rows = []
    for loc, part in _sections(text, Path(d.get("title", "")).suffix.lower()):
        for chunk in _chunks(part.strip()):
            rows.append((_norm(chunk), d["id"], d["title"], loc, chunk))
    with con:
        con.execute("DELETE FROM parca WHERE doc = ?", (d["id"],))
        con.executemany("INSERT INTO parca (metin, doc, baslik, konum, ham) VALUES (?, ?, ?, ?, ?)", rows)
    if own:
        con.close()


def _sync_index(profile, con) -> None:
    """Dizini belge listesiyle eşitler: eski sürümde eklenen belgeleri dizinler, silinenleri çıkarır."""
    have = {r[0] for r in con.execute("SELECT DISTINCT doc FROM parca")}
    want = {d["id"]: d for d in _docs(profile)}
    for doc_id in have - set(want):
        with con:
            con.execute("DELETE FROM parca WHERE doc = ?", (doc_id,))
    for doc_id in set(want) - have:
        try:
            text = (_dir(profile) / f"{doc_id}.txt").read_text(encoding="utf-8")
        except OSError:
            continue
        _index(profile, want[doc_id], text, con)


# Soruda aranmayacak kelimeler (soru kalıbı, belge sözcükleri).
_STOP = {"ne", "neydi", "nedir", "kadar", "kaç", "hangi", "nerede", "nerde", "geçiyor", "geçen", "geçti", "var",
         "mı", "mi", "mu", "mü", "bu", "şu", "bir", "ve", "ile", "için", "olan", "dosya", "dosyada", "dosyadaydı",
         "dosyalarımda", "dosyamda", "belge", "belgede", "belgelerimde", "belgedeydi", "yüklediğim", "yazıyor",
         "yazıyordu", "bul", "ara", "bana", "söyle", "dosyalarda", "belgelerde",
         # ASCII yazım ve dosya türü adları ("hangi dosyadaydi", "dosyalarimda geciyor mu", "hangi pdf'teydi")
         "kac", "geciyor", "gecen", "gecti", "su", "icin", "dosyadaydi", "dosyalarimda", "belgedeydi",
         "yukledigim", "yaziyor", "yaziyordu", "soyle", "pdf", "pdfte", "pdfteydi",
         "excel", "excelde", "word", "wordde", "sunum", "sunumda", "tablo", "tabloda", "teydi", "tadir", "tedir"}


def _match_query(question: str) -> str:
    words = [w for w in re.findall(r"\w{2,}", _norm(question)) if w not in _STOP]
    # Türkçe ekler için kök yaklaşımı: ilk 5 harf + önek araması ("faturaların" → "fatur*").
    terms = dict.fromkeys(f'"{w[:5]}"*' if len(w) > 5 else f'"{w}"*' for w in words)
    return " OR ".join(terms)


def _keyword_rows(profile, question: str, top: int) -> list[tuple[int, str, str, str]] | None:
    """FTS5 araması: (belge kimliği, dosya adı, konum, parça). Dizin yoksa None."""
    import sqlite3
    query = _match_query(question)
    if not query:
        return []
    con = _db(profile)
    if con is None:
        return None
    try:
        _sync_index(profile, con)
        return con.execute("SELECT doc, baslik, konum, ham FROM parca WHERE parca MATCH ? ORDER BY bm25(parca) LIMIT ?",
                           (query, top)).fetchall()
    except sqlite3.Error:
        _record_failure('modules/kb.py:keyword_search')
        return None
    finally:
        con.close()


def keyword_search(profile, question: str, top: int = 5) -> list[tuple[str, str]] | None:
    """FTS5 araması: (dosya › konum, parça) listesi. Dizin yoksa None."""
    rows = _keyword_rows(profile, question, top)
    if rows is None:
        return None
    return [(t + (f" › {loc}" if loc else ""), chunk) for _, t, loc, chunk in rows]


# Dosyalar sayfasındaki arama kutusunun içerik araması için dizinlenen türler (Bilgi tabanı ekranındakiyle aynı).
INDEXABLE = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".csv", ".html", ".htm", ".txt", ".md"}


def file_hits(profile, question: str, top: int = 30) -> list[dict]:
    """Soruyla eşleşen belgeler: [{path, name, where, snippet}], aynı dosya bir kez, en iyi eşleşme önce."""
    # Belge kimliğiyle eşlenir: farklı klasörlerde aynı adlı iki dosya varsa doğru olanı döner.
    by_id = {d.get("id"): d.get("path") for d in _docs(profile)}
    out, seen = [], set()
    for doc_id, title, where, chunk in _keyword_rows(profile, question, top) or []:
        path = by_id.get(doc_id)
        if not path or path in seen:
            continue
        seen.add(path)
        out.append({"path": path, "name": title, "where": where, "snippet": " ".join(chunk.split())[:160]})
    return out


def index_files(profile, paths) -> int:
    """Yüklenen dosyaları aranabilir yapar; okunamayanları (taranmış PDF, bozuk dosya) atlar. Eklenen sayısını döner."""
    done = 0
    for path in paths:
        if Path(path).suffix.lower() not in INDEXABLE:
            continue
        try:
            add(profile, str(path))
            done += 1
        except (ValueError, OSError, RuntimeError):
            _record_failure('modules/kb.py:index_files')
    return done


def _words(s: str) -> set[str]:
    s = s.replace("I", "ı").replace("İ", "i").lower()
    return {w[:6] for w in re.findall(r"\w{3,}", s)}      # kök yaklaşımı: ilk 6 harf (Türkçe ekler için)


def _chunks(text: str) -> list[str]:
    return [text[i:i + _CHUNK] for i in range(0, len(text), _CHUNK)]


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _vectors(profile, d: dict, chunks: list[str]) -> list[list[float]] | None:
    """Belgenin parça vektörleri; ilk aramada hesaplanıp ~/.jarvis/kb/<kullanıcı>/<id>.emb.json içine yazılır."""
    if len(chunks) > 600:          # çok büyük belge: her aramada binlerce gömme çağrısı yapma, anahtar kelimeyle ara
        return None
    f = _dir(profile) / f"{d['id']}.emb.json"
    tag = llm.provider()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("tag") == tag and len(data.get("v", [])) == len(chunks):
            return data["v"]
    except (OSError, ValueError):
        pass
    try:
        vecs = llm.embed(chunks)
    except ValueError:
        return None
    if len(vecs) != len(chunks):
        return None
    f.write_text(json.dumps({"tag": tag, "v": vecs}), encoding="utf-8")
    return vecs


def search(profile, question: str, top: int = 5, semantic: bool = False) -> list[tuple[str, str]]:
    """(belge adı, parça) listesi. Varsayılan kelime araması (FTS5, kota harcamaz).

    semantic=True yalnız açık "anlamsal ara" komutunda: vektör araması, gömme alınamazsa anahtar kelime eşleşmesi.
    """
    if not semantic:
        hits = keyword_search(profile, question, top)
        if hits is not None:
            return hits
    q = _words(question)
    qv = None
    if semantic:
        try:
            qv = llm.embed([question])[0]
        except ValueError:
            qv = None
    scored = []
    for d in _docs(profile):
        try:
            text = (_dir(profile) / f"{d['id']}.txt").read_text(encoding="utf-8")
        except OSError:
            continue
        chunks = _chunks(text)
        vecs = _vectors(profile, d, chunks) if qv else None
        for i, chunk in enumerate(chunks):
            kw = len(q & _words(chunk))
            if vecs:
                score = _cos(qv, vecs[i]) + min(kw, 5) * 0.02      # anlam + hafif anahtar kelime desteği
                if score > 0.3:
                    scored.append((score, d["title"], chunk))
            elif kw:
                scored.append((kw, d["title"], chunk))
    scored.sort(key=lambda x: -x[0])
    return [(t, c) for _, t, c in scored[:top]]


def answer(profile, question: str) -> str:
    if not _docs(profile):
        return "Bilgi tabanında belge yok. Önce Bilgi tabanı sayfasından belge ekle."
    hits = search(profile, question)
    if not hits:
        return "Belgelerinde bu soruyla ilgili bir bölüm bulamadım."
    context = "\n\n".join(f"[{t}]\n{c}" for t, c in hits)
    reply = ask("Aşağıdaki belge parçalarına dayanarak soruyu Türkçe, kısa ve net yanıtla. Yanıt parçalarda yoksa "
                "bunu söyle, tahmin etme.\n\n" + context + "\n\nSoru: " + question, max_tokens=800)
    return reply + "\n\nKaynak: " + ", ".join(dict.fromkeys(t for t, _ in hits))


_FILE_QUESTION = re.compile(
    r"hang[iı]\s+(?:dosya|belge|pdf|excel|word|sunum|tablo)(?:lar|ler)?'?(?:da|de|ta|te)(?:yd[ıi]|d[ıi]r)?\b|"
    r"(?:dosyalar[ıi]m|belgelerim|y[üu]kledi[ğg]im\s+(?:dosya|belge)\w*)\w*\s+(?:\w+\s+){0,4}"
    r"(?:ge[çc]iyor|ge[çc]en|var\s*m)")


def handle(cmd_lower: str, profile) -> str | None:
    m = re.match(r"^(?:anlamsal ara|belgelerimde anlamca ara)\s*[:,]?\s*(.{3,})$", cmd_lower.strip())
    if m:
        hits = search(profile, m.group(1), semantic=True)
        if not hits:
            return "İlgili bir bölüm bulamadım."
        return "\n\n".join(f"{t}: {c[:200].strip()}…" for t, c in hits[:3])
    m = re.match(r"^(?:bilgi tabanı(?:nda|ma)?|belgelerimde|belgelerimden)\s*(?:ara|sor)?\s*[:,]?\s*(.{4,})$", cmd_lower.strip())
    if m:
        return answer(profile, m.group(1))
    # "kira bedeli hangi dosyadaydı?", "yüklediğim dosyalarda vida geçiyor mu" gibi doğal sorular
    # Yalnız "hangi dosyaDA" ve "dosyalarımda … geçiyor mu" kalıpları: "yüklediğim dosyayı özetle" gibi komutlara karışmaz.
    # ASCII yazım da tanınır: "hangi dosyadaydi", "hangi pdf'teydi", "dosyalarimda kira geciyor mu".
    if _docs(profile) and _FILE_QUESTION.search(cmd_lower):
        return answer(profile, cmd_lower)
    return None
