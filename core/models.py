"""Zona modeli va alert hodisasi."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Zone:
    """Narx zonasi: [min_price, max_price]."""

    id: int
    min_price: float
    max_price: float
    triggered: bool = False
    created_at: str = field(default_factory=_now)
    triggered_at: Optional[str] = None
    triggered_price: Optional[float] = None
    hits: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if self.min_price > self.max_price:
            self.min_price, self.max_price = self.max_price, self.min_price

    # ---------- masofa ----------
    def distance(self, price: float) -> float:
        """Zonaning eng yaqin chegarasigacha bo'lgan masofa (USD). Ichida bo'lsa 0."""
        if price < self.min_price:
            return self.min_price - price
        if price > self.max_price:
            return price - self.max_price
        return 0.0

    def side(self, price: float) -> str:
        if price < self.min_price:
            return "below"
        if price > self.max_price:
            return "above"
        return "inside"

    def in_buffer(self, price: float, buffer_price: float) -> bool:
        """Narx [min-buffer, max+buffer] oralig'idami?"""
        return (self.min_price - buffer_price) <= price <= (self.max_price + buffer_price)

    def outside_rearm(self, price: float, buffer_price: float, rearm_price: float) -> bool:
        """Zona qayta 'quroliansa' bo'ladigan darajada uzoqlashdimi?"""
        if rearm_price <= 0:
            return False
        low = self.min_price - buffer_price - rearm_price
        high = self.max_price + buffer_price + rearm_price
        return price < low or price > high

    def mark_triggered(self, price: float) -> None:
        self.triggered = True
        self.triggered_at = _now()
        self.triggered_price = price
        self.hits += 1

    def rearm(self) -> None:
        self.triggered = False
        self.triggered_at = None
        self.triggered_price = None

    # ---------- serializatsiya ----------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "min_price": round(self.min_price, 5),
            "max_price": round(self.max_price, 5),
            "triggered": self.triggered,
            "created_at": self.created_at,
            "triggered_at": self.triggered_at,
            "triggered_price": self.triggered_price,
            "hits": self.hits,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Zone":
        return cls(
            id=int(raw["id"]),
            min_price=float(raw["min_price"]),
            max_price=float(raw["max_price"]),
            triggered=bool(raw.get("triggered", False)),
            created_at=str(raw.get("created_at") or _now()),
            triggered_at=raw.get("triggered_at"),
            triggered_price=raw.get("triggered_price"),
            hits=int(raw.get("hits", 0)),
            note=str(raw.get("note") or ""),
        )

    @property
    def label(self) -> str:
        return f"{self.min_price:.2f} - {self.max_price:.2f}"


@dataclass(frozen=True)
class AlertEvent:
    """Zona bufer chegarasiga kirganda tug'iladigan hodisa."""

    zone: Zone
    price: float
    bid: float
    ask: float
    distance: float        # USD
    distance_pips: float
    side: str              # below | above | inside
    symbol: str

    @property
    def direction_text(self) -> str:
        return {
            "below": "pastdan yaqinlashmoqda",
            "above": "yuqoridan yaqinlashmoqda",
            "inside": "ZONA ICHIDA",
        }[self.side]

    @property
    def arrow(self) -> str:
        return {"below": "\u2b06\ufe0f", "above": "\u2b07\ufe0f", "inside": "\U0001f3af"}[self.side]
