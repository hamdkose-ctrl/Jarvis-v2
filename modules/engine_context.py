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

def set_profile_voice(profile, key: str, *, voices=None, lane=None) -> tuple[bool, str]:
    """One profile mutation authority shared by typed web and spoken voice controls.

    Neither UI nor model may bypass exact installed-voice checks. Keep this
    function in engine_context rather than creating another preference writer.
    """
    from modules import voice_runtime
    if lane is None and voice_runtime.legacy_blocked():
        return False, "Voice Core yapılandırması geçersiz; önceki ses tercihin değişmedi."
    if lane is not None:
        try:
            label = lane.check_voice(key).label
        except (ValueError, OSError):
            return False, "Bu sesin yerel modeli veya Piper motoru kurulu değil. Önceki ses tercihin değişmedi."
    else:
        entry = voices.get(key) if isinstance(voices, dict) else None
        if entry is None:
            return False, "Seçilen ses mevcut değil; önceki ses tercihin değişmedi."
        label = entry[0].split(' · ')[0]
    if lane is not None and profile.data["prefs"].get("voice") != key:
        # Do not play queued speech from the previous identity after selection.
        lane.interrupt()
    profile.set_pref("voice", key)
    return True, label


def set_profile_rate(profile, rate: int, *, lane=None) -> bool:
    """Only voice-control preference writer for both web UI and spoken controls.

    Rate is a bounded request property, not a new voice identity. If a user
    explicitly enabled Piper but its selected voice is unavailable, do not
    save a setting and pretend it was applied to audible output.
    """
    from modules import voice_runtime
    if voice_runtime.legacy_blocked() or type(rate) is not int or not -40 <= rate <= 40:
        return False
    if lane is not None:
        selected = profile.data["prefs"].get("voice") or "tr_erkek"
        try:
            lane.check_voice(selected)
        except (ValueError, OSError):
            return False
    profile.set_pref("rate", rate)
    return True


def _set_voice(runtime, key: str) -> str:
    from modules import voice_runtime
    ok, label = set_profile_voice(
        runtime.profile, key, voices=runtime.voice.VOICES,
        lane=voice_runtime.active(),
    )
    if not ok:
        return label
    return f"Tamam {runtime.profile.name}, artık {label} sesiyle konuşuyorum."

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
    previous_owner = runtime.pc_profile().slug   # hoparlörün şu anki sahibi (geçiş öncesi)
    runtime.profile = runtime._get_profile(name)
    runtime.profile.save()
    runtime._llm.set_user_context(runtime.profile.slug)
    if runtime._guest is None:
        runtime.set_active(runtime.profile.name)          # bilgisayarın kullanıcısı değişti
    else:
        runtime._guest = runtime.profile.name             # telefondan: yalnızca o telefonun kullanıcısı (bilgisayar etkilenmez)
    runtime._sessions.reset(runtime.profile.slug)
    runtime._sessions._owner.set(runtime.profile.slug)
    speech_stop = ""
    if runtime.pc_profile().slug != previous_owner:
        # The audible speaker owner changed: stop the previous user's queued and
        # in-progress speech before the new user is greeted, so their audio never
        # continues into the new session. Called after the profile reassignment so
        # the per-chunk owner gate also rejects not-yet-started stale speech.
        from modules import voice_runtime
        if not voice_runtime.on_owner_switch(previous_owner):
            # The player did not acknowledge the stop inside the bound. Greeting the
            # new user as if it had would claim a stop that was not verified, so the
            # switch says exactly the two things that are true and nothing more: the
            # audio already in the speaker was not cut and can run on for its own
            # length, while no further chunk of the previous user's utterance starts
            # because the owner gate now names this new user. The one output owner
            # also means the new user's own speech queues behind that leftover
            # audio rather than playing over it (tests/test_voice_runtime_bridge.py).
            speech_stop = (" Önceki kullanıcının sesi kesilemedi; çalmakta olan bölüm"
                           " kısa süre devam edebilir ama kalan bölümleri çalmaz,"
                           " senin yanıtın da onunla üst üste binmez.")
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
                "Hedefini söylemek için hedefim, sesini seçmek için sesimi seç de." + speech_stop)
    goals = runtime.profile.data["goals"]
    if goals:
        return (f"Merhaba {runtime.profile.name}. Hedefin: {goals[-1]}. "
                f"Kaldığımız yerden devam edebiliriz.{speech_stop}")
    return f"Merhaba {runtime.profile.name}." + speech_stop
