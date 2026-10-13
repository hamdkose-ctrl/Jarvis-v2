"""Open Jarvis's isolated browser for manual login; no model reads credentials."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules import browser_agent, llm, privacy
from modules.diagnostics import record_failure as _record_failure
if __name__=='__main__':
    if blocked:=privacy.blocked('web'): raise SystemExit(blocked)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit('Önce Jarvis kökündeki kurulum.bat dosyasını çalıştır.')
    owner=llm.current_user()
    with browser_agent._LOCK, sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(browser_agent._root(owner)/'profile'),headless=False,accept_downloads=False)
        page=context.pages[0] if context.pages else context.new_page()
        page.goto('https://www.google.com',wait_until='domcontentloaded')
        print('Siteye kendin gir. Oturum bu kullanıcının tarayıcı profilinde tutulur. Bitince tarayıcı pencerelerini kapat.')
        try:
            while context.pages:
                context.pages[0].wait_for_timeout(500)
        except Exception:
            _record_failure('scripts/tarayici_oturumu.py:manual_session')
        finally: context.close()
