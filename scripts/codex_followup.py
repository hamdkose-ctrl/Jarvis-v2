from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


QUOTA_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "usage limit",
    "usage_limit",
    "capacity",
    "too many requests",
    "try again later",
    "temporarily unavailable",
)


def codex_exe() -> str | None:
    found = shutil.which("codex") or shutil.which("codex.exe")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    candidate = Path(local) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    return str(candidate) if candidate.is_file() else None


def _prompt(ref: str, sha: str, status: str, failure_hint: str = "") -> str:
    branch = ref.replace("refs/remotes/origin/", "", 1)
    validation = (
        "On Windows, run repository validation with .venv\\Scripts\\python.exe -X utf8 -m modules.validation "
        "when that interpreter exists; otherwise report the missing environment instead of silently using a different Python. "
    )
    if status == "failed":
        hint = f" Failure summary: {failure_hint[:1200]}" if failure_hint else ""
        return (
            "Read AGENTS.md and only the relevant docs/agents note for this task. "
            f"Windows acceptance failed for branch {branch} at commit {sha}.{hint} "
            "Fetch origin and verify this commit is still the remote branch head; if stale, stop without edits. "
            "Stay on this task and branch. Inspect only files needed for this failure, fix the root cause, "
            + validation +
            "Run the required focused tests plus repository validation, then commit and push a new SHA. "
            "Do not scan unrelated areas, do not start another roadmap item, do not write directly to main, "
            "do not use force, do not touch android or .venv, do not read or commit personal secrets, "
            "and do not weaken tests or safety checks."
        )
    return (
        "Read AGENTS.md, the relevant docs/agents note, docs/JARVIS_ANA_PLAN.md and docs/BEKLEYEN_ISLER.md. "
        f"Windows acceptance passed for branch {branch} at commit {sha}. "
        "Fetch origin and verify this commit is still the remote branch head; if stale, stop without edits. "
        + validation +
        "Use this PASS as the completion signal for the current approved task. Keep context small: do not rescan "
        "unrelated code. Finish the current PR according to existing repo rules; once that task is actually complete, "
        "continue only with the next already-approved open roadmap item in a separate gpt/ branch. "
        "Do not write directly to main, do not use force, do not touch android or .venv, and do not read or commit personal secrets. "
        "If fresh user approval is required for a scope that is not already approved, stop and report that blocker."
    )


def quota_or_rate_limited(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(marker in normalized for marker in QUOTA_MARKERS)


def run_followup(root: Path, ref: str, sha: str, status: str, failure_hint: str = "") -> dict:
    codex = codex_exe()
    if not codex:
        return {"state": "skipped", "reason": "codex_cli_missing"}
    proc = subprocess.run(
        [
            codex,
            "-m",
            "gpt-5.6-terra",
            "-c",
            "windows.sandbox='unelevated'",
            "exec",
            "--sandbox",
            "danger-full-access",
            _prompt(ref, sha, status, failure_hint),
        ],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    combined = "\n".join(part for part in (proc.stdout or "", proc.stderr or "") if part)
    tail = "\n".join(combined.splitlines()[-40:])
    if proc.returncode:
        if quota_or_rate_limited(combined):
            return {
                "state": "pending_quota",
                "reason": "quota_or_rate_limit",
                "exit_code": proc.returncode,
                "tail": tail[:3000],
            }
        return {"state": "failed", "exit_code": proc.returncode, "tail": tail[:3000]}
    return {"state": "completed", "exit_code": 0, "tail": tail[:3000]}
