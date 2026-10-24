from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_PATTERN = "refs/remotes/origin/gpt/*"
STATE_NAME = "pc_test_watcher_state.json"
REPORT_NAME = "pc_test_watcher_last.json"


def run(cmd, *, cwd: Path, check: bool = True, capture: bool = False):
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def git_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip())


def python_exe(root: Path) -> Path | None:
    candidate = root / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else None


def gh_exe() -> str | None:
    found = shutil.which("gh") or shutil.which("gh.exe")
    if found:
        return found
    candidate = Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "GitHub CLI" / "gh.exe"
    return str(candidate) if candidate.is_file() else None


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def remote_heads(root: Path, pattern: str) -> list[dict]:
    run(["git", "fetch", "--prune", "origin"], cwd=root)
    proc = run([
        "git", "for-each-ref", "--sort=-committerdate",
        "--format=%(objectname)|%(refname)|%(committerdate:unix)", pattern,
    ], cwd=root, capture=True)
    rows = []
    for line in (proc.stdout or "").splitlines():
        try:
            sha, ref, when = line.split("|", 2)
            rows.append({"sha": sha, "ref": ref, "time": int(when)})
        except ValueError:
            continue
    return rows


def open_pr_refs(root: Path) -> set[str] | None:
    """Return remote refs whose GitHub PR is currently open.

    A Windows acceptance run is expensive and can open desktop applications.
    Remote ``gpt/*`` branches are not sufficient proof that somebody currently
    needs a result: old, merged and abandoned branches remain on origin.  If
    GitHub cannot be queried, fail closed instead of accepting an unrelated
    branch.
    """
    gh = gh_exe()
    if not gh:
        return None
    listed = run(
        [gh, "pr", "list", "--state", "open", "--limit", "100", "--json", "headRefName"],
        cwd=root,
        check=False,
        capture=True,
    )
    if listed.returncode != 0:
        return None
    try:
        prs = json.loads(listed.stdout or "[]")
    except ValueError:
        return None
    if not isinstance(prs, list):
        return None
    names = {
        row.get("headRefName")
        for row in prs
        if isinstance(row, dict) and isinstance(row.get("headRefName"), str) and row["headRefName"]
    }
    return {"refs/remotes/origin/" + name for name in names}


def _seen_entry(seen: dict, ref: str) -> dict | None:
    raw = seen.get(ref)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        # Legacy watcher state only remembered the SHA. It did not prove that
        # the branch was resolved, so recheck it once under the structured state.
        return {"sha": raw, "status": "legacy_seen", "last_attempt": 0.0}
    return None


def choose_candidate(candidates: list[dict], seen: dict, *, now: float | None = None) -> dict | None:
    for item in candidates:
        entry = _seen_entry(seen, item["ref"])
        # Her SHA yalnızca bir kez kabulden geçer. PASS/FAIL fark etmez;
        # aynı commit otomatik tekrar edilmez, yeni SHA yeni adaydır.
        if not entry or entry.get("sha") != item["sha"]:
            return item
        if entry.get("status") == "legacy_seen":
            return item
    return None


def safe_name(ref: str) -> str:
    return ref.replace("refs/remotes/origin/", "").replace("/", "_")


def branch_from_ref(ref: str) -> str:
    prefix = "refs/remotes/origin/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def add_worktree(root: Path, sha: str, target: Path) -> None:
    if target.exists():
        # Never delete a registered worktree directly: its .git indirection
        # must be removed first or a later detached checkout can be partial.
        remove_worktree(root, target)
    run(["git", "worktree", "prune"], cwd=root, check=False)
    run(["git", "worktree", "add", "--detach", str(target), sha], cwd=root)


def remove_worktree(root: Path, target: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(target)], cwd=root, check=False)
    shutil.rmtree(target, ignore_errors=True)


def acceptance_details(worktree: Path) -> list[dict]:
    path = worktree / "v2_kabul_sonucu.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    checks = data.get("checks") if isinstance(data, dict) else None
    return checks if isinstance(checks, list) else []


def _check_state(checks: list[dict], name: str) -> str | None:
    for row in checks:
        if isinstance(row, dict) and row.get("check") == name:
            return str(row.get("state") or "unknown")
    return None


def run_acceptance(py: Path, worktree: Path, *flags: str) -> dict:
    proc = run([str(py), "-X", "utf8", "-m", "modules.acceptance_checks", *flags, "--skip-suite"],
               cwd=worktree, check=False, capture=True)
    return {
        "exit_code": proc.returncode,
        "tail": "\n".join((proc.stdout or "").splitlines()[-120:]),
        "checks": acceptance_details(worktree),
    }


def run_suite(root: Path, worktree: Path, ref: str, sha: str, *, desktop: bool, news: bool) -> dict:
    py = python_exe(root)
    report = {"ref": ref, "sha": sha, "started": time.time(), "status": "failed"}
    if py is None:
        report["validation"] = {
            "exit_code": 2,
            "tail": "Doğrulama çalıştırılmadı: .venv\\Scripts\\python.exe bulunamadı.",
        }
        report["finished"] = time.time()
        return report

    print("[A] Validation basladi...", flush=True)
    validation = run([str(py), "-X", "utf8", "-m", "modules.validation"],
                     cwd=worktree, check=False, capture=True)
    report["validation"] = {
        "exit_code": validation.returncode,
        "tail": "\n".join((validation.stdout or "").splitlines()[-80:]),
    }
    print(f"[A] Validation bitti: exit={validation.returncode}", flush=True)
    if validation.returncode != 0:
        report["finished"] = time.time()
        return report

    if desktop:
        print("[B] Desktop acceptance basladi...", flush=True)
        desktop_result = run_acceptance(py, worktree, "--desktop")
        report["desktop_acceptance"] = desktop_result
        print(f"[B] Desktop acceptance bitti: exit={desktop_result['exit_code']}", flush=True)
        if desktop_result["exit_code"] != 0 or _check_state(desktop_result["checks"], "calculator") != "passed":
            report["finished"] = time.time()
            return report

    if news:
        print("[C] Haber acceptance basladi...", flush=True)
        news_result = run_acceptance(py, worktree, "--news")
        report["news_acceptance"] = news_result
        print(f"[C] Haber acceptance bitti: exit={news_result['exit_code']}", flush=True)
        if news_result["exit_code"] != 0 or _check_state(news_result["checks"], "news_chat_resume") != "passed":
            report["finished"] = time.time()
            return report

    report["status"] = "passed"
    report["finished"] = time.time()
    return report


def pr_comment_body(report: dict) -> str:
    lines = [
        "<!-- jarvis-pc-acceptance -->",
        "### Gerçek Windows PC kabul sonucu",
        f"- Commit: `{str(report.get('sha') or '')[:12]}`",
        f"- Genel durum: **{report.get('status', 'unknown')}**",
    ]
    required = {"desktop_acceptance": "calculator", "news_acceptance": "news_chat_resume"}
    for key, label in (("validation", "Validation"), ("desktop_acceptance", "Desktop"), ("news_acceptance", "Haber")):
        row = report.get(key)
        if isinstance(row, dict):
            passed = row.get('exit_code') == 0
            if key in required:
                passed = passed and _check_state(row.get('checks') or [], required[key]) == 'passed'
            lines.append(f"- {label}: **{'passed' if passed else 'failed'}**")
    lines.append("\nBu yorum gerçek iş PC'sindeki watcher tarafından otomatik üretildi; anahtarlar ve kişisel içerik gönderilmez.")
    return "\n".join(lines)


def publish_pr_comment(root: Path, ref: str, report: dict) -> dict:
    gh = gh_exe()
    if not gh:
        return {"state": "skipped", "reason": "gh_cli_missing"}
    listed = run([gh, "pr", "list", "--head", branch_from_ref(ref), "--state", "open", "--limit", "1", "--json", "number,url"],
                 cwd=root, check=False, capture=True)
    if listed.returncode != 0:
        return {"state": "skipped", "reason": "gh_unavailable_or_not_authenticated"}
    try:
        prs = json.loads(listed.stdout or "[]")
    except ValueError:
        return {"state": "failed", "reason": "gh_pr_list_invalid_json"}
    if not isinstance(prs, list) or not prs:
        return {"state": "skipped", "reason": "open_pr_not_found"}
    pr = prs[0]
    number = pr.get("number")
    posted = run([gh, "pr", "comment", str(number), "--body", pr_comment_body(report)],
                 cwd=root, check=False, capture=True)
    if posted.returncode != 0:
        return {"state": "failed", "reason": "gh_pr_comment_failed", "pr": number}
    return {"state": "published", "pr": number, "url": pr.get("url")}


def once(root: Path, state_path: Path, report_path: Path, pattern: str, *, desktop: bool, news: bool) -> bool:
    state = load_state(state_path)
    seen = state.setdefault("seen", {})
    open_refs = open_pr_refs(root)
    if open_refs is None:
        print("Açık PR listesi doğrulanamadı; fail-closed olarak test başlatılmadı.", flush=True)
        return False
    candidates = [item for item in remote_heads(root, pattern) if item["ref"] in open_refs]
    target = choose_candidate(candidates, seen)
    if not target:
        return False
    worktree = Path(tempfile.gettempdir()) / "jarvis-pc-acceptance" / (safe_name(target["ref"]) + "-" + target["sha"][:8])
    attempted_at = time.time()
    try:
        add_worktree(root, target["sha"], worktree)
        print("[1/4] Testler basladi...", flush=True)
        result = run_suite(root, worktree, target["ref"], target["sha"], desktop=desktop, news=news)
        print(f"[2/4] Test sonucu: {result.get('status')}", flush=True)
        result["github_pr_comment"] = publish_pr_comment(root, target["ref"], result)
        print("[4/4] Rapor yaziliyor...", flush=True)
        save_json(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        remove_worktree(root, worktree)
    status = "passed" if result.get("status") == "passed" else "failed"
    seen[target["ref"]] = {
        "sha": target["sha"],
        "status": status,
        "last_attempt": attempted_at,
        "last_result": str(result.get("status") or "unknown"),
    }
    state["updated"] = time.time()
    save_json(state_path, state)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub Actions olmadan Windows PC kabul izleyicisi")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--news", action="store_true", help="Yavaş haber kabulünü ayrı final aşaması olarak çalıştır")
    args = parser.parse_args()

    root = git_root()
    local_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Jarvis" / "pc-acceptance"
    state_path = local_dir / STATE_NAME
    report_path = local_dir / REPORT_NAME
    print(f"Jarvis PC test watcher başladı: {root}")
    print(f"İzlenen ref: {args.pattern}")
    print(f"Sonuç: {report_path}")
    while True:
        try:
            changed = once(root, state_path, report_path, args.pattern, desktop=not args.no_desktop, news=args.news)
            if not changed:
                print("Yalnız açık PR dallarında yeni test adayı yok.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            error = {"status": "watcher_error", "error": f"{type(exc).__name__}: {exc}", "time": time.time()}
            save_json(report_path, error)
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
