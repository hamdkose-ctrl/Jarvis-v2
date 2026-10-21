from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path

import pc_test_watcher as watcher
from codex_followup import run_followup


CODEX_STATE_NAME = "codex_followup_state.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows PC watcher + Codex yol haritası döngüsü")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--pattern", default=watcher.DEFAULT_PATTERN)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    args = parser.parse_args()

    root = watcher.git_root()
    local_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Jarvis" / "pc-acceptance"
    state_path = local_dir / watcher.STATE_NAME
    report_path = local_dir / watcher.REPORT_NAME
    codex_state_path = local_dir / CODEX_STATE_NAME

    print(f"Jarvis PC test + Codex döngüsü başladı: {root}")
    print(f"İzlenen ref: {args.pattern}")
    print(f"Sonuç: {report_path}")

    while True:
        try:
            changed = watcher.once(root, state_path, report_path, args.pattern, desktop=not args.no_desktop)
            if changed:
                report = watcher.load_state(report_path)
                sha = str(report.get("sha") or "")
                codex_state = watcher.load_state(codex_state_path)
                if sha and codex_state.get("sha") != sha:
                    comment = report.get("github_pr_comment") if isinstance(report.get("github_pr_comment"), dict) else {}
                    if comment.get("state") == "published":
                        result = run_followup(
                            root,
                            str(report.get("ref") or ""),
                            sha,
                            str(report.get("status") or "unknown"),
                        )
                        report["codex_followup"] = result
                        watcher.save_json(report_path, report)
                        watcher.save_json(codex_state_path, {"sha": sha, "time": time.time(), "result": result})
                        print(f"Codex takip sonucu: {result.get('state')} ({result.get('reason', 'ok')})")
            else:
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
