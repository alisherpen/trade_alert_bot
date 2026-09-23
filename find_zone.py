"""Zona qidiruvchi — ishlash jarayonini MT5 chartida REAL VAQTDA ko'rsatadi.

    python find_zone.py                 # H4, standart sozlamalar
    python find_zone.py --tf H1 --bars 400
    python find_zone.py --speed 0.6     # sekinroq: har qadam ko'rinib tursin

Ishga tushirgach MT5 ni oching (XAUUSD charti, ZoneViewer indikatori ulangan) —
bot har bir qadamni chartda chizib boradi: avval swing nuqtalar, keyin nomzod
zonalar, oxirida tasdiqlangan zonalar.

=====================================================================
DIQQAT: bu yerdagi ALGORITM VAQTINCHALIK (demo).
Siz o'z qoidalaringizni aytganingizda `detect_zones()` funksiyasi
to'liq siz aytgan mantiqqa almashtiriladi. Qolgan hamma narsa —
vizualizatsiya, ko'prik, tasdiqlash — o'zgarmasdan ishlayveradi.
=====================================================================
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from config import load_settings
from core.mt5_bridge import Mt5Bridge, ViewLine, ViewMark, ViewState, ViewZone
from core.price_feed import Mt5PriceFeed
from core.storage import JsonStorage
from core.zone_manager import ZoneManager

log = logging.getLogger("find_zone")


# ======================================================================
#  Topilgan nomzod
# ======================================================================
@dataclass
class Candidate:
    id: int
    min_price: float
    max_price: float
    pivot_price: float
    pivot_ts: int
    kind: str          # high | low
    touches: int = 1
    accepted: bool = False
    reason: str = ""

    @property
    def label(self) -> str:
        return f"{self.min_price:.2f} - {self.max_price:.2f}"


# ======================================================================
#  Konsol chiqishi
# ======================================================================
class Console:
    def __init__(self, speed: float) -> None:
        self.speed = speed
        self.step = 0

    async def say(self, text: str, indent: int = 0) -> None:
        print("   " * indent + text, flush=True)
        if self.speed > 0:
            await asyncio.sleep(self.speed)

    async def stage(self, title: str) -> None:
        self.step += 1
        print(f"\n\033[96m[{self.step}] {title}\033[0m", flush=True)
        if self.speed > 0:
            await asyncio.sleep(self.speed)


# ======================================================================
#  ALGORITM — bu qism siz aytgan qoidalar bilan almashtiriladi
# ======================================================================
async def detect_zones(rates, settings, bridge, con, args) -> List[Candidate]:
    """Demo algoritm: fraktal swing high/low -> nomzod zona -> teginish filtri."""
    half = args.pivot
    width = args.width * settings.pip_size      # zona yarim kengligi (USD)
    highs = [float(r["high"]) for r in rates]
    lows = [float(r["low"]) for r in rates]
    times = [int(r["time"]) for r in rates]

    # ---------- 1-bosqich: swing nuqtalarni topish ----------
    await con.stage(f"Swing nuqtalar qidirilmoqda (chap/o'ngda {half} svecha)")
    marks: List[ViewMark] = []
    pivots = []

    for i in range(half, len(rates) - half):
        window_h = highs[i - half: i + half + 1]
        window_l = lows[i - half: i + half + 1]

        if highs[i] == max(window_h):
            pivots.append((i, highs[i], "high"))
            marks.append(ViewMark(times[i], highs[i], "high", ""))
        elif lows[i] == min(window_l):
            pivots.append((i, lows[i], "low"))
            marks.append(ViewMark(times[i], lows[i], "low", ""))

        # Har 20 svechada chartni yangilaymiz — jarayon ko'rinib tursin
        if i % 20 == 0 or i == len(rates) - half - 1:
            progress = int((i - half) / max(1, len(rates) - 2 * half) * 40)
            await bridge.publish(ViewState(
                status=f"Swing qidirilmoqda... {i}/{len(rates)} svecha",
                progress=progress,
                marks=list(marks),
            ))
            if args.speed > 0:
                await asyncio.sleep(args.speed * 0.15)

    await con.say(f"topildi: {len(pivots)} ta swing nuqta "
                  f"({sum(1 for p in pivots if p[2] == 'high')} high / "
                  f"{sum(1 for p in pivots if p[2] == 'low')} low)", 1)

    # ---------- 2-bosqich: nomzod zonalar ----------
    await con.stage("Har bir swing atrofida nomzod zona quriladi")
    candidates: List[Candidate] = []
    for n, (idx, price, kind) in enumerate(pivots, start=1):
        cand = Candidate(
            id=n,
            min_price=round(price - width, 2),
            max_price=round(price + width, 2),
            pivot_price=price,
            pivot_ts=times[idx],
            kind=kind,
        )
        candidates.append(cand)

        await bridge.publish(ViewState(
            status=f"Nomzod #{n}: {cand.label}",
            progress=40 + int(n / max(1, len(pivots)) * 25),
            zones=[ViewZone(c.id, c.min_price, c.max_price, "candidate", c.kind)
                   for c in candidates],
            marks=marks,
        ))
        await con.say(f"nomzod #{n}: {cand.label}  ({kind})", 1)

    # ---------- 3-bosqich: teginishlar soni ----------
    await con.stage(f"Teginishlar sanalmoqda (kamida {args.touches} ta kerak)")
    for n, cand in enumerate(candidates, start=1):
        touches = 0
        for i in range(len(rates)):
            if lows[i] <= cand.max_price and highs[i] >= cand.min_price:
                touches += 1
        cand.touches = touches
        cand.accepted = touches >= args.touches
        cand.reason = (f"{touches} teginish" if cand.accepted
                       else f"faqat {touches} teginish - rad etildi")

        await bridge.publish(ViewState(
            status=f"Tekshirilmoqda #{n}/{len(candidates)}: {cand.reason}",
            progress=65 + int(n / max(1, len(candidates)) * 30),
            zones=[ViewZone(c.id, c.min_price, c.max_price,
                            "active" if c.accepted else
                            ("rejected" if c.reason else "candidate"),
                            c.reason)
                   for c in candidates],
            marks=marks,
        ))
        mark = "\033[92mQABUL\033[0m" if cand.accepted else "\033[90mrad  \033[0m"
        await con.say(f"{mark} #{n} {cand.label}  -> {cand.reason}", 1)

    # ---------- 4-bosqich: bir-biriga kirib ketganlarini birlashtirish ----------
    await con.stage("Ustma-ust tushgan zonalar birlashtirilmoqda")
    accepted = sorted((c for c in candidates if c.accepted),
                      key=lambda c: c.min_price)
    merged: List[Candidate] = []
    for cand in accepted:
        if merged and cand.min_price <= merged[-1].max_price:
            prev = merged[-1]
            prev.max_price = max(prev.max_price, cand.max_price)
            prev.touches = max(prev.touches, cand.touches)
            prev.reason = f"{prev.touches} teginish (birlashtirildi)"
            await con.say(f"#{cand.id} -> #{prev.id} ga qo'shildi "
                          f"({prev.label})", 1)
        else:
            merged.append(cand)

    for i, c in enumerate(merged, start=1):
        c.id = i
    await con.say(f"yakuniy: {len(merged)} ta zona", 1)
    return merged


# ======================================================================
async def run(args) -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)-7s | %(message)s")
    settings = load_settings()
    con = Console(args.speed)

    print("\033[95m" + "=" * 62)
    print("  ZONA QIDIRUVI — jarayonni MT5 chartida kuzatib turing")
    print("=" * 62 + "\033[0m")

    # ---- MT5 ----
    feed = Mt5PriceFeed(settings)
    await feed.start()
    if not feed.connected:
        print("\033[91mMT5 ga ulanib bo'lmadi. Terminal ochiqmi?\033[0m")
        return

    bridge = await Mt5Bridge.from_feed(feed)
    if not bridge.enabled:
        print("\033[93mOgohlantirish: vizual ko'prik o'chiq, "
              "faqat konsolda ko'rinadi.\033[0m")
    else:
        print(f"Vizual fayl: {bridge.path}")
        print("MT5 da XAUUSD chartiga \033[96mZoneViewer\033[0m indikatorini ulang.\n")

    await bridge.publish(ViewState(status="Ma'lumot yuklanmoqda...", progress=2))

    tick = await feed.get_tick()
    price = tick.price(settings.price_source)
    rates = await feed.get_rates(args.tf, args.bars)
    if rates is None:
        print("\033[91mSvechalar olinmadi.\033[0m")
        await feed.close()
        return

    first = datetime.fromtimestamp(int(rates[0]["time"])).strftime("%d.%m %H:%M")
    last = datetime.fromtimestamp(int(rates[-1]["time"])).strftime("%d.%m %H:%M")
    print(f"Simvol : {feed.symbol}   Narx: {price:.2f}")
    print(f"Oraliq : {args.tf}, {len(rates)} svecha   ({first} -> {last})")

    # ---- Qidiruv ----
    zones = await detect_zones(rates, settings, bridge, con, args)

    # ---- Natija ----
    await con.stage("NATIJA")
    if not zones:
        print("   Zona topilmadi. --touches yoki --width ni o'zgartirib ko'ring.")
        await bridge.publish(ViewState(status="Zona topilmadi", progress=100))
        await feed.close()
        return

    buf = settings.buffer_price
    for z in zones:
        dist = 0.0 if z.min_price <= price <= z.max_price else min(
            abs(z.min_price - price), abs(z.max_price - price))
        print(f"   \033[92m#{z.id}\033[0m  {z.label}   "
              f"{z.touches} teginish   masofa: {dist:.2f} USD "
              f"({settings.to_pips(dist):.0f} pips)")

    await bridge.publish(ViewState(
        status=f"TAYYOR: {len(zones)} ta zona topildi",
        progress=100,
        zones=[ViewZone(z.id, z.min_price, z.max_price, "active", z.reason)
               for z in zones],
        lines=[ViewLine(price, "price", "joriy narx")],
    ))

    # ---- Tasdiqlash ----
    print()
    print("Bu zonalarni kuzatuvga qo'shaymizmi?")
    print("  hammasi        - barchasini qo'shish")
    print("  1 3 5          - faqat tanlanganlarni")
    print("  yo'q / Enter   - hech narsa qo'shmaslik")
    try:
        answer = input("\n> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    chosen: List[Candidate] = []
    if answer in {"hammasi", "all", "ha", "yes", "*"}:
        chosen = zones
    elif answer and answer not in {"yo'q", "yoq", "no", "n"}:
        wanted = {int(x) for x in answer.replace(",", " ").split() if x.isdigit()}
        chosen = [z for z in zones if z.id in wanted]

    if not chosen:
        print("Hech narsa qo'shilmadi.")
        await feed.close()
        return

    manager = ZoneManager(JsonStorage(settings.zones_file), settings)
    await manager.load()
    for z in chosen:
        created = await manager.add(z.min_price, z.max_price,
                                    note=f"auto {args.tf} ({z.touches} teginish)")
        print(f"  \033[92m+\033[0m zona #{created.id}  {created.label}")

    print(f"\n{len(chosen)} ta zona \033[96mzones.json\033[0m ga saqlandi. "
          f"Jami: {manager.count()} ta.")
    print("Endi `python main.py` ishga tushiring — kuzatuv boshlanadi.")

    await feed.close()


# ======================================================================
def main() -> None:
    p = argparse.ArgumentParser(
        description="XAUUSD zonalarini topish (jarayon MT5 chartida ko'rinadi)")
    p.add_argument("--tf", default="H4",
                   help="Timeframe: M15 M30 H1 H4 D1 (default: H4)")
    p.add_argument("--bars", type=int, default=300,
                   help="Nechta svecha tahlil qilinsin (default: 300)")
    p.add_argument("--pivot", type=int, default=5,
                   help="Swing uchun chap/o'ngdagi svechalar soni (default: 5)")
    p.add_argument("--width", type=float, default=15,
                   help="Zona yarim kengligi, pips (default: 15)")
    p.add_argument("--touches", type=int, default=2,
                   help="Kamida nechta teginish kerak (default: 2)")
    p.add_argument("--speed", type=float, default=0.25,
                   help="Har qadam orasidagi pauza, soniya. 0 = tez (default: 0.25)")
    args = p.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")


if __name__ == "__main__":
    main()
