"""Türkçe tarih/saat ifadelerini çözer: 'yarın 14:30 toplantı', '5 Ekim saat 10 diş randevusu', '2 saat sonra su iç'."""
import re
from datetime import datetime, timedelta

MONTHS = ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım",
          "aralık")
WEEKDAYS = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar")
MONTHS_TITLE = tuple(m.capitalize() if m != "ağustos" else "Ağustos" for m in MONTHS)
WEEKDAYS_TITLE = tuple(d.capitalize() for d in WEEKDAYS)


def _lower(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


# Türkçe harfsiz (ASCII) yazılan gün/saat sözcükleri: "yarin saat 9da toplanti" de anlaşılsın.
# Yalnız zaman sözcükleri çevrilir; başlık metnindeki diğer sözcüklere dokunulmaz.
_ASCII = {"yarin": "yarın", "bugun": "bugün", "obur": "öbür", "gun": "gün", "sali": "salı",
          "carsamba": "çarşamba", "persembe": "perşembe", "subat": "şubat", "mayis": "mayıs",
          "agustos": "ağustos", "eylul": "eylül", "kasim": "kasım", "aralik": "aralık",
          "aksam": "akşam", "oglen": "öğlen", "ogle": "öğle", "ogleden": "öğleden", "bucuk": "buçuk",
          "ceyrek": "çeyrek", "ici": "içi", "ayin": "ayın", "uc": "üç", "bes": "beş",
          "icinde": "içinde", "hatirlat": "hatırlat"}


def _turkish(s: str) -> str:
    return re.sub(r"[a-z]+", lambda m: _ASCII.get(m.group(0), m.group(0)), s)


def parse_when(text: str, now: datetime | None = None) -> tuple[str | None, str]:
    """(zaman, başlık) döndürür. Zaman 'YYYY-MM-DDTHH:MM' (saatli) ya da 'YYYY-MM-DD' (tüm gün);
    tarih/saat bulunamazsa None. Başlık, tarih ve saat ifadeleri çıkarılmış metindir."""
    now = now or datetime.now()
    s = " " + _turkish(_lower(text)) + " "
    day = None            # datetime.date
    hour = minute = None
    delta = None          # '2 saat sonra' gibi göreli süre

    def cut(pattern: str):
        nonlocal s
        m = re.search(pattern, s)
        if m:
            s = s[:m.start()] + " " + s[m.end():]
        return m

    # --- göreli süre
    m = cut(r"\b(\d+|bir|iki|üç|beş|on)\s*(dakika|dk|saat)\s*(sonra|içinde)\b")
    if m:
        words = {"bir": 1, "iki": 2, "üç": 3, "beş": 5, "on": 10}
        n = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1)]
        delta = timedelta(minutes=n) if m.group(2) in ("dakika", "dk") else timedelta(hours=n)
    m = cut(r"\b(\d+)\s*gün\s*sonra\b")
    if m:
        day = (now + timedelta(days=int(m.group(1)))).date()

    # --- gün
    if cut(r"\bbugün\b"):
        day = now.date()
    elif cut(r"\b(öbür gün|ertesi gün)\b"):
        day = (now + timedelta(days=2)).date()
    elif cut(r"\byarın\b"):
        day = (now + timedelta(days=1)).date()
    else:
        m = cut(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b(?!:)")
        if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
            year = int(m.group(3)) if m.group(3) else now.year
            year += 2000 if year < 100 else 0
            try:
                day = datetime(year, int(m.group(2)), int(m.group(1))).date()
            except ValueError:
                day = None
        elif m:
            s = s[:m.start()] + m.group(0) + s[m.start():]   # tarih değilse geri koy
        if day is None:
            m = cut(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?\b")
            if m:
                year = int(m.group(3)) if m.group(3) else now.year
                try:
                    day = datetime(year, MONTHS.index(m.group(2)) + 1, int(m.group(1))).date()
                    if not m.group(3) and day < now.date():
                        day = day.replace(year=year + 1)
                except ValueError:
                    day = None
        if day is None:
            m = cut(r"\b(haftaya\s+)?(" + "|".join(WEEKDAYS) + r")\b")
            if m:
                diff = (WEEKDAYS.index(m.group(2)) - now.weekday()) % 7
                if diff == 0 or m.group(1):
                    diff += 7 if (m.group(1) or diff == 0) else 0
                day = (now + timedelta(days=diff)).date()

    # --- saat
    m = cut(r"\b(?:saat\s+)?(\d{1,2})[:.](\d{2})\b")
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        if m:
            s = s[:m.start()] + m.group(0) + s[m.start():]
        m = cut(r"\b(?:saat\s+)?(\d{1,2})['’]?(?:da|de|ta|te)\b")    # "10'da", ASCII/sesle yazımda "10da"
        if m and int(m.group(1)) < 24:
            hour, minute = int(m.group(1)), 0
            m = None
        elif m:
            m = None
        if hour is not None:
            pass
        else:
            m = cut(r"\bsaat\s+(\d{1,2})(?:\s*(buçuk|çeyrek))?\b")
        if hour is not None:
            pass
        elif m and int(m.group(1)) < 24:
            hour, minute = int(m.group(1)), 30 if m.group(2) == "buçuk" else 0
        elif m:
            pass
        else:
            m = cut(r"\b(sabah|öğlen|öğleden sonra|akşam|gece)\s+(\d{1,2})(?:[:.](\d{2}))?\b")
            if m and int(m.group(2)) < 24:
                hour, minute = int(m.group(2)), int(m.group(3) or 0)
            elif cut(r"\böğlen\b"):
                hour, minute = 12, 0
    if hour is not None:
        period = re.search(r"\b(öğleden sonra|akşam|gece)\b", s) or (m and re.match(r"(öğleden sonra|akşam|gece)", m.group(0).strip()))
        if period and hour < 12:
            hour += 12
        cut(r"\b(sabah|öğleden sonra|akşam|gece)\b")

    title = re.sub(r"\b(takvime|hatırlat\w*|ekle|etkinlik|randevu|bana|için|lütfen|de|da)\b", " ", s)
    title = re.sub(r"\s+", " ", title).strip(" ,.:-")

    if delta is not None:
        when = now + delta
        return when.strftime("%Y-%m-%dT%H:%M"), title
    if day is None and hour is None:
        return None, title
    if day is None:                       # yalnızca saat: bugün, geçtiyse yarın
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        day = (cand if cand > now else cand + timedelta(days=1)).date()
    if hour is None:
        return day.strftime("%Y-%m-%d"), title
    return f"{day:%Y-%m-%d}T{hour:02d}:{minute:02d}", title


def describe(when: str, now: datetime | None = None) -> str:
    """'2026-10-02T14:30' -> 'yarın 14:30' (bugün/yarın değilse '5 Ekim 14:30')."""
    now = now or datetime.now()
    d = datetime.strptime(when[:10], "%Y-%m-%d").date()
    if d == now.date():
        label = "bugün"
    elif d == (now + timedelta(days=1)).date():
        label = "yarın"
    else:
        label = f"{d.day} {MONTHS_TITLE[d.month - 1]}"
    return f"{label} {when[11:16]}" if len(when) > 10 else label


# --- Tekrarlayan hatırlatma: "her gün 9'da", "her pazartesi 10'da", "hafta içi her gün 8'de", "her ayın 1'inde"
# Kural metni: "daily", "weekdays", "weekly:<0-6>", "monthly:<1-31>". Tanınmayan bir "her ..." tekrar isteği
# "unknown" döner; çağıran yanlış bir tek seferlik kayıt açmak yerine kullanıcıya sorar.
_DAY_ALT = "|".join(WEEKDAYS)


def parse_repeat(text: str) -> tuple[str | None, str]:
    """(kural, kalan metin). Tekrar ifadesi yoksa (None, metin)."""
    s = " " + _turkish(_lower(text)) + " "

    def take(pattern):
        nonlocal s
        m = re.search(pattern, s)
        if m:
            s = s[:m.start()] + " " + s[m.end():]
        return m

    rule = None
    if take(r"\bhafta\s*içi(?:\s+her\s*(?:gün|sabah|akşam))?\b|\bher\s+hafta\s*içi\b"):
        rule = "weekdays"
    elif m := take(r"\bher\s+ayın\s+(\d{1,2})\s*['’]?\s*(?:i|ı|u|ü|si|sı|sü|su)?(?:nde|nda|inde|ında|unda|ünde)?\b"):
        if 1 <= int(m.group(1)) <= 31:
            rule = f"monthly:{int(m.group(1))}"
        else:
            return "unknown", text
    elif m := take(r"\bher\s+(?:hafta\s+)?(" + _DAY_ALT + r")(?:\s+günü)?\b|\b(" + _DAY_ALT + r")(?:ları|leri)\b"):
        rule = f"weekly:{WEEKDAYS.index(m.group(1) or m.group(2))}"
    elif take(r"\bher\s*gün\b|\bhergün\b|\bher\s+(?:sabah|akşam|gece|öğlen)\b"):
        rule = "daily"
        # "her sabah 8'de": sabah/akşam sözcüğü saati belirlesin diye geri bırakılır
        for word in ("sabah", "akşam", "gece", "öğlen"):
            if re.search(r"\bher\s+" + word + r"\b", " " + _turkish(_lower(text)) + " "):
                s = f" {word} " + s
    elif re.search(r"\bher\s+(?:\d+\s+)?(?:saat|dakika|hafta|ay|yıl|sene)\w*\b|\bher\s+ayın\b|"
                   r"\bher\s+\d+\s+g[uü]n\w*|\b(?:\d+|iki|üç|uc|dört|dort|beş|bes|altı|yedi|on)\s+g[uü]n\w*\s+(?:de\s+)?bir\b|"
                   r"\bg[uü]n\s+a[sş]ırı\b", s):
        return "unknown", text
    if rule is None:
        return None, text
    return rule, re.sub(r"\s+", " ", s).strip()


def next_occurrence(rule: str, after: datetime, hour: int, minute: int) -> datetime:
    """Kurala uyan, `after`dan sonraki ilk zaman (saniyesiz)."""
    base = after.replace(second=0, microsecond=0)
    for add in range(0, 400):
        day = (base + timedelta(days=add)).replace(hour=hour, minute=minute)
        if day <= after:
            continue
        if rule == "daily":
            return day
        if rule == "weekdays" and day.weekday() < 5:
            return day
        if rule.startswith("weekly:") and day.weekday() == int(rule[7:]):
            return day
        if rule.startswith("monthly:"):
            want = int(rule[8:])
            last = ((day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
            if day.day == min(want, last):          # 31'i olmayan ayda ayın son günü
                return day
    raise ValueError(f"tekrar kuralı anlaşılmadı: {rule}")


def occurs_on(rule: str | None, first: str, day) -> bool:
    """Tekrar kuralı `day` (date) gününe düşer mi? `first` ilk (kayıttaki) zaman; ondan önceki günler sayılmaz."""
    if not rule or day.isoformat() < first[:10]:
        return False
    if rule == "daily":
        return True
    if rule == "weekdays":
        return day.weekday() < 5
    if rule.startswith("weekly:"):
        return day.weekday() == int(rule[7:])
    if rule.startswith("monthly:"):
        last = ((day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
        return day.day == min(int(rule[8:]), last)
    return False


def describe_repeat(rule: str, hour: int, minute: int) -> str:
    at = f"{hour:02d}:{minute:02d}"
    if rule == "daily":
        return f"her gün {at}"
    if rule == "weekdays":
        return f"hafta içi her gün {at}"
    if rule.startswith("weekly:"):
        return f"her {WEEKDAYS[int(rule[7:])]} {at}"
    return f"her ayın {rule[8:]}. günü {at}"
