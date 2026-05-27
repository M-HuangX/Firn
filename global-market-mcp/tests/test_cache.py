"""Tests for the TTL cache implementation — expiry, LRU eviction, concurrent deduplication."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.data_sources import cache
from src.data_sources.cache import (
    CacheEntry,
    TTLCache,
    _make_cache_key,
    _SENTINEL,
    cached,
    get_cache,
)



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_cache() -> TTLCache:
    """Create a fresh TTLCache instance for isolation (not the module singleton)."""
    return TTLCache(max_size=16)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset the module-level singleton before and after each test."""
    cache._cache = None
    yield  # type: ignore[misc]
    cache._cache = None


# ===========================================================================
# CacheEntry
# ===========================================================================


class TestCacheEntry:
    def test_cache_entry_not_expired(self) -> None:
        """Freshly created entry with future expiration is not expired."""
        entry = CacheEntry(value="hello", expires_at=time.monotonic() + 3600)
        assert not entry.is_expired

    def test_cache_entry_expired(self) -> None:
        """Entry with expiration in the past is expired."""
        entry = CacheEntry(value="hello", expires_at=time.monotonic() - 1)
        assert entry.is_expired


# ===========================================================================
# TTLCache — basic get / set
# ===========================================================================


class TestTTLCacheBasic:
    def test_get_miss_returns_sentinel(self, fresh_cache: TTLCache) -> None:
        """get() on an empty cache returns _SENTINEL."""
        result = fresh_cache.get("nonexistent")
        assert result is _SENTINEL

    def test_set_and_get(self, fresh_cache: TTLCache) -> None:
        """set() followed by get() returns the cached value."""
        fresh_cache.set("key1", {"data": 42}, ttl_seconds=60)
        result = fresh_cache.get("key1")
        assert result == {"data": 42}

    def test_get_expired_entry(self, fresh_cache: TTLCache) -> None:
        """Expired entry returns _SENTINEL and is removed from cache."""
        # Insert with a TTL that has already elapsed
        fresh_cache._cache["expired_key"] = CacheEntry(
            value="stale", expires_at=time.monotonic() - 1
        )
        fresh_cache._access_order.append("expired_key")

        result = fresh_cache.get("expired_key")
        assert result is _SENTINEL
        assert "expired_key" not in fresh_cache._cache

    def test_cache_none_value(self, fresh_cache: TTLCache) -> None:
        """None is a valid cached value (must not be confused with a cache miss)."""
        fresh_cache.set("none_key", None, ttl_seconds=60)
        result = fresh_cache.get("none_key")
        assert result is None
        assert result is not _SENTINEL


# ===========================================================================
# TTLCache — LRU eviction
# ===========================================================================


class TestTTLCacheEviction:
    def test_lru_eviction(self) -> None:
        """When cache is at max_size, setting a new key evicts the LRU entry."""
        small_cache = TTLCache(max_size=3)
        small_cache.set("a", 1, ttl_seconds=60)
        small_cache.set("b", 2, ttl_seconds=60)
        small_cache.set("c", 3, ttl_seconds=60)

        # Access "a" to make it recently used; "b" becomes LRU
        small_cache.get("a")

        # Insert a 4th entry — should evict "b" (LRU)
        small_cache.set("d", 4, ttl_seconds=60)

        assert small_cache.get("b") is _SENTINEL
        assert small_cache.get("a") == 1
        assert small_cache.get("c") == 3
        assert small_cache.get("d") == 4

    def test_lru_prefers_expired(self) -> None:
        """Eviction prefers expired entries over the LRU entry."""
        small_cache = TTLCache(max_size=3)
        small_cache.set("a", 1, ttl_seconds=60)
        small_cache.set("b", 2, ttl_seconds=60)
        small_cache.set("c", 3, ttl_seconds=60)

        # Manually expire "c"
        small_cache._cache["c"] = CacheEntry(
            value=3, expires_at=time.monotonic() - 1
        )

        # Insert a 4th entry — should evict expired "c", not LRU "a"
        small_cache.set("d", 4, ttl_seconds=60)

        assert small_cache.get("a") == 1
        assert small_cache.get("b") == 2
        assert small_cache.get("c") is _SENTINEL  # was expired and evicted
        assert small_cache.get("d") == 4


# ===========================================================================
# TTLCache — cleanup, clear, stats, max_size
# ===========================================================================


class TestTTLCacheUtilities:
    def test_cleanup_expired(self, fresh_cache: TTLCache) -> None:
        """cleanup_expired removes all expired entries and orphaned locks."""
        fresh_cache.set("alive", "ok", ttl_seconds=3600)
        # Insert expired entries
        for i in range(5):
            key = f"dead_{i}"
            fresh_cache._cache[key] = CacheEntry(
                value=i, expires_at=time.monotonic() - 1
            )
            fresh_cache._access_order.append(key)
            fresh_cache._locks[key] = asyncio.Lock()

        removed = fresh_cache.cleanup_expired()
        assert removed == 5
        assert fresh_cache.size == 1
        assert fresh_cache.get("alive") == "ok"
        # Orphaned locks for dead keys should be cleaned up
        for i in range(5):
            assert f"dead_{i}" not in fresh_cache._locks

    def test_clear(self, fresh_cache: TTLCache) -> None:
        """clear() removes everything and resets stats."""
        fresh_cache.set("x", 1, ttl_seconds=60)
        fresh_cache.set("y", 2, ttl_seconds=60)
        fresh_cache.get("x")  # generates a hit
        fresh_cache.get("miss_key")  # generates a miss

        fresh_cache.clear()

        assert fresh_cache.size == 0
        assert fresh_cache.stats.hits == 0
        assert fresh_cache.stats.misses == 0
        assert len(fresh_cache._access_order) == 0
        assert len(fresh_cache._locks) == 0

    def test_stats_tracking(self, fresh_cache: TTLCache) -> None:
        """Hits and misses are counted correctly."""
        fresh_cache.set("k", "v", ttl_seconds=60)

        fresh_cache.get("k")  # hit
        fresh_cache.get("k")  # hit
        fresh_cache.get("nope")  # miss
        fresh_cache.get("also_nope")  # miss
        fresh_cache.get("still_nope")  # miss

        assert fresh_cache.stats.hits == 2
        assert fresh_cache.stats.misses == 3

    def test_max_size_property(self) -> None:
        """max_size returns the configured value."""
        c = TTLCache(max_size=512)
        assert c.max_size == 512


# ===========================================================================
# _make_cache_key
# ===========================================================================


class TestMakeCacheKey:
    def test_cache_key_standalone_function(self) -> None:
        """Correct key for a standalone async function."""

        async def fetch_data(ticker: str, period: str = "1y") -> dict[str, Any]:
            ...

        key = _make_cache_key(fetch_data, ("AAPL",), {})
        assert "fetch_data" in key
        assert "ticker='AAPL'" in key
        assert "period='1y'" in key  # default applied

    def test_cache_key_method_excludes_self(self) -> None:
        """'self' parameter is excluded from the cache key."""

        class DataSource:
            async def get_info(self, ticker: str) -> dict[str, Any]:
                ...

        ds = DataSource()
        key = _make_cache_key(DataSource.get_info, (ds, "MSFT"), {})
        # 'self=' should not appear as a parameter binding in the key
        assert "self=" not in key
        assert "ticker='MSFT'" in key

    def test_cache_key_with_kwargs(self) -> None:
        """Keyword arguments are included in the key."""

        async def search(query: str, limit: int = 10) -> list[str]:
            ...

        key = _make_cache_key(search, (), {"query": "tech", "limit": 5})
        assert "query='tech'" in key
        assert "limit=5" in key

    def test_cache_key_long_key_hashed(self) -> None:
        """Keys longer than 256 characters are SHA-256 hashed."""

        async def process(data: str) -> str:
            ...

        long_arg = "x" * 300
        key = _make_cache_key(process, (long_arg,), {})
        assert ":" in key
        # The hash part should be a valid sha256 hex digest (64 chars)
        hash_part = key.split(":", 1)[1]
        assert len(hash_part) == 64
        # Verify it matches the expected hash
        expected_key_str = f"TestMakeCacheKey.test_cache_key_long_key_hashed.<locals>.process|data='{long_arg}'"
        expected_hash = hashlib.sha256(expected_key_str.encode()).hexdigest()
        assert hash_part == expected_hash


# ===========================================================================
# @cached decorator
# ===========================================================================


class TestCachedDecorator:
    async def test_cached_returns_value(self) -> None:
        """Decorated function returns the correct value."""

        @cached(ttl_seconds=60)
        async def compute(x: int, y: int) -> int:
            return x + y

        result = await compute(3, 4)
        assert result == 7

    async def test_cached_hits_cache(self) -> None:
        """Second call returns cached value without calling the function again."""
        call_count = 0

        @cached(ttl_seconds=60)
        async def expensive(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result_{key}"

        r1 = await expensive("abc")
        r2 = await expensive("abc")
        assert r1 == "result_abc"
        assert r2 == "result_abc"
        assert call_count == 1

    async def test_cached_with_ttl_func(self) -> None:
        """Dynamic TTL via ttl_func works correctly."""
        call_count = 0

        def dynamic_ttl() -> float:
            return 120.0

        @cached(ttl_func=dynamic_ttl)
        async def fetch(item: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"fetched_{item}"

        r1 = await fetch("data")
        r2 = await fetch("data")
        assert r1 == "fetched_data"
        assert r2 == "fetched_data"
        assert call_count == 1

    async def test_cached_concurrent_dedup(self) -> None:
        """Multiple concurrent calls result in only one function execution."""
        call_count = 0
        gate = asyncio.Event()

        @cached(ttl_seconds=60)
        async def slow_fetch(ticker: str) -> str:
            nonlocal call_count
            call_count += 1
            await gate.wait()
            return f"price_{ticker}"

        # Launch 5 concurrent calls for the same key
        tasks = [asyncio.create_task(slow_fetch("AAPL")) for _ in range(5)]

        # Let them all start and compete for the lock
        await asyncio.sleep(0.05)

        # Release the gate so the one executing call completes
        gate.set()

        results = await asyncio.gather(*tasks)

        assert all(r == "price_AAPL" for r in results)
        assert call_count == 1

    def test_cached_requires_ttl(self) -> None:
        """Raises ValueError if neither ttl_seconds nor ttl_func is provided."""
        with pytest.raises(ValueError, match="requires either"):

            @cached()
            async def noop() -> None:
                ...

    def test_cached_rejects_both_ttl(self) -> None:
        """Raises ValueError if both ttl_seconds and ttl_func are provided."""
        with pytest.raises(ValueError, match="not both"):

            @cached(ttl_seconds=60, ttl_func=lambda: 60.0)
            async def noop() -> None:
                ...


# ===========================================================================
# get_cache singleton
# ===========================================================================


class TestGetCacheSingleton:
    def test_get_cache_returns_same_instance(self) -> None:
        """get_cache() returns the same instance on repeated calls (singleton)."""
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2
