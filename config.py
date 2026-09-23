"""Markaziy konfiguratsiya: .env faylidan o'qiladi."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _str(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key) or default)
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float((_str(key) or str(default)).replace(",", "."))
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = _str(key).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "ha"}


def _target(raw: str):
    """'@user' -> str, '123456' -> int, '+998..' -> str."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


@dataclass(frozen=True)
class Settings:
    # --- Telegram ---
    api_id: int
    api_hash: str
    phone: str
    session: str
    alert_target: object
    notify_chat: object
    admins: tuple = ()

    # --- MT5 ---
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""
    symbol: str = "XAUUSD"
    symbol_autodetect: bool = True

    # --- Alert mantiq ---
    pip_size: float = 0.1
    buffer_pips: float = 60.0
    poll_interval: float = 1.0
    rearm_pips: float = 30.0
    price_source: str = "bid"

    # --- Call ---
    call_enabled: bool = True
    call_ring_seconds: float = 25.0
    call_hangup_delay: float = 0.0
    call_retries: int = 2
    call_retry_delay: float = 8.0
    call_max_speak_seconds: float = 60.0

    # --- TTS ---
    tts_enabled: bool = True
    tts_voice: str = "uz-UZ-SardorNeural"
    tts_rate: str = "+10%"

    # --- Chart rasm ---
    chart_enabled: bool = True
    chart_timeframe: str = "M15"
    chart_bars: int = 120

    # --- MT5 chart vizual ko'prigi ---
    bridge_enabled: bool = True

    # --- Misc ---
    log_level: str = "INFO"
    heartbeat_minutes: int = 0

    # --- Yo'llar ---
    base_dir: Path = BASE_DIR
    zones_file: Path = field(default_factory=lambda: BASE_DIR / "zones.json")
    cache_dir: Path = field(default_factory=lambda: BASE_DIR / "data")

    # ---- hosila qiymatlar ----
    @property
    def buffer_price(self) -> float:
        """60 pips -> 6.00 USD."""
        return self.buffer_pips * self.pip_size

    @property
    def rearm_price(self) -> float:
        return self.rearm_pips * self.pip_size

    def to_pips(self, price_distance: float) -> float:
        return price_distance / self.pip_size if self.pip_size else 0.0


def load_settings() -> Settings:
    admins = tuple(
        t for t in (_target(x) for x in _str("ADMINS").split(",")) if t is not None
    )
    notify = _target(_str("NOTIFY_CHAT"))
    alert_target = _target(_str("ALERT_TARGET", "@CBU2025"))

    s = Settings(
        api_id=_int("TG_API_ID", 0),
        api_hash=_str("TG_API_HASH"),
        phone=_str("TG_PHONE"),
        session=_str("TG_SESSION", "sessions/userbot"),
        alert_target=alert_target,
        notify_chat=notify if notify is not None else alert_target,
        admins=admins,
        mt5_login=_int("MT5_LOGIN", 0),
        mt5_password=_str("MT5_PASSWORD"),
        mt5_server=_str("MT5_SERVER"),
        mt5_path=_str("MT5_PATH"),
        symbol=_str("SYMBOL", "XAUUSD"),
        symbol_autodetect=_bool("SYMBOL_AUTODETECT", True),
        pip_size=_float("PIP_SIZE", 0.1),
        buffer_pips=_float("BUFFER_PIPS", 60.0),
        poll_interval=max(0.2, _float("POLL_INTERVAL", 1.0)),
        rearm_pips=_float("REARM_PIPS", 30.0),
        price_source=_str("PRICE_SOURCE", "bid").lower(),
        call_enabled=_bool("CALL_ENABLED", True),
        call_ring_seconds=_float("CALL_RING_SECONDS", 25.0),
        call_hangup_delay=_float("CALL_HANGUP_DELAY", 0.0),
        call_retries=_int("CALL_RETRIES", 2),
        call_retry_delay=_float("CALL_RETRY_DELAY", 8.0),
        call_max_speak_seconds=_float("CALL_MAX_SPEAK_SECONDS", 60.0),
        tts_enabled=_bool("TTS_ENABLED", True),
        tts_voice=_str("TTS_VOICE", "uz-UZ-SardorNeural"),
        tts_rate=_str("TTS_RATE", "+10%"),
        chart_enabled=_bool("CHART_ENABLED", True),
        chart_timeframe=_str("CHART_TIMEFRAME", "M15").upper(),
        chart_bars=max(20, _int("CHART_BARS", 120)),
        bridge_enabled=_bool("BRIDGE_ENABLED", True),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        heartbeat_minutes=_int("HEARTBEAT_MINUTES", 0),
    )
    _validate(s)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "sessions").mkdir(parents=True, exist_ok=True)
    return s


def _validate(s: Settings) -> None:
    problems = []
    if not s.api_id or not s.api_hash:
        problems.append("TG_API_ID / TG_API_HASH to'ldirilmagan")
    if s.alert_target is None:
        problems.append("ALERT_TARGET to'ldirilmagan")
    if s.price_source not in {"bid", "ask", "mid"}:
        problems.append("PRICE_SOURCE faqat bid|ask|mid bo'lishi mumkin")
    if s.pip_size <= 0:
        problems.append("PIP_SIZE musbat bo'lishi kerak")
    if problems:
        raise SystemExit("Konfiguratsiya xatosi (.env):\n  - " + "\n  - ".join(problems))
