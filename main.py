"""XAUUSD Zone Alert Bot — kirish nuqtasi.

Ishga tushirish:
    python main.py

To'xtatish: Ctrl+C
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from config import BASE_DIR, load_settings
from core.alerting import AlertDispatcher
from core.chart import ChartRenderer
from core.monitor import Heartbeat, MonitorLoop
from core.mt5_bridge import Mt5Bridge
from core.price_feed import Mt5Error, Mt5PriceFeed
from core.storage import JsonStorage
from core.zone_manager import ZoneManager
from tg.client import TelegramService
from tg.commands import CommandRouter

log = logging.getLogger("trade_alert")

BANNER = r"""
  __  __   _   _   _ _   _ ___ ___     _   _    ___ ___ _____
  \ \/ /  /_\ | | | | | | / __|   \   /_\ | |  | __| _ \_   _|
   >  <  / _ \| |_| | |_| \__ \ |) | / _ \| |__| _||   / | |
  /_/\_\/_/ \_\\___/ \___/|___/___/ /_/ \_\____|___|_|_\ |_|
"""


def setup_logging(level: str) -> None:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(BASE_DIR / "bot.log", encoding="utf-8"),
        ],
    )
    # Telethon juda gapiruvchan
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


async def run() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    print(BANNER)

    # ---- 1. Zonalar (fayldan tiklash) ----
    storage = JsonStorage(settings.zones_file)
    zones = ZoneManager(storage, settings)
    await zones.load()

    # ---- 2. Telegram ----
    tg = TelegramService(settings)
    await tg.start()

    # ---- 3. MT5 ----
    feed = Mt5PriceFeed(settings)
    try:
        await feed.start()
    except Mt5Error as exc:
        log.error("%s", exc)
        await tg.send_text(f"❌ MT5 ishga tushmadi: {exc}")
        await tg.stop()
        return

    if not feed.connected:
        msg = (
            "❌ MT5 ga ulanib bo'lmadi. Tekshiring:\n"
            "1. MetaTrader 5 terminali ochiqmi?\n"
            "2. .env dagi MT5_LOGIN / MT5_PASSWORD / MT5_SERVER to'g'rimi?\n"
            "3. Terminalda Algo Trading yoqilganmi?"
        )
        log.error(msg)
        await tg.send_text(msg)
        await tg.stop()
        await feed.close()
        return

    # ---- 4. MT5 chart vizual ko'prigi ----
    bridge = await Mt5Bridge.from_feed(feed, enabled=settings.bridge_enabled)

    # ---- 5. Chart rasmi + alert dispatcher ----
    chart = ChartRenderer(feed, settings)
    dispatcher = AlertDispatcher(tg, chart, settings)
    await dispatcher.start()

    # ---- 6. Buyruqlar ----
    router = CommandRouter(tg, zones, feed, settings, dispatcher)
    await router.register()

    # ---- 7. Ishga tushdi xabari ----
    tick = await feed.get_tick()
    price_txt = f"{tick.price(settings.price_source):.2f}" if tick else "-"
    await tg.send_text(
        "\U0001f7e2 **XAUUSD Zone Alert Bot ishga tushdi**\n\n"
        f"Simvol: `{feed.symbol}`  |  Narx: `{price_txt}`\n"
        f"Zonalar: **{zones.count()}** ta (fayldan tiklandi)\n"
        f"Bufer: {settings.buffer_pips:.0f} pips (${settings.buffer_price:.2f})\n"
        f"Qo'ng'iroq: `{settings.alert_target}` — {tg.call_engine}\n"
        f"TTS: {tg.tts.engine_name}\n"
        f"Chart: {settings.chart_timeframe}, {settings.chart_bars} svecha\n\n"
        "Buyruqlar uchun `/help`"
    )

    # ---- 8. Sikllar ----
    monitor = MonitorLoop(feed, zones, dispatcher, tg, settings, bridge)
    heartbeat = Heartbeat(tg, feed, zones, settings)

    tasks = [
        asyncio.create_task(monitor.run(), name="monitor"),
        asyncio.create_task(tg.client.run_until_disconnected(), name="telegram"),
    ]
    if settings.heartbeat_minutes > 0:
        tasks.append(asyncio.create_task(heartbeat.run(), name="heartbeat"))

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc:
                log.error("'%s' taski xato bilan tugadi: %s", task.get_name(), exc)
    except asyncio.CancelledError:
        pass
    finally:
        log.info("To'xtatilmoqda...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispatcher.stop()
        await tg.stop_calls()
        await feed.close()
        await tg.stop()
        log.info("Bot to'xtadi. Zonalar saqlandi: %s", settings.zones_file.name)


def main() -> None:
    # Windows'da standart ProactorEventLoop qoldiriladi: Selector policy
    # subprocess (ffmpeg) chaqiruvlarini buzadi.
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nCtrl+C — to'xtatildi.")


if __name__ == "__main__":
    main()
