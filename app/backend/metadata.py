"""Best-effort metadata lookup with subprocess isolation and short-lived caching."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from app.backend.inputs import ensure_supported_single_track

METADATA_TIMEOUT = max(3, int(os.getenv("SPOTDL_METADATA_TIMEOUT", "45")))
METADATA_CACHE_TTL = max(30, int(os.getenv("SPOTDL_METADATA_CACHE_TTL", "600")))
METADATA_CONCURRENCY = max(1, int(os.getenv("SPOTDL_METADATA_CONCURRENCY", "2")))


class MetadataError(RuntimeError):
    """Structured metadata failure for the HTTP layer."""

    def __init__(self, message: str, *, code: str = "metadata_error", status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class _CacheEntry:
    metadata: dict[str, str]
    song_payload: Optional[dict[str, Any]]
    expires_at: float


class MetadataService:
    """Resolve UI metadata without letting library/network hangs wedge Flask."""

    def __init__(
        self,
        *,
        timeout: int = METADATA_TIMEOUT,
        cache_ttl: int = METADATA_CACHE_TTL,
        metadata_concurrency: int = METADATA_CONCURRENCY,
    ) -> None:
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.metadata_concurrency = max(1, metadata_concurrency)
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = threading.RLock()
        self._worker_slots = threading.BoundedSemaphore(self.metadata_concurrency)

    @staticmethod
    def _command() -> list[str]:
        return [sys.executable, "-m", "app.backend.metadata_worker"]

    def _lookup_cache(self, key: str) -> Optional[_CacheEntry]:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() >= entry.expires_at:
                self._cache.pop(key, None)
                return None
            return entry

    def _store_cache(
        self,
        *,
        key: str,
        metadata: dict[str, str],
        song_payload: Optional[dict[str, Any]],
    ) -> None:
        with self._cache_lock:
            self._cache[key] = _CacheEntry(
                metadata=dict(metadata),
                song_payload=dict(song_payload) if song_payload else None,
                expires_at=time.monotonic() + self.cache_ttl,
            )

    def get_cached_song_payload(self, link: str) -> Optional[dict[str, Any]]:
        """Return a cached song payload, if one is still fresh."""
        info = ensure_supported_single_track(link)
        for key in (link.strip(), info.normalized):
            entry = self._lookup_cache(key)
            if entry and entry.song_payload is not None:
                return dict(entry.song_payload)
        return None

    def get_metadata(self, link: str) -> dict[str, str]:
        """Fetch metadata via a short-lived subprocess and cache the result."""
        info = ensure_supported_single_track(link)
        for key in (link.strip(), info.normalized):
            entry = self._lookup_cache(key)
            if entry is not None:
                return dict(entry.metadata)

        try:
            with self._worker_slots:
                completed = subprocess.run(
                    self._command(),
                    input=json.dumps({"link": info.normalized}, ensure_ascii=True),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise MetadataError(
                f"Metadata lookup timed out after {self.timeout} seconds.",
                code="metadata_timeout",
                status_code=504,
            ) from exc

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if not stdout:
            raise MetadataError(
                stderr or "Metadata worker returned no data.",
                code="metadata_worker_error",
                status_code=502,
            )

        try:
            payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError as exc:
            raise MetadataError(
                "Metadata worker returned malformed data.",
                code="metadata_worker_error",
                status_code=502,
            ) from exc

        if not isinstance(payload, dict):
            raise MetadataError(
                "Metadata worker returned an invalid response.",
                code="metadata_worker_error",
                status_code=502,
            )

        if payload.get("ok") is not True:
            message = str(payload.get("error") or "Failed to load track metadata.")
            code = str(payload.get("code") or "metadata_error")
            status_code = 400 if code == "unsupported_input" else 502
            raise MetadataError(message, code=code, status_code=status_code)

        metadata = payload.get("metadata") or {}
        song_payload = payload.get("song_payload")
        if not isinstance(metadata, dict):
            raise MetadataError(
                "Metadata worker returned invalid metadata.",
                code="metadata_worker_error",
                status_code=502,
            )

        normalized_metadata = {
            "title": str(metadata.get("title") or "(unknown)"),
            "artist": str(metadata.get("artist") or ""),
            "album": str(metadata.get("album") or ""),
            "cover": str(metadata.get("cover") or ""),
        }
        for key in (link.strip(), info.normalized):
            self._store_cache(
                key=key,
                metadata=normalized_metadata,
                song_payload=song_payload if isinstance(song_payload, dict) else None,
            )
        return dict(normalized_metadata)
