from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
from pathlib import Path

import pc_test_watcher as watcher
from codex_followup import run_followup

CODEX_STATE_NAME = "codex_followup_state.json"


def failure_hint(report: dict) -> str:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    if validation.get("exit_code") not in (None, 0):
        return "validation: " + " ".join(str(validation.get("tail") or "").split())[-1200:]
    for key in ("news_acceptance", "desktop_acceptance"):
        block = report.get(key) if isinstance(report.get(key), dict) else {}
        if block.get("exit_code") not in (None, 0):
            return key + ": " + " ".join(str(block.get("tail") or "").split())[-1200:]
    return "acceptance failed"


def failure_signature(report: dict) -> str:
    if str(report.get("status") or "") != "failed":
        return ""
    return hashlib.sha256(failure_hint(report).lower().encode("utf-8", errors="replace")).hexdigest()[:20]


def should_run_codex(report: dict, state: dict) -> tuple[bool, str]:
    sha = str(report.get("sha") or "")
    if not sha:
        return False, "sha_missing"
    if state.get("sha") == sha:
        return False, "same_sha_already_handled"
    signature = failure_signature(report)
    if signature and state.get("last_failure_signature") == signature:
        return False, "repeated_failure_stopped"
    return True, "new_result"


def next_state(report: dict, result: dict) -> dict:
    state = {"sha": str(report.get("sha") or ""), "time": time.time(), "result": result}
    signature = failure_signature(report)
    if signature:
        state["last_failure_signature"] = signature
    return state


def run_news_final(root: Path, report: dict) -> dict:
    ref = str(report.get("ref") or "")
    sha = str(report.get("sha") or "")
    worktree = Path(tempfile.gettempdir()) / "jarvis-pc-acceptance" / (watcher.safe_name(ref) + "-news-" + sha[:8])
    try:
        watcher.add_worktree(root, sha, worktree)
        print("[C] Haber final acceptance basladi...", flush=True)
        result = watcher.run_acceptance(watcher.python_exe(root), worktree, "--news")
        print(f"[C] Haber final acceptance bitti: exit={result['exit_code']}", flush=True)
        report["news_acceptance"] = result
        news_state = watcher._check_state(result.get("checks") or [], "news_chat_resume")
        report["status"] = "passed" if result["exit_code"] == 0 and news_state == "passed" else "failed"
        report["finished"] = time.time()
        return report
    finally:
        watcher.remove_worktree(root, worktree)


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows PC kabul + Terra takip döngüsü")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--pattern", default=watcher.DEFAULT_PATTERN)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    root = watcher.git_root()
    local_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Jarvis" / "pc-acceptance"
    state_path = local_dir / watcher.STATE_NAME
    report_path = local_dir / watcher.REPORT_NAME
    codex_state_path = local_dir / CODEX_STATE_NAME

    print(f"Jarvis PC test + Terra döngüsü başladı: {root}")
    print("Aşamalar: validation -> desktop -> ayrı haber finali -> Terra")

    while True:
        try:
            changed = watcher.once(root, state_path, report_path, args.pattern, desktop=True, news=False)
            if not changed:
                print("Yeni test adayı yok.")
            else:
                report = watcher.load_state(report_path)
                if report.get("status") == "passed":
                    report = run_news_final(root, report)
                    report["github_pr_comment"] = watcher.publish_pr_comment(root, str(report.get("ref") or ""), report)
                    watcher.save_json(report_path, report)

                codex_state = watcher.load_state(codex_state_path)
                run_it, reason = should_run_codex(report, codex_state)
                if run_it:
                    print(f"[3/4] Terra cagriliyor: {report.get('status')}", flush=True)
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
                    print(f"[3/4] Terra tamamlandi: {result.get('state')}", flush=True)
                elif reason == "repeated_failure_stopped":
                    result = {"state": "stopped", "reason": reason}
                    report["codex_followup"] = result
                    watcher.save_json(report_path, report)
                    watcher.save_json(codex_state_path, next_state(report, result))
                    print("Terra durdu: aynı hata tekrarlandı; kota koruması devrede.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
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
