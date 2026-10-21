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
    prompt = (
        "Read AGENTS.md and the relevant docs/agents notes first. "
        f"The Windows acceptance result for {ref} at {sha} is {status}. "
        "Use the repository's existing workflow and roadmap. If the result failed, fix only that task. "
        "If it passed, finish that task and continue with the next already-approved roadmap item. "
        "Do not write directly to main, do not use force, do not touch android or .venv, "
        "and do not weaken tests or safety checks."
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
