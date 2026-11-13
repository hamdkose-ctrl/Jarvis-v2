"""Operator-observed Windows acceptance for BRAIN-07 Issue #584.

Run from a clean checkout of the exact PR source SHA. No passwords, tokens,
screenshots, or test stdout are persisted. Most provider/device adapters in these
tests are synthetic; passing does not prove live OAuth or audible speech.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


# One concrete, separately executed Windows process per acceptance scenario.
# Tests deliberately use the existing Scheduler, Core and OS resource contracts.
SCENARIOS = (
    ("research_account_join", "Research + Gmail roots and verified join",
     "tests.test_brain_07_typed_canonical_e2e.TypedCanonicalFlowTests.test_real_scheduler_verify_joins_research_and_gmail_without_writer", "Provider mocked; Core and Scheduler real"),
    ("three_independent_goals", "Three same-owner independent Scheduler goals",
     "tests.test_brain_07_canonical_scheduler_lane.SchedulerOfferTests.test_three_independent_goals_same_owner_overlap_on_real_scheduler", "Provider mocked; real bounded worker pool"),
    ("duplicate_wake", "Duplicate wake never starts second attempt",
     "tests.test_brain_07_canonical_scheduler_lane.SchedulerOfferTests.test_duplicate_wake_cannot_start_same_canonical_attempt", "Canonical first attempt fence"),
    ("distinct_files", "Independent file operations do not share one lock",
     "tests.test_brain_07_file_effect_claim.FileEffectClaimTests.test_independent_file_is_not_blocked_by_occupied_source", "Actual temporary Windows file claims"),
    ("same_file", "Same physical file conflicts across data directories",
     "tests.test_brain_07_file_effect_claim.FileEffectClaimTests.test_distinct_data_roots_share_one_physical_file_claim", "Actual temporary Windows file claims"),
    ("desktop_sessions", "Two Windows Jarvis instances cannot own desktop simultaneously",
     "tests.test_brain_07_cross_process_native_desktop.CrossProcessNativeDesktopTests.test_distinct_data_roots_cannot_claim_same_physical_desktop", "Desktop adapter mocked; real cross-process lock"),
    ("deadline", "Expired worker deadline fences late Core acceptance",
     "tests.test_brain_07_canonical_scheduler_lane.SchedulerOfferTests.test_real_scheduler_worker_deadline_fences_late_core_cas_no_replay", "Soft deadline, not process kill"),
    ("stolen_queue_token", "Stolen SQLite queue lease cannot commit or read again",
     "tests.test_brain_07_queue_worker_journal_fence.DurableQueuedWorkerFenceTests.test_queue_lease_stolen_inside_provider_fences_next_read_and_no_result", "Real SQLite queue and probe"),
    ("foreign_cancel", "Cancelled queue generation cannot publish stale success",
     "tests.test_brain_07_queue_worker_journal_fence.DurableQueuedWorkerFenceTests.test_external_cancel_keeps_original_cancel_exception_not_stale_write", "Owner/cancel fence"),
    ("core_crash", "Crash between Core CAS and journal keeps result readable",
     "tests.test_brain_07_typed_canonical_e2e.TypedCanonicalFlowTests.test_core_done_before_record_crash_preserves_owner_readable_result", "Fault injection, real durable Core"),
    ("restart", "Restart resumes accepted completion without worker replay",
     "tests.test_brain_07_typed_canonical_e2e.TypedCanonicalFlowTests.test_scheduler_restart_resumes_verified_completion_without_worker_replay", "Provider mocked"),
    ("plan_edit", "Plan mutation invalidates running old attempt",
     "tests.test_brain_07_canonical_scheduler_lane.SchedulerOfferTests.test_live_canonical_plan_edit_fences_next_provider_step", "Plan version and Core CAS"),
    ("busy_wake", "One blocked owner does not stall another owner's wake",
     "tests.test_brain_07_single_scheduler_owner_dispatch.ExistingSchedulerOwnerDispatchTests.test_blocked_first_owner_does_not_block_other_owners", "Bounded existing Scheduler"),
    ("long_task_interleaving", "Foreground accepts another goal during background work",
     "tests.test_brain_07_typed_canonical_e2e.TypedCanonicalFlowTests.test_foreground_accepts_second_independent_goal_while_worker_is_running", "Model/provider mocked, no human hearing"),
    ("cross_owner_account", "Separate owners share trusted provider-wide OS claim",
     "tests.test_brain_07_cross_process_resource_claim.CrossProcessReadOnlyResourceClaimTests.test_account_claim_root_is_shared_between_owner_names_and_processes", "Fallback claim, not authenticated OAuth subject"),
    ("receipt_collision", "Independent process cannot overwrite live undo receipt",
     "tests.test_brain_07_file_effect_claim.FileEffectClaimTests.test_second_process_owning_receipt_blocks_file_effect_before_move", "Physical receipt claim"),
    ("started_unknown_restart", "Started unknown work cannot replay after lock release",
     "tests.test_brain_07_canonical_scheduler_lane.SchedulerOfferTests.test_restart_never_replays_started_unknown_after_os_lock_release", "Manual reconciliation remains required"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True, help="Exact 40-character PR source SHA")
    args = parser.parse_args()
    expected = args.expected_sha.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        parser.error("--expected-sha must be a full 40-digit commit SHA")
    if os.name != "nt":
        print("Only Windows PC acceptance is eligible.", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("Manual operator TTY required: never silently attest acceptance.", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", timeout=15, check=True,
        )
        actual = result.stdout.strip().lower()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Cannot verify local checkout SHA: {type(exc).__name__}", file=sys.stderr)
        return 2
    if actual != expected:
        print(f"Wrong source: expected {expected}, local checkout is {actual}.", file=sys.stderr)
        return 2

    print("\nBRAIN-07 manual Windows acceptance")
    print("Checked-out source SHA:", actual)
    print("17 separate Windows unittest processes are run and observed one by one.")
    print("IMPORTANT: Some providers/devices are MOCKED. This is not live account or audio evidence.")
    print("Do not enter or send passwords, email addresses, access tokens, or private data.")
    records = []
    for index, (case, label, test_id, limitation) in enumerate(SCENARIOS, 1):
        print(f"\n[{index}/{len(SCENARIOS)}] {label}")
        print("Limitation:", limitation)
        choice = input("Enter = run this scenario; s = skip: ").strip().lower()
        if choice == "s":
            records.append({"id": case, "test": test_id, "status": "skipped",
                            "operator_observed": False})
            continue
        start = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "unittest", test_id],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180, check=False,
            )
            status = "passed" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        except OSError:
            status = "failed"
        seconds = round(time.monotonic() - start, 2)
        print("Local Windows test:", status.upper(), f"({seconds}s)")
        if status != "passed":
            print("Review local unittest output by running:")
            print(f"  {sys.executable} -X utf8 -m unittest {test_id}")
        observed = False
        if status == "passed":
            observed = input(
                "Did YOU observe this local PC run finish successfully? [yes/no]: "
            ).strip().lower() in {"yes", "evet", "e", "y"}
        records.append({
            "id": case, "test": test_id, "status": status,
            "operator_observed": observed,
            "elapsed_seconds": seconds,
            "limitation": limitation,
        })

    success = sum(r["status"] == "passed" and r["operator_observed"] for r in records)
    summary = {
        "schema": "brain07-windows-operator-regression-v1",
        "source_sha": actual,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "platform": "Windows",
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "scenario_count": len(records),
        "operator_observed_local_regressions": success,
        "all_local_regressions_observed": success == len(records),
        "live_external_account_verified": False,
        "real_audio_playback_verified": False,
        "all_native_adapters_verified": False,
        "scenarios": records,
    }
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jarvis" / "pc-acceptance"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for nonce in range(100):
        output = base / f"brain07-operator-{actual[:12]}-{stamp}-{nonce:02d}.json"
        try:
            with output.open("x", encoding="utf-8") as stream:
                json.dump(summary, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            break
        except FileExistsError:
            continue
    else:
        print("Cannot allocate create-only report filename.", file=sys.stderr)
        return 2
    print(f"\nObserved local Windows regressions: {success}/{len(records)}")
    print("Report:", output)
    print("No private test output, passwords or personal data were saved.")
    print("This does not itself establish live provider / microphone / hardware manual acceptance.")
    return 0 if success == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
