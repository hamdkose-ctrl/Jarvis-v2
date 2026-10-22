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
QUOTA_RETRY_SECONDS = 300

FOCUS_PROFILES = (
    (("news", "rss", "haber"), "news", "--news", "news_chat_resume"),
    (("gmail", "mail"), "gmail", "--gmail", "gmail_attachment"),
    (("video",), "video", "--video", "video_runtime"),
    (("narration", "voice", "ses"), "narration", "--narration", "speaker_voice_quality"),
    (("public-data", "public_data"), "public_data", "--public-data", "public_news_report"),
    (("desktop", "windows-pc", "pc-control", "pc_control"), "desktop", "--desktop", "calculator"),
)


def focus_profile(ref: str) -> tuple[str, str, str] | None:
    name = str(ref or "").casefold()
    for tokens, profile, flag, check in FOCUS_PROFILES:
        if any(token in name for token in tokens):
            return profile, flag, check
    return None


def failure_hint(report: dict) -> str:
    focus = report.get("focus_acceptance") if isinstance(report.get("focus_acceptance"), dict) else {}
    if focus.get("exit_code") not in (None, 0):
        return "focus_acceptance: " + " ".join(str(focus.get("tail") or "").split())[-1200:]
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


def _result_state(state: dict) -> str:
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    return str(result.get("state") or "")


def should_run_codex(report: dict, state: dict, *, now: float | None = None) -> tuple[bool, str]:
    status = str(report.get("status") or "")
    if status in {"passed", "focus_passed"}:
        return False, "already_passed"
    sha = str(report.get("sha") or "")
    if not sha:
        return False, "sha_missing"
    current_time = time.time() if now is None else now
    if state.get("sha") == sha:
        if _result_state(state) == "pending_quota":
            retry_after = float(state.get("retry_after") or 0)
            if current_time >= retry_after:
                return True, "quota_retry"
            return False, "quota_wait"
        return False, "same_sha_already_handled"
    # A new SHA is a new repair attempt. Even if it exposes the same failure
    # signature, Terra must get another turn because the code changed.
    return True, "new_result"


def next_state(report: dict, result: dict) -> dict:
    now = time.time()
    state = {"sha": str(report.get("sha") or ""), "time": now, "result": result}
    if str(result.get("state") or "") == "pending_quota":
        state["retry_after"] = now + QUOTA_RETRY_SECONDS
        return state
    signature = failure_signature(report)
    if signature:
        state["last_failure_signature"] = signature
    return state


def run_focus_gate(root: Path, target: dict, profile: tuple[str, str, str]) -> dict:
    profile_name, flag, check_name = profile
    ref = str(target.get("ref") or "")
    sha = str(target.get("sha") or "")
    report = {
        "ref": ref,
        "sha": sha,
        "started": time.time(),
        "status": "failed",
        "focus_profile": profile_name,
    }
    worktree = Path(tempfile.gettempdir()) / "jarvis-pc-acceptance" / (watcher.safe_name(ref) + "-focus-" + sha[:8])
    try:
        watcher.add_worktree(root, sha, worktree)
        py = watcher.python_exe(root)
        if py is None:
            report["focus_acceptance"] = {
                "exit_code": 2,
                "tail": "Odak kabulü çalıştırılmadı: .venv\\Scripts\\python.exe bulunamadı.",
                "checks": [],
            }
        else:
            print(f"[F] Odak kabulü basladi: {profile_name}", flush=True)
            result = watcher.run_acceptance(py, worktree, flag)
            report["focus_acceptance"] = result
            check_state = watcher._check_state(result.get("checks") or [], check_name)
            passed = result.get("exit_code") == 0 and check_state == "passed"
            report["status"] = "focus_passed" if passed else "failed"
            print(f"[F] Odak kabulü bitti: {profile_name} -> {report['status']}", flush=True)
        report["finished"] = time.time()
        return report
    finally:
        watcher.remove_worktree(root, worktree)


def mark_focus_failure(state_path: Path, target: dict, report: dict) -> None:
    state = watcher.load_state(state_path)
    seen = state.setdefault("seen", {})
    seen[str(target["ref"])] = {
        "sha": str(target["sha"]),
        "status": "pending_retry",
        "last_attempt": time.time(),
        "last_result": str(report.get("status") or "failed"),
    }
    state["updated"] = time.time()
    watcher.save_json(state_path, state)


def run_terra_if_needed(root: Path, report_path: Path, codex_state_path: Path, report: dict) -> None:
    codex_state = watcher.load_state(codex_state_path)
    run_it, reason = should_run_codex(report, codex_state)
    if run_it:
        label = "kota sonrasi yeniden deneniyor" if reason == "quota_retry" else str(report.get("status") or "unknown")
        print(f"[3/4] Terra cagriliyor: {label}", flush=True)
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
        if result.get("state") == "pending_quota":
            print(f"Terra kotasi dolu; {QUOTA_RETRY_SECONDS // 60} dk sonra otomatik tekrar denenecek.", flush=True)
        else:
            print(f"[3/4] Terra tamamlandi: {result.get('state')}", flush=True)
    elif reason == "already_passed":
        print("Terra atlandi: bu SHA tum gerekli kapilardan gecti.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows PC odak kabul + genel doğrulama + Terra takip döngüsü")
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
    print("Aşamalar: işin odak kabulü -> geçerse validation + desktop -> Terra")

    while True:
        try:
            state = watcher.load_state(state_path)
            seen = state.setdefault("seen", {})
            target = watcher.choose_candidate(watcher.remote_heads(root, args.pattern), seen)
            report = watcher.load_state(report_path)

            if target:
                profile = focus_profile(str(target.get("ref") or ""))
                if profile:
                    focus_report = run_focus_gate(root, target, profile)
                    if focus_report.get("status") != "focus_passed":
                        focus_report["github_pr_comment"] = watcher.publish_pr_comment(root, str(target.get("ref") or ""), focus_report)
                        watcher.save_json(report_path, focus_report)
                        mark_focus_failure(state_path, target, focus_report)
                        run_terra_if_needed(root, report_path, codex_state_path, focus_report)
                        if args.once:
                            return 0
                        time.sleep(max(10, args.interval))
                        continue
                    print("[F] Odak geçti; genel doğrulamaya geçiliyor.", flush=True)

                changed = watcher.once(root, state_path, report_path, args.pattern, desktop=True, news=False)
                report = watcher.load_state(report_path)
                if changed:
                    run_terra_if_needed(root, report_path, codex_state_path, report)
            else:
                run_terra_if_needed(root, report_path, codex_state_path, report)
                print("Yeni test adayı yok.")
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
