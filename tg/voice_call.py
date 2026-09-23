"""Telegram 1-ga-1 qo'ng'irog'i + qo'ng'iroq ICHIDA ovoz bilan gapirish.

Ikki qatlamli:

  1. VoiceCaller (py-tgcalls / ntgcalls) — ASOSIY.
     Haqiqiy P2P qo'ng'iroq ochadi va qabul qilingach TTS ovozini QO'NG'IROQ
     ICHIDA eshittiradi. ffmpeg + ffprobe o'rnatilgan bo'lishi SHART.

  2. CallManager (tg/calls.py, raw MTProto) — ZAXIRA.
     ffmpeg bo'lmasa ishlatiladi: telefon jiringlaydi, ko'tarilsa uziladi,
     ovoz esa alohida voice-message bo'lib keladi.

Qatlam ishga tushishda avtomatik tanlanadi (`RingResult.engine` da ko'rinadi).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    from pytgcalls import PyTgCalls, filters as pytg_filters
    from pytgcalls.exceptions import (
        CallBusy,
        CallDeclined,
        CallDiscarded,
        NotInCallError,
        TimedOutAnswer,
    )
    from pytgcalls.types import CallConfig, MediaStream
except ImportError:  # pragma: no cover
    PyTgCalls = None


@dataclass
class RingResult:
    ok: bool
    answered: bool = False
    spoke: bool = False
    duration: float = 0.0
    error: Optional[str] = None
    engine: str = "-"

    @property
    def summary(self) -> str:
        if not self.ok:
            return f"❌ Qo'ng'iroq amalga oshmadi: {self.error}"
        if self.answered and self.spoke:
            return f"\U0001f5e3 Qo'ng'iroq ko'tarildi, ovoz eshittirildi ({self.duration:.0f}s)"
        if self.answered:
            return f"✅ Qo'ng'iroq ko'tarildi va uzildi ({self.duration:.0f}s)"
        return f"\U0001f4de Qo'ng'iroq qilindi, javob bo'lmadi ({self.duration:.0f}s)"


def ffmpeg_ready() -> bool:
    """py-tgcalls media o'qish uchun ikkalasini ham talab qiladi."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class VoiceCaller:
    """py-tgcalls orqali gapiruvchi P2P qo'ng'iroq."""

    def __init__(self, client, settings) -> None:
        self._client = client
        self._s = settings
        self._calls = None
        self._lock = asyncio.Lock()
        self._stream_done: dict = {}
        self._reason: str = ""

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._calls is not None

    @property
    def status(self) -> str:
        if PyTgCalls is None:
            return "o'chirilgan (py-tgcalls o'rnatilmagan)"
        if not ffmpeg_ready():
            return "o'chirilgan (ffmpeg/ffprobe topilmadi)"
        if self._calls is None:
            return f"ishga tushmadi ({self._reason})" if self._reason else "ishga tushmagan"
        return "yoqilgan (qo'ng'iroq ichida gapiradi)"

    async def start(self) -> bool:
        if PyTgCalls is None:
            self._reason = "py-tgcalls yo'q"
            log.warning("py-tgcalls o'rnatilmagan - qo'ng'iroqda ovoz bo'lmaydi.")
            return False
        if not ffmpeg_ready():
            self._reason = "ffmpeg yo'q"
            log.warning(
                "ffmpeg/ffprobe topilmadi - qo'ng'iroqda ovoz bo'lmaydi. "
                "O'rnatish: winget install Gyan.FFmpeg"
            )
            return False
        try:
            calls = PyTgCalls(self._client)

            @calls.on_update(pytg_filters.stream_end)
            async def _on_stream_end(_, update):  # noqa: ANN001
                ev = self._stream_done.get(update.chat_id)
                if ev is not None:
                    ev.set()

            await calls.start()
            self._calls = calls
            log.info("py-tgcalls ishga tushdi - qo'ng'iroqda ovoz uzatiladi.")
            return True
        except Exception as exc:  # noqa: BLE001
            self._reason = str(exc)
            log.warning("py-tgcalls ishga tushmadi: %s", exc)
            self._calls = None
            return False

    async def stop(self) -> None:
        if self._calls is None:
            return
        try:
            for chat_id in list(self._stream_done):
                await self._leave(chat_id)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    async def call_and_speak(self, audio: Path, target=None) -> RingResult:
        """Qo'ng'iroq qiladi va ko'tarilsa `audio` ni qo'ng'iroq ichida eshittiradi."""
        if self._calls is None:
            return RingResult(ok=False, error="py-tgcalls tayyor emas", engine="pytgcalls")

        target = target if target is not None else self._s.alert_target
        loop = asyncio.get_running_loop()

        async with self._lock:
            started = loop.time()
            chat_id: Optional[int] = None
            try:
                chat_id = await self._calls.resolve_chat_id(target)
                if chat_id <= 0:
                    return RingResult(
                        ok=False,
                        error=f"{target!r} foydalanuvchi emas (guruh/kanal)",
                        engine="pytgcalls",
                    )

                self._stream_done[chat_id] = asyncio.Event()
                log.info("Qo'ng'iroq (ovozli) -> %s (id=%s)", target, chat_id)

                await self._calls.play(
                    chat_id,
                    MediaStream(
                        audio,
                        audio_flags=MediaStream.Flags.REQUIRED,
                        video_flags=MediaStream.Flags.IGNORE,
                    ),
                    CallConfig(timeout=int(self._s.call_ring_seconds)),
                )

                # Shu yergacha yetdik = qo'ng'iroq ko'tarildi va ovoz oqmoqda.
                spoke = await self._wait_stream_end(chat_id)
                duration = loop.time() - started
                await self._leave(chat_id)
                return RingResult(
                    ok=True, answered=True, spoke=spoke,
                    duration=duration, engine="pytgcalls",
                )

            except TimedOutAnswer:
                return RingResult(
                    ok=True, answered=False,
                    duration=loop.time() - started, engine="pytgcalls",
                )
            except CallDeclined:
                return RingResult(ok=True, answered=False, error="rad etildi",
                                  duration=loop.time() - started, engine="pytgcalls")
            except CallBusy:
                return RingResult(ok=False, error="band (boshqa qo'ng'iroqda)",
                                  engine="pytgcalls")
            except CallDiscarded:
                return RingResult(ok=True, answered=False, error="qo'ng'iroq uzildi",
                                  duration=loop.time() - started, engine="pytgcalls")
            except FileNotFoundError as exc:
                return RingResult(ok=False, error=f"audio o'qilmadi: {exc}",
                                  engine="pytgcalls")
            except Exception as exc:  # noqa: BLE001
                log.exception("Ovozli qo'ng'iroqda kutilmagan xato")
                return RingResult(ok=False, error=str(exc), engine="pytgcalls")
            finally:
                if chat_id is not None:
                    self._stream_done.pop(chat_id, None)

    # ------------------------------------------------------------------
    async def _wait_stream_end(self, chat_id: int) -> bool:
        """Ovoz tugashini kutadi. Cheksiz kutmaslik uchun qattiq limit bor."""
        ev = self._stream_done.get(chat_id)
        if ev is None:
            return False
        try:
            await asyncio.wait_for(ev.wait(), timeout=self._s.call_max_speak_seconds)
            return True
        except asyncio.TimeoutError:
            log.warning("Ovoz %.0fs ichida tugamadi - qo'ng'iroq uzilmoqda",
                        self._s.call_max_speak_seconds)
            return False

    async def _leave(self, chat_id: int) -> None:
        try:
            await self._calls.leave_call(chat_id)
        except NotInCallError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.debug("leave_call e'tiborsiz: %s", exc)
