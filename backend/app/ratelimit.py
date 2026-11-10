"""Fixed-window rate limiting. In-memory by default; Redis-backed when REDIS_URL is set (multi-instance safe)."""

import time
from collections import OrderedDict

from app.config import get_settings

_windows: OrderedDict[str, tuple[int, int]] = OrderedDict()  # key -> (window_start, count)
_MAX_KEYS = 50_000
_redis = None


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


async def hit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Register one request. Returns ``(allowed, retry_after_seconds)``."""
    global _redis
    settings = get_settings()
    if settings.redis_url:
        try:
            if _redis is None:
                import redis.asyncio as aioredis

                _redis = aioredis.from_url(settings.redis_url, socket_timeout=1.0)
            now = int(time.time())
            bucket = f"sa:rl:{key}:{now // window_seconds}"
            count = await _redis.incr(bucket)
            if count == 1:
                await _redis.expire(bucket, window_seconds + 1)
            return count <= limit, max(window_seconds - (now % window_seconds), 1)
        except Exception:  # noqa: BLE001 - never fail a request because the limiter backend is down
            pass
    return _memory_hit(key, limit, window_seconds)


def reset() -> None:
    _windows.clear()
