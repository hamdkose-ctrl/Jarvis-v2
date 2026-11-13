from __future__ import annotations

import argparse
import json
import re
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# The expensive run is restricted by ``open_pr_refs`` below.  Do not restrict
# it further by an individual agent's branch prefix: draft PRs may originate
# from Codex, Claude, a human hotfix branch, or a future worker.  Pass the
# remote namespace root to for-each-ref so nested names are included too.
DEFAULT_PATTERN = "refs/remotes/origin"
STATE_NAME = "pc_test_watcher_state.json"
REPORT_NAME = "pc_test_watcher_last.json"


def run(cmd, *, cwd: Path, check: bool = True, capture: bool = False, stdin=None):
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        stdin=stdin,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


class WatcherAlreadyRunning(RuntimeError):
    """Another real PC watcher owns this machine's acceptance run."""


@contextmanager
def single_watcher(lock_path: Path):
    """OS-held, crash-released lock across independent Scheduled Task launches.

    The lock file is intentionally never removed: unlinking it while another
    process holds the handle allows two different files to claim exclusivity.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WatcherAlreadyRunning(
                "Ayrı bir Jarvis PC watcher zaten çalışıyor; ikinci kabul başlatılmadı."
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def archive_report(report_path: Path, report: dict) -> Path:
    """Keep exact-commit reports independently of the last-result convenience file."""
    sha=str(report.get('sha') or '')
    if not re.fullmatch(r'[0-9a-f]{40}',sha):
        raise ValueError('Rapor için geçerli exact commit SHA gerekli.')
    archive=report_path.parent/'reports'/(sha+'.json')
    save_json(archive,report)
    return archive


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
    Remote branches alone are not sufficient proof that somebody currently
    needs a result: old, merged and abandoned branches remain on origin.  If
    GitHub cannot be queried, fail closed instead of accepting an unrelated
    branch.  This open-PR check is deliberately the sole branch eligibility
    rule, independent of whether the author used ``gpt/``, ``claude/`` or
    another branch prefix.
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


def changed_paths(root: Path, sha: str) -> list[str] | None:
    """Return paths changed by a candidate relative to the current main tip.

    The watcher already fetches origin before choosing a candidate.  Scope is
    deliberately derived locally instead of making a second GitHub API call:
    the acceptance decision must remain available whenever the open-PR check
    itself has succeeded.
    """
    diff = run(["git", "diff", "--name-only", f"origin/main...{sha}"], cwd=root,
               check=False, capture=True)
    if diff.returncode != 0:
        return None
    return [line.strip().replace("\\", "/") for line in (diff.stdout or "").splitlines() if line.strip()]


def acceptance_scope(paths: list[str], *, desktop: bool = False, news: bool = False,
                     local_model: bool = False) -> dict:
    """Choose opt-in real-PC acceptances from runtime-relevant changed paths.

    Validation always runs.  A documentation, hook, CI or watcher-only change
    must not open applications, perform live news, or call a local model.  The
    explicit flags remain operator overrides.
    """
    normalized = [str(path).lower().replace("\\", "/") for path in paths]
    runtime_paths = [path for path in normalized if path.startswith(("modules/", "tests/"))]
    desktop_markers = (
        "desktop", "desktop_uia", "system_control",
        "test_acceptance_desktop", "permission_gate_desktop",
    )
    news_markers = ("news", "publisher_news", "public_data_acceptance")
    local_model_paths = {
        "modules/llm.py",
        "web_models.py",
        "webui/ui-refresh.js",
        "webui/local-model-panel.js",
        "webui/nx.html",
        "tests/test_ollama_model_autoselect.py",
        "tests/ai_page_behavior.js",
        "scripts/local_model_acceptance.py",
    }
    shared_acceptance = "modules/acceptance_checks.py" in runtime_paths
    return {
        "desktop": bool(desktop or shared_acceptance or any(marker in path for path in runtime_paths for marker in desktop_markers)),
        "news": bool(news or shared_acceptance or any(marker in path for path in runtime_paths for marker in news_markers)),
        "local_model": bool(local_model or any(path in local_model_paths for path in normalized)),
        "paths": paths,
        "source": "manual" if desktop or news or local_model else "changed_paths",
    }


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


def isolated_worktree_path(ref: str, sha: str, *, nonce: str | None = None) -> Path:
    """Give EACH validation attempt its own checkout (even for the same SHA).

    An older already-running watcher may not use the single_watcher lock.
    Previously the deterministic branch-SHA directory let a second watcher
    delete the first validation's live checkout during a 300+ second suite.
    Never reuse or remove another process's checkout as part of admission.
    The short suffix also keeps nested branch names below Windows path limits.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Exact 40-hex commit required for PC validation.")
    nonce = secrets.token_hex(8) if nonce is None else nonce
    if not re.fullmatch(r"[0-9a-f]{16}", nonce):
        raise ValueError("PC validation attempt token invalid.")
    name = safe_name(ref)
    if not name or name.startswith((".", "-")) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("Remote branch name invalid for isolated PC acceptance.")
    return (Path(tempfile.gettempdir()) / "jarvis-pc-acceptance" /
            (name[:48] + "-" + sha[:8] + "-" + nonce))


def branch_from_ref(ref: str) -> str:
    prefix = "refs/remotes/origin/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def add_worktree(root: Path, sha: str, target: Path) -> None:
    if target.exists() or target.is_symlink():
        # Windows can hold a file handle open after a previous validation run.
        # Git's interactive "Should I try again?" prompt MUST NOT be answered
        # repeatedly, and a half-deleted checkout is not valid evidence.
        remove_worktree(root, target)
    if target.exists() or target.is_symlink():
        raise RuntimeError("Önceki test worktree klasörü hâlâ açık; eksik checkout ile test yapılmadı.")
    run(["git", "worktree", "prune"], cwd=root, check=False)
    run(["git", "worktree", "add", "--detach", str(target), sha], cwd=root)


def remove_worktree(root: Path, target: Path) -> None:
    # Never prompt a Scheduled Task operator for y/n. A locked file is a
    # failed cleanup, not permission to continue with a torn source tree.
    result = run(["git", "worktree", "remove", "--force", str(target)],
                 cwd=root, check=False, capture=True, stdin=subprocess.DEVNULL)
    shutil.rmtree(target, ignore_errors=True)
    if target.exists() or target.is_symlink():
        raise RuntimeError(
            "Windows test worktree temizlenemedi (dosya kullanımda olabilir): "
            + str(target) + ". Çalışan test/Watcher süreçlerini kontrol et."
        )


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


def _check_detail(checks: list[dict], name: str) -> str:
    """Bounded report-provided diagnostic; never publish raw command output."""
    for row in checks:
        if isinstance(row, dict) and row.get("check") == name:
            return " ".join(str(row.get("detail") or "").split())[:12000]
    return ""


def run_acceptance(py: Path, worktree: Path, *flags: str) -> dict:
    proc = run([str(py), "-X", "utf8", "-m", "modules.acceptance_checks", *flags, "--skip-suite"],
               cwd=worktree, check=False, capture=True)
    return {
        "exit_code": proc.returncode,
        "tail": "\n".join((proc.stdout or "").splitlines()[-120:]),
        "checks": acceptance_details(worktree),
    }


def run_local_model_acceptance(py: Path, worktree: Path) -> dict:
    proc = run([str(py), "-X", "utf8", "scripts/local_model_acceptance.py"],
               cwd=worktree, check=False, capture=True)
    result = {}
    for line in reversed((proc.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            result = candidate
            break
    return {
        "exit_code": proc.returncode,
        "tail": "\n".join((proc.stdout or "").splitlines()[-80:]),
        "result": result,
    }


def run_suite(root: Path, worktree: Path, ref: str, sha: str, *, desktop: bool, news: bool,
              local_model: bool = False) -> dict:
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

    if local_model:
        print("[L] Yerel model UI/inference acceptance basladi...", flush=True)
        local_result = run_local_model_acceptance(py, worktree)
        report["local_model_acceptance"] = local_result
        state = (local_result.get("result") or {}).get("state")
        print(f"[L] Yerel model acceptance bitti: exit={local_result['exit_code']}, state={state}", flush=True)
        if local_result["exit_code"] != 0 or state != "passed":
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
    for key, label in (
        ("validation", "Validation"),
        ("local_model_acceptance", "Yerel model UI/inference"),
        ("desktop_acceptance", "Desktop"),
        ("news_acceptance", "Haber"),
    ):
        row = report.get(key)
        if isinstance(row, dict):
            passed = row.get('exit_code') == 0
            if key == "local_model_acceptance":
                passed = passed and (row.get("result") or {}).get("state") == "passed"
            if key in required:
                passed = passed and _check_state(row.get('checks') or [], required[key]) == 'passed'
            lines.append(f"- {label}: **{'passed' if passed else 'failed'}**")
            if not passed and key == 'local_model_acceptance':
                detail = str((row.get('result') or {}).get('detail') or '')[:1200]
                if detail:
                    lines.append(f'  - Tanı: {detail}')
            if not passed and key in required:
                checks=row.get("checks") or []
                names=([str(check['check'])[:100] for check in checks
                        if isinstance(check,dict) and str(check.get('check','')).startswith('news')
                        and check.get('state')=='failed'][:4] if key=='news_acceptance' else [])
                for name in names or [required[key]]:
                    detail = _check_detail(checks, name)
                    if detail:
                        lines.append(f"  - Tanı ({name}): {detail}")
    lines.append("\nBu yorum gerçek iş PC'sindeki watcher tarafından otomatik üretildi; anahtarlar ve kişisel içerik gönderilmez.")
    return "\n".join(lines)


def publish_pr_comment(root: Path, ref: str, report: dict, *, verify_existing: bool = False) -> dict:
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
    if verify_existing:
        # A previous publish may have succeeded but timed out before its status was saved.
        # Do not post the same exact-SHA acceptance twice; fail closed if verification fails.
        existing = run([gh, "pr", "view", str(number), "--json", "comments"],
                       cwd=root, check=False, capture=True)
        if existing.returncode != 0:
            return {"state": "failed", "reason": "gh_pr_comment_lookup_failed", "pr": number}
        try:
            comments = json.loads(existing.stdout or "{}").get("comments")
        except (ValueError, AttributeError):
            comments = None
        if not isinstance(comments, list):
            return {"state": "failed", "reason": "gh_pr_comment_lookup_invalid", "pr": number}
        exact = "- Commit: " + chr(96) + str(report.get("sha") or "")[:12] + chr(96)
        for comment in comments:
            body = comment.get("body") if isinstance(comment, dict) else None
            if (isinstance(body, str) and "<!-- jarvis-pc-acceptance -->" in body
                    and exact in body.splitlines()):
                return {"state": "published", "pr": number, "url": pr.get("url"),
                        "already_present": True}
    posted = run([gh, "pr", "comment", str(number), "--body", pr_comment_body(report)],
                 cwd=root, check=False, capture=True)
    if posted.returncode != 0:
        return {"state": "failed", "reason": "gh_pr_comment_failed", "pr": number}
    return {"state": "published", "pr": number, "url": pr.get("url")}



def _archived_candidate_report(report_path: Path, candidate: dict) -> dict | None:
    """Only this ref's complete exact-SHA local evidence can suppress a repeated test."""
    sha = str(candidate.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    path = report_path.parent / "reports" / (sha + ".json")
    report = load_state(path)
    if (report.get("sha") != sha or report.get("ref") != candidate.get("ref")
            or report.get("status") not in {"passed", "failed"}
            or not isinstance(report.get("validation"), dict)):
        return None
    return report


def reconcile_archived_reports(root: Path, state_path: Path, report_path: Path,
                               candidates: list[dict], seen: dict, *,
                               now: float | None = None) -> bool:
    """Repair publication independently of running tests. Never rerun an archived SHA."""
    now = time.time() if now is None else now
    activity = False
    state_changed = False
    for item in candidates:
        report = _archived_candidate_report(report_path, item)
        if report is None:
            continue
        ref, sha = item["ref"], item["sha"]
        known = _seen_entry(seen, ref)
        if known is None or known.get("sha") != sha:
            # Crash after archiving, before persisting 'seen': the completed test
            # must not run a second time just to recover its PR comment.
            seen[ref] = {"sha": sha, "status": report["status"],
                         "last_attempt": float(report.get("started") or now),
                         "last_result": report["status"]}
            state_changed = True
            activity = True
            print(f"Yerel test raporu kurtarildi: {branch_from_ref(ref)} {sha[:12]}", flush=True)

        published = report.get("github_pr_comment")
        if isinstance(published, dict) and published.get("state") == "published":
            continue
        if now < float(report.get("publication_retry_after") or 0):
            continue
        print(f"Test tekrar edilmiyor; PR raporu yayinlaniyor: {branch_from_ref(ref)} {sha[:12]}", flush=True)
        publication = publish_pr_comment(root, ref, report, verify_existing=True)
        report["github_pr_comment"] = publication
        if publication.get("state") == "published":
            report.pop("publication_retry_after", None)
            print(f"PR raporu yayinlandi: {branch_from_ref(ref)} {sha[:12]}", flush=True)
        else:
            report["publication_retry_after"] = now + 300
            print("PR raporu gonderilemedi: " + str(publication.get("reason") or "unknown"),
                  flush=True)
        archive_report(report_path, report)
        if load_state(report_path).get("sha") == sha:
            save_json(report_path, report)
        activity = True
    if state_changed:
        previous = load_state(state_path)
        previous["seen"] = seen
        previous["updated"] = now
        save_json(state_path, previous)
    return activity


def queue_status(root: Path, state_path: Path, report_path: Path, pattern: str) -> dict:
    """Read-only acceptance diagnosis. No validation, desktop or live model calls."""
    open_refs = open_pr_refs(root)
    if open_refs is None:
        return {"state": "unavailable", "reason": "open_pr_list_unavailable",
                "hint": "GitHub CLI installation/authentication must be checked on this Windows PC."}
    remote = {item["ref"]: item for item in remote_heads(root, pattern)}
    seen = load_state(state_path).get("seen") or {}
    rows = []
    for ref in sorted(open_refs):
        item = remote.get(ref)
        if item is None:
            rows.append({"branch": branch_from_ref(ref), "state": "remote_ref_missing"})
            continue
        sha = item["sha"]
        known = _seen_entry(seen, ref)
        report = _archived_candidate_report(report_path, item)
        if report is None:
            state = ("awaiting_test" if known is None or known.get("sha") != sha
                     else "recorded_but_local_report_missing")
        elif (report.get("github_pr_comment") or {}).get("state") == "published":
            state = "published"
        else:
            state = "report_not_published"
        rows.append({"branch": branch_from_ref(ref), "sha": sha[:12], "state": state})
    return {"state": "ok", "open_pr_count": len(open_refs),
            "visible_ref_count": len(remote), "branches": rows}


def once(root: Path, state_path: Path, report_path: Path, pattern: str, *, desktop: bool, news: bool,
         local_model: bool = False) -> bool:
    state = load_state(state_path)
    seen = state.setdefault("seen", {})
    open_refs = open_pr_refs(root)
    if open_refs is None:
        print("Açık PR listesi doğrulanamadı; fail-closed olarak test başlatılmadı.", flush=True)
        return False
    candidates = [item for item in remote_heads(root, pattern) if item["ref"] in open_refs]
    recovered = reconcile_archived_reports(root, state_path, report_path, candidates, seen)
    target = choose_candidate(candidates, seen)
    if not target:
        return recovered
    paths = changed_paths(root, target["sha"])
    # Scope discovery never makes an optional live call on uncertainty.  The
    # validation gate still gives the PR a useful, non-destructive result.
    scope = acceptance_scope(paths or [], desktop=desktop, news=news, local_model=local_model)
    if paths is None:
        scope["source"] = "unavailable"
    # A same-commit concurrent (including OLD-version) watcher must not have
    # authority to delete this live validation tree. No shared SHA directory.
    worktree = isolated_worktree_path(target["ref"], target["sha"])
    attempted_at = time.time()
    archived = False
    try:
        add_worktree(root, target["sha"], worktree)
        print("[1/4] Testler basladi...", flush=True)
        result = run_suite(
            root, worktree, target["ref"], target["sha"],
            desktop=scope["desktop"], news=scope["news"], local_model=scope["local_model"],
        )
        result["sha"] = target["sha"]
        result["acceptance_scope"] = scope
        archive_report(report_path, result)
        archived = True
        print(f"[2/4] Test sonucu: {result.get('status')}", flush=True)
        result["github_pr_comment"] = publish_pr_comment(root, target["ref"], result)
        print("[4/4] Rapor yaziliyor...", flush=True)
        archive_report(report_path, result)
        save_json(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if archived:
            remove_worktree(root, worktree)
        else:
            print("Rapor arşivlenemedi; kabul worktree kanıtı korundu.", flush=True)
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
    parser.add_argument("--status", action="store_true",
                        help="Açık PR/SHA/kayıt/yayın durumunu göster; test çalıştırma")
    parser.add_argument("--desktop", action="store_true", help="Kapsamdan bağımsız gerçek desktop kabulünü zorla")
    parser.add_argument("--news", action="store_true", help="Yavaş haber kabulünü ayrı final aşaması olarak çalıştır")
    parser.add_argument("--local-model", action="store_true", help="Gerçek yerel model UI/inference kabulünü zorla")
    args = parser.parse_args()

    root = git_root()
    local_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Jarvis" / "pc-acceptance"
    state_path = local_dir / STATE_NAME
    report_path = local_dir / REPORT_NAME
    if args.status:
        summary = queue_status(root, state_path, report_path, args.pattern)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["state"] == "ok" else 1
    try:
        with single_watcher(local_dir / "pc_test_watcher.lock"):
            print(f"Jarvis PC test watcher başladı: {root}")
            print(f"İzlenen ref: {args.pattern}")
            print(f"Sonuç: {report_path}")
            while True:
                try:
                    changed = once(
                        root, state_path, report_path, args.pattern,
                        desktop=args.desktop, news=args.news, local_model=args.local_model,
                    )
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
    
    except WatcherAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
