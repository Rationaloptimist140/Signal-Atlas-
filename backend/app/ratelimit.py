"""Fixed-window rate limiting.

* **Redis** (``REDIS_URL``) - shared counters, correct with any number of API instances. Required in
  production unless ``RATE_LIMIT_BACKEND=memory`` is set explicitly.
* **Memory** - per-process counters for local development and single-instance deployments.

Failing safely: when Redis is the configured backend and cannot be reached, *sensitive* limits
(sign-in, registration, tokens, key creation, billing) fail closed with ``RateLimitUnavailable``
(HTTP 503) rather than silently allowing unlimited attempts. Ordinary read traffic degrades to the
per-process limiter, so it is still limited on each instance.
"""

import time
from collections import OrderedDict

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger("ratelimit")

_windows: OrderedDict[str, tuple[int, int]] = OrderedDict()  # key -> (window_start, count)
_MAX_KEYS = 50_000
_redis = None
_redis_down_until = 0.0
_RETRY_AFTER_FAILURE_SECONDS = 5.0


class RateLimitUnavailable(Exception):
    """The shared limiter is unreachable and the operation is too sensitive to run unlimited."""


def _memory_hit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    now = int(time.time())
    start = now - (now % window_seconds)
    win_start, count = _windows.get(key, (start, 0))
    if win_start != start:
        win_start, count = start, 0
    count += 1
    _windows[key] = (win_start, count)
    _windows.move_to_end(key)
    while len(_windows) > _MAX_KEYS:
        _windows.popitem(last=False)
    return count <= limit, max(start + window_seconds - now, 1)


def _client():
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(get_settings().redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
    return _redis


async def _redis_hit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    now = int(time.time())
    bucket = f"sa:rl:{key}:{now // window_seconds}"
    async with _client().pipeline(transaction=True) as pipe:  # INCR + EXPIRE applied atomically
        pipe.incr(bucket)
        pipe.expire(bucket, window_seconds + 1)
        count, _ = await pipe.execute()
    return int(count) <= limit, max(window_seconds - (now % window_seconds), 1)


async def hit(key: str, limit: int, window_seconds: int = 60, *, sensitive: bool = False) -> tuple[bool, int]:
    """Register one request. Returns ``(allowed, retry_after_seconds)``."""
    global _redis_down_until
    if get_settings().rate_limit_uses_redis:
        if time.monotonic() >= _redis_down_until:
            try:
                return await _redis_hit(key, limit, window_seconds)
            except Exception as exc:  # noqa: BLE001 - any backend failure takes the same safe path
                _redis_down_until = time.monotonic() + _RETRY_AFTER_FAILURE_SECONDS
                log.error("rate_limit_backend_unavailable", error=type(exc).__name__)
        if sensitive:
            raise RateLimitUnavailable("rate limit backend unavailable")
    return _memory_hit(key, limit, window_seconds)


async def status() -> dict:
    """Backend in use and whether it is reachable (for the readiness probe)."""
    if not get_settings().rate_limit_uses_redis:
        return {"backend": "memory", "healthy": True, "shared": False}
    try:
        await _client().ping()
        return {"backend": "redis", "healthy": True, "shared": True}
    except Exception:  # noqa: BLE001
        return {"backend": "redis", "healthy": False, "shared": True}


def reset() -> None:
    global _redis, _redis_down_until
    _windows.clear()
    _redis = None
    _redis_down_until = 0.0
