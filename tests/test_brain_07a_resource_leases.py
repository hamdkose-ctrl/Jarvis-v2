"""BRAIN-07A: scheduler-owned ResourceLease behavior without starting workers.

Tests establish local lease fencing only. Cross-process persistence, real
effects, restart recovery and canonical WorkerResult commit are out of scope.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import unittest

from modules.resource_leases import (
    LeaseConflict, LeaseFenceError, LeaseTable, resource_key,
)


FILE_A = resource_key("file", "a" * 64)
FILE_B = resource_key("file", "b" * 64)
DESKTOP = resource_key("pc_desktop")


def claim(table, keys=(DESKTOP,), *, owner="alice", job="job1",
          step="s1", command="s1:1", version=1, ttl=30):
    return table.acquire(
        owner=owner, job_id=job, step_id=step, plan_version=version,
        command_id=command, keys=keys, ttl=ttl,
    )


class ResourceLeaseTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.table = LeaseTable(clock=lambda: self.now[0])

    def test_global_desktop_is_exclusive_across_owners_and_goals(self):
        first = claim(self.table)
        self.assertTrue(self.table.occupied(DESKTOP))
        with self.assertRaises(LeaseConflict):
            claim(self.table, owner="bob", job="different", command="other")
        self.assertTrue(self.table.validate(first))
        self.table.release(first)
        self.assertFalse(self.table.occupied(DESKTOP))
        other = claim(self.table, owner="bob", job="different")
        self.assertGreater(other.serial, first.serial)
        self.assertTrue(self.table.validate(other))

    def test_distinct_files_can_run_concurrently_without_global_filesystem_lock(self):
        ready = threading.Barrier(2)
        def run(k):
            ready.wait(2)
            return claim(self.table, keys=(k,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(run, FILE_A)
            b = pool.submit(run, FILE_B)
            leases = [a.result(timeout=2), b.result(timeout=2)]
        self.assertTrue(all(self.table.validate(t) for t in leases))
        self.assertEqual({t.keys for t in leases}, {(FILE_A,), (FILE_B,)})

    def test_multikey_atomic_collision_never_partially_leases_free_key(self):
        busy = claim(self.table, keys=(DESKTOP,))
        with self.assertRaises(LeaseConflict):
            claim(self.table, keys=(FILE_A, DESKTOP), command="other")
        self.assertFalse(self.table.occupied(FILE_A))
        self.table.release(busy)
        both = claim(self.table, keys=(FILE_A, DESKTOP))
        self.assertTrue(self.table.occupied(FILE_A))
        self.assertTrue(self.table.occupied(DESKTOP))
        self.table.release(both)
        self.assertFalse(self.table.occupied(FILE_A))

    def test_expiry_reclaims_lease_and_blocks_stale_worker_release(self):
        old = claim(self.table, ttl=2)
        self.now[0] = 102.0
        fresh = claim(self.table, owner="bob", ttl=25)
        self.assertGreater(fresh.serial, old.serial)
        self.assertFalse(self.table.validate(old))
        with self.assertRaises(LeaseFenceError):
            self.table.release(old)
        with self.assertRaises(LeaseFenceError):
            self.table.heartbeat(old)
        self.assertTrue(self.table.validate(fresh))
        self.assertTrue(self.table.occupied(DESKTOP))

    def test_heartbeat_renews_generation_even_at_frozen_clock(self):
        first = claim(self.table, ttl=4)
        renewed = self.table.heartbeat(first, ttl=10)
        self.assertEqual(renewed.serial, first.serial)
        self.assertEqual(renewed.renewal, first.renewal + 1)
        self.assertFalse(self.table.validate(first))
        self.assertTrue(self.table.validate(renewed))
        with self.assertRaises(LeaseFenceError):
            self.table.release(first)
        self.now[0] = 105
        self.assertTrue(self.table.validate(renewed))
        self.now[0] = 110
        self.assertFalse(self.table.validate(renewed))

    def test_duplicate_wake_same_command_cannot_reenter_active_lease(self):
        original = claim(self.table)
        with self.assertRaises(LeaseConflict):
            claim(self.table)
        self.assertTrue(self.table.validate(original))

    def test_forged_owner_job_step_plan_or_token_fails_closed(self):
        ticket = claim(self.table)
        variants = (
            replace(ticket, owner="other"),
            replace(ticket, job_id="other"),
            replace(ticket, step_id="other"),
            replace(ticket, plan_version=2),
            replace(ticket, command_id="other"),
            replace(ticket, serial=ticket.serial + 1),
            replace(ticket, keys=(FILE_A,)),
        )
        for bad in variants:
            with self.subTest(bad=bad):
                self.assertFalse(self.table.validate(bad))
                with self.assertRaises(LeaseFenceError):
                    self.table.release(bad)
        self.assertTrue(self.table.validate(ticket))

    def test_ticket_from_old_scheduler_instance_is_never_valid(self):
        ticket = claim(self.table)
        another = LeaseTable(clock=lambda: self.now[0])
        claim(another)
        self.assertFalse(another.validate(ticket))
        with self.assertRaises(LeaseFenceError):
            another.heartbeat(ticket)

    def test_resource_key_allowlist_rejects_raw_paths_and_aliases(self):
        self.assertEqual(DESKTOP, "pc_desktop")
        self.assertEqual(resource_key("window", "456"), "window:456")
        self.assertEqual(resource_key("browser_session", "session-1"),
                         "browser_session:session-1")
        for kind, target in (
            ("file", "../a.txt"), ("file", "A" * 64),
            ("window", "0001"), ("window", "0"),
            ("provider", "../x"), ("browser_session", "ABC"),
            ("pc_desktop", "alice"), ("random", "resource"),
        ):
            with self.subTest(kind=kind, target=target), self.assertRaises(ValueError):
                resource_key(kind, target)

    def test_keys_must_be_canonical_sorted_and_nonempty(self):
        bad = ((), (DESKTOP, DESKTOP), (DESKTOP, FILE_A),
               ("some_file",), ("file:../secrets",),
               tuple(FILE_A for _ in range(13)))
        for keys in bad:
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                claim(self.table, keys=keys)
        self.assertFalse(self.table.occupied(DESKTOP))

    def test_invalid_owner_ttl_or_version_fail_without_locking(self):
        for kw in ({"owner": ""}, {"version": True},
                   {"version": 0}, {"ttl": 0}, {"ttl": 301},
                   {"ttl": float("nan")}, {"ttl": True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                claim(self.table, **kw)
        self.assertFalse(self.table.occupied(DESKTOP))


if __name__ == "__main__":
    unittest.main()
