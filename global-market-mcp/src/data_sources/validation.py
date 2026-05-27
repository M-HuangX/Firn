"""Ticker validation and normalization for the MCP data source layer.

Provides:
- normalize_ticker(): Cleans and uppercases ticker strings.
- validate_ticker(): Validates a ticker against yfinance, with caching and suggestions.
- validate_ticker_lenient(): Convenience wrapper that returns the normalized ticker or raises.
- TickerValidationResult: Frozen dataclass with validation outcome.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import yfinance as yf

from ..config import CacheTTL
from .exceptions import ExternalAPIError, TickerNotFoundError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Maximum ticker length (NYSE/NASDAQ tickers are at most 5 chars,
# but some OTC / international tickers can be longer).
_MAX_TICKER_LENGTH: int = 15

# Pattern: letters, digits, dots, hyphens, carets (for indices like ^GSPC).
_VALID_TICKER_RE: re.Pattern[str] = re.compile(r"^[A-Z0-9.\-^]+$")


@dataclass(frozen=True)
class TickerValidationResult:
    """Result of a ticker validation check.

    Attributes:
        ticker: The normalized ticker symbol.
        valid: Whether the ticker is recognized by the data source.
        name: The security's short name, if valid.
        exchange: The exchange the security trades on, if valid.
        suggestions: Alternative ticker symbols if the ticker is invalid.
    """

    ticker: str
    valid: bool
    name: str | None = None
    exchange: str | None = None
    suggestions: tuple[str, ...] | None = None


def normalize_ticker(ticker: str) -> str:
    """Normalize a ticker symbol: strip whitespace, uppercase, basic validation.

    Args:
        ticker: Raw ticker string from user input.

    Returns:
        Cleaned and uppercased ticker string.

    Raises:
        ValueError: If the ticker is empty, too long, or contains invalid characters.
    """
    cleaned = ticker.strip().upper()

    if not cleaned:
        raise ValueError("Ticker symbol cannot be empty.")

    if len(cleaned) > _MAX_TICKER_LENGTH:
        raise ValueError(
            f"Ticker symbol '{cleaned}' is too long "
            f"(max {_MAX_TICKER_LENGTH} characters)."
        )

    if not _VALID_TICKER_RE.match(cleaned):
        raise ValueError(
            f"Ticker symbol '{cleaned}' contains invalid characters. "
            "Only letters, digits, dots, hyphens, and carets are allowed."
        )

    return cleaned


async def _run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous function in a thread to avoid blocking the event loop.

    All yfinance calls in validation go through this helper. yfinance uses
    requests internally and Ticker objects do not share mutable state, making
    them safe for concurrent thread execution.

    Args:
        func: The synchronous callable to execute.
        *args: Positional arguments forwarded to func.
        **kwargs: Keyword arguments forwarded to func.

    Returns:
        The return value of func(*args, **kwargs).
    """
    return await asyncio.to_thread(func, *args, **kwargs)


async def _find_suggestions(ticker: str) -> list[str]:
    """Search for similar ticker symbols using yfinance.

    Args:
        ticker: The ticker that failed validation.

    Returns:
        Up to 5 alternative ticker symbols, or an empty list on failure.
    """
    try:
        search = await _run_sync(yf.Search, ticker)
        quotes = search.quotes

        if not quotes:
            return []

        suggestions: list[str] = []
        for quote in quotes[:5]:
            symbol = quote.get("symbol")
            if symbol and symbol != ticker:
                suggestions.append(symbol)

        return suggestions

    except Exception as e:
        logger.debug("Failed to find suggestions for '%s': %s", ticker, e)
        return []


async def validate_ticker(ticker: str) -> TickerValidationResult:
    """Validate a ticker symbol against yfinance.

    Normalizes the ticker, checks the cache, then queries yfinance for
    confirmation. Results are cached (valid: 24h, invalid: 1h).

    Args:
        ticker: Raw ticker string to validate.

    Returns:
        TickerValidationResult with validation outcome.

    Raises:
        TickerNotFoundError: If the ticker is not recognized (includes suggestions).
        ExternalAPIError: If a network or infrastructure error prevents validation.
        ValueError: If the ticker string is syntactically invalid (empty, too long, etc.).
    """
    normalized = normalize_ticker(ticker)

    # Lazy import to avoid circular imports (cache.py may import from this package)
    from .cache import _SENTINEL, get_cache

    cache = get_cache()
    cache_key = f"ticker_validation|{normalized}"

    # Check cache first
    cached_result = cache.get(cache_key)
    if cached_result is not _SENTINEL:
        if isinstance(cached_result, TickerValidationResult):
            if cached_result.valid:
                return cached_result
            # Cached as invalid — re-raise
            raise TickerNotFoundError(
                ticker=cached_result.ticker,
                suggestions=list(cached_result.suggestions) if cached_result.suggestions else None,
            )

    # Validate against yfinance
    try:
        yf_ticker = yf.Ticker(normalized)
        info = await _run_sync(getattr, yf_ticker, "info")

        if not info or not info.get("shortName"):
            suggestions = await _find_suggestions(normalized)
            result = TickerValidationResult(
                ticker=normalized,
                valid=False,
                suggestions=tuple(suggestions),
            )
            cache.set(cache_key, result, ttl_seconds=3600)  # Invalid: 1 hour
            raise TickerNotFoundError(
                ticker=normalized,
                suggestions=list(suggestions) if suggestions else None,
            )

        result = TickerValidationResult(
            ticker=normalized,
            valid=True,
            name=info.get("shortName"),
            exchange=info.get("exchange"),
        )
        cache.set(cache_key, result, ttl_seconds=CacheTTL.TICKER_VALIDATION)  # Valid: 24 hours
        return result

    except TickerNotFoundError:
        raise
    except (ConnectionError, TimeoutError, OSError) as e:
        # Network/infrastructure errors — DO NOT cache, DO NOT report as "not found"
        logger.warning("Network error during ticker validation for '%s': %s", normalized, e)
        raise ExternalAPIError(
            message=f"Could not validate ticker '{normalized}' due to network error: {e}",
            source="yfinance",
            ticker=normalized,
        ) from e
    except Exception as e:
        # Unexpected errors — also infrastructure, not "not found"
        logger.warning("Unexpected error during ticker validation for '%s': %s", normalized, e)
        raise ExternalAPIError(
            message=f"Ticker validation failed unexpectedly: {e}",
            source="yfinance",
            ticker=normalized,
        ) from e


async def validate_ticker_lenient(ticker: str) -> str:
    """Convenience wrapper: normalize and validate, return the normalized ticker on success.

    Used by the tool layer as a one-liner before passing tickers to data source methods.

    Args:
        ticker: Raw ticker string from user input.

    Returns:
        The normalized (uppercased, stripped) ticker string.

    Raises:
        TickerNotFoundError: If the ticker is not recognized.
        ExternalAPIError: If a network or infrastructure error prevents validation.
        ValueError: If the ticker string is syntactically invalid.
    """
    result = await validate_ticker(ticker)
    return result.ticker
