"""Windows sistem kontrolü: ses, parlaklık, medya, uygulama açma, kapatma."""
from modules.diagnostics import record_failure as _record_failure
from modules import requests_state
import difflib
import json
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any

import pyautogui
from functools import wraps


def _permission_decision(action, target=''):
    try:
        from modules import llm, permission_audit, permission_classify, permission_gate, permission_policy, service_store
        owner = llm._key_context.get()
        service_store.identity(owner)
        kind, recognized = permission_classify.classify_detail('system', action, target)
        if not recognized:
            kind = 'local_reversible'  # Tanınmayan ad mevcut işlem politikasında kalır.
        result = permission_gate.decide({'class': kind, 'target': target, 'via': 'system'})
        decision, reason = permission_policy.apply(owner, 'system', kind, result['decision'], result['reason'])
        if decision not in ('allow', 'ask', 'deny'):
            raise ValueError('Geçersiz izin kararı.')
        permission_audit.record(owner, decision, kind, target, 'system', reason)
    except Exception:
        _record_failure('modules/system_control.py:permission_gate')
        decision, reason = 'deny', 'İzin denetimi tamamlanamadı; sistem işlemi yapılmadı.'
    if decision != 'allow':
        raise PermissionError(reason)


def _permission_instrument(action, target):
    @wraps(target)
    def guarded(*args, **kwargs):
        name = next((value for value in (*args, *kwargs.values()) if isinstance(value, str)), action)
        _permission_decision(action, name)
        return target(*args, **kwargs)
    return guarded

# Sabit kısayollar. Bunların dışında yalnızca Başlat menüsünde kurulu görünen uygulamalar açılır
# (serbest komut çalıştırılmaz; komut enjeksiyonu olmaz).
# Yeni uygulama eklemek için: "söylenen ad": "çalıştırılacak program" satırı ekle.
APPS = {
    "chrome": "chrome",
    "krom": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "tarayıcı": "msedge",
    "notepad": "notepad",
    "not defteri": "notepad",
    "notdefteri": "notepad",
    "hesap makinesi": "calc",
    "calculator": "calc",
    "calc": "calc",
    "calculatorapp": "calc",
    "paint": "mspaint",
    "excel": "excel",
    "word": "winword",
    "powerpoint": "powerpnt",
    "power point": "powerpnt",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "outlook": "outlook",
    "teams": "ms-teams",
    "dosya gezgini": "explorer",
}


_TR = str.maketrans({"İ": "i", "I": "ı"})


def _norm(text: str) -> str:
    """Küçük harfe çevirir (Türkçe İ/I doğru), noktalama ve fazla boşluğu temizler."""
    t = text.translate(_TR).casefold().replace("i̇", "i")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


# --- Kurulu uygulamalar: Başlat menüsünden bulunur; yalnızca bu listedekiler açılır -------------
_installed: dict[str, tuple[str, str, str]] = {}   # normalleşmiş ad -> (gösterilen ad, tür, hedef)
_installed_at = 0.0
_installed_lock = threading.Lock()


def _scan_installed() -> dict[str, tuple[str, str, str]]:
    found: dict[str, tuple[str, str, str]] = {}
    if os.name != "nt":
        return found
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:   # mağaza ve klasik uygulamalar (Steam, Spotify, Hesap Makinesi, WhatsApp ...)
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, timeout=25, creationflags=flags).stdout.decode("utf-8", "ignore")
        data = json.loads(out) if out.strip() else []
        for item in data if isinstance(data, list) else [data]:
            name, app_id = str(item.get("Name") or ""), str(item.get("AppID") or "")
            if name and app_id:
                found.setdefault(_norm(name), (name, "appid", app_id))
    except Exception:
        _record_failure('modules/system_control.py:_scan_installed')
        pass
    roots = [os.path.join(os.environ.get(v, ""), "Microsoft", "Windows", "Start Menu", "Programs")
             for v in ("ProgramData", "APPDATA")]
    for root in roots:   # Başlat menüsü kısayolları (yukarıdaki liste boş kalırsa da çalışır)
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".lnk"):
                    name = f[:-4]
                    found.setdefault(_norm(name), (name, "lnk", os.path.join(dirpath, f)))
    return found


def installed_apps(refresh: bool = False) -> dict[str, tuple[str, str, str]]:
    """Kurulu uygulamalar (30 dakika önbellekli)."""
    global _installed, _installed_at
    with _installed_lock:
        if refresh or not _installed or time.time() - _installed_at > 1800:
            _installed, _installed_at = _scan_installed(), time.time()
        return _installed


def _match_installed(n: str) -> tuple[str, str, str] | None:
    apps = installed_apps()
    if not apps or not n:
        return None
    if n in apps:
        return apps[n]
    words = n.split()
    matches = []
    for key, val in apps.items():                       # "steam" -> "Steam", "code" -> "Visual Studio Code"
        kw = key.split()
        if len(n) >= 4 and (kw[:len(words)] == words or (len(words) == 1 and n in kw)):
            matches.append(val)
    if matches:
        return matches[0] if len(matches) == 1 else None
    flat = n.replace(" ", "")                          # "power point" -> "powerpoint"
    for key, val in apps.items():
        if key.replace(" ", "") == flat and len(flat) >= 4:
            return val
    close = difflib.get_close_matches(n, list(apps), n=3, cutoff=0.82) if len(n) >= 4 else []
    return apps[close[0]] if len(close) == 1 else None


def find_app(name: str) -> str | None:
    """Söylenen adı açılabilir bir uygulama adına çevirir (sabit liste, sonra kurulu uygulamalar)."""
    n = name.casefold().strip(" '’.")
    n = re.sub(r"\s+uygulaması$", "", n)
    if re.fullmatch(r"(?:pc|bilgisayar|windows)['’]?(?:in|ın|un|ün)?\s+ayar\w*", n):
        n = "ayarlar"   # "pc ayarları / windows ayarları": Windows Ayarlar uygulaması (Jarvis'in kendi sayfası değil)
    elif n not in APPS and not _match_installed(_norm(n)):
        n = re.sub(r"^(?:pc|bilgisayar|windows)['’]?(?:in|ın|un|ün)?\s+(?=\S)", "", n)   # "pc not defteri" -> "not defteri"
    if n in APPS:
        return n
    stripped = re.sub(r"['’]?(?:y?[ıiuü]|n[ıiuü])$", "", n).strip(" '’")
    if stripped in APPS:
        return stripped
    for cand in (_norm(n), _norm(stripped)):
        hit = _match_installed(cand)
        if hit:
            return hit[0]
    return None


class ApplicationResult(str):
    """Keep the spoken string API, with independently verified action evidence."""
    def __new__(cls, message, *, ok=False, candidates=()):
        value = super().__new__(cls, message)
        value.ok = ok
        value.candidates = tuple(candidates)
        return value


def suggest_apps(name: str) -> list[str]:
    n = _norm(name)
    if len(n) < 2:
        return []
    ranked = []
    for key, (display, _kind, _target) in installed_apps().items():
        score = difflib.SequenceMatcher(None, n, key).ratio()
        if n in key or any(word.startswith(n) for word in key.split()):
            score = max(score, .85)
        if score >= .55:
            ranked.append((score, display))
    return [display for _score, display in sorted(ranked, key=lambda row: (-row[0], row[1]))[:5]]


def _visible_application(key):
    executable = APPS.get(key, '')
    aliases = {'calc': {'calc', 'calculator', 'calculatorapp'}, 'notepad': {'notepad'},
               'ms-teams': {'ms-teams', 'teams'}, 'code': {'code'}}
    names = aliases.get(executable, {executable}) if executable else set()
    for hwnd, title, exe in _app_windows():
        # A browser tab with an app's name is not evidence that that app opened.
        native_name = _norm(exe).replace(' ', '')
        installed_names = {_norm(key).replace(' ', '')} | {word for word in _norm(key).split() if len(word) >= 4}
        if exe in names or (not executable and native_name in installed_names):
            return hwnd
        if exe == 'applicationframehost' and ((executable == 'calc' and _norm(title) in {'hesap makinesi', 'calculator'}) or
                                              (not executable and _norm(title) == _norm(key))):
            # A UWP frame's title is only a candidate; prove its child identity.
            from modules import desktop_uia
            try:
                result = desktop_uia._call({'op': 'observe', 'hwnd': hwnd})
                hosted = result.get('app') not in ('applicationframehost', '', None)
                if (result.get('app') in names or (not executable and hosted)) and result.get('app_pid'):
                    return hwnd
            except requests_state.Cancelled:
                raise
            except (ValueError, OSError):
                pass
    return None


def open_application(app_name: str) -> str:
    """Sabit listedeki ya da Başlat menüsünde kurulu uygulamayı açar; kullanıcıya söylenecek mesajı döndürür."""
    key = find_app(app_name)
    if not key:
        choices = suggest_apps(app_name)
        message = f"'{app_name}' adını uygulamalar arasında kesin olarak eşleştiremedim."
        if choices:
            message += ' Hangisini açayım? ' + '; '.join(f'{i+1}. {n}' for i, n in enumerate(choices))
        else:
            message += ' Uygulamanın başka bir adını söyleyebilir misin?'
        return ApplicationResult(message, candidates=choices)
    try:
        # Opening an already verified window again can create duplicate UWP
        # instances (notably Calculator) during repeated PC acceptance runs.
        # Existing visibility is sufficient evidence for an "open" request;
        # do not manufacture another instance or steal its foreground focus.
        if _visible_application(key):
            return ApplicationResult(f'{key.capitalize()} zaten açık; yeni pencere başlatmadım.', ok=True)
        if key in APPS:
            logging.getLogger("jarvis").info("Uygulama açılıyor: %s (sabit: %s)", key, APPS[key])
            launched = subprocess.run(["cmd", "/c", "start", "", APPS[key]],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,   # boru yok: açılan uygulama boruyu tutup 8 sn'lik zaman aşımına yol açmasın
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if launched.returncode:
                return ApplicationResult(f'{key} başlatılamadı; Windows başlatma komutu hata verdi.')
            display = key.capitalize()
        else:
            hit = _match_installed(_norm(key))
            if not hit:
                return ApplicationResult(f"'{app_name}' adında kurulu bir uygulama bulamadım.")
            display, kind, target = hit
            if kind == "lnk":
                os.startfile(target)   # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 12   # yeni Not Defteri gibi uygulamalar pencereyi geç açabilir
        for _ in range(48):
            requests_state.check()
            if time.monotonic() >= deadline:
                break
            if _visible_application(key):
                return ApplicationResult(f'{display} penceresi açık; açılışı doğruladım.', ok=True)
            time.sleep(.25)
        return ApplicationResult(f'{display} için başlatma komutunu gönderdim ama açık bir pencere doğrulayamadım. Açıldı demiyorum.')
    except requests_state.Cancelled:
        raise
    except Exception as e:
        _record_failure('modules/system_control.py:open_application')
        print(f"Uygulama açılırken hata: {e}")
        return ApplicationResult(f"{key} uygulamasını açamadım.")


def _volume_endpoint() -> Any:
    """Windows ana ses denetleyicisini (pycaw) döndürür; yeni ve eski pycaw sürümleriyle çalışır."""
    from pycaw.pycaw import AudioUtilities

    speakers: Any = AudioUtilities.GetSpeakers()
    if speakers is None:
        raise RuntimeError("Varsayılan hoparlör bulunamadı.")

    endpoint = getattr(speakers, "EndpointVolume", None)   # yeni pycaw
    if endpoint is not None:
        return endpoint

    from ctypes import POINTER, cast                        # eski pycaw
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface: Any = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(level: int) -> bool:
    """Ses seviyesini yüzde olarak ayarlar, sessizdeyse (Mute) açar. Başarılıysa True döner."""
    try:
        volume = _volume_endpoint()
        if volume.GetMute() == 1:
            volume.SetMute(0, None)
        clamped = max(0, min(100, level)) / 100.0
        volume.SetMasterVolumeLevelScalar(clamped, None)
        print(f"Ses seviyesi %{max(0, min(100, level))} yapıldı.")
        return True
    except Exception as e:
        _record_failure('modules/system_control.py:set_volume')
        print(f"Ses ayarlanırken hata oluştu: {e}")
        return False


def change_volume_by_delta(delta: int) -> int | None:
    """Mevcut sesi delta (örn. +15 / -10) kadar değiştirir. Yeni seviyeyi döndürür, hata olursa None."""
    try:
        volume = _volume_endpoint()
        if volume.GetMute() == 1:
            volume.SetMute(0, None)
        current = round(volume.GetMasterVolumeLevelScalar() * 100)
        new_volume = max(0, min(100, current + delta))
        volume.SetMasterVolumeLevelScalar(new_volume / 100.0, None)
        return new_volume
    except Exception as e:
        _record_failure('modules/system_control.py:change_volume_by_delta')
        print(f"Kademeli ses değiştirilirken hata: {e}")
        return None


def is_muted() -> bool | None:
    """Bilgisayarın sesi sessizde mi? Okunamazsa None."""
    try:
        return bool(_volume_endpoint().GetMute())
    except Exception:
        _record_failure('modules/system_control.py:is_muted')
        return None


def set_mute(on: bool) -> bool:
    """Sesi kesin olarak sessize alır (on=True) ya da sessizden çıkarır. Klavyedeki sessiz tuşu gibi durumu
    tersine çevirmez: zaten sessizdeyken "sessize al" sesi açmaz. Başarılıysa True."""
    try:
        _volume_endpoint().SetMute(1 if on else 0, None)
        return True
    except Exception as e:
        _record_failure('modules/system_control.py:set_mute')
        print(f"Sessiz ayarlanamadı: {e}")
        return False


def current_volume() -> int | None:
    try:
        return round(_volume_endpoint().GetMasterVolumeLevelScalar() * 100)
    except Exception:
        _record_failure('modules/system_control.py:current_volume')
        return None


def mute_volume():
    """Eski uyumluluk: sessize alır (artık durumu tersine çevirmez). Ayarlanamazsa klavye tuşuna basar."""
    _permission_decision('mute_volume')
    if not set_mute(True):
        pyautogui.press("volumemute")


def shutdown_pc():
    """Bilgisayarı 60 saniye içinde kapatmak üzere zamanlar."""
    return subprocess.run(["shutdown", "/s", "/t", "60"], check=False).returncode==0


def cancel_shutdown():
    """Zamanlanmış bilgisayar kapatma işlemini iptal eder."""
    return subprocess.run(["shutdown", "/a"], check=False).returncode==0


def set_brightness(level: int) -> bool:
    """Ekran parlaklığını yüzde olarak ayarlar (0-100). Başarılıysa True döner."""
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(max(0, min(100, level)))
        return True
    except Exception as e:
        _record_failure('modules/system_control.py:set_brightness')
        print(f"Parlaklık ayarlanırken hata: {e}")
        return False


def brightness_matches(level: int) -> bool:
    """True only if every readable display reports the requested percentage."""
    try:
        import screen_brightness_control as sbc
        observed = sbc.get_brightness()
        values = [observed] if isinstance(observed, (int, float)) and not isinstance(observed, bool) else observed
        if not isinstance(values, (list, tuple)) or not values:
            return False
        target = max(0, min(100, int(level)))
        return all(isinstance(value, (int, float)) and not isinstance(value, bool) and round(value) == target
                   for value in values)
    except Exception:
        _record_failure('modules/system_control.py:brightness_matches')
        return False


def set_brightness_verified(level: int) -> bool:
    """Set brightness, then require an exact device readback before success."""
    return set_brightness(level) and brightness_matches(level)


def media_control(action: str) -> bool:
    """Müzik/medya tuşlarını simüle eder. Tanınan bir eylemse True döner."""
    actions = {
        "play_pause": "playpause",
        "durdur": "playpause",
        "oynat": "playpause",
        "next": "nexttrack",
        "sonraki": "nexttrack",
        "prev": "prevtrack",
        "önceki": "prevtrack",
    }
    target = actions.get(str(action or "").lower())
    if not target:
        return False
    pyautogui.press(target)
    return True


def open_new_tab(url: str = "https://google.com"):
    """Tarayıcıda yeni bir sekme açar."""
    _permission_decision('open_new_tab', url)
    try:
        import webbrowser
        webbrowser.open_new_tab(url)
    except Exception as e:
        _record_failure('modules/system_control.py:open_new_tab')
        print(f"Sekme açılırken hata: {e}")


# --- Uygulama kapatma: açık pencerelere "kapan" mesajı gönderilir (zorla öldürülmez) ----------------
# Uygulama kaydedilmemiş bir iş varsa her zamanki gibi "kaydedilsin mi?" diye sorar.
_CLOSE_EXE = {"calc": "calculatorapp", "explorer": "explorer"}
_NEVER_CLOSE = {"python", "pythonw", "py", "dwm", "csrss", "winlogon", "searchhost", "startmenuexperiencehost",
                "shellexperiencehost", "textinputhost", "lockapp", "systemsettings"}


def _window_cloaked(hwnd):
    """UWP hidden backing windows can be visible to EnumWindows but not on screen."""
    import ctypes
    from ctypes import wintypes
    try:
        fn = ctypes.windll.dwmapi.DwmGetWindowAttribute
        fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        fn.restype = ctypes.c_long
        cloaked = wintypes.DWORD()
        return fn(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and bool(cloaked.value)
    except (AttributeError, OSError):
        return False


def _app_windows() -> list[tuple[int, str, str]]:
    """Görünür üst düzey pencereler: (tutamaç, başlık, program adı küçük harf, .exe'siz)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    import psutil
    user32 = _window_api()
    out: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):     # 4 = GW_OWNER (açılır pencereler)
            return True
        if _window_cloaked(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            exe = psutil.Process(pid.value).name().lower()
        except Exception:
            _record_failure('modules/system_control.py:cb')
            return True
        out.append((hwnd, buf.value, exe[:-4] if exe.endswith(".exe") else exe))
        return True

    user32.EnumWindows(cb, 0)
    return out


# Windows Ayarlar sayfaları (sabit ms-settings adresleri; serbest komut çalıştırılmaz).
# İlk liste "ayarları" denince Windows'a aittir; ikinci liste Jarvis'in kendi sayfalarıyla karışabilir, yalnız pc/bilgisayar/windows denince.
_SETTINGS_PAGES = [
    (r"wi-?fi|kablosuz", "network-wifi", "Wi-Fi"), (r"bluetooth", "bluetooth", "Bluetooth"),
    (r"\bağ\b|internet", "network", "Ağ ve internet"), (r"ekran|görüntü|parlaklık", "display", "Ekran"),
    (r"güncelleme", "windowsupdate", "Windows Update"), (r"pil|güç|uyku", "powersleep", "Güç ve pil"),
    (r"depolama|disk", "storagesense", "Depolama"), (r"bildirim", "notifications", "Bildirimler"),
    (r"görev çubuğu", "taskbar", "Görev çubuğu"), (r"arka plan|duvar kağıdı", "personalization-background", "Arka plan"),
    (r"renk|karanlık mod|koyu mod|tema|kişiselleştirme", "colors", "Renkler ve tema"),
    (r"klavye", "typing", "Klavye"), (r"fare|dokunmatik", "mousetouchpad", "Fare ve dokunmatik yüzey"),
    (r"yazıcı|tarayıcı cihaz", "printers", "Yazıcılar"), (r"saat|tarih", "dateandtime", "Tarih ve saat"),
    (r"\bdil\b|bölge", "regionlanguage", "Dil ve bölge"), (r"varsayılan uygulama", "defaultapps", "Varsayılan uygulamalar"),
    (r"hesap(?:lar)?(?:ım)?\b", "yourinfo", "Hesap bilgileri"),
]
_SETTINGS_QUALIFIED = [
    (r"\bses\b", "sound", "Ses"), (r"gizlilik", "privacy", "Gizlilik"), (r"güvenlik", "windowsdefender", "Windows Güvenliği"),
    (r"uygulama", "appsfeatures", "Uygulamalar"), (r"sistem", "about", "Sistem"),
]


def windows_settings(command: str):
    """“wifi ayarlarını aç”, “pc ses ayarları” gibi komutta Windows Ayarlar sayfasını açar; komut buna ait değilse None."""
    text = _norm(command)
    if not re.search(r"\bayar", text) or not re.search(r"\b(?:aç\w*|göster\w*|git\w*|getir\w*)\b", text) or re.search(r"\bjarvis", text):
        return None
    qualified = bool(re.search(r"\b(?:pc|bilgisayar\w*|windows)\b", text))
    for pages, allowed in ((_SETTINGS_PAGES, True), (_SETTINGS_QUALIFIED, qualified)):
        if not allowed:
            continue
        for pattern, page, label in pages:
            if re.search(pattern, text):
                _permission_decision('windows_settings', command)
                if os.name != "nt":
                    return ApplicationResult("Windows Ayarlar yalnız Windows'ta açılır.")
                try:
                    os.startfile("ms-settings:" + page)   # type: ignore[attr-defined]
                except OSError:
                    _record_failure('modules/system_control.py:windows_settings')
                    return ApplicationResult(f"{label} ayarlarını açamadım.")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    requests_state.check()
                    if _visible_application("ayarlar"):
                        return ApplicationResult(f"Windows Ayarlar açık; {label} sayfasına gitmesi için komutu gönderdim.", ok=True)
                    time.sleep(.25)
                return ApplicationResult(f"{label} ayarları için komutu gönderdim ama Ayarlar penceresini doğrulayamadım. Açıldı demiyorum.")
    return None


def close_application(app_name: str) -> str | None:
    """Söylenen uygulamanın açık pencerelerini kapatır. Ad hiçbir uygulamaya benzemiyorsa None döner."""
    base = _norm(app_name)
    base = re.sub(r"\s*\b(?:uygulamas[ıi]n?[ıi]?|program[ıi]n?[ıi]?|penceres[ıi]n?[ıi]?|oyunu?n?u?)\b", "", base).strip()
    stripped = re.sub(r"\s*(?:y?[ıiuü]|n[ıiuü])$", "", base).strip()       # "chrome u" / "hesap makinesini"
    windows = _app_windows()
    order = [stripped, base] if re.search(r"\s(?:y|n)?[ıiuü]$", base) else [base, stripped]   # "chrome'u" -> önce "chrome"
    for n in dict.fromkeys(order):
        if len(n) < 2:
            continue
        key = n if n in APPS else find_app(n)
        want_exe = _CLOSE_EXE.get(APPS.get(key or "", ""), APPS.get(key or "", "")).lower()
        flat = n.replace(" ", "")
        hits = []
        for hwnd, title, exe in windows:
            if exe in _NEVER_CLOSE or ("jarvis" in title.lower() and "komut merkezi" in title.lower()):
                continue
            t = _norm(title)
            names = {n} | ({_norm(key)} if key else set())
            if (want_exe and exe == want_exe) or exe == flat \
                    or any(len(m) >= 4 and (m.replace(" ", "") in exe or m in t.split() or (" " in m and m in t))
                           for m in names) \
                    or (len(flat) >= 4 and difflib.SequenceMatcher(None, flat, exe).ratio() >= .82):
                hits.append(hwnd)
        label = key.capitalize() if key and key in APPS else (key or n.capitalize())
        if hits:
            import ctypes
            for hwnd in hits:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE: nazikçe kapan
            for _ in range(12):
                requests_state.check()
                remaining = {hwnd for hwnd, _title, _exe in _app_windows()}.intersection(hits)
                if not remaining:
                    return ApplicationResult(f'{label} pencerelerinin kapandığını doğruladım.', ok=True)
                time.sleep(.25)
            return ApplicationResult(f'{label} için kapatma isteği gönderdim ama pencere hâlâ açık. Kaydetme sorusu veya uygulama uyarısı bekliyor olabilir.')
        if key:
            return ApplicationResult(f"{label} şu an açık görünmüyor.", ok=True)
    return None


def _window_api():
    """Pointer-sized HWND declarations (64-bit Windows handles must not be truncated)."""
    import ctypes
    from ctypes import wintypes
    if os.name != 'nt':
        raise OSError('Pencere kontrolü yalnızca Windows üzerinde kullanılabilir.')
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = wintypes.HWND
    for name in ('IsWindow', 'IsIconic', 'IsZoomed', 'SetForegroundWindow'):
        fn=getattr(api,name);fn.argtypes=[wintypes.HWND];fn.restype=wintypes.BOOL
    api.IsWindowVisible.argtypes=[wintypes.HWND];api.IsWindowVisible.restype=wintypes.BOOL
    api.GetWindow.argtypes=[wintypes.HWND,ctypes.c_uint];api.GetWindow.restype=wintypes.HWND
    api.GetWindowTextLengthW.argtypes=[wintypes.HWND];api.GetWindowTextLengthW.restype=ctypes.c_int
    api.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    api.PostMessageW.argtypes=[wintypes.HWND,ctypes.c_uint,wintypes.WPARAM,wintypes.LPARAM]
    api.PostMessageW.restype=wintypes.BOOL
    api.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    api.ShowWindow.restype=wintypes.BOOL
    return api


def list_windows() -> dict:
    if os.name != 'nt':
        return {'ok':False,'message':'Pencere kontrolü yalnızca Windows üzerinde kullanılabilir.'}
    return {'ok':True,'windows':[{'title':title,'app':exe} for _,title,exe in _app_windows()]}


def _select_window(target, windows):
    n=_norm(target)
    if not n:return []
    exact=[w for w in windows if _norm(w[1])==n]
    if exact:return exact
    app_name = re.sub(r'\s+uygulaması$', '', n)
    if app_name not in APPS:
        stripped = re.sub(r"['’]?(?:y?[ıiuü]|n[ıiuü])$", '', app_name).strip()
        if stripped in APPS:
            app_name = stripped
    key=APPS.get(app_name,n)
    if key == 'calc':
        hits = [w for w in windows if w[2] in {'calc', 'calculator', 'calculatorapp'} or
                (w[2] == 'applicationframehost' and _norm(w[1]) in {'hesap makinesi', 'calculator'})]
        if hits:
            return hits
    exe=_CLOSE_EXE.get(key,key).removesuffix('.exe')
    hits=[w for w in windows if _norm(w[2])==_norm(exe)]
    if hits:return hits
    return [w for w in windows if len(n)>=3 and n in _norm(w[1])]


def window_action(target: str, action: str, *, hwnd=None) -> dict:
    """Choose a unique window and verify native state after the operation."""
    if action not in ('focus','minimize','maximize','restore'):
        return {'ok':False,'message':'Pencere işlemi geçersiz.'}
    try:
        api=_window_api()
        hits=_select_window(target,_app_windows())
        if hwnd is not None:
            hits = [w for w in hits if w[0] == hwnd]
        if not hits:return {'ok':False,'message':f'“{target}” için açık pencere bulunamadı.'}
        if len(hits)!=1:
            choices=[w[1] for w in hits]
            return {'ok':False,'needs_clarification':True,'message':'Birden fazla pencere var. Hangisi? '+ '; '.join(choices),'choices':choices}
        hwnd,title,_=hits[0]
        if not api.IsWindow(hwnd):return {'ok':False,'message':'Seçilen pencere artık açık değil.'}
        if action=='focus':
            if api.IsIconic(hwnd):api.ShowWindow(hwnd,9) # SW_RESTORE
            api.SetForegroundWindow(hwnd)
            check=lambda:api.GetForegroundWindow()==hwnd
        else:
            api.ShowWindow(hwnd,{'minimize':6,'maximize':3,'restore':9}[action])
            check=lambda: (bool(api.IsIconic(hwnd)) if action=='minimize' else
                           bool(api.IsZoomed(hwnd)) if action=='maximize' else
                           not api.IsIconic(hwnd) and not api.IsZoomed(hwnd))
        # Native changes can be asynchronous; bounded verification, never a false success.
        success=check()
        for _ in range(5):
            if success:break
            time.sleep(.05);success=check()
        if not success:return {'ok':False,'message':'Pencere değişikliğini doğrulayamadım. Windows işlemi engellemiş olabilir.'}
        labels={'focus':'öne getirildi','minimize':'küçültüldü','maximize':'büyütüldü','restore':'eski boyutuna getirildi'}
        return {'ok':True,'message':title+' '+labels[action]+'.','title':title,'hwnd':hwnd}
    except (OSError,AttributeError) as e:
        return {'ok':False,'message':str(e)}


_SHORTCUTS={'new_tab':('ctrl','t'),'next_tab':('ctrl','tab'),'previous_tab':('ctrl','shift','tab'),
            'find':('ctrl','f'),'save':('ctrl','s'),'copy':('ctrl','c'),'paste':('ctrl','v'),
            'select_all':('ctrl','a'),'undo':('ctrl','z'),'redo':('ctrl','y')}

def window_shortcut(target: str, shortcut: str) -> dict:
    """Only named shortcuts, sent after verifying the specified foreground window."""
    from modules import requests_state
    requests_state.check()
    if shortcut not in _SHORTCUTS:return {'ok':False,'message':'Bu klavye işlemi kayıtlı değil.'}
    focused=window_action(target,'focus')
    if not focused.get('ok'):return focused
    requests_state.check()
    if _window_api().GetForegroundWindow()!=focused['hwnd']:
        return {'ok':False,'message':'Odak değişti; klavye işlemi gönderilmedi.'}
    pyautogui.hotkey(*_SHORTCUTS[shortcut])
    return {'ok':True,'message':focused['title']+': klavye kısayolu gönderildi. Uygulamanın sonucunu ekrandan kontrol edebilirsin.'}

# Keep all existing PC entry points on the same typed execution boundary.
# The underlying functions retain their window, owner and approval guards.
from modules.pc_contracts import CATALOG as _PC_CONTRACTS, instrument as _pc_instrument
for _pc_name in _PC_CONTRACTS:
    globals()[_pc_name]=_pc_instrument(_pc_name,_permission_instrument(_pc_name,globals()[_pc_name]))
