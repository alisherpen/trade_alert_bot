"""MT5 ma'lumotidan candlestick chart rasmini chizish (Pillow).

Nega terminal screenshot emas?
-----------------------------
MT5 Python API'da chart screenshot funksiyasi yo'q (`ChartScreenShot` faqat MQL5'da).
Terminal oynasini rasmga olish esa oyna ochiq turishini, to'g'ri o'lchamda va ustida
boshqa oyna bo'lmasligini talab qiladi — 24/7 bot uchun ishonchsiz.

Shuning uchun chart `copy_rates_from_pos` ma'lumotidan chiziladi: natija har doim
bir xil, zona to'rtburchagi, bufer chegarasi va joriy narx aniq ko'rinadi.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None

# --- o'lchamlar ---
W, H = 1280, 720
PAD_L, PAD_R, PAD_T, PAD_B = 16, 96, 64, 52

# --- ranglar (TradingView dark) ---
BG = (19, 23, 34)
GRID = (42, 46, 57)
TEXT = (150, 158, 172)
TEXT_HI = (214, 220, 230)
UP = (38, 166, 154)
DOWN = (239, 83, 80)
ZONE_FILL = (255, 82, 82, 46)
ZONE_EDGE = (255, 112, 96)
BUF_EDGE = (255, 183, 77)
PRICE_LINE = (66, 165, 245)

_FONTS = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_FONTS_BOLD = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int, bold: bool = False):
    for path in (_FONTS_BOLD if bold else _FONTS):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


class ChartRenderer:
    """MT5 svechalaridan zona belgilangan chart rasmini yasaydi."""

    def __init__(self, feed, settings) -> None:
        self._feed = feed
        self._s = settings
        self._dir = Path(settings.cache_dir) / "charts"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return self._s.chart_enabled and Image is not None

    # ------------------------------------------------------------------
    async def render(self, zone, price: float, side: str) -> Optional[Path]:
        """Zona uchun chart rasmini qaytaradi. Xato bo'lsa None."""
        if not self.available:
            return None

        rates = await self._feed.get_rates(self._s.chart_timeframe, self._s.chart_bars)
        if rates is None or len(rates) < 2:
            log.warning("Chart uchun svechalar yetarli emas")
            return None

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self._dir / f"zone{zone.id}_{stamp}.png"
        try:
            import asyncio

            img = await asyncio.to_thread(self._draw, rates, zone, price, side)
            await asyncio.to_thread(img.save, out, "PNG", optimize=True)
            return out
        except Exception as exc:  # noqa: BLE001 - chart hech qachon alertni to'xtatmasin
            log.warning("Chart chizilmadi: %s", exc)
            return None

    # ------------------------------------------------------------------
    def _draw(self, rates: Sequence, zone, price: float, side: str):
        buf = self._s.buffer_price
        plot_w = W - PAD_L - PAD_R
        plot_h = H - PAD_T - PAD_B

        highs = [float(r["high"]) for r in rates]
        lows = [float(r["low"]) for r in rates]

        # Ko'rinish diapazoni: svechalar + zona + bufer chegaralari sig'ishi kerak
        y_hi = max(max(highs), zone.max_price + buf, price)
        y_lo = min(min(lows), zone.min_price - buf, price)
        margin = (y_hi - y_lo) * 0.08 or 1.0
        y_hi, y_lo = y_hi + margin, y_lo - margin
        span = y_hi - y_lo

        def to_y(p: float) -> float:
            return PAD_T + (y_hi - p) / span * plot_h

        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)

        self._grid(d, y_lo, y_hi, to_y)
        self._zone_band(img, d, zone, buf, to_y)
        self._candles(d, rates, to_y, plot_w)
        self._price_line(d, price, to_y)
        self._header(d, zone, price, side, buf, len(rates))
        self._footer(d, rates)
        return img

    # ------------------------------------------------------------------
    def _grid(self, d, y_lo: float, y_hi: float, to_y) -> None:
        """Gorizontal to'r + o'ngdagi narx shkalasi."""
        f = _font(15)
        steps = 8
        for i in range(steps + 1):
            p = y_lo + (y_hi - y_lo) * i / steps
            y = to_y(p)
            d.line([(PAD_L, y), (W - PAD_R, y)], fill=GRID, width=1)
            d.text((W - PAD_R + 10, y - 9), f"{p:.2f}", font=f, fill=TEXT)
        d.line([(W - PAD_R, PAD_T), (W - PAD_R, H - PAD_B)], fill=GRID, width=1)

    def _zone_band(self, img, d, zone, buf: float, to_y) -> None:
        """Zona to'rtburchagi + bufer (trigger) chegaralari."""
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        y1, y2 = to_y(zone.max_price), to_y(zone.min_price)
        od.rectangle([PAD_L, y1, W - PAD_R, y2], fill=ZONE_FILL)
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))

        d = ImageDraw.Draw(img)
        f = _font(14, bold=True)
        for p in (zone.min_price, zone.max_price):
            y = to_y(p)
            d.line([(PAD_L, y), (W - PAD_R, y)], fill=ZONE_EDGE, width=2)
        d.text((PAD_L + 8, to_y(zone.max_price) + 6),
               f"ZONA  {zone.min_price:.2f} - {zone.max_price:.2f}", font=f, fill=ZONE_EDGE)

        # Bufer (trigger) chegaralari — punktir
        for p, label in (
            (zone.max_price + buf, f"trigger {zone.max_price + buf:.2f}"),
            (zone.min_price - buf, f"trigger {zone.min_price - buf:.2f}"),
        ):
            y = to_y(p)
            self._dashed(d, y, BUF_EDGE)
            d.text((PAD_L + 8, y - 20), label, font=f, fill=BUF_EDGE)

    @staticmethod
    def _dashed(d, y: float, color, dash: int = 9, gap: int = 7) -> None:
        x = PAD_L
        while x < W - PAD_R:
            d.line([(x, y), (min(x + dash, W - PAD_R), y)], fill=color, width=2)
            x += dash + gap

    def _candles(self, d, rates, to_y, plot_w: int) -> None:
        n = len(rates)
        step = plot_w / n
        body_w = max(2.0, step * 0.62)
        for i, r in enumerate(rates):
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            color = UP if c >= o else DOWN
            cx = PAD_L + step * (i + 0.5)
            d.line([(cx, to_y(h)), (cx, to_y(l))], fill=color, width=1)
            top, bot = to_y(max(o, c)), to_y(min(o, c))
            if bot - top < 1:
                bot = top + 1
            d.rectangle([cx - body_w / 2, top, cx + body_w / 2, bot], fill=color)

    def _price_line(self, d, price: float, to_y) -> None:
        y = to_y(price)
        self._dashed(d, y, PRICE_LINE, dash=5, gap=4)
        f = _font(16, bold=True)
        label = f"{price:.2f}"
        tw = d.textlength(label, font=f)
        d.rectangle([W - PAD_R + 2, y - 12, W - PAD_R + 12 + tw, y + 12], fill=PRICE_LINE)
        d.text((W - PAD_R + 7, y - 9), label, font=f, fill=(255, 255, 255))

    def _header(self, d, zone, price: float, side: str, buf: float, bars: int) -> None:
        d.rectangle([0, 0, W, PAD_T - 8], fill=(26, 31, 44))
        d.text((PAD_L, 10), f"{self._feed.symbol}  {self._s.chart_timeframe}",
               font=_font(24, bold=True), fill=TEXT_HI)

        dist = zone.distance(price)
        pips = self._s.to_pips(dist)
        if side == "inside":
            status, color = "NARX ZONA ICHIDA", ZONE_EDGE
        elif side == "below":
            status, color = f"PASTDAN  {pips:.0f} pips  (${dist:.2f})", UP
        else:
            status, color = f"YUQORIDAN  {pips:.0f} pips  (${dist:.2f})", DOWN
        d.text((PAD_L + 250, 14), status, font=_font(21, bold=True), fill=color)

        now = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
        f = _font(16)
        tw = d.textlength(now, font=f)
        d.text((W - PAD_R - tw, 18), now, font=f, fill=TEXT)

    def _footer(self, d, rates) -> None:
        f = _font(15)
        y = H - PAD_B + 12
        first = datetime.fromtimestamp(int(rates[0]["time"])).strftime("%d.%m %H:%M")
        last = datetime.fromtimestamp(int(rates[-1]["time"])).strftime("%d.%m %H:%M")
        d.text((PAD_L, y), first, font=f, fill=TEXT)
        tw = d.textlength(last, font=f)
        d.text((W - PAD_R - tw, y), last, font=f, fill=TEXT)
        mid = f"{len(rates)} ta {self._s.chart_timeframe} svecha"
        tw = d.textlength(mid, font=f)
        d.text(((W - tw) / 2, y), mid, font=f, fill=TEXT)
