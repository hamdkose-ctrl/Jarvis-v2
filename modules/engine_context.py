"""engine context; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _get_profile(runtime, name: str):
    slug = runtime.slugify(name or "") or "kullanici"
    with runtime._profile_lock:
        if slug not in runtime._profiles:
            runtime._profiles[slug] = runtime.Profile(name)
        return runtime._profiles[slug]

def _session(runtime):
    return runtime._sessions.get(runtime.profile.slug)

def pc_profile(runtime):
    """Bilgisayar ekranının kullanıcısı. Telefondan başka biri adına iş yapılırken bile bilgisayarın kullanıcısını verir."""
    return runtime._home if (runtime._guest is not None and runtime._home is not None) else runtime.profile

def match_user(runtime, name: str | None) -> str | None:
    """Telefondan gelen adı kayıtlı kullanıcıyla eşleştirir (büyük/küçük harf, Türkçe karakter fark etmez)."""
    if not name or not name.strip():
        return None
    want = runtime.slugify(name.strip())
    return next((n for n in runtime.list_users() if runtime.slugify(n) == want), None)

@contextlib.contextmanager
def as_user(runtime, name: str | None):
    """Serialize engine profile changes; each owner retains their own session object."""
    pass  # Shared fields are held by the explicit engine context.
    with runtime._execution_lock:
        # The active PC profile can exist only in memory on first startup,
        # or its saved display name can differ from the active-file name.
        # Reuse that trusted object rather than requiring a phone user lookup.
        pc = runtime.pc_profile()
        current = runtime.profile
        known = next((p for p in (current, pc)
                      if name and runtime.slugify(name) == runtime.slugify(p.name)), None)
        target = known.name if known is not None else runtime.match_user(name)
        if name and not target:
            raise ValueError("Telefon kullanıcısı bulunamadı")
        home, previous_guest, previous_home = runtime.profile, runtime._guest, runtime._home
        other = known if known is not None else runtime._get_profile(target) if target else home
        if other.slug != home.slug:
            runtime._home = previous_home if previous_guest is not None else home
            runtime.profile, runtime._guest = other, other.name
        runtime._llm.set_user_context(other.slug)
        try:
            with runtime._sessions.use(other.slug):
                yield
        finally:
            # A PC user switch inside this scope intentionally persists.
            if runtime._guest is not None:
                runtime.profile, runtime._guest, runtime._home = home, previous_guest, previous_home
            runtime._llm.set_user_context(runtime.profile.slug)

def _voice_opts(runtime) -> dict:
    """Aktif kullanıcının seçtiği ses ve konuşma hızı."""
    prefs = runtime.profile.data["prefs"]
    entry = runtime.voice.VOICES.get(prefs.get("voice", ""))
    opts: dict = {"voice": entry[1]} if entry else {}
    if isinstance(prefs.get("rate"), int):
        opts["rate"] = prefs["rate"]
    return opts

def _parse_voice(runtime, cmd_lower: str, partial: str | None = None) -> tuple[str | None, str | None]:
    """Konuşmadan ses anahtarını çıkarır. (anahtar, None) ya da eksikse (None, yarım dil)."""
    names = {"kerem": "tr_erkek", "defne": "tr_kadin", "liam": "ml_erkek", "olivia": "ml_kadin",
             "noah": "ml_erkek2", "mia": "ml_kadin2",
             "mert": "ml_erkek", "zeynep": "ml_kadin", "emir": "ml_erkek2", "asya": "ml_kadin2",   # önceki adlar
             "ahmet": "tr_erkek", "emel": "tr_kadin", "andrew": "ml_erkek", "ava": "ml_kadin",   # eski adlar
             "brian": "ml_erkek2", "emma": "ml_kadin2"}
    for word, key in names.items():
        if runtime.re.search(rf"\b{word}\b", cmd_lower):
            return key, None
    lang = partial
    if runtime.re.search(r"çok dilli|çokdilli|multi|ingilizce|yabancı", cmd_lower):
        lang = "ml"
    elif runtime.re.search(r"türkçe", cmd_lower):
        lang = "tr"
    gender = "kadin" if runtime.re.search(r"kadın|bayan|hanım|kız", cmd_lower) else \
             "erkek" if runtime.re.search(r"erkek|adam", cmd_lower) else None
    second = bool(runtime.re.search(r"ikinci|diğer|başka", cmd_lower))
    if gender is None:
        return None, lang
    key = f"{lang or 'tr'}_{gender}"
    if second and key.startswith("ml"):
        key += "2"
    return key, None

def _set_voice(runtime, key: str) -> str:
    from modules import voice_runtime
    lane = voice_runtime.active()
    if lane is not None:
        try:
            lane.check_voice(key)
        except (ValueError, OSError):
            return "Bu sesin yerel modeli veya Piper motoru kurulu değil. Önceki ses tercihin değişmedi."
    runtime.profile.set_pref("voice", key)
    return f"Tamam {runtime.profile.name}, artık {runtime.voice.VOICES[key][0].split(' · ')[0]} sesiyle konuşuyorum."

def _switch_user(runtime, name: str, created: bool = False) -> str:
    """Aktif kullanıcıyı değiştirir; profil, hedefler ve sohbet geçmişi o kullanıcıya göre yüklenir."""
    pass  # Shared fields are held by the explicit engine context.
    if runtime._cur_source == "telefon":
        # Telefondan kullanıcı değiştirilmez/eklenirken bilgisayardaki kullanıcı değişmez; her telefon kendi menüsünden seçer.
        p = runtime._get_profile(name)
        if created or not p.exists:
            p.save()
            return f"{p.name} için profil açtım. Telefonda sağ üstteki kullanıcı menüsünden {p.name} seçebilirsin."
        return f"Bu telefonda kullanıcıyı değiştirmek için sağ üstteki kullanıcı menüsünden {p.name} seç."
    from modules import pc_guide
    pc_guide.stop()
    runtime.profile = runtime._get_profile(name)
    runtime.profile.save()
    runtime._llm.set_user_context(runtime.profile.slug)
    if runtime._guest is None:
        runtime.set_active(runtime.profile.name)          # bilgisayarın kullanıcısı değişti
    else:
        runtime._guest = runtime.profile.name             # telefondan: yalnızca o telefonun kullanıcısı (bilgisayar etkilenmez)
    runtime._sessions.reset(runtime.profile.slug)
    runtime._sessions._owner.set(runtime.profile.slug)
    from modules import hooks
    hooks.observe("session", {"event": "user_switched", "created": bool(created)}, owner=runtime.profile.slug)
    runtime._session().last_doc = None            # bir kullanıcının analizi diğerine kaydedilmesin
    runtime._session().pending_level = None
    runtime._session().pending_confirm = None
    runtime._session().pending_voice = None
    runtime._session().pending_event_title = None
    runtime._session().pending_msg = None
    runtime._session().pending_organize = None
    runtime.log.info("Kullanıcı: %s", runtime.profile.name)
    if created:
        return (f"Merhaba {runtime.profile.name}, senin için yeni bir profil açtım. "
                "Hedefini söylemek için hedefim, sesini seçmek için sesimi seç de.")
    goals = runtime.profile.data["goals"]
    if goals:
        return f"Merhaba {runtime.profile.name}. Hedefin: {goals[-1]}. Kaldığımız yerden devam edebiliriz."
    return f"Merhaba {runtime.profile.name}."

def _user_controls(runtime, command: str, cmd_lower: str) -> str | None:
    """Existing sharing and voice controls; profile intent belongs to Core."""
    # Ekran paylaşımı ve kamera
    # "paylaşımı kapat/durdur/bitir" (ekran ya da kamera, hangisi açıksa): mevcut kapatma yolu
    if runtime.re.search(r"\bpayla[şs](?:ı|i)m(?:ı|i|ımı|imi)?\s+(?:kapat|durdur|bitir|sonlandır|kes)\w*|"
                         r"\bpayla[şs]may(?:ı|i)\s+(?:kapat|durdur|bitir|kes|bırak)\w*", cmd_lower):
        return runtime.set_share(None)
    if runtime.re.search(r"ekran(?:ı|ımı|i|imi)?\s+payla[şs]", cmd_lower):
        stop = runtime.re.search(r"durdur|kapat|bitir|kes|dur\b", cmd_lower)
        return runtime.set_share(None if stop else "screen")
    if runtime.re.search(r"\bkamera(yı|mı)?\b", cmd_lower) and runtime.re.search(r"aç|başlat|kapat|durdur", cmd_lower):
        return runtime.set_share(None if runtime.re.search(r"kapat|durdur", cmd_lower) else "camera")

    # Ses seçimi (her kullanıcı kendi sesini seçer)
    if runtime._session().pending_voice is not None:
        partial = None if runtime._session().pending_voice == "sor" else runtime._session().pending_voice
        runtime._session().pending_voice = None
        if runtime.re.search(r"\b(iptal|vazgeç\w*|boşver)\b", cmd_lower):
            return "Tamam, sesi değiştirmedim."
        key, lang = runtime._parse_voice(cmd_lower, partial)
        if key:
            return runtime._set_voice(key)
        if lang:
            runtime._session().pending_voice = lang
            return "Erkek mi kadın mı?"
        # alakasız bir cümle: seçim sorusu iptal, normal akışa devam
    elif runtime.re.search(r"\bsesimi\b|konuşma sesi|ses(i)? (seç|değiştir)|sesini değiştir|"
                   r"\b(erkek|kadın|bayan) ses(i|le)?\b|çok dilli ses|ingilizce ses|türkçe ses", cmd_lower) \
            and not runtime.re.search(r"\d", cmd_lower):
        key, lang = runtime._parse_voice(cmd_lower)
        if key:
            return runtime._set_voice(key)
        runtime._session().pending_voice = lang or "sor"
        if lang:
            return "Erkek mi kadın mı?"
        return ("Sesler: Kerem (Türkçe erkek), Defne (Türkçe kadın), Liam ve Noah (çok dilli erkek), "
                "Olivia ve Mia (çok dilli kadın). İngilizce çalışıyorsan çok dilli sesler İngilizceyi de doğru okur. Hangisi?")

    m = runtime.re.search(r"(yavaş|hızlı)\w*\s+konuş|konuşma hızı|konuşmayı (yavaşlat|hızlandır)", cmd_lower)
    if m:
        slower = "yavaş" in m.group(0)
        cur = runtime.profile.data["prefs"].get("rate", -8)
        new = max(-40, min(40, (cur if isinstance(cur, int) else -8) + (-10 if slower else 10)))
        runtime.profile.set_pref("rate", new)
        return "Daha yavaş konuşuyorum." if slower else "Daha hızlı konuşuyorum."

    return None

# Compatibility for direct callers; production uses the narrowed controls only.
_user_command = _user_controls
