"""Gerçek tarayıcıda (Playwright Chromium) menü gezinti senaryosu: ana ekran → menü → Sohbet → Çalışma → Ekran → Dosyalar → kapat.
Geçici USERPROFILE kullanır; kullanıcının gerçek verisine dokunmaz. Her adımda sayfa, yan sayfa başlığı ve eski kabuğun
(üst çubuk, alt çubuk, sağ şerit) görünmediği yazılır.
Kullanım: .venv\\Scripts\\python.exe -X utf8 -I tools\\ui_senaryo.py <depo klasörü> <ekran görüntüsü klasörü>"""
import os, sys, tempfile, types, json, threading
from pathlib import Path
from unittest.mock import MagicMock
REPO = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
tmp = tempfile.mkdtemp(prefix='jarvis_probe_')
os.environ['USERPROFILE'] = tmp; os.environ['HOME'] = tmp
sys.path.insert(0, str(REPO)); os.chdir(REPO)
if 'pyautogui' not in sys.modules:
    stub = types.ModuleType('pyautogui'); stub.__getattr__ = lambda a: MagicMock(); sys.modules['pyautogui'] = stub
import web
web._fonts_ready.set()
srv, url = web.serve()
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright
STATE = """()=>{const sc=document.querySelector('.mnscene');const t=document.querySelector('#mn-card .mn-ovh b');
 const top=document.querySelector('#top'),dock=document.querySelector('#body>#dock'),rail=document.querySelector('#rail');
 const vis=e=>!!e&&getComputedStyle(e).display!=='none'&&e.getBoundingClientRect().height>0;
 return {page:S.page,altOrblar:[...document.querySelectorAll('#mn-svg text tspan')].map(x=>x.textContent).join('|'),scene:!!sc,docked:!!sc&&sc.classList.contains('docked'),wide:!!sc&&sc.classList.contains('dock-wide'),panel:t?t.textContent:null,
  eskiUst:vis(top),eskiAltCubuk:vis(dock),eskiSag:vis(rail),askInPanel:!!document.querySelector('#dockhost #dock'),holo:!!document.querySelector('.jarvis-hologram')}}"""
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1594, 'height': 850})
    pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.on('console', lambda m: errs.append('console:' + m.text[:160]) if m.type == 'error' else None)
    pg.goto(url); pg.wait_for_timeout(3500)
    def step(name, js=None, wait=1800, shot=False):
        if js: pg.evaluate(js)
        pg.wait_for_timeout(wait)
        print(f'{name:34}', json.dumps(pg.evaluate(STATE), ensure_ascii=False))
        if shot: pg.screenshot(path=str(OUT / f'{shot}.png'))
    step('1 açılış (ana ekran)')
    step('2 MENÜ', "go('menu')")
    step('3 Sohbet orbuna bas', "menuCard(MENU_ROSTER.find(r=>r[0]==='chat'))")
    step('4 Çalışma orbuna bas', "menuCard(MENU_ROSTER.find(r=>r[0]==='study'))")
    step('5 Ekran orbuna bas', "menuCard(MENU_ROSTER.find(r=>r[0]==='ekran'))", 2500)
    step('6 Dosyalar alt orbuna bas', "go('files')")
    step('7 Sohbet tekrar', "menuCard(MENU_ROSTER.find(r=>r[0]==='chat'))")
    step('8 × ile kapat', "ACT.mnclose()")
    step('9 boş yere bas (docked yok)', "menuOutsideClick(document.querySelector('.mnscene'),{target:document.body})")
    step('10 eski adres go(vision)', "go('vision')", 2500)
    step('11 eski adres go(settings)', "S.sset='ses';go('settings')", 2500)
    step('12 ana ekrana dön', "go('home')", 2500)
    step('13 sohbet (eski adres) go(chat)', "go('chat')", 2500, 'chat_from_home')
    print('JS hataları:', errs[:6])
    b.close()
