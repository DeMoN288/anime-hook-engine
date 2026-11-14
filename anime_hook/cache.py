from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


class DiskCache:
    """Thread-safe JSON cache with TTL-based expiration."""

    def __init__(
        self,
        directory: str | Path = ".cache/anime-hook",
        ttl_seconds: float = 3600,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        path = self._path_for(key)
        with self._lock:
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                expires_at = entry["expires_at"]
                if time.time() >= expires_at:
                    path.unlink(missing_ok=True)
                    return None
                return entry["value"]
            except (OSError, ValueError, TypeError, KeyError):
                path.unlink(missing_ok=True)
                return None

    def set(self, key: str, value: Any) -> None:
        path = self._path_for(key)
        entry = {
            "expires_at": time.time() + self.ttl_seconds,
            "value": value,
        }
        encoded = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(encoded)
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def clear(self) -> None:
        with self._lock:
            if not self.directory.exists():
                return
            for path in self.directory.glob("*.json"):
                path.unlink(missing_ok=True)
