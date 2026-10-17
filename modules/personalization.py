"""Kişiselleştirme: her kullanıcının ayrı profili (hedefler, notlar, tercihler, geri bildirim)."""
from modules.diagnostics import record_failure as _record_failure
import json
import os
import re
import shutil
import threading
import weakref
from datetime import datetime
from collections import Counter

from config import ACTIVE_FILE, DEFAULT_USER, PROFILE_DB, USERS_DIR, WAKE_WORD
try:
    from config import ASSISTANT_NAME
except ImportError:
    ASSISTANT_NAME = "Jarvis"

_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slugify(name: str) -> str:
    """'Merve' / 'MERVE' / 'Şeyma' -> dosya adı için küçük ASCII ('merve', 'seyma')."""
    return re.sub(r"[^a-z0-9]", "", name.translate(_ASCII).lower())


def display_name(token: str) -> str:
    """Konuşmadan gelen küçük harfli adı düzgün yazar ('ismail' -> 'İsmail')."""
    token = token.strip()
    if not token:
        return token
    first = "İ" if token[0] == "i" else token[0].upper()
    return first + token[1:]


def list_users() -> list[str]:
    names = []
    for f in sorted(USERS_DIR.glob("*.json")):
        try:
            names.append(json.loads(f.read_text(encoding="utf-8")).get("name") or f.stem.title())
        except (ValueError, OSError):
            names.append(f.stem.title())
    return names


def get_active() -> str:
    try:
        name = ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if name:
            return name
    except OSError:
        pass
    return DEFAULT_USER


def set_active(name: str) -> None:
    try:
        ACTIVE_FILE.write_text(name, encoding="utf-8")
    except OSError:
        pass


def rename_user(old: str, new: str) -> str | None:
    """Kullanıcıyı yeniden adlandırır (dosya adı ve profil içindeki ad). Hata varsa açıklama döndürür, olduysa None."""
    new = new.strip()
    old_path, new_slug = USERS_DIR / f"{slugify(old)}.json", slugify(new)
    if not new_slug:
        return "Yeni ad geçersiz."
    if not old_path.exists() and old.lower() == get_active().lower():
        Profile(old).save()          # henüz dosyası yoksa aktif kullanıcının profilini oluştur
    if not old_path.exists():
        return f"{old} adında kullanıcı yok."
    new_path = USERS_DIR / f"{new_slug}.json"
    if new_path.exists() and new_path != old_path:
        return f"{new} adında başka bir kullanıcı zaten var."
    try:
        data = json.loads(old_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        data = {}
    data["name"] = new
    with _LOCK:
        new_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if new_path != old_path:
            old_path.unlink()
    if get_active().lower() == old.lower():
        set_active(new)
    return None


def delete_user(name: str) -> str | None:
    """Profili silmez; 'silinenler' klasörüne taşır (geri alınabilir). Hata varsa açıklama döndürür."""
    path = USERS_DIR / f"{slugify(name)}.json"
    if not path.exists():
        return f"{name} adında kullanıcı yok."
    if len(list_users()) <= 1:
        return "Son kullanıcıyı silemem."
    trash = USERS_DIR / "silinenler"
    try:
        trash.mkdir(exist_ok=True)
        shutil.move(str(path), str(trash / f"{path.stem}_{datetime.now():%Y%m%d%H%M%S}.json"))
    except OSError as exc:
        return f"Silinemedi: {exc}"
    return None


def migrate_legacy() -> None:
    """Eski tek profili (profile.json) varsayılan kullanıcıya taşır; veri kaybolmaz."""
    target = USERS_DIR / f"{slugify(DEFAULT_USER)}.json"
    if PROFILE_DB.exists() and not target.exists():
        try:
            shutil.copy(PROFILE_DB, target)
        except OSError:
            pass


_LOCK = threading.RLock()   # Required: mutators/learning call save() while holding it.
_SHARED = weakref.WeakValueDictionary()

class _ProfileState:
    def __init__(self):
        self.data = {}


def _assistant_name() -> str:
    """Asistanın o anki adı (Ayarlar'dan değiştirilince yeniden başlatmadan geçerli olsun)."""
    try:
        import config
        return config.ASSISTANT_NAME or ASSISTANT_NAME
    except Exception:       # noqa: BLE001
        _record_failure('modules/personalization.py:_assistant_name')
        return ASSISTANT_NAME


class Profile:
    def __init__(self, name: str | None = None):
        with _LOCK:
            self._initialize(name)

    def _initialize(self, name):
        self.name = name or get_active()
        self.slug = slugify(self.name) or "kullanici"
        self.path = USERS_DIR / f"{self.slug}.json"
        key = str(self.path.resolve())
        state = _SHARED.get(key)
        if state is not None:
            self._state = state
            return
        self._state = _ProfileState()
        self.data = {"name": self.name,
                     "prefs": {"language": "tr", "verbosity": "orta"},
                     "command_counts": {}, "feedback": {"+": 0, "-": 0},
                     "notes": [],    # geri bildirimden gelenler
                     "goals": [],    # "hedefim ..." ile eklenenler
                     "facts": [],    # "hatırla ..." ile eklenenler
                     "items": [],    # not defteri: [{id, text, ts}]
                     "events": [],   # takvim: [{id, title, when, notified}]
                     "next_id": 1}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass   # bozuk dosyada varsayılanlarla başla
        self.data["name"] = self.data.get("name") or self.name
        _SHARED[key] = self._state

    @property
    def data(self):
        return self._state.data

    @data.setter
    def data(self, value):
        if not hasattr(self, '_state'):
            self._state = _ProfileState()
        self._state.data = value

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def save(self):
        with _LOCK:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def set_pref(self, k, v):
        with _LOCK:
            self.data["prefs"][k] = v
            self.save()

    def log_command(self, intent: str):
        with _LOCK:
            c = self.data["command_counts"]; c[intent] = c.get(intent, 0) + 1
            self.data.setdefault("last_used", {})[intent] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.save()

    def log_agent(self, key: str) -> None:
        """Komutun hangi yetenek alanına girdiğini sayar (Ajanlar sayfası için)."""
        with _LOCK:
            d = self.data
            d.setdefault("agent_counts", {})[key] = d.setdefault("agent_counts", {}).get(key, 0) + 1
            d.setdefault("agent_last", {})[key] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.save()

    def feedback(self, positive: bool, note: str = ""):
        with _LOCK:
            self.data["feedback"]["+" if positive else "-"] += 1
            if note: self.data["notes"].append(note); self.data["notes"] = self.data["notes"][-30:]
            self.save()

    def top_intents(self, n=3):
        return [k for k, _ in Counter(self.data["command_counts"]).most_common(n)]

    # ---- hedefler ve bilgiler
    def add_goal(self, text: str):
        with _LOCK:
            text = str(text or "").strip()
            if not text:
                return
            self.data["goals"] = (self.data["goals"] + [text])[-8:]
            self.save()

    def clear_goals(self):
        with _LOCK:
            self.data["goals"] = []
            self.save()

    def add_fact(self, text: str):
        text = str(text or "").strip()
        if not text: return
        with _LOCK:
            facts = self.data.setdefault("facts", [])
            if text.casefold() not in {str(f).casefold() for f in facts}:
                facts.append(text)
                self.save()

    # ---- not defteri ve takvim (her kullanıcıya ayrı)
    def edit_fact(self, idx: int, expected: str, text: str | None):
        """Change only the exact selected fact; roll back memory on disk failure."""
        if type(idx) is not int or not isinstance(expected,str) or not expected.strip():
            raise ValueError('Kesin bilgi kaydı gerekli.')
        if text is not None and (not isinstance(text,str) or not text.strip() or len(text)>4000):
            raise ValueError('Yeni bilgi boş olamaz ve en çok 4000 karakter olabilir.')
        with _LOCK:
            facts=self.data.setdefault('facts',[])
            if not 0<=idx<len(facts) or facts[idx]!=expected:
                raise ValueError('Bilgi kaydı değişmiş; hafızayı yeniden listele.')
            before=list(facts)
            if text is None:facts.pop(idx)
            else:
                text=text.strip()
                if any(i!=idx and str(f).casefold()==text.casefold() for i,f in enumerate(facts)):
                    raise ValueError('Yeni bilgi başka bir kayıtla aynı.')
                facts[idx]=text
            try:self.save()
            except BaseException:
                facts[:]=before
                raise
        return True

    def _new_id(self) -> int:
        with _LOCK:
            n = int(self.data.get("next_id", 1))
            self.data["next_id"] = n + 1
            return n

    def _add_note_item(self, text: str, photo: str | None = None, title: str = "") -> dict:
        item = {"id": self._new_id(), "text": text.strip(), "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
        if title.strip():
            item['title'] = title.strip()[:120]
        if photo:
            item['photo'] = photo
        self.data["items"].append(item)
        try:
            self.save()
        except OSError:
            self.data['items'].remove(item)
            raise
        return item

    def _delete_note_item(self, nid: int) -> bool:
        before = len(self.data["items"])
        self.data["items"] = [n for n in self.data["items"] if n["id"] != nid]
        self.save()
        return len(self.data["items"]) < before

    def _clear_note_items(self) -> None:
        self.data["items"] = []
        self.save()

    def _add_event(self, title: str, when: str) -> dict:
        ev = {"id": self._new_id(), "title": title.strip() or "Etkinlik", "when": when, "notified": False}
        self.data["events"].append(ev)
        self.save()
        return ev

    def _delete_event(self, eid: int) -> bool:
        before = len(self.data["events"])
        self.data["events"] = [e for e in self.data["events"] if e["id"] != eid]
        self.save()
        return len(self.data["events"]) < before

    def events_on(self, day: str) -> list[dict]:
        """'YYYY-MM-DD' gününün etkinlikleri (saatlisi saat sırasıyla, tüm gün olanlar başta)."""
        return sorted((e for e in self.data["events"] if e["when"][:10] == day), key=lambda e: e["when"])

    def upcoming(self, now: datetime, limit: int = 6) -> list[dict]:
        today = now.strftime("%Y-%m-%d")
        return sorted((e for e in self.data["events"] if e["when"][:10] >= today), key=lambda e: e["when"])[:limit]

    def _due_events(self, now: datetime) -> list[dict]:
        """Saati gelmiş hatırlatmaları bir kez döndürür.

        Saat verilmemiş tüm-gün kayıtları o gün 09:00'da; Jarvis daha geç açıldıysa o gün ilk kontrolde
        bildirilir. Böylece "Pazartesi hatırlat" gerçekten kendiliğinden hatırlatır.
        """
        due = []
        marked = []
        for e in self.data["events"]:
            if e.get("notified"):
                continue
            raw = str(e.get("when") or "")
            try:
                if len(raw) == 10:
                    day = datetime.strptime(raw, "%Y-%m-%d")
                    t = day.replace(hour=9, minute=0)
                    if now.date() != t.date() or now < t:
                        continue
                    due.append(e)
                    marked.append(e)
                    continue
                t = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                continue
            if t <= now:
                if (now - t).total_seconds() < 6 * 3600:
                    due.append(e)
                    marked.append(e)
        if due:
            for e in marked: e["notified"] = True
            try: self.save()
            except BaseException:
                for e in marked: e.pop("notified", None)
                # Preserve an already-notified event's original value.
                for e in self.data["events"]:
                    if e in marked and e.get("id") in {x.get("id") for x in marked}:
                        pass
                raise
        return due

    def add_note_item(self, *a, **k):
        with _LOCK: return self._add_note_item(*a, **k)

    def delete_note_item(self, *a, **k):
        with _LOCK: return self._delete_note_item(*a, **k)

    def clear_note_items(self, *a, **k):
        with _LOCK: return self._clear_note_items(*a, **k)

    def add_event(self, *a, **k):
        with _LOCK: return self._add_event(*a, **k)

    def delete_event(self, *a, **k):
        with _LOCK: return self._delete_event(*a, **k)

    def due_events(self, *a, **k):
        with _LOCK: return self._due_events(*a, **k)

    def system_prompt(self, query: str = "") -> str:
        p = self.data["prefs"]
        goals, facts = self.data["goals"], self.data["facts"]
        parts = [
            f"Sen {_assistant_name()} adlı, Türkçe konuşan sesli bir masaüstü asistanısın. "
            f"Şu an {self.data['name']} ile konuşuyorsun. Başka kullanıcılar hakkında bilgi verme.",
            "Yanıtların kısa olsun: en fazla "
            + ("4-5 cümle" if goals else "2-3 cümle")
            + ". Madde işareti, markdown ve emoji kullanma, çünkü yanıt sesli okunuyor.",
            "Uygulama açma, ses ve parlaklık ayarı gibi işlemleri ayrı komutlar yapar, "
            "sen yapmadığın bir işlemi yaptım deme. Özellikle not alma, hatırlatma, takvime ekleme ve mesaj gönderme "
            "işlemlerini sen yapamazsın; böyle bir istek sana gelirse 'kaydettim/not aldım' DEME, "
            "'Not ekle …' ya da 'yarın 10'da hatırlat …' gibi söylemesini öner.",
            "Kod yazman istenirse kodu ```dil biçiminde bir kod bloğuna koy (kod sesli okunmaz, ekranda "
            "görünür) ve kod dışındaki açıklamayı kısa tut.",
            "Matematik ifadelerini LaTeX ile ($...$, \\pm, \\frac gibi) yazma; düz metin ve Unicode kullan "
            "(örn. 6k ± 1, x², √x, a/b, ≤).",
            "Güncel fiyat, haber ve benzeri dış veriyi tahmin etme; bu istekler araçlı görev yoluna yönlendirilir.",
        ]
        if goals:
            parts.append(
                "Kullanıcının hedefleri: " + "; ".join(goals) + ". Bu hedeflerle ilgili konularda iyi bir "
                "öğretmen gibi davran: sade ve adım adım anlat, gerekirse tek bir kısa soru sor, hatayı nazikçe "
                "düzelt ve bir sonraki küçük adımı öner. Hedefle ilgisiz sorularda normal yardımcı ol."
            )

        try:
            from modules import learning
            kp = learning.knowledge_prompt(self, query)
            if kp: parts.append(kp)
            rp = learning.rules_prompt(self, query)
            if rp:
                parts.append(rp)
        except Exception:                          # noqa: BLE001
            _record_failure('modules/personalization.py:system_prompt')
            pass
        parts.append(f"Kullanıcı tercihi: yanıt uzunluğu={p.get('verbosity', 'orta')}.")
        return " ".join(parts)
