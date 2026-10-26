"""Small, dependency-free five-field cron parser for durable local schedules.

The parser is deliberately limited to standard minute/hour/day/month/weekday
expressions. It validates before a schedule is persisted and never executes a
command by itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta


_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


class CronExpression:
    """Validated five-field cron expression.

    Weekday accepts both 0 and 7 for Sunday. When both day-of-month and
    weekday are restricted, matching follows standard cron OR semantics.
    """

    def __init__(self, expression: str):
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("Cron ifadesi gerekli.")
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("Cron ifadesi beş alan içermeli: dakika saat gün ay hafta_günü.")
        self.expression = " ".join(fields)
        self._values = []
        self._any = []
        for token, (lower, upper) in zip(fields, _RANGES):
            values, unrestricted = self._parse_field(token, lower, upper)
            self._values.append(values)
            self._any.append(unrestricted)

    @staticmethod
    def _parse_field(token: str, lower: int, upper: int) -> tuple[frozenset[int], bool]:
        if not token or token == "?":
            raise ValueError("Cron alanı geçersiz.")
        values: set[int] = set()
        unrestricted = token == "*"
        for part in token.split(","):
            if not part:
                raise ValueError("Cron alanı boş olamaz.")
            base, separator, step_text = part.partition("/")
            if separator:
                if not step_text.isdigit() or int(step_text) <= 0:
                    raise ValueError("Cron adımı pozitif sayı olmalı.")
                step = int(step_text)
            else:
                step = 1
            if base == "*":
                start, end = lower, upper
            elif "-" in base:
                pieces = base.split("-")
                if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
                    raise ValueError("Cron aralığı geçersiz.")
                start, end = (int(piece) for piece in pieces)
                if start > end:
                    raise ValueError("Cron aralığı ters çevrilmiş.")
            elif base.isdigit():
                start = end = int(base)
            else:
                raise ValueError("Cron değeri geçersiz.")
            if start < lower or end > upper:
                raise ValueError("Cron değeri alan sınırının dışında.")
            values.update(range(start, end + 1, step))
        if not values:
            raise ValueError("Cron alanı boş sonuç üretti.")
        return frozenset(values), unrestricted

    def matches(self, value: datetime) -> bool:
        if not isinstance(value, datetime):
            raise TypeError("Cron yalnız datetime kabul eder.")
        minute, hour = value.minute, value.hour
        dom, month = value.day, value.month
        dow = (value.weekday() + 1) % 7
        minute_ok = minute in self._values[0]
        hour_ok = hour in self._values[1]
        month_ok = month in self._values[3]
        dom_ok = dom in self._values[2]
        dow_ok = dow in self._values[4] or (dow == 0 and 7 in self._values[4])
        if not (minute_ok and hour_ok and month_ok):
            return False
        if not self._any[2] and not self._any[4]:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def next_after(self, value: datetime, *, limit_days: int = 366) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError("Cron yalnız datetime kabul eder.")
        current = value.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = current + timedelta(days=limit_days)
        while current <= limit:
            if self.matches(current):
                return current
            current += timedelta(minutes=1)
        raise ValueError("Cron ifadesi sınır içinde bir sonraki zamanı üretmedi.")
