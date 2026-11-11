"""BRAIN-07B: conservative read-only Core-plan / ResourceLease admission.

This is an adapter for the ONE existing scheduler to call in a later cutover.
No worker is launched, no task/goal store is created, and acquiring a lease is
NOT a permission to perform any effect. It deliberately rejects unknown and
effectful capabilities and dependent steps until verified predecessors exist.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import threading

from modules import capability_manifest, goal_plan_gate, resource_leases


class ReadOnlyAdmissionError(ValueError):
    """Cannot acquire a bounded read-only lease for this canonical plan node."""


def _typed_resource_keys(node: dict, owner: str) -> tuple[str, ...]:
    """Derive keys from trusted capability metadata and canonical input.

    Never accept resource keys supplied by the model in an arbitrary node field.
    """
    capability_id = node["capability_id"]
    if capability_id.startswith("task."):
        kind = capability_id.removeprefix("task.")
        try:
            manifest = capability_manifest.from_task_tool(kind)
        except ValueError as exc:
            raise ReadOnlyAdmissionError("Unknown read-only task capability.") from exc
    elif capability_id.startswith("goal."):
        kind = capability_id.removeprefix("goal.")
        try:
            manifest = capability_manifest.from_goal_tool(kind)
        except ValueError as exc:
            raise ReadOnlyAdmissionError("Unknown read-only goal capability.") from exc
    else:
        raise ReadOnlyAdmissionError("Unsupported capability namespace.")

    if (manifest["id"] != capability_id or manifest["effect_policy"] != "read_only"
            or manifest["decision_authority"] != "execute"):
        raise ReadOnlyAdmissionError("An effectful capability cannot obtain this lease.")

    params = node["input"]
    if not isinstance(params, dict):
        raise ReadOnlyAdmissionError("Input must be canonical object.")

    if capability_id in ("task.computer", "goal.observe"):
        if capability_id == "task.computer":
            from modules import task_tools
            task_tools.validate_input("computer", params)
        else:
            from modules import goal_tools
            goal_tools.validate("observe", params)
        return (resource_leases.resource_key("pc_desktop"),)

    if capability_id == "task.file":
        from modules import task_tools
        task_tools.validate_input("file", params)
        try:
            target = Path(params["path"]).resolve(strict=True)
            if not target.is_file():
                raise ReadOnlyAdmissionError("File read target is not a regular file.")
        except (OSError, RuntimeError) as exc:
            raise ReadOnlyAdmissionError("File read target unavailable.") from exc
        canonical = os.path.normcase(str(target)).encode("utf-8")
        return (resource_leases.resource_key(
            "file", hashlib.sha256(canonical).hexdigest(),
        ),)

    if capability_id == "task.account":
        from modules import task_tools
        task_tools.validate_input("account", params)
        service = params["service"]
        identity = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
        if service == "gmail":
            return (resource_leases.resource_key("gmail_account", identity),)
        if not isinstance(service, str) or not service.isascii() or not service.islower():
            raise ReadOnlyAdmissionError("Provider identifier invalid.")
        # Model cannot set arbitrary account IDs or resource keys.
        return (resource_leases.resource_key("provider", f"{service}-{identity}"),)

    # Stateless research/finance and other read-only kinds are deliberately not
    # mapped to fake global resources. They remain outside this lease gate.
    raise ReadOnlyAdmissionError("No scheduler resource mapping for this capability.")


def _require_attempt(state: dict, selected: goal_plan_gate.NodeCandidate,
                     attempt: int) -> None:
    """A retry is never automatic: only the caller's strictly newer attempt."""
    try:
        goal_plan_gate.validate_root_attempt(state, selected, attempt=attempt)
    except goal_plan_gate.PlanFenceError as exc:
        raise ReadOnlyAdmissionError("Canonical root not ready or attempt invalid.") from exc


def admit(
    leases: resource_leases.LeaseTable, state: dict,
    selected: goal_plan_gate.NodeCandidate, *,
    attempt: int, ttl: float = 30.0,
) -> resource_leases.LeaseTicket:
    """Claim resources only for an independent canonical read-only root node."""
    if not isinstance(leases, resource_leases.LeaseTable):
        raise ReadOnlyAdmissionError("The existing scheduler must supply its lease table.")
    if type(attempt) is not int or not 1 <= attempt <= 1_000_000:
        raise ReadOnlyAdmissionError("Worker attempt invalid.")
    node = goal_plan_gate.revalidate(state, selected)
    if node["depends_on"]:
        raise ReadOnlyAdmissionError("Dependent node requires verified predecessor evidence.")
    _require_attempt(state, selected, attempt)
    keys = _typed_resource_keys(node, selected.owner)
    return leases.acquire(
        owner=selected.owner,
        job_id=selected.job_id,
        step_id=selected.node_id,
        plan_version=selected.plan_version,
        command_id=f"{selected.node_id}:{attempt}:p{selected.plan_version}",
        keys=keys,
        ttl=ttl,
    )


def validate_before_dispatch(
    leases: resource_leases.LeaseTable, state: dict,
    selected: goal_plan_gate.NodeCandidate, ticket: resource_leases.LeaseTicket,
    *, attempt: int,
) -> dict:
    """Recheck identity, canonical plan, derived resources and exact live lease.

    This revalidation is a pre-dispatch safety check, NOT WorkerResult acceptance,
    Core permission approval or proof that the output will be valid.
    """
    if not isinstance(leases, resource_leases.LeaseTable) or not isinstance(
        ticket, resource_leases.LeaseTicket
    ):
        raise ReadOnlyAdmissionError("Lease ticket or owner invalid.")
    if type(attempt) is not int or not 1 <= attempt <= 1_000_000:
        raise ReadOnlyAdmissionError("Worker attempt invalid.")
    node = goal_plan_gate.revalidate(state, selected)
    if node["depends_on"]:
        raise ReadOnlyAdmissionError("Dependent node requires verified predecessor evidence.")
    _require_attempt(state, selected, attempt)
    expected = (
        selected.owner, selected.job_id, selected.node_id,
        selected.plan_version, f"{selected.node_id}:{attempt}:p{selected.plan_version}",
        _typed_resource_keys(node, selected.owner),
    )
    actual = (
        ticket.owner, ticket.job_id, ticket.step_id, ticket.plan_version,
        ticket.command_id, ticket.keys,
    )
    if actual != expected or not leases.validate(ticket):
        raise ReadOnlyAdmissionError("Lease is stale, foreign or bound to another worker.")
    return node


# This is held only while the EXISTING specialist executor is actually running
# a planned read-only account job. The private context cannot be minted from a
# model/worker result and is not a durable cross-process lock.
_ACCOUNT_RESULT_LEASE = ContextVar('jarvis_account_result_lease', default=None)


@contextmanager
def account_read_worker(leases: resource_leases.LeaseTable,
                        identity: dict, expected: dict, *, ttl: float = 60.0):
    """Own one account-read resource from pre-worker admission to Core CAS.

    Only the existing goal_executor supplies the singleton table. No second
    task loop or scheduler is created. A daemon renews the exact ticket until
    this context exits; it is joined before releasing any resources.
    """
    if (not isinstance(identity, dict) or not isinstance(expected, dict)
            or expected.get('capability_id') != 'task.account'
            or type(expected.get('plan_version')) is not int
            or expected.get('owner') != identity.get('owner')
            or expected.get('job_id') != identity.get('job_id')
            or expected.get('step_id') != identity.get('task_id')
            or type(expected.get('attempt')) is not int
            or expected['attempt'] != identity.get('attempt')):
        raise ReadOnlyAdmissionError('Planned account read execution identity invalid.')
    from modules import runtime_worker_result
    state = runtime_worker_result.canonical_snapshot(identity)
    selected = goal_plan_gate.candidate(
        state, owner=expected['owner'], job_id=expected['job_id'],
        node_id=expected['step_id'],
    )
    if (expected['plan_version'] != selected.plan_version
            or expected.get('node_digest') != selected.node_digest
            or expected.get('command_id') !=
            f"{selected.node_id}:{expected['attempt']}:p{selected.plan_version}"):
        raise ReadOnlyAdmissionError('Planned account read command fence invalid.')
    ticket = admit(leases, state, selected, attempt=expected['attempt'], ttl=ttl)
    lock = threading.RLock()
    holder = [ticket]
    stop = threading.Event()
    lost = threading.Event()

    def pulse():
        while not stop.wait(ttl / 3):
            with lock:
                try:
                    holder[0] = leases.heartbeat(holder[0], ttl=ttl)
                except resource_leases.LeaseFenceError:
                    lost.set()
                    return

    def commit_checked(output: dict) -> dict:
        # Freeze renewal generation during the final lease proof and CAS.
        # A non-owner/expired ticket or revised plan fails before success can
        # enter canonical GoalState. Domain output was verified in the worker
        # hook; the normal WorkerResult acceptor validates its envelope.
        with lock:
            if lost.is_set():
                raise ReadOnlyAdmissionError('Account resource lease was lost.')
            current = runtime_worker_result.canonical_snapshot(identity)
            refreshed = goal_plan_gate.candidate(
                current, owner=expected['owner'], job_id=expected['job_id'],
                node_id=expected['step_id'],
            )
            validate_before_dispatch(
                leases, current, refreshed, holder[0],
                attempt=expected['attempt'],
            )
            token = _ACCOUNT_RESULT_LEASE.set((leases, holder[0], expected))
            try:
                return runtime_worker_result.accept_and_commit(output, expected)
            finally:
                _ACCOUNT_RESULT_LEASE.reset(token)

    thread = threading.Thread(
        target=pulse, name='canonical-account-lease', daemon=True,
    )
    started = False
    try:
        validate_before_dispatch(
            leases, state, selected, holder[0],
            attempt=expected['attempt'],
        )
        thread.start()
        started = True
        yield commit_checked
    finally:
        stop.set()
        if started:
            thread.join()
        with lock:
            # Expired/taken-over lease already has no ownership to release.
            if leases.validate(holder[0]):
                leases.release(holder[0])


def require_account_result_lease(accepted: dict) -> None:
    """Core-side exact ticket check before accepting a planned account result."""
    binding = _ACCOUNT_RESULT_LEASE.get()
    if not isinstance(binding, tuple) or len(binding) != 3:
        raise ReadOnlyAdmissionError('Planned account result needs a live owner lease.')
    leases, ticket, expected = binding
    fields = (
        'owner', 'job_id', 'step_id', 'command_id', 'attempt',
        'expected_job_version', 'capability_id', 'capability_version',
        'input_digest', 'plan_version', 'node_digest',
    )
    if (not isinstance(leases, resource_leases.LeaseTable)
            or not isinstance(ticket, resource_leases.LeaseTicket)
            or not isinstance(expected, dict)
            or any(accepted.get(field) != expected.get(field) for field in fields)
            or (ticket.owner, ticket.job_id, ticket.step_id,
                ticket.plan_version, ticket.command_id) !=
               (accepted['owner'], accepted['job_id'], accepted['step_id'],
                accepted['plan_version'], accepted['command_id'])):
        raise ReadOnlyAdmissionError('Account result exact execution fence mismatched.')
    if not leases.validate(ticket):
        raise ReadOnlyAdmissionError('Account result resource lease expired.')


# Only the in-process existing goal executor lease table may supply this
# scoped fence. It is not a cross-process durable claim or worker authority.
_DEPENDENT_RESEARCH_RESULT_LEASE = ContextVar(
    'jarvis_dependent_research_result_lease', default=None,
)


@contextmanager
def dependent_research_worker(
    leases: resource_leases.LeaseTable, identity: dict, expected: dict,
    *, ttl: float = 60.0,
):
    """Own one canonical research-child command from dispatch through CAS.

    Different jobs/steps remain parallel; duplicate wakes for the same
    canonical node/attempt conflict on one command-scoped resource key.
    """
    if (not isinstance(leases, resource_leases.LeaseTable)
            or not isinstance(identity, dict)
            or not isinstance(expected, dict)
            or expected.get('capability_id') != 'task.research'
            or type(expected.get('plan_version')) is not int
            or expected.get('owner') != identity.get('owner')
            or expected.get('job_id') != identity.get('job_id')
            or expected.get('step_id') != identity.get('task_id')
            or type(expected.get('attempt')) is not int
            or expected['attempt'] != identity.get('attempt')):
        raise ReadOnlyAdmissionError('Dependent research command identity invalid.')
    from modules import dependency_evidence, runtime_worker_result
    state = runtime_worker_result.canonical_snapshot(identity)
    selected = goal_plan_gate.candidate(
        state, owner=expected['owner'], job_id=expected['job_id'],
        node_id=expected['step_id'],
    )
    if (expected.get('node_digest') != selected.node_digest
            or expected['plan_version'] != selected.plan_version
            or expected.get('command_id') !=
            f"{selected.node_id}:{expected['attempt']}:p{selected.plan_version}"
            or expected.get('expected_job_version') != state['version']):
        raise ReadOnlyAdmissionError('Dependent research plan command fence invalid.')
    node = goal_plan_gate.validate_dependent_research_attempt(
        state, selected, attempt=expected['attempt'],
    )
    dependency_evidence.require_persisted_research_dependencies(identity, node)
    # A dedicated command namespace prevents a misleading global "provider"
    # lease and leaves independent read-only jobs parallel.
    digest = hashlib.sha256(json.dumps(
        [selected.owner, selected.job_id, selected.node_id,
         selected.plan_version, expected['command_id']],
        ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    key = resource_leases.resource_key('command', digest)
    ticket = leases.acquire(
        owner=selected.owner, job_id=selected.job_id,
        step_id=selected.node_id, plan_version=selected.plan_version,
        command_id=expected['command_id'], keys=(key,), ttl=ttl,
    )
    lock = threading.RLock()
    holder = [ticket]
    stop = threading.Event()
    lost = threading.Event()

    def require_current() -> None:
        if lost.is_set() or not leases.validate(holder[0]):
            raise ReadOnlyAdmissionError('Dependent research command lease lost.')
        current = runtime_worker_result.canonical_snapshot(identity)
        if current['version'] != expected['expected_job_version']:
            raise ReadOnlyAdmissionError('Dependent research GoalState changed during worker.')
        chosen = goal_plan_gate.candidate(
            current, owner=selected.owner, job_id=selected.job_id,
            node_id=selected.node_id,
        )
        if (chosen.plan_version != selected.plan_version
                or chosen.node_digest != selected.node_digest):
            raise ReadOnlyAdmissionError('Dependent research plan was replaced.')
        refreshed = goal_plan_gate.validate_dependent_research_attempt(
            current, chosen, attempt=expected['attempt'],
        )
        dependency_evidence.require_persisted_research_dependencies(
            identity, refreshed,
        )

    def pulse() -> None:
        while not stop.wait(ttl / 3):
            with lock:
                try:
                    holder[0] = leases.heartbeat(holder[0], ttl=ttl)
                except resource_leases.LeaseFenceError:
                    lost.set()
                    return

    def commit_checked(output: dict) -> dict:
        with lock:
            require_current()
            token = _DEPENDENT_RESEARCH_RESULT_LEASE.set(
                (leases, holder[0], expected),
            )
            try:
                return runtime_worker_result.accept_and_commit(output, expected)
            finally:
                _DEPENDENT_RESEARCH_RESULT_LEASE.reset(token)

    thread = threading.Thread(
        target=pulse, name='canonical-research-command-lease', daemon=True,
    )
    started = False
    try:
        with lock:
            require_current()
        thread.start()
        started = True
        yield commit_checked
    finally:
        stop.set()
        if started:
            thread.join()
        with lock:
            if leases.validate(holder[0]):
                leases.release(holder[0])


def require_dependent_research_result_lease(accepted: dict) -> None:
    """Core CAS may accept a new dependent result only from a live command."""
    binding = _DEPENDENT_RESEARCH_RESULT_LEASE.get()
    if not isinstance(binding, tuple) or len(binding) != 3:
        raise ReadOnlyAdmissionError(
            'Dependent research result requires a live Core command lease.'
        )
    leases, ticket, expected = binding
    fields = (
        'owner', 'job_id', 'step_id', 'command_id', 'attempt',
        'expected_job_version', 'capability_id', 'capability_version',
        'input_digest', 'plan_version', 'node_digest',
    )
    if (not isinstance(leases, resource_leases.LeaseTable)
            or not isinstance(ticket, resource_leases.LeaseTicket)
            or not isinstance(expected, dict)
            or any(accepted.get(field) != expected.get(field) for field in fields)
            or (ticket.owner, ticket.job_id, ticket.step_id,
                ticket.plan_version, ticket.command_id) !=
               (accepted['owner'], accepted['job_id'], accepted['step_id'],
                accepted['plan_version'], accepted['command_id'])
            or not leases.validate(ticket)):
        raise ReadOnlyAdmissionError('Dependent research exact command lease invalid.')
