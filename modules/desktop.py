"""4) Masaüstü işlemleri (Windows/macOS/Linux). Güvenlik için beyaz liste kullanılır."""
import os, platform, subprocess, webbrowser
import psutil

OS = platform.system()
ALLOWED_APPS = {
    "not defteri": {"Windows": "notepad", "Darwin": "TextEdit", "Linux": "gedit"},
    "hesap makinesi": {"Windows": "calc", "Darwin": "Calculator", "Linux": "gnome-calculator"},
    "tarayıcı": None,  # webbrowser ile açılır
}

def open_app(name: str) -> str:
    name = name.lower()
    if name not in ALLOWED_APPS:
        return f"'{name}' izinli uygulamalar listesinde yok."
    if ALLOWED_APPS[name] is None:
        webbrowser.open("https://www.google.com"); return "Tarayıcı açıldı."
    cmd = ALLOWED_APPS[name][OS]
    if OS == "Darwin": subprocess.Popen(["open", "-a", cmd])
    else: subprocess.Popen([cmd])
    return f"{name} açıldı."

def open_url(url: str) -> str:
    webbrowser.open(url); return f"Açıldı: {url}"

def system_status() -> str:
    mem = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=0.5)
    batt = psutil.sensors_battery()
    b = f", pil %{batt.percent:.0f}" if batt else ""
    return f"CPU %{cpu}, RAM %{mem}{b}"

def screenshot(path: str | None = None) -> str:
    """Ekran görüntüsü alır. path verilmezse Pictures\\Jarvis altına zaman damgalı kaydeder."""
    import time
    import pyautogui
    if path is None:
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("ekran_%Y%m%d_%H%M%S.png"))
    pyautogui.screenshot(path)
    return f"Kaydedildi: {os.path.abspath(path)}"

def volume(delta: int) -> str:
    import pyautogui
    key = "volumeup" if delta > 0 else "volumedown"
    for _ in range(abs(delta)): pyautogui.press(key)
    return "Ses ayarlandı."
