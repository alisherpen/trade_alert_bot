"""zones.json uchun atomik, buzilishga chidamli JSON saqlagich."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class JsonStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    # ---------- public ----------
    async def load(self, default: Any = None) -> Any:
        async with self._lock:
            return await asyncio.to_thread(self._load_sync, default)

    async def save(self, data: Any) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_sync, data)

    # ---------- internal ----------
    def _load_sync(self, default: Any) -> Any:
        if not self.path.exists():
            return default if default is not None else {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            broken = self.path.with_suffix(self.path.suffix + ".broken")
            log.error("%s o'qib bo'lmadi (%s). Zaxira: %s", self.path.name, exc, broken.name)
            try:
                shutil.copy2(self.path, broken)
            except OSError:
                pass
            return default if default is not None else {}

    def _save_sync(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        # Bir xil papkaga vaqtinchalik fayl -> os.replace atomik almashtiradi.
        fd, tmp_name = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
