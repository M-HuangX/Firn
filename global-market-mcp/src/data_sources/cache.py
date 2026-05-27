"""TTL cache with concurrent request deduplication and LRU eviction for the MCP data source layer.

Components:
- CacheEntry: Holds a cached value with monotonic expiration timestamp.
- CacheStats: Hit/miss counters for observability.
- TTLCache: Bounded async-aware cache with per-key locking and LRU eviction.
- _make_cache_key(): Deterministic key generation using inspect.signature.
- @cached(): Decorator for transparent caching with static or dynamic TTL.
- get_cache(): Module-level singleton accessor.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SENTINEL = object()
_MAX_KEY_LENGTH = 256


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A single cached value with a monotonic expiration timestamp.

    Attributes:
        value: The cached data (any type).
        expires_at: Absolute expiration time from ``time.monotonic()``.
    """

    value: Any
    expires_at: float

    @property
    def is_expired(self) -> bool:
        """Return True if this entry has passed its expiration time."""
        return time.monotonic() >= self.expires_at


@dataclass
class CacheStats:
    """Basic cache observability counters.

    Attributes:
        hits: Number of cache hits (key found and not expired).
        misses: Number of cache misses (key absent or expired).
    """

    hits: int = 0
    misses: int = 0


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------


class TTLCache:
    """Bounded TTL cache with per-key locking for concurrent request deduplication.

    Features:
        - Time-based expiration using ``time.monotonic()`` (immune to wall-clock changes).
        - LRU eviction when the cache reaches ``max_size``.
        - Per-key ``asyncio.Lock`` to deduplicate concurrent requests for the same key.
        - Periodic cleanup of expired entries and orphaned locks.

    Attributes:
        stats: A ``CacheStats`` instance tracking hit/miss counts.
    """

    def __init__(self, max_size: int = 2048) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._max_size = max_size
        self._access_order: list[str] = []
        self.stats = CacheStats()

    def get(self, key: str) -> Any:
        """Retrieve a value from the cache.

        Returns the cached value if found and not expired, otherwise returns
        the module-level ``_SENTINEL`` object to distinguish a miss from a
        cached ``None`` value.

        Args:
            key: The cache key to look up.

        Returns:
            The cached value on hit, or ``_SENTINEL`` on miss/expiry.
        """
        entry = self._cache.get(key)
        if entry is None:
            self.stats.misses += 1
            return _SENTINEL
        if entry.is_expired:
            del self._cache[key]
            self.stats.misses += 1
            return _SENTINEL
        # Update access order for LRU
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
        self.stats.hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a value in the cache with the given TTL.

        If the cache is at capacity, expired entries are evicted first,
        then the least recently used entry is evicted.

        Args:
            key: The cache key.
            value: The value to cache.
            ttl_seconds: Time-to-live in seconds.
        """
        # If key already exists, remove old access order entry
        if key in self._access_order:
            self._access_order.remove(key)
        # Evict if at capacity (only if key is not already present)
        if key not in self._cache:
            while len(self._cache) >= self._max_size:
                self._evict_lru()
        self._cache[key] = CacheEntry(
            value=value,
            expires_at=time.monotonic() + ttl_seconds,
        )
        self._access_order.append(key)

    def _evict_lru(self) -> None:
        """Evict one entry: prefer expired entries, otherwise evict the least recently used."""
        # First try to remove an expired entry
        for k, v in self._cache.items():
            if v.is_expired:
                del self._cache[k]
                if k in self._access_order:
                    self._access_order.remove(k)
                return
        # Otherwise evict the least recently used
        if self._access_order:
            key = self._access_order.pop(0)
            self._cache.pop(key, None)

    def cleanup_expired(self) -> int:
        """Remove all expired entries and orphaned locks.

        Returns:
            The number of expired entries that were removed.
        """
        expired = [k for k, v in self._cache.items() if v.is_expired]
        for k in expired:
            del self._cache[k]
            if k in self._access_order:
                self._access_order.remove(k)
        # Clean up locks for keys no longer in cache
        orphaned_locks = [k for k in self._locks if k not in self._cache]
        for k in orphaned_locks:
            if not self._locks[k].locked():
                del self._locks[k]
        return len(expired)

    def clear(self) -> None:
        """Remove all entries, locks, and reset stats."""
        self._cache.clear()
        self._locks.clear()
        self._access_order.clear()
        self.stats = CacheStats()

    async def get_or_create_lock(self, key: str) -> asyncio.Lock:
        """Get or create a per-key lock for concurrent request deduplication.

        Uses a global lock to ensure only one ``asyncio.Lock`` is created
        per cache key, even under concurrent access.

        Args:
            key: The cache key to get a lock for.

        Returns:
            An ``asyncio.Lock`` specific to this key.
        """
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    @property
    def size(self) -> int:
        """Return the current number of entries in the cache."""
        return len(self._cache)

    @property
    def max_size(self) -> int:
        """Return the maximum capacity of the cache."""
        return self._max_size


# ---------------------------------------------------------------------------
# Cache key generation
# ---------------------------------------------------------------------------


def _make_cache_key(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Generate a deterministic cache key from function name and arguments.

    Uses ``inspect.signature`` to properly bind arguments and exclude
    ``self``/``cls`` parameters. This avoids the unreliable ``hasattr``
    heuristic for bound method detection.

    If binding fails (e.g., variadic-only signatures), falls back to
    ``repr``-based key generation. Keys longer than 256 characters are
    truncated to ``qualname:sha256_hex``.

    Args:
        func: The original (unwrapped) function or method.
        args: Positional arguments passed to the call.
        kwargs: Keyword arguments passed to the call.

    Returns:
        A string cache key.
    """
    sig = inspect.signature(func)
    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
    except TypeError:
        # Fallback for edge cases (e.g., *args-only signatures)
        key_str = f"{func.__qualname__}|{repr(args)}|{repr(sorted(kwargs.items()))}"
        if len(key_str) > _MAX_KEY_LENGTH:
            return func.__qualname__ + ":" + hashlib.sha256(key_str.encode()).hexdigest()
        return key_str

    # Filter out 'self' and 'cls'
    key_parts: list[str] = [func.__qualname__]
    for param_name, value in bound.arguments.items():
        if param_name in ("self", "cls"):
            continue
        key_parts.append(f"{param_name}={repr(value)}")

    key_str = "|".join(key_parts)
    if len(key_str) > _MAX_KEY_LENGTH:
        return func.__qualname__ + ":" + hashlib.sha256(key_str.encode()).hexdigest()
    return key_str


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------


def cached(
    ttl_seconds: float | None = None,
    ttl_func: Callable[..., float] | None = None,
) -> Callable[..., Any]:
    """Decorator for transparent caching with concurrent request deduplication.

    Supports both a static TTL and a dynamic TTL via a callable. Exactly one
    of ``ttl_seconds`` or ``ttl_func`` must be provided.

    The decorator works on both async standalone functions and async methods
    (with ``self``). Cache keys automatically exclude ``self``/``cls`` via
    ``_make_cache_key``.

    Per-key locking ensures that if multiple coroutines request the same
    cache key concurrently, only one executes the underlying function while
    the others wait and receive the cached result.

    Args:
        ttl_seconds: Static time-to-live in seconds.
        ttl_func: A callable that returns the TTL in seconds. Called with
            no arguments at decoration time (e.g., a function that checks
            market hours to decide the TTL).

    Raises:
        ValueError: If neither or both of ``ttl_seconds`` and ``ttl_func``
            are provided.

    Returns:
        A decorator that wraps an async function with caching behaviour.

    Example::

        @cached(ttl_seconds=300)
        async def get_stock_info(self, ticker: str) -> dict[str, Any]:
            ...

        @cached(ttl_func=_price_data_ttl)
        async def get_price_history(self, ticker: str, period: str) -> Any:
            ...
    """
    if ttl_seconds is None and ttl_func is None:
        raise ValueError("@cached requires either ttl_seconds or ttl_func")
    if ttl_seconds is not None and ttl_func is not None:
        raise ValueError("@cached accepts ttl_seconds or ttl_func, not both")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache()
            key = _make_cache_key(func, args, kwargs)

            # Fast path: check cache before acquiring lock
            result = cache.get(key)
            if result is not _SENTINEL:
                return result

            # Slow path: acquire per-key lock for deduplication
            lock = await cache.get_or_create_lock(key)
            async with lock:
                # Double-check after acquiring lock (another coroutine may have populated it)
                result = cache.get(key)
                if result is not _SENTINEL:
                    return result

                # Execute the actual function
                value = await func(*args, **kwargs)

                # Determine TTL
                ttl = ttl_seconds if ttl_seconds is not None else ttl_func()  # type: ignore[misc]

                cache.set(key, value, ttl)
                return value

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_cache: TTLCache | None = None


def get_cache() -> TTLCache:
    """Return the module-level TTLCache singleton, creating it on first access.

    Returns:
        The shared ``TTLCache`` instance used across the MCP server.
    """
    global _cache
    if _cache is None:
        _cache = TTLCache()
    return _cache
