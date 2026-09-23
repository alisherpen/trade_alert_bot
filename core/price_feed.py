"""MetaTrader5 narx manbai.

MetaTrader5 paketi sinxron va thread'ga sezgir, shuning uchun barcha chaqiruvlar
bitta ajratilgan worker-thread'da bajariladi (max_workers=1).
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from config import Settings

log = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


class Mt5Error(RuntimeError):
    pass


TIMEFRAMES = {
    "M1": getattr(mt5, "TIMEFRAME_M1", None),
    "M5": getattr(mt5, "TIMEFRAME_M5", None),
    "M15": getattr(mt5, "TIMEFRAME_M15", None),
    "M30": getattr(mt5, "TIMEFRAME_M30", None),
    "H1": getattr(mt5, "TIMEFRAME_H1", None),
    "H4": getattr(mt5, "TIMEFRAME_H4", None),
    "D1": getattr(mt5, "TIMEFRAME_D1", None),
} if mt5 is not None else {}


@dataclass(frozen=True)
class Tick:
    bid: float
    ask: float
    ts: float
    symbol: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def price(self, source: str) -> float:
        return {"bid": self.bid, "ask": self.ask, "mid": self.mid}[source]


class Mt5PriceFeed:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")
        self._connected = False
        self._symbol: str = settings.symbol
        self._last_tick: Optional[Tick] = None
        self._last_ok: float = 0.0
        self._reconnects = 0

    # ---------------- public ----------------
    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_tick(self) -> Optional[Tick]:
        return self._last_tick

    @property
    def reconnects(self) -> int:
        return self._reconnects

    async def start(self) -> None:
        if mt5 is None:
            raise Mt5Error(
                "MetaTrader5 paketi o'rnatilmagan. `pip install MetaTrader5` (faqat Windows)."
            )
        await self.connect()

    async def connect(self) -> bool:
        ok = await self._run(self._connect_sync)
        self._connected = ok
        return ok

    async def reconnect(self) -> bool:
        self._reconnects += 1
        log.warning("MT5 qayta ulanmoqda (#%d)...", self._reconnects)
        await self._run(self._shutdown_sync)
        self._connected = False
        await asyncio.sleep(2)
        return await self.connect()

    async def get_tick(self) -> Optional[Tick]:
        """Joriy tick. Ulanish uzilgan bo'lsa None qaytaradi (chaqiruvchi reconnect qiladi)."""
        if not self._connected:
            return None
        tick = await self._run(self._tick_sync)
        if tick is not None:
            self._last_tick = tick
            self._last_ok = time.time()
        return tick

    async def close(self) -> None:
        try:
            await self._run(self._shutdown_sync)
        except Exception:  # noqa: BLE001 - yopilishda xatoni yutamiz
            pass
        self._connected = False
        self._pool.shutdown(wait=False)

    async def account_info(self) -> Optional[dict]:
        return await self._run(self._account_sync)

    async def terminal_data_path(self) -> Optional[str]:
        """MT5 terminalining data papkasi (MQL5/Files shu yerda)."""
        if not self._connected:
            return None
        return await self._run(self._terminal_path_sync)

    async def get_rates(self, timeframe: str = "M15", count: int = 120):
        """Oxirgi `count` ta svechani qaytaradi (numpy structured array yoki None)."""
        if not self._connected:
            return None
        return await self._run(self._rates_sync, timeframe, count)

    # ---------------- thread helper ----------------
    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, fn, *args)

    # ---------------- sinxron qism (worker-thread) ----------------
    def _connect_sync(self) -> bool:
        kwargs = {}
        if self._s.mt5_path:
            kwargs["path"] = self._s.mt5_path
        if self._s.mt5_login:
            kwargs.update(
                login=self._s.mt5_login,
                password=self._s.mt5_password,
                server=self._s.mt5_server,
            )
        if not mt5.initialize(**kwargs):
            log.error("mt5.initialize() muvaffaqiyatsiz: %s", mt5.last_error())
            return False

        if self._s.mt5_login:
            if not mt5.login(
                login=self._s.mt5_login,
                password=self._s.mt5_password,
                server=self._s.mt5_server,
            ):
                log.error("mt5.login() muvaffaqiyatsiz: %s", mt5.last_error())
                mt5.shutdown()
                return False

        symbol = self._resolve_symbol_sync(self._s.symbol)
        if not symbol:
            log.error("'%s' simvoli terminalda topilmadi.", self._s.symbol)
            mt5.shutdown()
            return False
        self._symbol = symbol

        if not mt5.symbol_select(symbol, True):
            log.error("symbol_select('%s') muvaffaqiyatsiz: %s", symbol, mt5.last_error())
            mt5.shutdown()
            return False

        info = mt5.account_info()
        who = f"#{info.login} ({info.server})" if info else "noma'lum hisob"
        log.info("MT5 ulandi: %s | simvol: %s", who, symbol)
        return True

    def _resolve_symbol_sync(self, wanted: str) -> Optional[str]:
        if mt5.symbol_info(wanted) is not None:
            return wanted
        if not self._s.symbol_autodetect:
            return None
        # Exness: XAUUSDm, XAUUSD.z, XAUUSDz ...
        candidates = mt5.symbols_get(group=f"*{wanted}*") or ()
        for sym in candidates:
            if sym.name.upper().startswith(wanted.upper()):
                log.warning("Simvol '%s' -> '%s' deb topildi.", wanted, sym.name)
                return sym.name
        return candidates[0].name if candidates else None

    def _tick_sync(self) -> Optional[Tick]:
        t = mt5.symbol_info_tick(self._symbol)
        if t is None or (t.bid == 0 and t.ask == 0):
            err = mt5.last_error()
            log.debug("Tick olinmadi: %s", err)
            return None
        return Tick(bid=float(t.bid), ask=float(t.ask), ts=float(t.time), symbol=self._symbol)

    def _account_sync(self) -> Optional[dict]:
        info = mt5.account_info()
        return info._asdict() if info else None

    def _terminal_path_sync(self) -> Optional[str]:
        info = mt5.terminal_info()
        return info.data_path if info else None

    def _rates_sync(self, timeframe: str, count: int):
        tf = TIMEFRAMES.get(timeframe.upper())
        if tf is None:
            log.error("Noma'lum timeframe: %s", timeframe)
            return None
        rates = mt5.copy_rates_from_pos(self._symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            log.warning("Svechalar olinmadi (%s %s): %s", self._symbol, timeframe, mt5.last_error())
            return None
        return rates

    def _shutdown_sync(self) -> None:
        if mt5 is not None:
            mt5.shutdown()
