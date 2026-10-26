"""Phase 4G ComputerWorker boundary: pilot-only, observable and receipt-oriented."""
from __future__ import annotations

import re
from typing import Any, Iterable

PILOT_APPS = frozenset({"calculator", "notepad"})
_ALLOWED_OPERATIONS = frozenset({"observe", "measure"})
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{3,100}$")


class ComputerWorkerContractError(ValueError):
    pass


def _app_name(app: str) -> str:
    if not isinstance(app, str) or not app.strip():
        raise ComputerWorkerContractError("Uygulama adı geçersiz.")
    return app.casefold().strip()


def app_allowed(app: str) -> bool:
    return _app_name(app) in PILOT_APPS


def capability(app: str, operation: str) -> dict[str, str]:
    normalized = _app_name(app)
    if normalized not in PILOT_APPS:
        raise ComputerWorkerContractError("Bu uygulama ComputerWorker pilot izin listesinde değil.")
    if operation not in _ALLOWED_OPERATIONS:
        raise ComputerWorkerContractError("ComputerWorker pilotunda etkileşimli işlem fail-closed reddedilir.")
    return {"app": normalized, "operation": operation, "effect": "read_only", "evidence_required": "true"}


def measure_uia(elements: Iterable[dict[str, Any]], *, limit: int = 100) -> dict[str, Any]:
    """Normalizes an already-observed UIA tree; this function never invokes or types."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ComputerWorkerContractError("UIA ölçüm sınırı geçersiz.")
    measured = []
    for element in elements:
        if len(measured) >= limit:
            break
        if not isinstance(element, dict):
            raise ComputerWorkerContractError("UIA öğesi geçersiz.")
        bounds = element.get("bounds", [])
        if not isinstance(bounds, list) or len(bounds) != 4 or any(type(value) is not int for value in bounds):
            raise ComputerWorkerContractError("UIA sınırları geçersiz.")
        measured.append({
            "automation_id": str(element.get("automation_id", ""))[:200],
            "name": str(element.get("name", ""))[:500],
            "control_type": str(element.get("control_type", ""))[:100],
            "bounds": list(bounds),
        })
    return {"state": "observed", "elements": measured, "count": len(measured)}


def receipt(job_id: str, granted_capability: dict[str, str], state: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ComputerWorkerContractError("ComputerWorker iş kimliği geçersiz.")
    if not isinstance(granted_capability, dict) or granted_capability.get("effect") != "read_only":
        raise ComputerWorkerContractError("Geçerli salt-okunur yetenek makbuzu gerekli.")
    if state not in {"observed", "blocked", "unavailable"}:
        raise ComputerWorkerContractError("ComputerWorker makbuz durumu geçersiz.")
    if not isinstance(evidence, dict):
        raise ComputerWorkerContractError("ComputerWorker kanıtı geçersiz.")
    return {"job_id": job_id, "state": state, "capability": dict(granted_capability), "evidence": dict(evidence)}
