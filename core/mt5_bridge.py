"""Python -> MT5 chart vizual ko'prigi.

NEGA KO'PRIK KERAK?
-------------------
MetaTrader5 Python paketida 46 ta funksiya bor va ularning ORASIDA CHIZISH
FUNKSIYASI YO'Q: `ObjectCreate`, `ChartScreenShot` kabi narsalar faqat MQL5'da.
Ya'ni Python MT5 chartiga to'g'ridan-to'g'ri hech narsa chiza olmaydi.

YECHIM: fayl orqali ko'prik.

    Python  --yozadi-->  MQL5/Files/zone_view.csv  --o'qiydi-->  ZoneViewer.mq5
                                                                 (indikator)
                                                                       |
                                                                 chartda chizadi

Python har qadamda faylni yangilab turadi, MQL5 indikatori esa uni har 500 ms da
o'qib chartni qayta chizadi. Natijada siz MT5 oynasida botning ishini
REAL VAQTDA ko'rib turasiz.

FAYL FORMATI (satr boshidagi teg | maydonlar):
    TS     | unix_time
    STATUS | matn | progress(0-100)
    ZONE   | id | min | max | holat | izoh
    LINE   | narx | turi | izoh
    MARK   | unix_time | narx | turi | izoh

CSV tanlandi (JSON emas): MQL5'da tayyor JSON parser yo'q, `StringSplit` esa
bir satrda ishlaydi — indikator kodi sodda va tez bo'ladi.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

log = logging.getLogger(__name__)

FEED_NAME = "zone_view.csv"


@dataclass
class ViewZone:
    id: int
    min_price: float
    max_price: float
    state: str = "active"     # active | candidate | rejected | triggered
    note: str = ""


@dataclass
class ViewLine:
    price: float
    kind: str = "trigger"     # trigger | price | level
    note: str = ""


@dataclass
class ViewMark:
    ts: int                   # unix time (svecha vaqti)
    price: float
    kind: str = "high"        # high | low | touch
    note: str = ""


@dataclass
class ViewState:
    """Chartda ko'rsatiladigan hozirgi holat."""

    status: str = ""
    progress: int = 0
    zones: List[ViewZone] = field(default_factory=list)
    lines: List[ViewLine] = field(default_factory=list)
    marks: List[ViewMark] = field(default_factory=list)


class Mt5Bridge:
    """Vizual holatni MT5 o'qiy oladigan faylga yozadi."""

    def __init__(self, files_dir: Path, enabled: bool = True) -> None:
        self.files_dir = Path(files_dir)
        self.path = self.files_dir / FEED_NAME
        self.enabled = enabled
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    @classmethod
    async def from_feed(cls, feed, enabled: bool = True) -> "Mt5Bridge":
        """MT5 terminalining MQL5/Files papkasini topib ko'prik yasaydi."""
        data_path = await feed.terminal_data_path()
        if not data_path:
            log.warning("MT5 data_path topilmadi - vizual ko'prik o'chirildi")
            return cls(Path("."), enabled=False)
        files_dir = Path(data_path) / "MQL5" / "Files"
        files_dir.mkdir(parents=True, exist_ok=True)
        log.info("Vizual ko'prik: %s", files_dir / FEED_NAME)
        return cls(files_dir, enabled=enabled)

    # ------------------------------------------------------------------
    async def publish(self, state: ViewState) -> None:
        if not self.enabled:
            return
        async with self._lock:
            await asyncio.to_thread(self._write_sync, self._render(state))

    async def clear(self) -> None:
        """Chartni tozalash uchun bo'sh holat yuboradi."""
        await self.publish(ViewState(status="", progress=0))

    # ------------------------------------------------------------------
    def _render(self, s: ViewState) -> str:
        out = [f"TS|{int(time.time())}"]
        if s.status:
            out.append(f"STATUS|{_clean(s.status)}|{max(0, min(100, s.progress))}")
        for z in s.zones:
            out.append(
                f"ZONE|{z.id}|{z.min_price:.3f}|{z.max_price:.3f}|{z.state}|{_clean(z.note)}"
            )
        for ln in s.lines:
            out.append(f"LINE|{ln.price:.3f}|{ln.kind}|{_clean(ln.note)}")
        for m in s.marks:
            out.append(f"MARK|{m.ts}|{m.price:.3f}|{m.kind}|{_clean(m.note)}")
        return "\n".join(out) + "\n"

    def _write_sync(self, payload: str) -> None:
        """Atomik yozish: MT5 yarim yozilgan faylni o'qib qolmasligi uchun."""
        self.files_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=FEED_NAME + ".", suffix=".tmp",
                                   dir=str(self.files_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            # MT5 faylni o'qiyotgan bo'lsa Windows almashtirishga ruxsat bermaydi -
            # qisqa oyna, shuning uchun bir necha marta urinamiz.
            for attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    time.sleep(0.05)
            log.debug("Vizual fayl band - bu yangilanish o'tkazib yuborildi")
            os.unlink(tmp)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _clean(text: str) -> str:
    """'|' va yangi qator formatni buzmasligi uchun."""
    return str(text).replace("|", "/").replace("\n", " ").replace("\r", " ").strip()
