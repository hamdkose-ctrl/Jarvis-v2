"""Focused runtime actions with explicitly injected dependencies."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

def _jarvis_hwnds(runtime) -> list[int]:
    """Komut Merkezi pencerelerinin Windows tutamaçları (başlığa göre)."""
    if not runtime.sys.platform.startswith('win'):
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            v = buf.value
            if v.startswith('JARVIS · Senin Yapay Zek') or ('Komut Merkezi' in v and 'Jarvis' in v):
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return found

def _win_action(runtime, action: str) -> bool:
    """Üst çubuktaki pencere düğmeleri: küçült, tam ekran/pencere arası geçiş, gizle (tepsiye) ve geri getir."""
    hwnds = runtime._jarvis_hwnds()
    if not hwnds:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    for h in hwnds:
        if action == 'min':
            user32.ShowWindow(h, 6)
        elif action == 'hide':
            user32.ShowWindow(h, 0)
        elif action == 'show':
            if not user32.IsWindowVisible(h) or user32.IsIconic(h):
                user32.ShowWindow(h, 9)
            user32.SetForegroundWindow(h)
        elif action == 'full':
            runtime.config.save_settings(fullscreen=not runtime.config.load_settings().get('fullscreen', False))
            runtime.threading.Thread(target=runtime._reopen_window, daemon=True).start()
            break
    return True

def _reopen_window(runtime) -> None:
    with runtime._window_lock:
        runtime.time.sleep(0.3)
        runtime._close_windows()
        runtime.time.sleep(0.8)
        runtime._window_open_until = 0.0
        runtime.open_window(runtime._url)

def _close_windows(runtime) -> None:
    """Jarvis'in kendi açtığı Komut Merkezi pencerelerini (ayrı tarayıcı profili) kapatır; kullanıcının tarayıcısına dokunmaz."""
    try:
        import psutil
        mark = str(runtime.DATA_DIR / 'webprofile').lower()
        for p in psutil.process_iter(['cmdline']):
            try:
                if mark in ' '.join(p.info.get('cmdline') or []).lower():
                    p.kill()
            except (psutil.Error, OSError):
                pass
    except Exception:
        _record_failure('web.py:_close_windows')
        pass

def _find_browser(runtime) -> str | None:
    if runtime.sys.platform.startswith('win'):
        roots = [runtime.os.environ.get(v) for v in ('ProgramFiles(x86)', 'ProgramFiles', 'LocalAppData')]
        rel = ['Microsoft\\Edge\\Application\\msedge.exe', 'Google\\Chrome\\Application\\chrome.exe']
        for r in rel:
            for root in roots:
                if root and runtime.Path(root, r).exists():
                    return str(runtime.Path(root, r))
        return None
    for name in ('microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser', 'chrome'):
        p = runtime.shutil.which(name)
        if p:
            return p
    return None

def _loading_hwnds(runtime) -> list[int]:
    """Yeni açılan, sayfası henüz yüklenmemiş Jarvis penceresi: başlığı Jarvis adresi (127.0.0.1:port) olan pencere."""
    if not runtime.sys.platform.startswith('win') or not runtime._url:
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    key = runtime._url.split('://', 1)[-1].split('/', 1)[0]
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if key in buf.value:
                found.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return found

def _set_jarvis_icon(runtime, hwnd) -> None:
    """Pencerenin (görev çubuğu + başlık) simgesini doğrudan jarvis.ico yapar. Edge önce kendi simgesini,
    sayfa yüklenince sitenin simgesini gösteriyordu; pencere bulunur bulunmaz Jarvis simgesi atanır."""
    import ctypes
    ico = runtime.WEB / 'jarvis.ico'
    if not ico.exists():
        return
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    try:
        set_cls = user32.SetClassLongPtrW
        set_cls.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    except AttributeError:
        set_cls = None
    for size, which, gcl in ((256, 1, -14), (32, 0, -34)):
        try:
            h = user32.LoadImageW(None, str(ico), 1, size, size, 16)
            if h:
                user32.SendMessageW(hwnd, 128, ctypes.c_void_p(which), ctypes.c_void_p(h))
                if set_cls is not None:
                    set_cls(hwnd, gcl, ctypes.c_void_p(h))
        except Exception:
            _record_failure('web.py:_set_jarvis_icon')
            pass

def _center_window(runtime, wait: float=15.0) -> None:
    """Pencere her açılışta aynı boyutta ve ekranın ortasında açılsın (Edge son konumu hatırlayıp
    pencereyi taşırabiliyordu). Boyut: çalışma alanının %84 genişliği, %87 yüksekliği."""
    if not runtime.sys.platform.startswith('win'):
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    try:
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        _record_failure('web.py:_center_window')
        pass
    end = runtime.time.time() + wait
    while runtime.time.time() < end:
        runtime.time.sleep(0.05)
        for h in runtime._loading_hwnds():
            runtime._set_jarvis_icon(h)
        hw = runtime._jarvis_hwnds()
        if not hw:
            continue
        for h in hw:
            runtime._set_jarvis_icon(h)
        runtime.time.sleep(0.4)
        for h in runtime._jarvis_hwnds():
            try:
                mon = user32.MonitorFromWindow(h, 2)

                class MI(ctypes.Structure):
                    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]
                mi = MI()
                mi.cbSize = ctypes.sizeof(MI)
                user32.GetMonitorInfoW(mon, ctypes.byref(mi))
                wa = mi.rcWork
                ww, wh = (wa.right - wa.left, wa.bottom - wa.top)
                w, hgt = (int(ww * 0.84), int(wh * 0.87))
                x, y = (wa.left + (ww - w) // 2, wa.top + (wh - hgt) // 2)
                user32.ShowWindow(h, 9)
                user32.SetWindowPos(h, 0, x, y, w, hgt, 4 | 16)
            except Exception:
                _record_failure('web.py:_center_window')
                pass
        return

def open_window(runtime, url: str) -> None:
    # Tray, widget and startup can all arrive before the first SSE connection.
    # Reserve the launch until a window appears or the startup timeout expires.
    with runtime._window_lock:
        if runtime._jarvis_hwnds() or runtime._loading_hwnds():
            runtime._win_action('show')
            return
        now = runtime.time.monotonic()
        if now < runtime._window_open_until:
            return
        runtime._window_open_until = now + 15.0
        try:
            _open_window(runtime, url)
        except BaseException:
            runtime._window_open_until = 0.0
            raise

def _open_window(runtime, url: str) -> None:
    exe = runtime._find_browser()
    if exe and '--no-window' not in runtime.sys.argv:
        try:
            profile = runtime.DATA_DIR / 'webprofile'
            runtime.subprocess.Popen([exe, f'--app={url}', f'--user-data-dir={profile}', '--window-size=1290,722', '--window-position=120,50', '--no-first-run', '--no-default-browser-check', '--disable-features=Translate', '--autoplay-policy=no-user-gesture-required'])
            runtime.threading.Thread(target=runtime._center_window, daemon=True).start()
            return
        except OSError:
            pass
    import webbrowser
    if not webbrowser.open(url):
        runtime._window_open_until = 0.0

def _watchdog(runtime) -> None:
    """Pencere kapanınca (hiç tarayıcı bağlı kalmayınca) Jarvis'i de kapatır; sistem tepsisi açıksa tepside çalışmaya devam eder."""
    while True:
        runtime.time.sleep(2)
        with runtime.hub.lock:
            gone = runtime.hub.ever and (not runtime.hub.clients) and (runtime.time.time() - runtime.hub.empty_since > 25)
        if (gone and runtime._tray is None and getattr(runtime, '_mascot', None) is None
                and not runtime.phone.running):
            runtime._shutdown(reason='pencere kapandı')

def _main_window_open(runtime) -> bool:
    """Komut Merkezi ekranda mı (gizli ya da küçültülmüş değil)?"""
    if not runtime.sys.platform.startswith('win'):
        with runtime.hub.lock:
            return bool(runtime.hub.clients)
    import ctypes
    user32 = ctypes.windll.user32
    return any((user32.IsWindowVisible(h) and (not user32.IsIconic(h)) for h in runtime._jarvis_hwnds()))

def _widget_should_hide(runtime) -> bool:
    """Küçük Jarvis YALNIZCA ana pencere simge durumuna küçültülünce görünür (Hamdi'nin isteği).
    Pencere açıkken (arkada kalsa bile) ya da hiç pencere yokken gizli kalır."""
    if not runtime.sys.platform.startswith('win'):
        return runtime._main_window_open()
    import ctypes
    user32 = ctypes.windll.user32
    hw = runtime._jarvis_hwnds()
    return not (hw and all((user32.IsIconic(h) for h in hw)))

def _aname(runtime) -> str:
    """Asistanın şu anki adı (Ayarlar'dan değiştirilebilir; yeniden başlatmadan ekrana yansır). 3 sn önbellekli."""
    if runtime.time.time() - runtime._aname_cache['t'] > 3:
        runtime._aname_cache.update(t=runtime.time.time(), v=(runtime.config.load_settings().get('assistant_name') or 'Jarvis').strip() or 'Jarvis')
    return runtime._aname_cache['v']

def _show_main(runtime) -> None:
    """Komut Merkezi'ni öne getirir (gizliyse gösterir, kapalıysa yeniden açar)."""
    if runtime._win_action('show'):
        return
    with runtime.hub.lock:
        has = bool(runtime.hub.clients)
    if not has:
        runtime.open_window(runtime._url)

def _set_mic(runtime, on: bool) -> bool:
    """Mikrofonun tek merkezi anahtarı. Küçük pencere, tepsi ve web arayüzü aynı yolu kullanır.

    Kapanırken süren kayıtları ortak iptal olayıyla (mic_cancel) keser ve uyandırma sayacını
    sıfırlar; yalnız bayrağı değiştirmek aktif dinlemeyi ekranda açık bırakabiliyordu.
    """
    on = bool(on)
    if on:
        from modules import developer
        state = developer.status(runtime._p().slug)
        if state.get('enabled') and state.get('unlocked'):
            runtime.hub.publish('system', 'Geliştirme ekranında mikrofon kapalı; yazı veya görsel kullan.')
            return False
    runtime.engine.flags['mic'] = on
    try:
        if on:
            runtime.engine.mic_cancel.clear()
        else:
            runtime.engine.mic_cancel.set()
    except Exception:
        _record_failure('web.py:_set_mic')
        pass
    if not on:
        try:
            from modules import wakeword as _ww
            _ww.reset()
        except Exception:
            _record_failure('web.py:_set_mic')
            pass
        runtime.hub.publish('state', 'idle')
    else:
        runtime.hub.publish('state', 'idle' if runtime.hub.state == 'listening' else runtime.hub.state)
    return on

def _run_widget(runtime) -> bool:
    """Masaüstü küçük Jarvis'i ana iş parçacığında çalıştırır (kapanana kadar döner). Kullanılamazsa False."""
    if not runtime.config.load_settings().get('widget', True):
        return False
    try:
        from modules import widget as widgetmod
        if not widgetmod.available():
            return False
    except Exception:
        _record_failure('web.py:_run_widget')
        return False

    def state() -> tuple[str, dict]:
        f = dict(runtime.engine.flags)
        if f.get('sleep'):
            return ('sleep', f)
        st = runtime.hub.state or 'idle'
        if not f.get('mic', True) and st == 'idle':
            st = 'muted'
        return (st, f)

    def talk() -> None:
        if not runtime.engine.flags.get('mic', True):
            runtime.hub.publish('state', 'idle')
            return
        if runtime.engine.flags.get('sleep'):
            runtime.engine.set_sleep(False, announce=False)
        runtime.engine.events.put(('listen',))

    def mic() -> None:
        runtime._set_mic(not runtime.engine.flags.get('mic', True))
    pos = runtime.config.load_settings().get('widget_pos2')
    runtime._widget = widgetmod.Widget(state, {'talk': talk, 'open': runtime._show_main, 'mic': mic, 'sleep': lambda: runtime.engine.set_sleep(not runtime.engine.flags.get('sleep')), 'quit': lambda: runtime.threading.Thread(target=lambda: runtime._shutdown(reason='küçük Jarvis menüsü'), daemon=True).start()}, pos=tuple(pos) if isinstance(pos, list) and len(pos) == 2 else None, save_pos=lambda x, y: runtime.config.save_settings(widget_pos2=[x, y]), main_open=runtime._widget_should_hide, visible=runtime.config.load_settings().get('widget_on', True) is not False)
    try:
        runtime._widget.run()
    except Exception as exc:
        _record_failure('web.py:_run_widget')
        print(f'Masaüstü küçük Jarvis açılamadı: {type(exc).__name__}')
        runtime._widget = None
        return False
    return True

def _start_tray(runtime) -> None:
    """Sağ alttaki tepsi simgesi: göster / mikrofon aç-kapat / çıkış. pystray yoksa eski davranış (pencere kapanınca kapanır)."""
    if not runtime.config.load_settings().get('tray', True):
        return
    from modules import tray as traymod
    def surface():
        return getattr(runtime, '_mascot', None) or runtime._widget

    def show():
        mascot = getattr(runtime, '_mascot', None)
        if mascot:
            mascot.reveal_card()
        else:
            runtime._show_main()

    def toggle():
        widget = surface()
        if widget:
            widget.toggle()

    def mic() -> None:
        runtime._set_mic(not runtime.engine.flags.get('mic', True))

    def sleep() -> None:
        runtime.engine.set_sleep(not runtime.engine.flags.get('sleep'))
    runtime._tray = traymod.start(show, mic, lambda: runtime.engine.flags['mic'], lambda *a: runtime._shutdown(reason='tepsi menüsü'), name=runtime._aname, on_sleep=sleep, is_sleep=lambda: bool(runtime.engine.flags.get('sleep')), on_widget=toggle, is_widget=lambda: bool(surface() and surface().is_visible()), on_console=runtime._show_main)
