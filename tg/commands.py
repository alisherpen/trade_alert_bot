"""Userbot buyruqlari: /addzone, /zones, /clear va yordamchilar.

Buyruqlarni qayerdan yozish mumkin:
  * o'z akkauntingizdan istalgan chatda (outgoing xabar) - masalan Saved Messages'da;
  * .env dagi ADMINS ro'yxatidagi foydalanuvchilardan kelgan xabarlarda.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Tuple

from telethon import events

from tg.tts import build_alert_speech

log = logging.getLogger(__name__)

_NUM = r"\d+(?:[.,]\d+)?"
_PAIR_RE = re.compile(rf"({_NUM})\s*(?:[-–—/:]|\.\.|\s)\s*({_NUM})")

# Vergul ikki xil ma'noda kelishi mumkin:
#   "4291,5 4296"          -> kasr belgisi  (vergundan keyin 1-2 raqam va keyin raqam emas)
#   "4291 4296, 4310 4315" -> zonalar ajratuvchisi
_SPLIT_RE = re.compile(r";|,(?!\d{1,2}(?:\D|$))")

HELP_TEXT = """\U0001f4d8 **XAUUSD Zone Alert Bot**

**Zonalar**
`/addzone 4291 4296` — zona qo'shish
`/addzone 4291-4296, 4310 4315` — bir nechta zona
`/zones` — barcha zonalar va masofalar
`/delzone 3` — #3 zonani o'chirish
`/clear` — hammasini o'chirish
`/rearm` yoki `/rearm 3` — signal bergan zonani qayta yoqish

**Holat**
`/price` — joriy Bid/Ask
`/status` — bot, MT5 va Telegram holati
`/testcall` — qo'ng'iroqni sinab ko'rish
`/testalert` — to'liq alertni sinash (qo'ng'iroq + ovoz + rasm)
`/help` — shu yordam"""


def _f(raw: str) -> float:
    return float(raw.replace(",", "."))


def parse_zone_args(text: str) -> Tuple[List[Tuple[float, float]], List[str]]:
    """'4291 4296, 4310-4315' -> [(4291,4296),(4310,4315)]."""
    pairs: List[Tuple[float, float]] = []
    errors: List[str] = []
    for chunk in _SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _PAIR_RE.search(chunk)
        if not m:
            errors.append(chunk)
            continue
        low, high = _f(m.group(1)), _f(m.group(2))
        if low <= 0 or high <= 0:
            errors.append(chunk)
            continue
        pairs.append((min(low, high), max(low, high)))
    return pairs, errors


class CommandRouter:
    def __init__(self, tg, zones, feed, settings, dispatcher) -> None:
        self._tg = tg
        self._zones = zones
        self._feed = feed
        self._s = settings
        self._dispatcher = dispatcher
        self._admin_ids: set = set()

    # ------------------------------------------------------------------
    async def register(self) -> None:
        """Handlerlarni Telethon'ga ulaydi."""
        for admin in self._s.admins:
            try:
                entity = await self._tg.client.get_entity(admin)
                self._admin_ids.add(entity.id)
            except (ValueError, TypeError) as exc:
                log.warning("ADMINS: '%s' topilmadi (%s)", admin, exc)

        handlers = (
            (r"^/addzone(?:@\w+)?\s+(.+)$", self.cmd_addzone),
            (r"^/zones?(?:@\w+)?\s*$", self.cmd_zones),
            (r"^/delzone(?:@\w+)?\s+(\d+)\s*$", self.cmd_delzone),
            (r"^/clear(?:@\w+)?\s*$", self.cmd_clear),
            (r"^/rearm(?:@\w+)?\s*(\d+)?\s*$", self.cmd_rearm),
            (r"^/price(?:@\w+)?\s*$", self.cmd_price),
            (r"^/status(?:@\w+)?\s*$", self.cmd_status),
            (r"^/testcall(?:@\w+)?\s*$", self.cmd_testcall),
            (r"^/testalert(?:@\w+)?\s*$", self.cmd_testalert),
            (r"^/(?:help|start)(?:@\w+)?\s*$", self.cmd_help),
        )
        for pattern, fn in handlers:
            self._tg.client.add_event_handler(
                self._guard(fn),
                events.NewMessage(pattern=re.compile(pattern, re.IGNORECASE)),
            )
        log.info("Buyruqlar ro'yxatdan o'tdi (%d ta)", len(handlers))

    def _guard(self, fn: Callable):
        """Faqat o'zingiz yoki ADMINS buyruq bera olsin."""
        async def wrapper(event):
            if not (event.out or event.sender_id in self._admin_ids):
                return
            try:
                await fn(event)
            except Exception as exc:  # noqa: BLE001 - handler hech qachon botni yiqitmasin
                log.exception("Buyruq xatosi")
                await event.respond(f"⚠️ Xato: `{exc}`")
        return wrapper

    # ------------------------------------------------------------------
    async def cmd_addzone(self, event) -> None:
        pairs, errors = parse_zone_args(event.pattern_match.group(1))
        if not pairs:
            await event.respond(
                "⚠️ Format noto'g'ri.\nMisol: `/addzone 4291 4296`"
            )
            return

        buf = self._s.buffer_price
        created = await self._zones.add_many(pairs)
        price = self._current_price()

        lines = [f"✅ **{len(created)} ta zona qo'shildi**\n"]
        for z in created:
            lines.append(f"`#{z.id}` **{z.label}**")
            lines.append(f"      trigger: {z.min_price - buf:.2f} ↔ {z.max_price + buf:.2f}")
            if price is not None:
                d = z.distance(price)
                lines.append(
                    "      \U0001f3af narx hozir zona ichida!" if d == 0
                    else f"      masofa: {d:.2f} USD ({self._s.to_pips(d):.0f} pips)"
                )
        if errors:
            lines.append("\n⚠️ Tushunilmadi: " + ", ".join(f"`{e}`" for e in errors))
        lines.append(f"\nJami: {self._zones.count()} ta zona kuzatilmoqda.")
        await event.respond("\n".join(lines))

    async def cmd_zones(self, event) -> None:
        await event.respond(self._zones.render_list(self._current_price()))

    async def cmd_delzone(self, event) -> None:
        zone_id = int(event.pattern_match.group(1))
        removed = await self._zones.remove(zone_id)
        if removed:
            await event.respond(
                f"\U0001f5d1 Zona `#{zone_id}` ({removed.label}) o'chirildi. "
                f"Qoldi: {self._zones.count()} ta."
            )
        else:
            await event.respond(f"⚠️ `#{zone_id}` topilmadi.")

    async def cmd_clear(self, event) -> None:
        count = await self._zones.clear()
        await event.respond(f"\U0001f9f9 {count} ta zona o'chirildi. Ro'yxat bo'sh.")

    async def cmd_rearm(self, event) -> None:
        raw = event.pattern_match.group(1)
        zone_id = int(raw) if raw else None
        changed = await self._zones.rearm(zone_id)
        if changed:
            target = f"`#{zone_id}`" if zone_id else "Barcha zonalar"
            await event.respond(f"\U0001f504 {target} qayta yoqildi ({changed} ta).")
        else:
            await event.respond("ℹ️ Qayta yoqiladigan zona yo'q.")

    async def cmd_price(self, event) -> None:
        tick = await self._feed.get_tick()
        if tick is None:
            await event.respond("⚠️ MT5'dan narx olinmadi. `/status` ni tekshiring.")
            return
        await event.respond(
            f"\U0001f4b0 **{tick.symbol}**\n"
            f"Bid: `{tick.bid:.2f}`\n"
            f"Ask: `{tick.ask:.2f}`\n"
            f"Spread: `{tick.spread:.2f}` ({self._s.to_pips(tick.spread):.0f} pips)\n"
            f"Kuzatilayotgan narx ({self._s.price_source}): `{tick.price(self._s.price_source):.2f}`"
        )

    async def cmd_status(self, event) -> None:
        tick = self._feed.last_tick
        zones = self._zones.all()
        active = sum(1 for z in zones if not z.triggered)
        mt5_state = "ulangan ✅" if self._feed.connected else "uzilgan ❌"
        tg_state = "ulangan ✅" if self._tg.connected else "uzilgan ❌"
        price_txt = (
            f"{tick.price(self._s.price_source):.2f}" if tick else "-"
        )
        call_state = "yoqilgan" if self._s.call_enabled else "o'chirilgan"

        await event.respond(
            "\U0001f9ed **Bot holati**\n\n"
            f"MT5: {mt5_state} (qayta ulanish: {self._feed.reconnects})\n"
            f"Telegram: {tg_state}\n"
            f"Simvol: `{self._feed.symbol}`\n"
            f"Oxirgi narx ({self._s.price_source}): `{price_txt}`\n\n"
            f"Zonalar: **{len(zones)}** ta "
            f"(faol {active}, signal bergan {len(zones) - active})\n"
            f"Bufer: {self._s.buffer_pips:.0f} pips (${self._s.buffer_price:.2f})\n"
            f"Qayta yoqish: {self._s.rearm_pips:.0f} pips\n"
            f"Tekshiruv: har {self._s.poll_interval:.1f} soniyada\n\n"
            f"Qo'ng'iroq: {call_state} → `{self._s.alert_target}`\n"
            f"Rejim: {self._tg.call_engine}\n"
            f"TTS: {self._tg.tts.engine_name}\n"
            f"Chart: {self._s.chart_timeframe}, {self._s.chart_bars} svecha"
        )

    async def cmd_testcall(self, event) -> None:
        await event.respond(
            f"\U0001f4de `{self._s.alert_target}` ga test qo'ng'iroq...\n"
            f"Rejim: {self._tg.call_engine}"
        )
        # Qo'ng'iroq ichida gapirishi uchun TTS ovozini oldindan tayyorlaymiz
        tick = self._feed.last_tick
        price = tick.price(self._s.price_source) if tick else 4300.0
        clip = await self._tg.tts.synthesize(build_alert_speech(price, 60, "below"))
        result = await self._tg.place_call(audio=clip.path if clip else None)
        await event.respond(result.summary)

    async def cmd_testalert(self, event) -> None:
        tick = self._feed.last_tick
        price = tick.price(self._s.price_source) if tick else 4300.00
        await event.respond("\U0001f9ea Test alert yuborilmoqda...")
        await self._dispatcher.send_test(price)

    async def cmd_help(self, event) -> None:
        await event.respond(HELP_TEXT)

    # ------------------------------------------------------------------
    def _current_price(self) -> Optional[float]:
        tick = self._feed.last_tick
        return tick.price(self._s.price_source) if tick else None
