"""A tiny on-disk response cache.

The MVP run model is one-shot over a frozen snapshot (PRODUCT_PLAN §9), but a transparent
cache of *API responses* (keyed by model + prompt + schema) is a pure engineering win: it
makes re-runs after an interruption, a crash, or a prompt tweak cheap, without changing
results. Disable with --no-cache.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional


class Cache:
    def __init__(self, directory: str, enabled: bool = True):
        self.dir = Path(directory)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*parts: Any) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update(repr(p).encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()[:40]

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        p = self._path(key)
        if p.exists():
            try:
                value = json.loads(p.read_text("utf-8"))
                self.hits += 1
                return value
            except Exception:
                return None
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        try:
            self._path(key).write_text(json.dumps(value), "utf-8")
        except Exception:
            pass  # cache is best-effort; never fail a run because of it
