"""Matnni ovozga aylantirish (TTS).

Ustuvorlik:
  1. edge-tts  - o'zbekcha neural ovoz (uz-UZ-SardorNeural), bepul, internet talab qiladi.
  2. gTTS      - zaxira variant (o'zbekcha 'uz' qo'llab-quvvatlanadi).
  3. Hech biri bo'lmasa - None qaytaradi, alert faqat matn/rasm bilan ketadi.

ffmpeg topilsa mp3 -> ogg/opus ga o'giriladi va Telegram'ga haqiqiy "voice message"
sifatida yuboriladi. ffmpeg bo'lmasa mp3 oddiy audio fayl sifatida ketadi.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None

try:
    from gtts import gTTS
except ImportError:  # pragma: no cover
    gTTS = None


@dataclass(frozen=True)
class VoiceClip:
    path: Path
    is_voice_note: bool   # True bo'lsa ogg/opus -> Telegram voice message
    duration: Optional[int] = None


class TtsEngine:
    def __init__(self, settings) -> None:
        self._s = settings
        self._dir = Path(settings.cache_dir) / "tts"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg = shutil.which("ffmpeg")
        self._voice: Optional[str] = None
        self._voice_checked = False
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._s.tts_enabled and (edge_tts is not None or gTTS is not None)

    @property
    def engine_name(self) -> str:
        if not self._s.tts_enabled:
            return "o'chirilgan"
        if edge_tts is not None:
            return f"edge-tts ({self._s.tts_voice})"
        if gTTS is not None:
            return "gTTS"
        return "yo'q"

    # ------------------------------------------------------------------
    async def synthesize(self, text: str) -> Optional[VoiceClip]:
        """Matndan ovoz fayli yasaydi. Xato bo'lsa None."""
        if not self.available:
            return None

        async with self._lock:
            key = hashlib.md5(
                f"{text}|{self._s.tts_voice}|{self._s.tts_rate}".encode("utf-8")
            ).hexdigest()[:16]
            mp3 = self._dir / f"{key}.mp3"

            try:
                if not mp3.exists():
                    if edge_tts is not None:
                        await self._edge(text, mp3)
                    else:
                        await asyncio.to_thread(self._gtts, text, mp3)
            except Exception as exc:  # noqa: BLE001 - TTS hech qachon alertni to'xtatmasin
                log.warning("TTS generatsiyasi muvaffaqiyatsiz: %s", exc)
                return None

            if not mp3.exists() or mp3.stat().st_size < 512:
                log.warning("TTS fayli bo'sh chiqdi")
                return None

            ogg = await self._to_opus(mp3)
            if ogg is not None:
                return VoiceClip(path=ogg, is_voice_note=True)
            return VoiceClip(path=mp3, is_voice_note=False)

    # ------------------------------------------------------------------
    async def _edge(self, text: str, out: Path) -> None:
        voice = await self._resolve_voice()
        kwargs = {"voice": voice}
        if self._s.tts_rate:
            kwargs["rate"] = self._s.tts_rate
        communicate = edge_tts.Communicate(text, **kwargs)
        await communicate.save(str(out))

    def _gtts(self, text: str, out: Path) -> None:
        lang = (self._s.tts_voice or "uz")[:2].lower()
        try:
            gTTS(text=text, lang=lang).save(str(out))
        except Exception:  # noqa: BLE001 - noma'lum til bo'lsa ruschaga o'tamiz
            gTTS(text=text, lang="ru").save(str(out))

    async def _resolve_voice(self) -> str:
        """Sozlangan ovoz mavjudligini bir marta tekshiradi, bo'lmasa muqobil topadi."""
        if self._voice_checked and self._voice:
            return self._voice

        wanted = self._s.tts_voice
        self._voice = wanted
        self._voice_checked = True
        try:
            voices: List[dict] = await edge_tts.list_voices()
            names = {v["ShortName"] for v in voices}
            if wanted in names:
                return wanted
            lang = wanted.split("-")[0]
            same_lang = sorted(n for n in names if n.startswith(lang + "-"))
            if same_lang:
                self._voice = same_lang[0]
                log.warning("Ovoz '%s' topilmadi, '%s' ishlatiladi.", wanted, self._voice)
            else:
                self._voice = "ru-RU-DmitryNeural"
                log.warning("'%s' tili topilmadi, '%s' ishlatiladi.", lang, self._voice)
        except Exception as exc:  # noqa: BLE001
            log.debug("Ovozlar ro'yxatini olib bo'lmadi: %s", exc)
        return self._voice

    async def _to_opus(self, mp3: Path) -> Optional[Path]:
        """mp3 -> ogg/opus. Telegram'da haqiqiy voice message bo'lishi uchun kerak."""
        if not self._ffmpeg:
            return None
        ogg = mp3.with_suffix(".ogg")
        if ogg.exists():
            return ogg
        # Diqqat: asyncio.create_subprocess_exec Windows'da faqat ProactorEventLoop
        # bilan ishlaydi, shuning uchun ffmpeg alohida thread'da chaqiriladi.
        try:
            return await asyncio.to_thread(self._run_ffmpeg, mp3, ogg)
        except Exception as exc:  # noqa: BLE001
            log.debug("ffmpeg ishga tushmadi: %s", exc)
            return None

    def _run_ffmpeg(self, mp3: Path, ogg: Path) -> Optional[Path]:
        cmd = [
            self._ffmpeg, "-y", "-loglevel", "error",
            "-i", str(mp3),
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000", "-ac", "1",
            str(ogg),
        ]
        proc = subprocess.run(  # noqa: S603 - yo'l shutil.which dan olingan
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0 and ogg.exists():
            return ogg
        log.debug("ffmpeg xatosi: %s", proc.stderr.decode(errors="ignore")[:300])
        return None


def build_alert_speech(price: float, pips: float, side: str, symbol: str = "Tilla") -> str:
    """Qo'ng'iroq/ovozli xabar matni."""
    price_txt = f"{price:.2f}".replace(".", " nuqta ")
    if side == "inside":
        return (
            f"Diqqat! {symbol} narxi {price_txt} ga yetdi. "
            f"Narx zonaning ichiga kirdi. Takrorlayman: {price_txt}."
        )
    yo_nalish = "pastdan" if side == "below" else "yuqoridan"
    return (
        f"Diqqat! {symbol} narxi {price_txt} ga yetdi. "
        f"Zonagacha {pips:.0f} pips masofa qoldi, {yo_nalish} yaqinlashmoqda. "
        f"Takrorlayman: narx {price_txt}."
    )
