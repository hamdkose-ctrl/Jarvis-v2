"""Exact, expiring Finance plan approvals; never an order or an execution grant.

The module is deliberately a small contract adapter.  It accepts only the
already calculated PASS decision from ``finance_readonly`` and preserves the
plan facts verbatim in an immutable fingerprint.  It has no broker, worker,
permission-gate or effect-dispatch dependency.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from modules import service_store


class TradeIntentError(ValueError):
    pass


_INTENT_SCHEMA = "finance_trade_intent.v1"
_RECEIPT_SCHEMA = "finance_trade_approval_receipt.v1"
_CHANNELS = frozenset({"chat", "voice", "web"})


def _timestamp(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TradeIntentError("Onay zamanı geçersiz.") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TradeIntentError("Onay zamanı saat dilimli olmalı.")
    return value.astimezone(timezone.utc)


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value).isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json(item) for key, item in value.items()}
    raise TradeIntentError("Intent verisi JSON uyumlu değil.")


def _digest(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise TradeIntentError(f"{name} geçersiz.")
    return value.strip()


def _plan_facts(decision: dict) -> dict:
    if not isinstance(decision, dict) or decision.get("decision") != "PASS":
        raise TradeIntentError("Yalnız PASS RiskDecision için intent oluşturulabilir.")
    plan = decision.get("plan")
    if not isinstance(plan, dict) or plan.get("freshness", {}).get("state") != "fresh":
        raise TradeIntentError("Fresh plan kanıtı olmadan intent oluşturulamaz.")
    ticker = _text(decision.get("ticker"), "ticker")
    scenario = plan.get("scenario")
    if not isinstance(scenario, str) or "uzun" not in scenario.casefold():
        raise TradeIntentError("Plan yönü doğrulanmış değil.")
    entry, stop, targets, size = (plan.get("used_price"), plan.get("stop"),
                                  plan.get("targets"), decision.get("position_size"))
    if entry is None or stop is None or not isinstance(targets, list) or not targets or size is None:
        raise TradeIntentError("Plan seviyeleri veya pozisyon boyutu eksik.")
    facts = {
        "ticker": ticker, "direction": "long", "entry": entry, "stop": stop,
        "targets": targets, "position_size": size,
        "risk_amount": decision.get("risk_amount"), "risk_fraction": decision.get("risk_fraction"),
        "evidence": plan.get("evidence"), "freshness": plan.get("freshness"),
    }
    return _json(facts)


def create(decision: dict, *, owner: str, intent_id: str, created_at: datetime | str,
           ttl_seconds: int) -> dict:
    """Bind one existing PASS decision to an exact, short-lived TradeIntent."""
    owner, intent_id = _text(owner, "owner"), _text(intent_id, "intent_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
        raise TradeIntentError("Intent süresi 1 ile 3600 saniye arasında olmalı.")
    created = _timestamp(created_at)
    facts = _plan_facts(decision)
    plan_fingerprint = _digest(facts)
    expires = created + timedelta(seconds=ttl_seconds)
    bound = {"schema": _INTENT_SCHEMA, "intent_id": intent_id, "owner": owner,
             "created_at": created.isoformat(), "expires_at": expires.isoformat(),
             "plan_fingerprint": plan_fingerprint, **facts}
    return {"state": "pending_approval", **bound, "fingerprint": _digest(bound),
            "disclaimer": "ApprovedIntent yürütülebilir emir değildir; broker veya effect dispatch yoktur."}


def _receipt(approved: dict) -> dict:
    receipt = approved.get("receipt") if isinstance(approved, dict) else None
    if not isinstance(receipt, dict) or receipt.get("schema") != _RECEIPT_SCHEMA:
        raise TradeIntentError("Onay receipt'i geçersiz.")
    return receipt


def _valid_intent(intent: dict) -> bool:
    if not isinstance(intent, dict) or intent.get("schema") != _INTENT_SCHEMA:
        return False
    try:
        protected = {key: value for key, value in intent.items()
                     if key not in {"state", "fingerprint", "disclaimer"}}
        facts = {key: protected[key] for key in (
            "ticker", "direction", "entry", "stop", "targets", "position_size",
            "risk_amount", "risk_fraction", "evidence", "freshness",
        )}
        return (intent.get("state") == "pending_approval"
                and intent.get("plan_fingerprint") == _digest(facts)
                and intent.get("fingerprint") == _digest(protected))
    except (KeyError, TypeError, ValueError, TradeIntentError):
        return False


def approve(intent: dict, *, owner: str, receipt_id: str, channel: str,
            now: datetime | str) -> dict:
    """Create a receipt for one exact, still-pending intent; does not execute it."""
    if not _valid_intent(intent):
        raise TradeIntentError("Onaylanacak intent beklemede değil.")
    moment, expiry = _timestamp(now), _timestamp(intent.get("expires_at"))
    if _text(owner, "owner") != intent.get("owner") or moment >= expiry:
        raise TradeIntentError("Intent sahibi veya süresi geçerli değil.")
    if channel not in _CHANNELS:
        raise TradeIntentError("Onay kanalı geçersiz.")
    receipt_id = _text(receipt_id, "receipt_id")
    receipt = {"schema": _RECEIPT_SCHEMA, "receipt_id": receipt_id, "owner": owner,
               "intent_id": intent.get("intent_id"), "intent_fingerprint": intent.get("fingerprint"),
               "plan_fingerprint": intent.get("plan_fingerprint"), "approved_at": moment.isoformat(),
               "expires_at": expiry.isoformat(), "state": "approved", "channel": channel,
               "revoked_at": None, "consumed_at": None}
    return {"state": "approved", "intent": copy.deepcopy(intent), "receipt": receipt,
            "disclaimer": "Approval execution permission veya broker emri değildir."}


def revoke(approved: dict, *, owner: str, now: datetime | str) -> dict:
    """Return an auditable, terminal revocation receipt without changing intent facts."""
    receipt = _receipt(approved)
    if receipt.get("state") != "approved" or _text(owner, "owner") != receipt.get("owner"):
        raise TradeIntentError("Onay revoke edilemez.")
    changed = copy.deepcopy(approved)
    changed["receipt"]["state"] = "revoked"
    changed["receipt"]["revoked_at"] = _timestamp(now).isoformat()
    changed["state"] = "revoked"
    return changed


def consume(approved: dict, intent: dict, *, owner: str, now: datetime | str) -> dict:
    """Consume once after verification; this records no external effect and dispatches none."""
    if not verify(approved, intent, owner=owner, now=now):
        raise TradeIntentError("Onay kullanılabilir değil.")
    changed = copy.deepcopy(approved)
    changed["receipt"]["state"] = "consumed"
    changed["receipt"]["consumed_at"] = _timestamp(now).isoformat()
    changed["state"] = "consumed"
    return changed


def verify(approved: dict, intent: dict, *, owner: str, now: datetime | str) -> bool:
    """Fail closed: a receipt is valid only for the unchanged exact current intent."""
    try:
        receipt = _receipt(approved)
        moment = _timestamp(now)
        return (
            isinstance(intent, dict)
            and _valid_intent(intent)
            and approved.get("state") == "approved"
            and receipt.get("state") == "approved"
            and approved.get("intent") == intent
            and _text(owner, "owner") == receipt.get("owner") == intent.get("owner")
            and moment < _timestamp(receipt.get("expires_at"))
            and receipt.get("intent_id") == intent.get("intent_id")
            and receipt.get("intent_fingerprint") == intent.get("fingerprint")
            and receipt.get("plan_fingerprint") == intent.get("plan_fingerprint")
        )
    except (TradeIntentError, TypeError, ValueError):
        return False


class ApprovalJournal:
    """Owner-scoped durable receipts; it records approval state but never effects."""

    def _schema(self, db) -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS finance_trade_approval_receipts(
            receipt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
            intent_fingerprint TEXT NOT NULL, receipt TEXT NOT NULL
        )""")

    def record(self, intent: dict, *, owner: str, receipt_id: str, channel: str,
               now: datetime | str) -> dict:
        approved = approve(intent, owner=owner, receipt_id=receipt_id, channel=channel, now=now)
        receipt = approved["receipt"]
        with service_store.database(owner) as db:
            self._schema(db)
            try:
                db.execute("INSERT INTO finance_trade_approval_receipts VALUES(?,?,?,?)", (
                    receipt["receipt_id"], receipt["intent_id"], receipt["intent_fingerprint"],
                    json.dumps(approved, ensure_ascii=False, allow_nan=False, sort_keys=True),
                ))
            except sqlite3.Error as exc:
                raise TradeIntentError("Approval receipt kaydedilemedi.") from exc
        return approved

    def get(self, owner: str, receipt_id: str) -> dict:
        receipt_id = _text(receipt_id, "receipt_id")
        try:
            with service_store.database(owner) as db:
                self._schema(db)
                row = db.execute("SELECT receipt FROM finance_trade_approval_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        except PermissionError as exc:
            raise TradeIntentError("Approval receipt sahibi doğrulanamadı.") from exc
        if row is None:
            raise TradeIntentError("Approval receipt bulunamadı.")
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise TradeIntentError("Approval receipt bozuk.") from exc
        if not isinstance(value, dict):
            raise TradeIntentError("Approval receipt bozuk.")
        return value

    def _replace(self, owner: str, value: dict) -> dict:
        receipt = _receipt(value)
        with service_store.database(owner) as db:
            self._schema(db)
            changed = db.execute("UPDATE finance_trade_approval_receipts SET receipt=? WHERE receipt_id=?", (
                json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True), receipt["receipt_id"],
            )).rowcount
        if changed != 1:
            raise TradeIntentError("Approval receipt güncellenemedi.")
        return value

    def revoke(self, owner: str, receipt_id: str, *, now: datetime | str) -> dict:
        return self._replace(owner, revoke(self.get(owner, receipt_id), owner=owner, now=now))

    def consume(self, owner: str, receipt_id: str, intent: dict, *, now: datetime | str) -> dict:
        return self._replace(owner, consume(self.get(owner, receipt_id), intent, owner=owner, now=now))
