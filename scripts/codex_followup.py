from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def codex_exe() -> str | None:
    found = shutil.which("codex") or shutil.which("codex.exe")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    candidate = Path(local) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    return str(candidate) if candidate.is_file() else None


def run_followup(root: Path, ref: str, sha: str, status: str) -> dict:
    codex = codex_exe()
    if not codex:
        return {"state": "skipped", "reason": "codex_cli_missing"}
    branch = ref.replace("refs/remotes/origin/", "", 1)
    prompt = (
        "Read AGENTS.md and the relevant docs/agents notes first. "
        f"The Windows acceptance result for branch {branch} at commit {sha} is {status}. "
        "Fetch origin and verify that this commit is still the remote branch head before changing anything; "
        "if it is stale, stop without edits. Read the open PR and its Windows acceptance comment. "
        "Use the repository's existing workflow and roadmap. If the result failed, stay on that branch, "
        "fix only that task, run the required tests and validation, then commit and push the new head so the watcher can retest it. "
        "If it passed, finish the current PR according to the existing repo rules; once that task is actually complete, "
        "read docs/JARVIS_ANA_PLAN.md and docs/BEKLEYEN_ISLER.md, choose the next already-approved open roadmap item, "
        "create a separate gpt/ branch from current main, implement it with a failing test first, validate it, open a draft PR, and push. "
        "Do not write directly to main, do not use force, do not touch android or .venv, do not read or commit personal secrets, "
        "and do not weaken tests or safety checks. Do not ask Hamdi to copy terminal output between agents. "
        "If repo rules require fresh user approval for a scope that is not already approved in the roadmap, stop and report that blocker instead of coding."
    )
    proc = subprocess.run(
        [codex, "exec", "--sandbox", "workspace-write", prompt],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    tail = "\n".join((proc.stdout or "").splitlines()[-40:])
    if proc.returncode:
        return {"state": "failed", "exit_code": proc.returncode, "tail": tail[:3000]}
    return {"state": "completed", "exit_code": 0, "tail": tail[:3000]}
