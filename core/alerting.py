"""Alert yetkazib berish: M15 chart + qo'ng'iroq ichida ovozli ogohlantirish.

Signallar navbat (queue) orqali ketma-ket qayta ishlanadi, shunda bir nechta zona
bir vaqtda ishga tushsa ham qo'ng'iroqlar ustma-ust tushmaydi.

Yetkazish tartibi:
  1. M15 chart rasmi + batafsil matn  ->  ALERT_TARGET ga
  2. Qo'ng'iroq: ko'tarilsa TTS matni QO'NG'IROQ ICHIDA eshitiladi
  3. Agar qo'ng'iroqda gapirish imkoni bo'lmasa (ffmpeg yo'q) -> voice message
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from core.models import AlertEvent
from tg.tts import build_alert_speech

log = logging.getLogger(__name__)


class AlertDispatcher:
    def __init__(self, tg, chart, settings) -> None:
        self._tg = tg
        self._chart = chart
        self._s = settings
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._worker: Optional[asyncio.Task] = None

    @property
    def call_engine(self) -> str:
        return self._tg.call_engine

    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="alert-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    def submit(self, event: AlertEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("Alert navbati to'lib ketdi - zona #%s o'tkazib yuborildi", event.zone.id)

    # ------------------------------------------------------------------
    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._deliver(event)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker hech qachon o'lmasin
                log.exception("Alert yetkazishda xato (zona #%s)", event.zone.id)
            finally:
                self._queue.task_done()

    async def _deliver(self, event: AlertEvent) -> None:
        z = event.zone
        log.warning(
            "\U0001f6a8 SIGNAL: zona #%s [%s] | narx %.2f | masofa %.0f pips (%s)",
            z.id, z.label, event.price, event.distance_pips, event.side,
        )

        # --- 1. M15 chart + matn ---
        caption = self._build_message(event)
        chart = await self._chart.render(z, event.price, event.side)
        if chart is not None:
            await self._tg.send_photo(chart, caption)
        else:
            await self._tg.send_text(caption)

        # --- 2. TTS ovozini tayyorlash ---
        speech = build_alert_speech(event.price, event.distance_pips, event.side)
        clip = await self._tg.tts.synthesize(speech)

        # --- 3. Qo'ng'iroq (ko'tarilsa ichida gapiradi) ---
        if not self._s.call_enabled:
            return

        audio = clip.path if clip is not None else None
        result = await self._tg.place_call(audio=audio)
        log.info("Qo'ng'iroq natijasi: %s [%s]", result.summary, result.engine)

        # --- 4. Qo'ng'iroqda gapirilmagan bo'lsa - voice message zaxirasi ---
        if clip is not None and not result.spoke:
            await self._tg.send_voice(clip, "\U0001f50a Ovozli ogohlantirish")

        if not result.ok:
            await self._tg.send_text(result.summary)

    # ------------------------------------------------------------------
    def _build_message(self, event: AlertEvent) -> str:
        z = event.zone
        buf = self._s.buffer_price
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        dist_txt = (
            "**ZONA ICHIDA**" if event.side == "inside"
            else f"**{event.distance_pips:.0f} pips** (${event.distance:.2f})"
        )
        return (
            f"\U0001f6a8 **ZONA SIGNALI — {event.symbol}** {event.arrow}\n"
            f"{'=' * 28}\n"
            f"Narx: **{event.price:.2f}**\n"
            f"Bid: `{event.bid:.2f}`  |  Ask: `{event.ask:.2f}`\n\n"
            f"Zona `#{z.id}`: **{z.label}**\n"
            f"Trigger diapazoni: `{z.min_price - buf:.2f}` ↔ `{z.max_price + buf:.2f}`\n"
            f"Masofa: {dist_txt}\n"
            f"Holat: {event.direction_text}\n\n"
            f"\U0001f550 {now}\n"
            f"ℹ️ Bu zona endi `triggered` — qayta signal bermaydi.\n"
            f"Qayta yoqish: `/rearm {z.id}`"
        )

    # ------------------------------------------------------------------
    async def send_test(self, price: float) -> None:
        """/testalert uchun: to'liq alert zanjirini sinab ko'radi."""
        from core.models import Zone

        fake = Zone(id=0, min_price=round(price + 4, 2), max_price=round(price + 9, 2),
                    note="TEST")
        event = AlertEvent(
            zone=fake,
            price=price,
            bid=price,
            ask=price + 0.2,
            distance=4.0,
            distance_pips=40.0,
            side="below",
            symbol=self._s.symbol,
        )
        await self._deliver(event)
