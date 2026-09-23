"""Zonalarni boshqarish: qo'shish, o'chirish, saqlash va bufer tekshiruvi."""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Optional

from config import Settings
from core.models import AlertEvent, Zone
from core.storage import JsonStorage

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class ZoneManager:
    """Zonalar ro'yxatining yagona egasi. Barcha o'zgarish darhol diskka yoziladi."""

    def __init__(self, storage: JsonStorage, settings: Settings) -> None:
        self._storage = storage
        self._s = settings
        self._zones: List[Zone] = []
        self._next_id: int = 1
        self._lock = asyncio.Lock()

    # ---------------- persistence ----------------
    async def load(self) -> None:
        raw = await self._storage.load(default={})
        zones: List[Zone] = []
        for item in raw.get("zones", []):
            try:
                zones.append(Zone.from_dict(item))
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Buzuq zona yozuvi o'tkazib yuborildi: %r (%s)", item, exc)
        self._zones = sorted(zones, key=lambda z: z.min_price)
        self._next_id = max([z.id for z in self._zones], default=0) + 1
        log.info("Fayldan %d ta zona tiklandi (%s)", len(self._zones), self._storage.path.name)

    async def _flush(self) -> None:
        await self._storage.save(
            {
                "version": SCHEMA_VERSION,
                "symbol": self._s.symbol,
                "buffer_pips": self._s.buffer_pips,
                "zones": [z.to_dict() for z in self._zones],
            }
        )

    # ---------------- CRUD ----------------
    async def add(self, low: float, high: float, note: str = "") -> Zone:
        async with self._lock:
            zone = Zone(id=self._next_id, min_price=low, max_price=high, note=note)
            self._next_id += 1
            self._zones.append(zone)
            self._zones.sort(key=lambda z: z.min_price)
            await self._flush()
            return zone

    async def add_many(self, pairs: Iterable[tuple]) -> List[Zone]:
        created = []
        for low, high in pairs:
            created.append(await self.add(low, high))
        return created

    async def remove(self, zone_id: int) -> Optional[Zone]:
        async with self._lock:
            for i, z in enumerate(self._zones):
                if z.id == zone_id:
                    removed = self._zones.pop(i)
                    await self._flush()
                    return removed
            return None

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._zones)
            self._zones.clear()
            self._next_id = 1
            await self._flush()
            return count

    async def rearm(self, zone_id: Optional[int] = None) -> int:
        """triggered=True bo'lgan zonalarni qayta yoqish."""
        async with self._lock:
            changed = 0
            for z in self._zones:
                if zone_id is not None and z.id != zone_id:
                    continue
                if z.triggered:
                    z.rearm()
                    changed += 1
            if changed:
                await self._flush()
            return changed

    def all(self) -> List[Zone]:
        return list(self._zones)

    def count(self) -> int:
        return len(self._zones)

    # ---------------- monitoring mantig'i ----------------
    async def evaluate(self, price: float, bid: float, ask: float) -> List[AlertEvent]:
        """Joriy narx uchun yangi signallar ro'yxatini qaytaradi va holatni saqlaydi."""
        buf = self._s.buffer_price
        rearm = self._s.rearm_price
        events: List[AlertEvent] = []
        dirty = False

        async with self._lock:
            for zone in self._zones:
                if zone.triggered:
                    # Anti-spam: narx yetarlicha uzoqlashsa, zonani qayta yoqamiz.
                    if zone.outside_rearm(price, buf, rearm):
                        zone.rearm()
                        dirty = True
                        log.info("Zona #%s qayta yoqildi (narx uzoqlashdi: %.2f)", zone.id, price)
                    continue

                if not zone.in_buffer(price, buf):
                    continue

                dist = zone.distance(price)
                zone.mark_triggered(price)
                dirty = True
                events.append(
                    AlertEvent(
                        zone=zone,
                        price=price,
                        bid=bid,
                        ask=ask,
                        distance=dist,
                        distance_pips=self._s.to_pips(dist),
                        side=zone.side(price),
                        symbol=self._s.symbol,
                    )
                )

            if dirty:
                await self._flush()

        return events

    # ---------------- ko'rinish ----------------
    def render_list(self, price: Optional[float] = None) -> str:
        if not self._zones:
            return "\U0001f4ed Hozircha zonalar yo'q.\n\nQo'shish: `/addzone 4291 4296`"

        buf = self._s.buffer_price
        lines = [
            f"\U0001f4ca **{self._s.symbol} zonalari** — {len(self._zones)} ta",
            f"Bufer: {self._s.buffer_pips:.0f} pips (${buf:.2f})",
        ]
        if price is not None:
            lines.append(f"Joriy narx: **{price:.2f}**")
        lines.append("")

        for z in self._zones:
            status = "\U0001f534 SIGNAL BERILGAN" if z.triggered else "\U0001f7e2 kuzatilmoqda"
            head = f"`#{z.id}`  **{z.label}**  — {status}"
            lines.append(head)
            lines.append(
                f"      trigger: {z.min_price - buf:.2f}  \u2194  {z.max_price + buf:.2f}"
            )
            if price is not None and not z.triggered:
                d = z.distance(price)
                if d == 0:
                    lines.append("      \U0001f3af narx zona ichida")
                else:
                    lines.append(
                        f"      masofa: {d:.2f} USD ({self._s.to_pips(d):.0f} pips)"
                    )
            if z.triggered and z.triggered_price is not None:
                lines.append(
                    f"      oxirgi signal: {z.triggered_price:.2f} ({z.hits}-marta)"
                )
            if z.note:
                lines.append(f"      \U0001f4dd {z.note}")
            lines.append("")

        active = sum(1 for z in self._zones if not z.triggered)
        lines.append(f"Faol: {active} | Signal bergan: {len(self._zones) - active}")
        return "\n".join(lines)
