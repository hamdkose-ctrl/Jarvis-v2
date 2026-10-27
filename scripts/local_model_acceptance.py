from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
_repo_root_text = str(REPO_ROOT)
if _repo_root_text not in sys.path:
    sys.path.insert(0, _repo_root_text)

EXPECTED_STALE = "llama3.2"
EXPECTED_EFFECTIVE = "qwen2.5-coder:7b"


def contract_errors(status: dict) -> list[str]:
    """Feature-specific acceptance invariant'ları; kullanıcı ayarını değiştirmez."""
    installed = [str(x) for x in status.get("local_installed_models") or []]
    errors = []
    if status.get("local_backend") != "ollama":
        errors.append("yerel backend Ollama değil")
    if status.get("local_model_preference") != EXPECTED_STALE:
        errors.append("kayıtlı tercih beklenen stale llama3.2 değil")
    if EXPECTED_EFFECTIVE not in installed:
        errors.append("qwen2.5-coder:7b kurulu model listesinde yok")
    if EXPECTED_STALE in installed:
        errors.append("llama3.2 artık stale değil; acceptance senaryosu oluşmadı")
    if status.get("local_effective_model") != EXPECTED_EFFECTIVE:
        errors.append("effective model qwen2.5-coder:7b değil")
    if status.get("local_model_stale") is not True:
        errors.append("backend stale preference durumunu doğrulamadı")
    if status.get("local_model_select_enabled") is not True:
        errors.append("kurulu-model seçimi backend contract'ında etkin değil")
    return errors


def _browser_check(root: Path, status: dict) -> tuple[bool, str]:
    """Gerçek nx.html'yi gerçek Jarvis HTTP sunucusunda Chromium ile açıp DOM'u doğrula."""
    try:
        from playwright.sync_api import sync_playwright
        import web
    except Exception as exc:
        return False, f"browser acceptance bağımlılığı yok: {type(exc).__name__}"

    expected_installed = [str(x) for x in status.get("local_installed_models") or []]
    srv = None
    browser = None
    errors: list[str] = []
    try:
        web._fonts_ready.set()
        srv, url = web.serve(port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1594, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)[:240]))
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_function("typeof S !== 'undefined' && !!S.snap", timeout=15_000)
            page.wait_for_function(
                "typeof ACT !== 'undefined' && typeof ACT.localmodelsave === 'function'",
                timeout=15_000,
            )

            # Gerçek kullanıcı yolu: ana menüyü aç, ardından canlı nx.html'deki
            # Yapay zekâ menü eylemini tetikle. Eski go('settings') deep-link'i
            # ürünün güncel yan-panel yaşam döngüsünü temsil etmiyor.
            page.evaluate("go('menu')")
            ai_menu = page.wait_for_selector(
                "[data-act=\"mnopen\"][data-k=\"ai\"]",
                state="attached",
                timeout=15_000,
            )
            ai_menu.dispatch_event("click")
            page.wait_for_selector("#spane", state="attached", timeout=15_000)
            page.evaluate("SX.aiSel='ollama'; drawSettings()")
            page.wait_for_selector("#local-model-select", timeout=15_000)
            page.wait_for_function(
                "document.querySelector('#local-model-select') && "
                "document.querySelector('#local-model-select').options.length > 0 && "
                "document.body.innerText.includes('Aktif Model')",
                timeout=15_000,
            )
            page.wait_for_timeout(500)
            observed = page.evaluate("""() => {
                const row=[...document.querySelectorAll('.srow2')].find(x=>x.querySelector('b')?.textContent.trim()==='Aktif Model');
                const sel=document.querySelector('#local-model-select');
                return {
                    active: row?.querySelector('small')?.textContent.trim() || '',
                    options: sel ? [...sel.options].map(o=>o.value).filter(Boolean) : [],
                    legacyInput: !!document.querySelector('#om'),
                    legacySave: !!document.querySelector('[data-act="omsave"]'),
                    warning: document.body.innerText.includes('Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.'),
                    panelScript: [...document.scripts].some(s=>s.src.endsWith('/local-model-panel.js')),
                };
            }""")
            browser.close()
            browser = None

        if errors:
            return False, "browser JS hatası: " + errors[0]
        if not observed.get("panelScript"):
            return False, "local-model-panel.js canlı nx.html tarafından yüklenmedi"
        if observed.get("legacyInput") or observed.get("legacySave"):
            return False, "legacy serbest model input/save canlı DOM'da kaldı"
        if observed.get("active") != EXPECTED_EFFECTIVE:
            return False, f"canlı Aktif Model yanlış: {observed.get('active')!r}"
        if observed.get("options") != expected_installed:
            return False, f"canlı dropdown backend listesiyle aynı değil: {observed.get('options')!r}"
        if EXPECTED_STALE in observed.get("options", []):
            return False, "stale llama3.2 canlı dropdown seçeneğinde görünüyor"
        if status.get("local_model_stale") and not observed.get("warning"):
            return False, "stale preference bilgi metni canlı DOM'da görünmedi"
        return True, f"active={observed['active']}; options={','.join(observed['options'])}; legacy_input=false"
    except Exception as exc:
        detail = f"gerçek browser UI acceptance başarısız: {type(exc).__name__}: {str(exc)[:180]}"
        if errors:
            detail += f"; browser JS: {errors[0]}"
        return False, detail
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        except Exception:
            pass


def run(root: Path | None = None) -> dict:
    """Gerçek PC'de stale Ollama preference -> browser UI + installed effective model + inference kabulü."""
    root = Path(root or REPO_ROOT)
    from modules import llm, personalization
    from web_models import WebModels

    owner = personalization.slugify(personalization.get_active())
    token = llm._key_context.set(owner)
    try:
        bridge = WebModels()
        bridge._runtime = SimpleNamespace(llm=llm)
        status = bridge.llm_status()
        errors = contract_errors(status)
        if errors:
            return {"state": "failed", "detail": "; ".join(errors)}

        browser_ok, browser_detail = _browser_check(root, status)
        if not browser_ok:
            return {"state": "failed", "detail": browser_detail}

        llm.take_route()
        try:
            answer = llm._timed(
                "ollama",
                lambda: llm._ollama([{"role": "user", "content": "merhaba"}], "", 64),
            )
            routes = llm.take_route()
        except Exception as exc:
            llm.take_route()
            return {"state": "failed", "detail": f"gerçek Ollama inference başarısız: {type(exc).__name__}"}

        expected_route = f"Cevap: Ollama (yerel) · {EXPECTED_EFFECTIVE}"
        route_text = [str(text) for text, ok in routes if ok]
        if not isinstance(answer, str) or not answer.strip():
            return {"state": "failed", "detail": "gerçek Ollama inference boş yanıt verdi"}
        if expected_route not in route_text:
            return {"state": "failed", "detail": "inference route effective qwen2.5-coder:7b modelini doğrulamadı"}

        installed = [str(x) for x in status.get("local_installed_models") or []]
        return {
            "state": "passed",
            "detail": (
                f"saved={EXPECTED_STALE}; effective={EXPECTED_EFFECTIVE}; installed={','.join(installed)}; "
                f"browser_ui=passed ({browser_detail}); inference=passed"
            ),
        }
    finally:
        llm._key_context.reset(token)


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("state") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
