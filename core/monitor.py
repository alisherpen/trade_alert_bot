"""Asosiy monitoring sikli: har POLL_INTERVAL sekundda narxni tekshiradi."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from core.mt5_bridge import ViewLine, ViewState, ViewZone

log = logging.getLogger(__name__)

MAX_BACKOFF = 60.0


class MonitorLoop:
    def __init__(self, feed, zones, dispatcher, tg, settings, bridge=None) -> None:
        self._feed = feed
        self._zones = zones
        self._dispatcher = dispatcher
        self._tg = tg
        self._s = settings
        self._bridge = bridge
        self._fail_streak = 0
        self._last_log = 0.0
        self._last_bridge = 0.0
        self._bridge_sig = ""
        self._ticks = 0

    async def run(self) -> None:
        log.info(
            "Monitoring boshlandi: %s | bufer %.0f pips ($%.2f) | har %.1fs",
            self._feed.symbol, self._s.buffer_pips, self._s.buffer_price,
            self._s.poll_interval,
        )
        while True:
            started = time.monotonic()
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - sikl hech qachon to'xtamasin
                log.exception("Monitoring sikli xatosi")
                self._fail_streak += 1

            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, self._s.poll_interval - elapsed))

    # ------------------------------------------------------------------
    async def _step(self) -> None:
        tick = await self._feed.get_tick()

        if tick is None:
            self._fail_streak += 1
            # 3 ta ketma-ket muvaffaqiyatsizlikdan keyin qayta ulanamiz
            if self._fail_streak % 3 == 0:
                backoff = min(MAX_BACKOFF, 2 ** min(self._fail_streak // 3, 6))
                log.warning(
                    "Narx olinmadi (%d marta). %.0fs dan keyin qayta ulanish...",
                    self._fail_streak, backoff,
                )
                await asyncio.sleep(backoff)
                await self._feed.reconnect()
            return

        if self._fail_streak:
            log.info("Narx oqimi tiklandi (%d ta xatodan keyin).", self._fail_streak)
            self._fail_streak = 0

        self._ticks += 1
        price = tick.price(self._s.price_source)

        # Telegram ulanishini fon rejimida kuzatib boramiz
        if not self._tg.connected:
            await self._tg.ensure_connected()

        events = await self._zones.evaluate(price, tick.bid, tick.ask)
        for event in events:
            self._dispatcher.submit(event)

        await self._publish_chart(price)
        self._debug_log(price)

    async def _publish_chart(self, price: float) -> None:
        """Zonalarni MT5 chartiga chiqaradi (ZoneViewer indikatori o'qiydi)."""
        if self._bridge is None or not self._bridge.enabled:
            return
        now = time.monotonic()
        if now - self._last_bridge < 1.0:
            return

        zones = self._zones.all()
        # Holat o'zgarmagan bo'lsa faylni bezovta qilmaymiz
        sig = "|".join(f"{z.id}:{z.triggered}" for z in zones)
        if sig == self._bridge_sig and now - self._last_bridge < 10.0:
            return
        self._last_bridge = now
        self._bridge_sig = sig

        buf = self._s.buffer_price
        view_zones, view_lines = [], [ViewLine(price, "price", "joriy narx")]
        for z in zones:
            state = "triggered" if z.triggered else "active"
            dist = z.distance(price)
            note = ("ZONA ICHIDA" if dist == 0
                    else f"{self._s.to_pips(dist):.0f} pips")
            view_zones.append(ViewZone(z.id, z.min_price, z.max_price, state, note))
            view_lines.append(ViewLine(z.min_price - buf, "trigger", f"#{z.id} past"))
            view_lines.append(ViewLine(z.max_price + buf, "trigger", f"#{z.id} yuqori"))

        active = sum(1 for z in zones if not z.triggered)
        await self._bridge.publish(ViewState(
            status=f"Kuzatuvda | narx {price:.2f} | faol {active}/{len(zones)}",
            progress=100,
            zones=view_zones,
            lines=view_lines,
        ))

    def _debug_log(self, price: float) -> None:
        """Har 60 soniyada bir marta eng yaqin zonagacha masofani yozadi."""
        now = time.monotonic()
        if now - self._last_log < 60:
            return
        self._last_log = now

        zones = [z for z in self._zones.all() if not z.triggered]
        if not zones:
            log.info("[%s] %.2f | faol zona yo'q", self._feed.symbol, price)
            return
        nearest = min(zones, key=lambda z: z.distance(price))
        d = nearest.distance(price)
        log.info(
            "[%s] %.2f | eng yaqin zona #%s (%s): %.2f USD / %.0f pips | faol: %d",
            self._feed.symbol, price, nearest.id, nearest.label,
            d, self._s.to_pips(d), len(zones),
        )


class Heartbeat:
    """Ixtiyoriy: HEARTBEAT_MINUTES da bir marta 'tirikman' xabari."""

    def __init__(self, tg, feed, zones, settings) -> None:
        self._tg = tg
        self._feed = feed
        self._zones = zones
        self._s = settings

    async def run(self) -> None:
        minutes = self._s.heartbeat_minutes
        if minutes <= 0:
            return
        while True:
            await asyncio.sleep(minutes * 60)
            tick = self._feed.last_tick
            price: Optional[float] = tick.price(self._s.price_source) if tick else None
            price_txt = f"{price:.2f}" if price is not None else "-"
            active = sum(1 for z in self._zones.all() if not z.triggered)
            await self._tg.send_text(
                f"\U0001f49a Bot ishlayapti | {self._feed.symbol}: `{price_txt}` "
                f"| faol zonalar: {active}"
            )
