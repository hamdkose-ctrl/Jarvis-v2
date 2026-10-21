from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import pc_test_watcher as watcher
from pc_test_watcher import _record_failure
from codex_followup import run_followup


CODEX_STATE_NAME = "codex_followup_state.json"


def failure_hint(report: dict) -> str:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    if validation.get("exit_code") not in (None, 0):
        return "validation: " + " ".join(str(validation.get("tail") or "").split())[-1200:]
    desktop = report.get("desktop_acceptance") if isinstance(report.get("desktop_acceptance"), dict) else {}
    checks = desktop.get("checks") if isinstance(desktop.get("checks"), list) else []
    parts = []
    for row in checks:
        if not isinstance(row, dict) or row.get("state") == "passed":
            continue
        if row.get('state')!='failed' and row.get('check') not in {'calculator','news_chat_resume'}:
            continue
        name = str(row.get("check") or "unknown")
        state = str(row.get("state") or "unknown")
        detail = " ".join(str(row.get("detail") or "").split())[:500]
        parts.append(f"{name}={state}: {detail}" if detail else f"{name}={state}")
    if parts:
        return " | ".join(parts)[:1200]
    return "desktop_acceptance: " + " ".join(str(desktop.get("tail") or "").split())[-1200:]


def failure_signature(report: dict) -> str:
    if str(report.get("status") or "") != "failed":
        return ""
    normalized = failure_hint(report).lower()
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:20]


def should_run_codex(report: dict, state: dict) -> tuple[bool, str]:
    sha = str(report.get("sha") or "")
    if not sha:
        return False, "sha_missing"
    if state.get("sha") == sha:
        return False, "same_sha_already_handled"
    if str(report.get("status") or "") == "failed":
        signature = failure_signature(report)
        if signature and state.get("last_failure_signature") == signature:
            return False, "repeated_failure_stopped"
    return True, "new_result"


def next_state(report: dict, result: dict) -> dict:
    state = {
        "sha": str(report.get("sha") or ""),
        "time": time.time(),
        "result": result,
    }
    signature = failure_signature(report)
    if signature:
        state["last_failure_signature"] = signature
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows PC watcher + Codex yol haritası döngüsü")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--pattern", default=watcher.DEFAULT_PATTERN)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    args = parser.parse_args()

    root = watcher.git_root()
    local_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Jarvis" / "pc-acceptance"
    state_path = local_dir / watcher.STATE_NAME
    report_path = local_dir / watcher.REPORT_NAME
    codex_state_path = local_dir / CODEX_STATE_NAME

    print(f"Jarvis PC test + Codex döngüsü başladı: {root}")
    print(f"İzlenen ref: {args.pattern}")
    print(f"Sonuç: {report_path}")

    while True:
        try:
            changed = watcher.once(root, state_path, report_path, args.pattern, desktop=not args.no_desktop)
            if changed:
                report = watcher.load_state(report_path)
                codex_state = watcher.load_state(codex_state_path)
                comment = report.get("github_pr_comment") if isinstance(report.get("github_pr_comment"), dict) else {}
                run_it, reason = should_run_codex(report, codex_state)
                if comment.get("state") == "published" and run_it:
                    result = run_followup(
                        root,
                        str(report.get("ref") or ""),
                        str(report.get("sha") or ""),
                        str(report.get("status") or "unknown"),
                        failure_hint(report),
                    )
                    report["codex_followup"] = result
                    watcher.save_json(report_path, report)
                    watcher.save_json(codex_state_path, next_state(report, result))
                    print(f"Codex takip sonucu: {result.get('state')} ({result.get('reason', 'ok')})")
                elif comment.get("state") == "published" and reason == "repeated_failure_stopped":
                    result = {"state": "stopped", "reason": reason}
                    report["codex_followup"] = result
                    watcher.save_json(report_path, report)
                    watcher.save_json(codex_state_path, next_state(report, result))
                    print("Codex takip durdu: aynı hata tekrarlandı; kota koruması devrede.")
            else:
                print("Yeni test adayı yok.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            _record_failure('scripts/pc_test_loop.py:main')
            error = {"status": "loop_error", "error": f"{type(exc).__name__}: {exc}", "time": time.time()}
            watcher.save_json(report_path, error)
            print(error)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
