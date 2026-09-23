"""Telethon userbot: ulanish, qayta ulanish, xabar/media yuborish."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from tg.calls import CallManager
from tg.tts import TtsEngine, VoiceClip
from tg.voice_call import RingResult, VoiceCaller, ffmpeg_ready

log = logging.getLogger(__name__)


class TelegramService:
    """Telethon klientining yagona egasi."""

    def __init__(self, settings) -> None:
        self._s = settings
        session = Path(settings.base_dir) / settings.session
        session.parent.mkdir(parents=True, exist_ok=True)

        self.client = TelegramClient(
            str(session),
            settings.api_id,
            settings.api_hash,
            connection_retries=None,      # cheksiz avtomatik qayta ulanish
            retry_delay=5,
            auto_reconnect=True,
            request_retries=5,
            device_model="XAUUSD Alert Bot",
            system_version="Windows",
            app_version="1.0",
        )
        self.voice_caller = VoiceCaller(self.client, settings)   # gapiruvchi qo'ng'iroq
        self.calls = CallManager(self.client, settings)          # zaxira: faqat jiringlaydi
        self.tts = TtsEngine(settings)
        self.me = None
        self._notify_entity = None
        self._send_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def start(self) -> None:
        await self.client.start(phone=self._s.phone)
        self.me = await self.client.get_me()

        # Asosiy qatlam: ovozli qo'ng'iroq. Ishga tushmasa - raw MTProto zaxirasi.
        if self._s.call_enabled:
            if not await self.voice_caller.start():
                self.calls.register()
                log.warning(
                    "Qo'ng'iroq ZAXIRA rejimida: jiringlaydi, lekin ichida gapirmaydi."
                )
        log.info(
            "Telegram ulandi: %s (@%s, id=%s)",
            self.me.first_name,
            self.me.username or "-",
            self.me.id,
        )
        await self._resolve_targets()

    async def _resolve_targets(self) -> None:
        """Manzillarni oldindan yechib, Telethon keshini isitadi.

        Buni startda qilish muhim: aks holda xato faqat signal paytida chiqadi.
        """
        # 1) Xabarlar ketadigan chat.
        # Zanjir: NOTIFY_CHAT -> ALERT_TARGET -> Saved Messages.
        # Shunday qilib noto'g'ri NOTIFY_CHAT bo'lsa ham rasm target userga boradi.
        for candidate, label in (
            (self._s.notify_chat, "NOTIFY_CHAT"),
            (self._s.alert_target, "ALERT_TARGET"),
            ("me", "Saved Messages"),
        ):
            if candidate is None:
                continue
            try:
                await self.client.get_entity(candidate)
                self._notify_entity = await self.client.get_input_entity(candidate)
                log.info("Xabarlar manzili: %s (%r)", label, candidate)
                break
            except (ValueError, TypeError) as exc:
                log.warning("%s (%r) topilmadi: %s", label, candidate, str(exc)[:120])

        # 2) Qo'ng'iroq manzili
        if not self._s.call_enabled:
            return
        try:
            target = await self.client.get_entity(self._s.alert_target)
            log.info(
                "Qo'ng'iroq manzili: %s (id=%s)",
                getattr(target, "first_name", None) or getattr(target, "title", "?"),
                target.id,
            )
        except (ValueError, TypeError) as exc:
            log.error(
                "ALERT_TARGET (%r) topilmadi: %s\n"
                "Yechim: shu akkauntdan %r ga bir marta xabar yozing yoki uni "
                "kontaktga qo'shing, shunda Telethon uni tanib oladi.",
                self._s.alert_target, exc, self._s.alert_target,
            )

    async def stop(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    @property
    def connected(self) -> bool:
        return self.client.is_connected()

    async def ensure_connected(self) -> bool:
        """Uzilgan bo'lsa qayta ulanishga harakat qiladi."""
        if self.client.is_connected():
            return True
        log.warning("Telegram uzildi - qayta ulanmoqda...")
        try:
            await self.client.connect()
            if await self.client.is_user_authorized():
                log.info("Telegram qayta ulandi.")
                return True
            log.error("Sessiya yaroqsiz - qayta login qilish kerak (login.py).")
        except Exception as exc:  # noqa: BLE001
            log.error("Telegram qayta ulanmadi: %s", exc)
        return False

    # ------------------------------------------------------------------
    async def send_text(self, text: str, chat=None) -> None:
        await self._send(chat, "message", message=text, link_preview=False)

    async def send_photo(self, path: Path, caption: str = "", chat=None) -> None:
        await self._send(
            chat, "file", file=str(path), caption=caption, force_document=False
        )

    async def send_voice(self, clip: VoiceClip, caption: str = "", chat=None) -> None:
        # voice_note faqat ogg/opus uchun; mp3 oddiy audio bo'lib ketadi.
        await self._send(
            chat,
            "file",
            file=str(clip.path),
            caption=caption,
            voice_note=clip.is_voice_note,
        )

    async def _send(self, chat, kind: str, **kwargs) -> None:
        entity = chat if chat is not None else (self._notify_entity or self._s.notify_chat)
        send = self.client.send_file if kind == "file" else self.client.send_message
        async with self._send_lock:
            for attempt in range(3):
                try:
                    await send(entity, **kwargs)
                    return
                except FloodWaitError as exc:
                    wait = min(exc.seconds + 1, 60)
                    log.warning("FloodWait %ss - kutilmoqda", wait)
                    await asyncio.sleep(wait)
                except (ConnectionError, asyncio.TimeoutError) as exc:
                    log.warning("Yuborish xatosi (%s) - qayta urinish", exc)
                    await self.ensure_connected()
                    await asyncio.sleep(2)
                except RPCError as exc:
                    log.error("Telegram RPC xatosi: %s", exc)
                    return
            log.error("Xabar yuborilmadi (3 urinishdan keyin)")

    # ------------------------------------------------------------------
    @property
    def call_engine(self) -> str:
        if self.voice_caller.available:
            return "ovozli (py-tgcalls)"
        if not self._s.call_enabled:
            return "o'chirilgan"
        return f"zaxira: faqat jiringlaydi — {self.voice_caller.status}"

    async def place_call(self, audio: Optional[Path] = None, target=None) -> RingResult:
        """Qo'ng'iroq qiladi.

        `audio` berilgan va py-tgcalls tayyor bo'lsa — qo'ng'iroq ICHIDA gapiradi.
        Aks holda raw MTProto bilan shunchaki jiringlatadi.
        """
        if audio is not None and self.voice_caller.available:
            return await self.voice_caller.call_and_speak(audio, target)

        legacy = await self.calls.call(target)
        return RingResult(
            ok=legacy.ok,
            answered=legacy.answered,
            spoke=False,
            duration=legacy.duration,
            error=legacy.error,
            engine="mtproto",
        )

    async def stop_calls(self) -> None:
        await self.voice_caller.stop()
