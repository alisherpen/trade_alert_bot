"""ZAXIRA qatlam: Telegram 1-ga-1 qo'ng'irog'i - raw MTProto orqali (ovozsiz).

Bu modul faqat ffmpeg topilmaganda ishlatiladi. Asosiy, gapiruvchi qo'ng'iroq
uchun `tg/voice_call.py` (py-tgcalls) ga qarang.

Telethon'da tayyor "call qil" metodi yo'q, shuning uchun `phone.RequestCall`
qo'lda chaqiriladi: Diffie-Hellman kaliti generatsiya qilinadi, g_a_hash
yuboriladi va qabul qiluvchi telefoni JIRINGLAYDI.

Ovoz uzatilmaydi (buning uchun ntgcalls kerak):
  * qabul qiluvchi ko'tarsa  -> aloqa avtomatik uziladi;
  * ko'tarmasa               -> CALL_RING_SECONDS dan keyin uziladi ("missed call").

Bu rejimda ovozli ogohlantirish alohida voice-message bo'lib keladi (tg/tts.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
from dataclasses import dataclass
from typing import Optional

from telethon import events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.messages import GetDhConfigRequest
from telethon.tl.functions.phone import DiscardCallRequest, RequestCallRequest
from telethon.tl.types import (
    InputPhoneCall,
    PhoneCall as PhoneCallEstablished,
    PhoneCallAccepted,
    PhoneCallDiscarded,
    PhoneCallDiscardReasonHangup,
    PhoneCallDiscardReasonMissed,
    PhoneCallProtocol,
    PhoneCallWaiting,
    UpdatePhoneCall,
)

log = logging.getLogger(__name__)

# Rasmiy klientlar yuboradigan qiymatlar; serverning validatsiyasidan o'tishi uchun kerak.
_PROTOCOL = PhoneCallProtocol(
    min_layer=65,
    max_layer=92,
    udp_p2p=True,
    udp_reflector=True,
    library_versions=["2.4.4", "4.1.2"],
)

_ACCEPTED_TYPES = (PhoneCallAccepted, PhoneCallEstablished)


@dataclass
class CallResult:
    ok: bool
    answered: bool = False
    duration: float = 0.0
    error: Optional[str] = None
    call_id: Optional[int] = None

    @property
    def summary(self) -> str:
        if not self.ok:
            return f"❌ Qo'ng'iroq amalga oshmadi: {self.error}"
        if self.answered:
            return f"✅ Qo'ng'iroq ko'tarildi va uzildi ({self.duration:.0f}s jiringladi)"
        return f"\U0001f4de Qo'ng'iroq qilindi, javob bo'lmadi ({self.duration:.0f}s)"


class CallManager:
    """Private call'larni boshqaradi. Bir vaqtda faqat bitta qo'ng'iroq."""

    def __init__(self, client, settings) -> None:
        self._client = client
        self._s = settings
        self._lock = asyncio.Lock()
        self._dh_cache: Optional[tuple] = None  # (p_int, g)
        self._active_id: Optional[int] = None
        self._answered = asyncio.Event()
        self._ended = asyncio.Event()
        self._handler_registered = False

    # ------------------------------------------------------------------
    def register(self) -> None:
        """updatePhoneCall hodisalarini tinglash."""
        if self._handler_registered:
            return
        self._client.add_event_handler(self._on_phone_call, events.Raw(types=UpdatePhoneCall))
        self._handler_registered = True
        log.debug("CallManager: updatePhoneCall handler ro'yxatdan o'tdi")

    async def _on_phone_call(self, update: UpdatePhoneCall) -> None:
        call = getattr(update, "phone_call", None)
        if call is None or self._active_id is None:
            return
        if getattr(call, "id", None) != self._active_id:
            return

        if isinstance(call, _ACCEPTED_TYPES):
            log.info("Qo'ng'iroq ko'tarildi (id=%s)", call.id)
            self._answered.set()
        elif isinstance(call, PhoneCallDiscarded):
            reason = type(getattr(call, "reason", None)).__name__
            log.info("Qo'ng'iroq yakunlandi (id=%s, sabab=%s)", call.id, reason)
            self._ended.set()

    # ------------------------------------------------------------------
    async def call(self, target=None) -> CallResult:
        """Qo'ng'iroq qiladi. CALL_RETRIES marta urinadi."""
        if not self._s.call_enabled:
            return CallResult(ok=False, error="CALL_ENABLED=false")

        target = target if target is not None else self._s.alert_target
        attempts = max(1, self._s.call_retries)
        last: Optional[CallResult] = None

        async with self._lock:
            for attempt in range(1, attempts + 1):
                last = await self._call_once(target, attempt)
                if last.ok and last.answered:
                    return last
                if last.ok and attempt >= attempts:
                    return last
                if not last.ok and _is_fatal(last.error):
                    return last
                if attempt < attempts:
                    log.info("Qayta urinish %d/%d ...", attempt + 1, attempts)
                    await asyncio.sleep(self._s.call_retry_delay)
        return last or CallResult(ok=False, error="noma'lum xato")

    # ------------------------------------------------------------------
    async def _call_once(self, target, attempt: int) -> CallResult:
        loop = asyncio.get_running_loop()
        started = loop.time()
        self._answered.clear()
        self._ended.clear()
        self._active_id = None
        phone_call = None

        try:
            peer = await self._client.get_input_entity(target)
            g_a_hash = await self._make_g_a_hash()

            result = await self._client(
                RequestCallRequest(
                    user_id=peer,
                    random_id=random.randint(1, 0x7FFFFFFF),
                    g_a_hash=g_a_hash,
                    protocol=_PROTOCOL,
                    video=False,
                )
            )
            phone_call = getattr(result, "phone_call", None)
            if phone_call is None or not isinstance(
                phone_call, (PhoneCallWaiting,) + _ACCEPTED_TYPES
            ):
                return CallResult(
                    ok=False, error=f"kutilmagan javob: {type(phone_call).__name__}"
                )

            self._active_id = phone_call.id
            log.info("Qo'ng'iroq boshlandi (id=%s, urinish %d)", phone_call.id, attempt)

            answered = await self._wait_answer(self._s.call_ring_seconds)
            duration = loop.time() - started

            if answered and self._s.call_hangup_delay > 0:
                await asyncio.sleep(self._s.call_hangup_delay)

            await self._discard(phone_call, answered, duration)
            return CallResult(
                ok=True, answered=answered, duration=duration, call_id=phone_call.id
            )

        except FloodWaitError as exc:
            msg = f"FloodWait {exc.seconds}s"
            log.error("Qo'ng'iroq: %s", msg)
            return CallResult(ok=False, error=msg)
        except RPCError as exc:
            log.error("Qo'ng'iroq RPC xatosi: %s", exc)
            if phone_call is not None:
                await self._discard(phone_call, False, 0.0)
            return CallResult(ok=False, error=_explain(exc))
        except (ValueError, TypeError) as exc:
            log.error("Qo'ng'iroq: manzil topilmadi (%s)", exc)
            return CallResult(ok=False, error=f"manzil topilmadi: {exc}")
        except Exception as exc:  # noqa: BLE001
            log.exception("Qo'ng'iroqda kutilmagan xato")
            return CallResult(ok=False, error=str(exc))
        finally:
            self._active_id = None

    async def _wait_answer(self, timeout: float) -> bool:
        """Ko'tarilishini kutadi. True = ko'tarildi."""
        answer_task = asyncio.create_task(self._answered.wait())
        end_task = asyncio.create_task(self._ended.wait())
        try:
            _, pending = await asyncio.wait(
                {answer_task, end_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            return self._answered.is_set()
        finally:
            for t in (answer_task, end_task):
                if not t.done():
                    t.cancel()

    async def _discard(self, phone_call, answered: bool, duration: float) -> None:
        if self._ended.is_set():
            return  # qarshi tomon allaqachon uzgan
        reason = PhoneCallDiscardReasonHangup() if answered else PhoneCallDiscardReasonMissed()
        try:
            await self._client(
                DiscardCallRequest(
                    peer=InputPhoneCall(id=phone_call.id, access_hash=phone_call.access_hash),
                    duration=int(duration) if answered else 0,
                    reason=reason,
                    connection_id=0,
                    video=False,
                )
            )
            log.debug("Qo'ng'iroq uzildi (id=%s)", phone_call.id)
        except RPCError as exc:
            log.debug("DiscardCall e'tiborsiz qoldirildi: %s", exc)

    # ------------------------------------------------------------------
    async def _make_g_a_hash(self) -> bytes:
        """DH konfiguratsiyasini olib, g_a = g^a mod p ning SHA256 hashini qaytaradi."""
        p_int, g = await self._dh_config()
        a = int.from_bytes(os.urandom(256), "big")
        g_a = pow(g, a, p_int)
        return hashlib.sha256(g_a.to_bytes(256, "big")).digest()

    async def _dh_config(self) -> tuple:
        if self._dh_cache is not None:
            return self._dh_cache
        dh = await self._client(GetDhConfigRequest(version=0, random_length=0))
        self._dh_cache = (int.from_bytes(dh.p, "big"), dh.g)
        return self._dh_cache


# ----------------------------------------------------------------------
_FATAL = (
    "USER_PRIVACY_RESTRICTED",
    "PARTICIPANT_VERSION_OUTDATED",
    "USER_IS_BLOCKED",
    "CALL_PROTOCOL_FLAGS_INVALID",
    "manzil topilmadi",
)

_HINTS = {
    "USER_PRIVACY_RESTRICTED": (
        "Qabul qiluvchining maxfiylik sozlamasi qo'ng'iroqni taqiqlagan. "
        "Telegram > Settings > Privacy and Security > Calls > 'Everybody' yoki "
        "'My Contacts' qilib qo'ying va ikkala akkaunt bir-birini kontaktga qo'shsin."
    ),
    "PARTICIPANT_VERSION_OUTDATED": "Qabul qiluvchi Telegram ilovasini yangilashi kerak.",
    "CALL_ALREADY_ACCEPTED": "Bu qo'ng'iroq allaqachon qabul qilingan.",
    "CALL_ALREADY_DECLINED": "Qo'ng'iroq rad etildi.",
    "USER_IS_BLOCKED": "Siz bloklangansiz.",
}


def _explain(exc: RPCError) -> str:
    name = getattr(exc, "message", "") or str(exc)
    for key, hint in _HINTS.items():
        if key in name:
            return f"{key} - {hint}"
    return name


def _is_fatal(error: Optional[str]) -> bool:
    if not error:
        return False
    return any(key in error for key in _FATAL)
