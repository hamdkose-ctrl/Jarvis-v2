"""Shell hook contract.

Phase 2 exposes only a capability-shaped, fail-closed stub. No subprocess,
shell, command interpreter, or filesystem side effect is allowed here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShellHookResult:
    status: str
    allowed: bool
    reason_code: str
    command: str


class ShellHook:
    """Placeholder until the Faz 6 sandbox exists; never executes commands."""

    def execute(self, command: str, *, cwd: str | None = None, env: dict | None = None) -> ShellHookResult:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Shell komutu boş olamaz.")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("Shell çalışma yolu metin olmalı.")
        if env is not None and not isinstance(env, dict):
            raise ValueError("Shell ortamı nesne olmalı.")
        return ShellHookResult(
            status="blocked",
            allowed=False,
            reason_code="SHELL_EXECUTION_DISABLED",
            command=command,
        )
