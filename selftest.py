"""Offline sinov: zona mantiqi, persistence, chart, TTS va qo'ng'iroq.

MT5 yoki Telegram ulanishisiz ishlaydi:
    python selftest.py
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from config import load_settings
from core.storage import JsonStorage
from core.zone_manager import ZoneManager
from tg.tts import TtsEngine, build_alert_speech

OK, FAIL = "  [OK]  ", "  [FAIL]"
_failures = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{OK if condition else FAIL} {name}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        _failures.append(name)


async def test_zone_logic(settings) -> None:
    print("\n--- 1. Zona mantiqi (bufer 60 pips = $6.00) ---")
    tmp = Path(tempfile.mkdtemp()) / "zones.json"
    zones = ZoneManager(JsonStorage(tmp), settings)
    await zones.load()

    z = await zones.add(4291, 4296)
    check("Zona qo'shildi", z.id == 1 and z.min_price == 4291.0)
    check("Trigger chegaralari 4285.00 / 4302.00",
          abs((z.min_price - settings.buffer_price) - 4285.0) < 1e-9
          and abs((z.max_price + settings.buffer_price) - 4302.0) < 1e-9)

    # Uzoq narx -> signal yo'q
    ev = await zones.evaluate(4320.0, 4320.0, 4320.2)
    check("4320.00 -> signal yo'q", ev == [], f"{len(ev)} ta")

    # Yuqoridan bufer chegarasi
    ev = await zones.evaluate(4302.00, 4302.0, 4302.2)
    check("4302.00 -> SIGNAL (yuqoridan)", len(ev) == 1 and ev[0].side == "above",
          f"{ev[0].distance_pips:.0f} pips" if ev else "yo'q")

    # Anti-spam
    ev = await zones.evaluate(4301.00, 4301.0, 4301.2)
    check("Takroriy signal bermaydi (anti-spam)", ev == [])
    check("triggered=True saqlandi", zones.all()[0].triggered)

    # Qayta yoqish (REARM_PIPS uzoqlashgach)
    far = 4296 + settings.buffer_price + settings.rearm_price + 1
    await zones.evaluate(far, far, far + 0.2)
    check("Narx uzoqlashgach qayta yoqildi", not zones.all()[0].triggered, f"{far:.2f}")

    # Pastdan kirish
    ev = await zones.evaluate(4285.00, 4285.0, 4285.2)
    check("4285.00 -> SIGNAL (pastdan)", len(ev) == 1 and ev[0].side == "below",
          f"{ev[0].distance_pips:.0f} pips" if ev else "yo'q")
    if ev:
        check("Masofa = 60 pips", abs(ev[0].distance_pips - 60.0) < 0.001)

    # Zona ichi
    await zones.rearm()
    ev = await zones.evaluate(4293.50, 4293.5, 4293.7)
    check("Zona ichida -> SIGNAL, masofa 0", len(ev) == 1 and ev[0].side == "inside")


async def test_persistence(settings) -> None:
    print("\n--- 2. Persistence (restart simulyatsiyasi) ---")
    tmp = Path(tempfile.mkdtemp()) / "zones.json"

    first = ZoneManager(JsonStorage(tmp), settings)
    await first.load()
    await first.add(4291, 4296)
    await first.add(4310, 4315)
    await first.evaluate(4302.0, 4302.0, 4302.2)   # #1 triggered bo'ladi
    check("Fayl yaratildi", tmp.exists(), str(tmp))

    second = ZoneManager(JsonStorage(tmp), settings)   # "restart"
    await second.load()
    check("Restartdan keyin 2 ta zona tiklandi", second.count() == 2)
    check("triggered holati ham saqlandi", second.all()[0].triggered)
    check("Yangi ID kolliziya qilmaydi", (await second.add(4400, 4405)).id == 3)


async def test_parsing() -> None:
    print("\n--- 3. Buyruq parseri ---")
    from tg.commands import parse_zone_args

    cases = [
        ("4291 4296", [(4291.0, 4296.0)]),
        ("4291-4296", [(4291.0, 4296.0)]),
        ("4296 4291", [(4291.0, 4296.0)]),          # teskari -> tartiblanadi
        ("4291.5 4296.75", [(4291.5, 4296.75)]),
        ("4291,5 4296", [(4291.5, 4296.0)]),        # vergulli kasr
        ("4291 4296, 4310-4315", [(4291.0, 4296.0), (4310.0, 4315.0)]),
    ]
    for raw, expected in cases:
        got, _ = parse_zone_args(raw)
        check(f"'{raw}'", got == expected, str(got))

    _, errors = parse_zone_args("salom")
    check("Noto'g'ri kiritish xato sifatida qaytadi", errors == ["salom"])


async def test_chart(settings) -> None:
    print(f"\n--- 4. {settings.chart_timeframe} chart (MT5 kerak) ---")
    from core.chart import ChartRenderer
    from core.models import Zone
    from core.price_feed import Mt5PriceFeed

    feed = Mt5PriceFeed(settings)
    try:
        await feed.start()
    except Exception as exc:  # noqa: BLE001
        print(f"  [SKIP] MT5 ishga tushmadi: {exc}")
        return
    if not feed.connected:
        print("  [SKIP] MT5 ulanmadi - chart testi o'tkazib yuborildi")
        return

    tick = await feed.get_tick()
    price = tick.price(settings.price_source)
    zone = Zone(id=99, min_price=round(price + 4, 2), max_price=round(price + 9, 2))
    path = await ChartRenderer(feed, settings).render(zone, price, "below")
    ok = path is not None and path.exists() and path.stat().st_size > 10_000
    check("Chart generatsiya qilindi", ok,
          f"{path.name} ({path.stat().st_size // 1024} KB), narx {price:.2f}" if ok else "-")
    await feed.close()


async def test_call_engine(settings) -> None:
    print("\n--- 6. Qo'ng'iroq dvigateli ---")
    from tg.voice_call import ffmpeg_ready

    try:
        import pytgcalls  # noqa: F401
        has_pytg = True
    except ImportError:
        has_pytg = False

    check("py-tgcalls o'rnatilgan", has_pytg)
    # ffmpeg yo'qligi kod xatosi emas - muhit talabi, shuning uchun ogohlantirish.
    if ffmpeg_ready():
        print(f"{OK} ffmpeg + ffprobe topildi  -> qo'ng'iroq ICHIDA gapiradi")
    else:
        print("  [WARN] ffmpeg/ffprobe topilmadi")
        print("         Qo'ng'iroq ZAXIRA rejimda ishlaydi: jiringlaydi, lekin")
        print("         ichida gapirmaydi (ovoz alohida voice-message bo'lib keladi).")
        print("         Yechim:  winget install Gyan.FFmpeg")


async def test_tts(settings) -> None:
    print("\n--- 5. TTS (internet talab qiladi) ---")
    text = build_alert_speech(4285.00, 60, "below")
    print(f"      Matn: {text}")
    engine = TtsEngine(settings)
    check("TTS dvigateli mavjud", engine.available, engine.engine_name)
    if not engine.available:
        return
    clip = await engine.synthesize(text)
    if clip is None:
        print("  [SKIP] Ovoz yaratilmadi (internet yo'q yoki edge-tts xatosi)")
        return
    check("Ovoz fayli yaratildi", clip.path.exists(),
          f"{clip.path.name}, {clip.path.stat().st_size // 1024} KB, "
          f"voice_note={clip.is_voice_note}")


async def main() -> None:
    settings = load_settings()
    print(f"Bufer: {settings.buffer_pips:.0f} pips = ${settings.buffer_price:.2f} | "
          f"rearm: {settings.rearm_pips:.0f} pips")

    await test_zone_logic(settings)
    await test_persistence(settings)
    await test_parsing()
    await test_chart(settings)
    await test_tts(settings)
    await test_call_engine(settings)

    print("\n" + "=" * 52)
    if _failures:
        print(f"XATO: {len(_failures)} ta test o'tmadi -> {', '.join(_failures)}")
        raise SystemExit(1)
    print("Barcha testlar muvaffaqiyatli o'tdi.")


if __name__ == "__main__":
    asyncio.run(main())
