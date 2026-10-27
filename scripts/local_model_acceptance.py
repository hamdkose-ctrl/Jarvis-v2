from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

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


def _render_check(root: Path, status: dict) -> tuple[bool, str]:
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        return False, "Node.js bulunamadı; production UI render acceptance çalışmadı."
    env = os.environ.copy()
    env["JARVIS_LOCAL_MODEL_STATUS_JSON"] = json.dumps(status, ensure_ascii=False)
    proc = subprocess.run(
        [node, "tests/ai_page_behavior.js"],
        cwd=str(root),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    tail = "\n".join((proc.stdout or "").splitlines()[-20:])
    marker = "canlı nx.html script zincirinde canonical status ile production render geçti."
    return proc.returncode == 0 and marker in (proc.stdout or ""), tail


def run(root: Path | None = None) -> dict:
    """Gerçek PC'de stale Ollama preference -> installed effective model + UI + inference kabulü."""
    root = Path(root or Path(__file__).resolve().parents[1])
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

        render_ok, render_tail = _render_check(root, status)
        if not render_ok:
            return {"state": "failed", "detail": "production model panel render başarısız", "render_tail": render_tail}

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
                f"saved={EXPECTED_STALE}; effective={EXPECTED_EFFECTIVE}; "
                f"installed={','.join(installed)}; production_render=passed; inference=passed"
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
