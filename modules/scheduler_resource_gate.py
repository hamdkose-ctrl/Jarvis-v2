"""BRAIN-07B: conservative read-only Core-plan / ResourceLease admission.

This is an adapter for the ONE existing scheduler to call in a later cutover.
No worker is launched, no task/goal store is created, and acquiring a lease is
NOT a permission to perform any effect. It deliberately rejects unknown and
effectful capabilities and dependent steps until verified predecessors exist.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

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
