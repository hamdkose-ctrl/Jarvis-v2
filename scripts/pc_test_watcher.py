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
    return Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    )


def python_exe(root: Path) -> Path:
    candidate = root / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else Path(sys.executable)


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
    proc = run(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(objectname)|%(refname)|%(committerdate:unix)",
            pattern,
        ],
        cwd=root,
        capture=True,
    )
    rows = []
    for line in (proc.stdout or "").splitlines():
        try:
            sha, ref, when = line.split("|", 2)
            rows.append({"sha": sha, "ref": ref, "time": int(when)})
        except ValueError:
            continue
    return rows


def choose_candidate(candidates: list[dict], seen: dict) -> dict | None:
    return next((item for item in candidates if seen.get(item["ref"]) != item["sha"]), None)


def safe_name(ref: str) -> str:
    return ref.replace("refs/remotes/origin/", "").replace("/", "_")


def branch_from_ref(ref: str) -> str:
    prefix = "refs/remotes/origin/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def add_worktree(root: Path, sha: str, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    run(["git", "worktree", "add", "--detach", str(target), sha], cwd=root)


def remove_worktree(root: Path, target: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(target)], cwd=root, check=False)
    shutil.rmtree(target, ignore_errors=True)


def acceptance_command(py: Path) -> list[str]:
    return [str(py), "-X", "utf8", "-m", "modules.acceptance_checks", "--desktop", "--news", "--skip-suite"]


def acceptance_details(worktree: Path) -> list[dict]:
    path = worktree / "v2_kabul_sonucu.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    checks = data.get("checks") if isinstance(data, dict) else None
    return checks if isinstance(checks, list) else []


def _brief(value, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def pr_comment_body(report: dict) -> str:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    desktop = report.get("desktop_acceptance") if isinstance(report.get("desktop_acceptance"), dict) else {}
    checks = desktop.get("checks") if isinstance(desktop.get("checks"), list) else []
    selected = {row.get("check"): row for row in checks if isinstance(row, dict)}
    lines = [
        "<!-- jarvis-pc-acceptance -->",
        "### Gerçek Windows PC kabul sonucu",
        f"- Commit: `{str(report.get('sha') or '')[:12]}`",
        f"- Genel durum: **{report.get('status', 'unknown')}**",
        f"- Validation: **{'passed' if validation.get('exit_code') == 0 else 'failed'}**",
    ]
    for name in ("calculator", "news_chat_resume"):
        row = selected.get(name)
        if not row:
            continue
        state = row.get("state", "unknown")
        lines.append(f"- `{name}`: **{state}**")
        if name == "news_chat_resume" and row.get("detail"):
            lines.append(f"  - {_brief(row.get('detail'))}")
    lines.append("\nBu yorum gerçek iş PC'sindeki watcher tarafından otomatik üretildi; anahtarlar ve kişisel içerik gönderilmez.")
    return "\n".join(lines)


def publish_pr_comment(root: Path, ref: str, report: dict) -> dict:
    if not shutil.which("gh"):
        return {"state": "skipped", "reason": "gh_cli_missing"}
    branch = branch_from_ref(ref)
    listed = run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--limit", "1", "--json", "number,url"],
        cwd=root,
        check=False,
        capture=True,
    )
    if listed.returncode != 0:
        return {"state": "skipped", "reason": "gh_unavailable_or_not_authenticated"}
    try:
        prs = json.loads(listed.stdout or "[]")
    except ValueError:
        return {"state": "failed", "reason": "gh_pr_list_invalid_json"}
    if not isinstance(prs, list) or not prs:
        return {"state": "skipped", "reason": "open_pr_not_found"}
    pr = prs[0] if isinstance(prs[0], dict) else {}
    number = pr.get("number")
    if not isinstance(number, int):
        return {"state": "failed", "reason": "open_pr_number_missing"}
    posted = run(
        ["gh", "pr", "comment", str(number), "--body", pr_comment_body(report)],
        cwd=root,
        check=False,
        capture=True,
    )
    if posted.returncode != 0:
        return {"state": "failed", "reason": "gh_pr_comment_failed", "pr": number}
    return {"state": "published", "pr": number, "url": pr.get("url")}


def run_suite(root: Path, worktree: Path, ref: str, sha: str, *, desktop: bool) -> dict:
    py = python_exe(root)
    report = {
        "ref": ref,
        "sha": sha,
        "started": time.time(),
        "validation": None,
        "desktop_acceptance": None,
        "status": "failed",
    }

    validation = run(
        [str(py), "-X", "utf8", "-m", "modules.validation"],
        cwd=worktree,
        check=False,
        capture=True,
    )
    report["validation"] = {
        "exit_code": validation.returncode,
        "tail": "\n".join((validation.stdout or "").splitlines()[-80:]),
    }
    if validation.returncode != 0:
        report["finished"] = time.time()
        return report

    if desktop:
        acceptance = run(
            acceptance_command(py),
            cwd=worktree,
            check=False,
            capture=True,
        )
        report["desktop_acceptance"] = {
            "exit_code": acceptance.returncode,
            "tail": "\n".join((acceptance.stdout or "").splitlines()[-120:]),
            "checks": acceptance_details(worktree),
        }
        if acceptance.returncode != 0:
            report["finished"] = time.time()
            return report

    report["status"] = "passed"
    report["finished"] = time.time()
    return report


def once(root: Path, state_path: Path, report_path: Path, pattern: str, *, desktop: bool) -> bool:
    state = load_state(state_path)
    seen = state.setdefault("seen", {})
    target = choose_candidate(remote_heads(root, pattern), seen)
    if not target:
        return False

    worktree = Path(tempfile.gettempdir()) / "jarvis-pc-acceptance" / (
        safe_name(target["ref"]) + "-" + target["sha"][:8]
    )
    try:
        add_worktree(root, target["sha"], worktree)
        result = run_suite(root, worktree, target["ref"], target["sha"], desktop=desktop)
        result["github_pr_comment"] = publish_pr_comment(root, target["ref"], result)
        save_json(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        remove_worktree(root, worktree)

    seen[target["ref"]] = target["sha"]
    state["updated"] = time.time()
    save_json(state_path, state)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub Actions olmadan Windows PC kabul izleyicisi")
    parser.add_argument("--interval", type=int, default=30, help="GitHub kontrol aralığı (saniye)")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="İzlenecek remote ref kalıbı")
    parser.add_argument("--once", action="store_true", help="Bir kez kontrol et ve çık")
    parser.add_argument("--no-desktop", action="store_true", help="Gerçek masaüstü ve canlı haber kabulünü çalıştırma")
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
            changed = once(root, state_path, report_path, args.pattern, desktop=not args.no_desktop)
            if not changed:
                print("Yeni test adayı yok.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            error = {
                "status": "watcher_error",
                "error": f"{type(exc).__name__}: {exc}",
                "time": time.time(),
            }
            save_json(report_path, error)
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
