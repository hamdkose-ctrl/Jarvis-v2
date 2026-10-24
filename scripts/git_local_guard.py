"""Atlanabilir yerel Git emniyet kemeri.

GitHub ruleset/branch protection yerine geçmez. Bu dosya yalnız bu repoda
kurulan Git hook'larından çağrılır ve yanlışlıkla main/master'a commit/push ile
non-fast-forward push'u reddeder.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ZERO = '0' * 40


def protected_branch(name: str | None) -> bool:
    return str(name or '').strip() in {'main', 'master'}


def _git(*args: str) -> str:
    cp = subprocess.run(
        ['git', *args], capture_output=True, text=True, encoding='utf-8',
        errors='replace', check=False,
    )
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout or 'git komutu başarısız').strip())
    return cp.stdout.strip()


def current_branch() -> str:
    return _git('symbolic-ref', '--quiet', '--short', 'HEAD')


def _is_ancestor(old: str, new: str) -> bool:
    cp = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', old, new],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if cp.returncode == 0:
        return True
    if cp.returncode == 1:
        return False
    raise RuntimeError('Push fast-forward doğrulaması yapılamadı; önce git fetch çalıştır.')


def push_violations(lines, *, is_ancestor=_is_ancestor) -> list[str]:
    violations = []
    for raw in lines:
        parts = str(raw).strip().split()
        if not parts:
            continue
        if len(parts) != 4:
            violations.append('pre-push girdisi çözümlenemedi; push güvenli biçimde durduruldu.')
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        remote_branch = remote_ref.removeprefix('refs/heads/') if remote_ref.startswith('refs/heads/') else ''
        if protected_branch(remote_branch):
            violations.append(f'{remote_branch} dalına doğrudan push yasak; ayrı dal + PR kullan.')
            continue
        # Yeni branch ve branch silme non-fast-forward kontrolüne girmez.
        if remote_sha == _ZERO or local_sha == _ZERO or not remote_ref.startswith('refs/heads/'):
            continue
        try:
            fast_forward = is_ancestor(remote_sha, local_sha)
        except Exception as exc:
            violations.append(str(exc))
            continue
        if not fast_forward:
            violations.append(f'non-fast-forward push yasak: {remote_ref}. --force kullanma; dalı güncel main üzerine taşı.')
    return violations


def pre_commit() -> int:
    try:
        branch = current_branch()
    except RuntimeError as exc:
        print(f'Git guard: aktif dal okunamadı: {exc}', file=sys.stderr)
        return 1
    if protected_branch(branch):
        print(f'Git guard: {branch} üzerinde commit yasak; ayrı dal açıp PR kullan.', file=sys.stderr)
        return 1
    return 0


def pre_push() -> int:
    violations = push_violations(sys.stdin)
    if not violations:
        return 0
    for item in violations:
        print('Git guard: ' + item, file=sys.stderr)
    return 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ['pre-commit']:
        return pre_commit()
    if argv == ['pre-push']:
        return pre_push()
    print('Kullanım: git_local_guard.py pre-commit|pre-push', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
