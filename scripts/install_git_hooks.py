"""Bu repo için .githooks yolunu etkinleştirir; global Git ayarına dokunmaz."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def configure_hooks(root: Path, *, runner=_run) -> None:
    root = Path(root)
    if not (root / '.git').exists():
        raise RuntimeError('Git repo kökü bulunamadı.')
    if not (root / '.githooks').is_dir():
        raise RuntimeError('.githooks klasörü bulunamadı.')
    runner(['git', 'config', '--local', 'core.hooksPath', '.githooks'], root)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        configure_hooks(root)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print('Git hook kurulumu başarısız: ' + str(exc), file=sys.stderr)
        return 1
    print('Yerel Git emniyet kemeri etkin: core.hooksPath=.githooks')
    print('Not: --no-verify, başka makine veya doğrudan API push bu yerel korumayı atlayabilir.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
