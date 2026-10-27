"""Phase 4E read-only finance analysis contracts; never a trading or advisory interface."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

NOT_INVESTMENT_ADVICE = "Bilgi amaçlıdır; yatırım tavsiyesi değildir."
SOURCES = ("TCMB", "Frankfurter", "CoinGecko Demo", "BtcTurk", "Yahoo Finance")
_TICKER = re.compile(r"^[A-Z0-9.-]{1,20}$")


class FinanceReadonlyError(ValueError):
    pass


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise FinanceReadonlyError(f"{field} sayısal olmalı.") from None
    if not number.is_finite() or (positive and number <= 0):
        raise FinanceReadonlyError(f"{field} geçersiz.")
    return number


def validate_ticker(ticker: str) -> str:
    value = str(ticker or "").upper()
    if not _TICKER.fullmatch(value):
        raise FinanceReadonlyError("Ticker geçersiz.")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise FinanceReadonlyError("Fiyat zamanı geçersiz.")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FinanceReadonlyError("Fiyat zamanı ISO-8601 olmalı.") from None
    return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)


def normalize_ohlcv(candles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for candle in candles:
        if not isinstance(candle, dict):
            raise FinanceReadonlyError("OHLCV mum kaydı geçersiz.")
        opened = _decimal(candle.get("open"), "open", positive=True)
        high = _decimal(candle.get("high"), "high", positive=True)
        low = _decimal(candle.get("low"), "low", positive=True)
        closed = _decimal(candle.get("close"), "close", positive=True)
        volume = _decimal(candle.get("volume", 0), "volume")
        if low > min(opened, closed) or high < max(opened, closed) or volume < 0:
            raise FinanceReadonlyError("OHLCV fiyat sınırları tutarsız.")
        rows.append({"observed_at": _timestamp(candle.get("date")), "open": opened, "high": high,
                     "low": low, "close": closed, "volume": volume})
    if not rows or len(rows) > 5_000:
        raise FinanceReadonlyError("OHLCV kayıt sayısı geçersiz.")
    return sorted(rows, key=lambda row: row["observed_at"])


def freshness(observed_at: datetime, *, now: datetime | None = None, maximum_age: timedelta = timedelta(days=2)) -> dict[str, Any]:
    if not isinstance(observed_at, datetime) or not isinstance(maximum_age, timedelta) or maximum_age <= timedelta():
        raise FinanceReadonlyError("Tazelik girdisi geçersiz.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seen = observed_at.astimezone(timezone.utc)
    age = current - seen
    if age < timedelta():
        raise FinanceReadonlyError("Kaynak zamanı gelecekte olamaz.")
    return {"state": "fresh" if age <= maximum_age else "stale", "observed_at": seen.isoformat(), "age_seconds": int(age.total_seconds())}


def compare_equities(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(rows, dict) or not 2 <= len(rows) <= 20:
        raise FinanceReadonlyError("Karşılaştırma için 2–20 hisse gerekli.")
    result = []
    for ticker, data in rows.items():
        if not isinstance(data, dict):
            raise FinanceReadonlyError("Hisse verisi geçersiz.")
        result.append({"ticker": validate_ticker(ticker), "price": _decimal(data.get("price"), "price", positive=True),
                       "market_cap": _decimal(data.get("market_cap"), "market_cap", positive=True),
                       "pe": _decimal(data.get("pe"), "pe", positive=True)})
    result.sort(key=lambda row: (row["pe"], row["ticker"]))
    return {"rows": result, "assumptions": ["Karşılaştırma yalnız sağlanan piyasa verisine dayanır.", NOT_INVESTMENT_ADVICE]}


def portfolio_summary(positions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows, total = [], Decimal(0)
    for position in positions:
        if not isinstance(position, dict):
            raise FinanceReadonlyError("Portföy pozisyonu geçersiz.")
        quantity = _decimal(position.get("quantity"), "quantity", positive=True)
        price = _decimal(position.get("price"), "price", positive=True)
        currency = str(position.get("currency", "")).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise FinanceReadonlyError("Portföy para birimi geçersiz.")
        value = quantity * price
        rows.append({"ticker": validate_ticker(position.get("ticker")), "quantity": quantity, "price": price,
                     "currency": currency, "value": value})
        total += value
    if not rows or len(rows) > 500:
        raise FinanceReadonlyError("Portföy büyüklüğü geçersiz.")
    return {"positions": rows, "total_value": total,
            "assumptions": ["Toplam, kur dönüşümü yapılmadan pozisyon fiyatı × miktarıdır.", NOT_INVESTMENT_ADVICE]}


def evidence_pack(subject: str, evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
    label = validate_ticker(subject)
    items = []
    for item in evidence:
        if not isinstance(item, dict) or item.get("source") not in SOURCES:
            raise FinanceReadonlyError("Finans kaynağı tanınmıyor.")
        items.append({"source": item["source"], "observed_at": _timestamp(item.get("observed_at")).isoformat()})
    if not items:
        raise FinanceReadonlyError("En az bir finans kanıtı gerekli.")
    return {"subject": label, "evidence": items, "disclaimer": NOT_INVESTMENT_ADVICE}


def dcf(inputs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inputs, dict):
        raise FinanceReadonlyError("DCF girdisi geçersiz.")
    cash_flow = _decimal(inputs.get("free_cash_flow"), "free_cash_flow", positive=True)
    discount = _decimal(inputs.get("discount_rate"), "discount_rate", positive=True)
    growth = _decimal(inputs.get("terminal_growth"), "terminal_growth")
    if growth < 0 or discount <= growth:
        raise FinanceReadonlyError("DCF iskonto oranı terminal büyümeden yüksek olmalı.")
    terminal_value = cash_flow * (Decimal(1) + growth) / (discount - growth)
    return {"enterprise_value": terminal_value, "assumptions": {"free_cash_flow": cash_flow, "discount_rate": discount,
            "terminal_growth": growth}, "disclaimer": NOT_INVESTMENT_ADVICE}


def comparable_companies(peers: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = []
    for peer in peers:
        if not isinstance(peer, dict):
            raise FinanceReadonlyError("Benzer şirket kaydı geçersiz.")
        values.append({"ticker": validate_ticker(peer.get("ticker")), "ev_ebitda": _decimal(peer.get("ev_ebitda"), "ev_ebitda", positive=True)})
    if not 2 <= len(values) <= 50:
        raise FinanceReadonlyError("2–50 benzer şirket gerekli.")
    median = sorted(row["ev_ebitda"] for row in values)[len(values) // 2]
    return {"peers": values, "median_ev_ebitda": median, "disclaimer": NOT_INVESTMENT_ADVICE}


def lbo(inputs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inputs, dict):
        raise FinanceReadonlyError("LBO girdisi geçersiz.")
    equity = _decimal(inputs.get("entry_equity"), "entry_equity", positive=True)
    debt = _decimal(inputs.get("debt"), "debt")
    multiple = _decimal(inputs.get("exit_multiple"), "exit_multiple", positive=True)
    ebitda = _decimal(inputs.get("ebitda"), "ebitda", positive=True)
    exit_value = multiple * ebitda
    return {"enterprise_value": equity + debt, "equity_value": exit_value - debt,
            "assumptions": {"entry_equity": equity, "debt": debt, "exit_multiple": multiple, "ebitda": ebitda},
            "disclaimer": NOT_INVESTMENT_ADVICE}


def trade_plan_draft(inputs: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Create a bounded, read-only plan draft from supplied verified market observations.

    Levels are only the observed two-candle range; the function never estimates a
    missing price, source, freshness, stop, or target.
    """
    if not isinstance(inputs, dict):
        raise FinanceReadonlyError("Plan girdisi geçersiz.")
    ticker = validate_ticker(inputs.get("ticker"))
    assumptions = [NOT_INVESTMENT_ADVICE, "Plan taslağı salt-okunur karar desteğidir; emir veya pozisyon boyutu üretmez."]
    missing = []
    try:
        price = _decimal(inputs.get("current_price"), "current_price", positive=True)
    except FinanceReadonlyError:
        price = None
        missing.append("doğrulanmış güncel fiyat")
    try:
        observed_at = _timestamp(inputs.get("price_observed_at"))
        current_freshness = freshness(observed_at, now=now)
    except FinanceReadonlyError:
        current_freshness = {"state": "unknown", "observed_at": None, "age_seconds": None}
        missing.append("fiyat tazelik zamanı")
    evidence = []
    try:
        source = inputs.get("source")
        if source not in SOURCES:
            raise FinanceReadonlyError("Finans kaynağı tanınmıyor.")
        pack = evidence_pack(ticker, inputs.get("evidence", []))
        evidence = pack["evidence"]
        if source not in {item["source"] for item in evidence}:
            raise FinanceReadonlyError("Fiyat kaynağı kanıt paketiyle eşleşmiyor.")
    except FinanceReadonlyError:
        missing.append("doğrulanmış kaynak kanıtı")
    candles = []
    try:
        candles = normalize_ohlcv(inputs.get("candles", []))
    except FinanceReadonlyError:
        missing.append("doğrulanmış OHLCV verisi")
    if current_freshness["state"] != "fresh":
        missing.append("güncel fiyat tazeliği")
    if len(candles) < 2:
        missing.append("en az iki doğrulanmış mum")
    if missing:
        return {"state": "incomplete", "ticker": ticker, "summary": "Trade planı için veri yetersiz.",
                "used_price": price, "scenario": None, "entry_zone": None, "entry_condition": None,
                "stop": None, "targets": [], "risk_reward": None, "method": None, "assumptions": assumptions,
                "evidence": evidence, "freshness": current_freshness, "missing_data": list(dict.fromkeys(missing)),
                "disclaimer": NOT_INVESTMENT_ADVICE}
    recent = candles[-2:]
    entry_low = max(row["low"] for row in recent)
    entry_high = max(row["close"] for row in recent)
    stop = min(row["low"] for row in recent)
    target = max(row["high"] for row in recent)
    if not stop < price < target or entry_low > entry_high:
        return {"state": "incomplete", "ticker": ticker,
                "summary": "Gözlenen aralık fiyat için doğrulanmış stop/hedef üretmiyor.", "used_price": price,
                "scenario": None, "entry_zone": None, "entry_condition": None, "stop": None, "targets": [],
                "risk_reward": None, "method": "son iki doğrulanmış mumun gözlenen aralığı",
                "assumptions": assumptions, "evidence": evidence, "freshness": current_freshness,
                "missing_data": ["fiyatı çevreleyen gözlenen stop ve hedef aralığı"], "disclaimer": NOT_INVESTMENT_ADVICE}
    method = "son iki doğrulanmış mumun gözlenen aralığı"
    assumptions.extend(["Kullanılan fiyat, kanıt paketindeki kaynak ve zamanla eşleşir.",
                        "Stop son iki mumun en düşük, hedef en yüksek gözlenen değeridir; tahmin değildir."])
    return {"state": "ready", "ticker": ticker, "summary": "Doğrulanmış fiyat ve gözlenen aralıkla plan taslağı.",
            "used_price": price, "scenario": "gözlenen aralık içinde uzun senaryo", 
            "entry_zone": {"low": entry_low, "high": entry_high},
            "entry_condition": "Fiyat gözlenen kapanış aralığında kalırsa.", "stop": stop, "targets": [target],
            "risk_reward": (target - price) / (price - stop), "method": method, "assumptions": assumptions,
            "evidence": evidence, "freshness": current_freshness, "missing_data": [], "disclaimer": NOT_INVESTMENT_ADVICE}


def trade_plan_risk_checklist(plan: dict[str, Any]) -> dict[str, Any]:
    """List plan-data limitations without making a trading or approval decision."""
    if not isinstance(plan, dict):
        raise FinanceReadonlyError("Plan kaydı geçersiz.")
    ticker = validate_ticker(plan.get("ticker"))
    observations = []
    freshness_state = plan.get("freshness", {}).get("state") if isinstance(plan.get("freshness"), dict) else None
    if freshness_state != "fresh":
        observations.append({"code": "STALE_DATA", "detail": "Fiyat verisinin tazeliği doğrulanmış değil."})
    if plan.get("stop") is None:
        observations.append({"code": "STOP_UNAVAILABLE", "detail": "Doğrulanmış stop seviyesi yok."})
    if not isinstance(plan.get("targets"), list) or not plan["targets"]:
        observations.append({"code": "TARGET_UNAVAILABLE", "detail": "Doğrulanmış hedef yok."})
    if plan.get("risk_reward") is None:
        observations.append({"code": "RISK_REWARD_UNAVAILABLE", "detail": "Risk-getiri görünümü hesaplanamadı."})
    if plan.get("missing_data"):
        observations.append({"code": "MISSING_EVIDENCE", "detail": "Planın eksik veri veya kanıt notları var."})
    return {"state": "observed", "ticker": ticker, "observations": observations,
            "assumptions": [NOT_INVESTMENT_ADVICE,
                            "Bu liste yalnız veri/plan sınırlamalarını gösterir; PASS/BLOCK veya işlem kararı vermez."],
            "disclaimer": NOT_INVESTMENT_ADVICE}


class FinanceResearchAgent:
    """Pure formatter: data must arrive through separately audited read-only adapters."""

    def report(self, ticker: str, evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
        pack = evidence_pack(ticker, evidence)
        return {"state": "observed", "ticker": pack["subject"], "evidence": pack["evidence"],
                "disclaimer": NOT_INVESTMENT_ADVICE}
