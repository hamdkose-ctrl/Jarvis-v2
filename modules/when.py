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


def parse_when(text: str, now: datetime | None = None) -> tuple[str | None, str]:
    """(zaman, başlık) döndürür. Zaman 'YYYY-MM-DDTHH:MM' (saatli) ya da 'YYYY-MM-DD' (tüm gün);
    tarih/saat bulunamazsa None. Başlık, tarih ve saat ifadeleri çıkarılmış metindir."""
    now = now or datetime.now()
    s = " " + _lower(text) + " "
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
        m = cut(r"\b(\d{1,2})['’](?:da|de|ta|te)\b")      # "10'da"
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
