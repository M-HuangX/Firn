"""Tests for ticker validation and normalization — valid tickers, invalid tickers, suggestions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from src.data_sources.cache import get_cache
from src.data_sources.exceptions import ExternalAPIError, TickerNotFoundError
from src.data_sources.validation import (
    TickerValidationResult,
    normalize_ticker,
    validate_ticker,
    validate_ticker_lenient,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the TTLCache singleton before and after each test to prevent cross-test pollution."""
    get_cache().clear()
    yield
    get_cache().clear()


@pytest.fixture
def mock_yf_ticker():
    """Mock yf.Ticker to return a ticker object with valid info."""
    ticker_mock = MagicMock()
    ticker_mock.info = {"shortName": "Apple Inc.", "exchange": "NMS", "symbol": "AAPL"}
    with patch("src.data_sources.validation.yf.Ticker", return_value=ticker_mock):
        yield ticker_mock


@pytest.fixture
def mock_yf_ticker_invalid():
    """Mock yf.Ticker to return a ticker object with empty info (invalid ticker)."""
    ticker_mock = MagicMock()
    ticker_mock.info = {}
    with patch("src.data_sources.validation.yf.Ticker", return_value=ticker_mock):
        yield ticker_mock


@pytest.fixture
def mock_yf_search():
    """Mock yf.Search to return suggestion quotes."""
    search_mock = MagicMock()
    search_mock.quotes = [{"symbol": "AAPL"}, {"symbol": "APLE"}]
    with patch("src.data_sources.validation.yf.Search", return_value=search_mock):
        yield search_mock


# ---------------------------------------------------------------------------
# normalize_ticker tests
# ---------------------------------------------------------------------------


class TestNormalizeTicker:
    """Tests for normalize_ticker() — pure string validation, no I/O."""

    def test_normalize_basic(self):
        """Lowercase input is uppercased."""
        assert normalize_ticker("aapl") == "AAPL"

    def test_normalize_strips_whitespace(self):
        """Leading and trailing whitespace is stripped."""
        assert normalize_ticker("  msft  ") == "MSFT"

    def test_normalize_empty_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            normalize_ticker("")

    def test_normalize_too_long_raises(self):
        """A 20-character string exceeds _MAX_TICKER_LENGTH (15) and raises ValueError."""
        with pytest.raises(ValueError, match="too long"):
            normalize_ticker("A" * 20)

    def test_normalize_invalid_chars_raises(self):
        """Dollar signs and other special characters are rejected."""
        with pytest.raises(ValueError, match="invalid characters"):
            normalize_ticker("AA$PL")

    def test_normalize_dots_allowed(self):
        """Dots are valid ticker characters (e.g., BRK.B)."""
        assert normalize_ticker("BRK.B") == "BRK.B"

    def test_normalize_caret_allowed(self):
        """Carets are valid for index symbols (e.g., ^GSPC)."""
        assert normalize_ticker("^GSPC") == "^GSPC"

    def test_normalize_hyphen_allowed(self):
        """Hyphens are valid ticker characters (e.g., BF-B)."""
        assert normalize_ticker("BF-B") == "BF-B"


# ---------------------------------------------------------------------------
# validate_ticker tests
# ---------------------------------------------------------------------------


class TestValidateTicker:
    """Tests for validate_ticker() — async, requires mocking yfinance."""

    @pytest.mark.asyncio
    async def test_validate_valid_ticker(self, mock_yf_ticker):
        """A ticker whose info contains 'shortName' is valid."""
        result = await validate_ticker("aapl")
        assert isinstance(result, TickerValidationResult)
        assert result.valid is True
        assert result.ticker == "AAPL"
        assert result.name == "Apple Inc."
        assert result.exchange == "NMS"

    @pytest.mark.asyncio
    async def test_validate_invalid_ticker(self, mock_yf_ticker_invalid, mock_yf_search):
        """A ticker whose info is empty raises TickerNotFoundError with suggestions."""
        with pytest.raises(TickerNotFoundError) as exc_info:
            await validate_ticker("XYZZY")
        assert exc_info.value.ticker == "XYZZY"
        # Suggestions should include symbols from mocked search (excluding the ticker itself)
        assert "AAPL" in exc_info.value.suggestions
        assert "APLE" in exc_info.value.suggestions

    @pytest.mark.asyncio
    async def test_validate_network_error(self):
        """ConnectionError during yfinance call raises ExternalAPIError."""
        ticker_mock = MagicMock()
        # Make accessing .info raise ConnectionError
        type(ticker_mock).info = property(lambda self: (_ for _ in ()).throw(ConnectionError("no network")))
        with patch("src.data_sources.validation.yf.Ticker", return_value=ticker_mock):
            with pytest.raises(ExternalAPIError) as exc_info:
                await validate_ticker("AAPL")
            assert "network error" in exc_info.value.message.lower()
            assert exc_info.value.source == "yfinance"
            assert exc_info.value.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_validate_unexpected_error(self):
        """RuntimeError during yfinance call raises ExternalAPIError."""
        ticker_mock = MagicMock()
        type(ticker_mock).info = property(lambda self: (_ for _ in ()).throw(RuntimeError("something broke")))
        with patch("src.data_sources.validation.yf.Ticker", return_value=ticker_mock):
            with pytest.raises(ExternalAPIError) as exc_info:
                await validate_ticker("AAPL")
            assert "unexpectedly" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_validate_caches_valid_result(self, mock_yf_ticker):
        """A valid result is cached — second call does not hit yfinance again."""
        result1 = await validate_ticker("aapl")
        assert result1.valid is True

        # Reset the mock call count
        from src.data_sources.validation import yf
        with patch("src.data_sources.validation.yf.Ticker", return_value=mock_yf_ticker) as ticker_cls:
            result2 = await validate_ticker("aapl")
            # yf.Ticker should NOT be called because the result was cached
            ticker_cls.assert_not_called()

        assert result2.valid is True
        assert result2.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_validate_caches_invalid_result(self, mock_yf_ticker_invalid, mock_yf_search):
        """An invalid result is cached — second call re-raises TickerNotFoundError from cache."""
        with pytest.raises(TickerNotFoundError):
            await validate_ticker("XYZZY")

        # Second call should raise from cache without calling yf.Ticker
        with patch("src.data_sources.validation.yf.Ticker") as ticker_cls:
            with pytest.raises(TickerNotFoundError):
                await validate_ticker("XYZZY")
            ticker_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_network_error_not_cached(self):
        """Network errors are NOT cached — subsequent call retries yfinance."""
        ticker_mock = MagicMock()
        type(ticker_mock).info = property(lambda self: (_ for _ in ()).throw(ConnectionError("no network")))

        with patch("src.data_sources.validation.yf.Ticker", return_value=ticker_mock):
            with pytest.raises(ExternalAPIError):
                await validate_ticker("AAPL")

        # Verify cache has no entry for this ticker
        cache = get_cache()
        from src.data_sources.cache import _SENTINEL
        cached = cache.get("ticker_validation|AAPL")
        assert cached is _SENTINEL, "Network errors must not be cached"

        # Second call should attempt yfinance again
        good_mock = MagicMock()
        good_mock.info = {"shortName": "Apple Inc.", "exchange": "NMS", "symbol": "AAPL"}
        with patch("src.data_sources.validation.yf.Ticker", return_value=good_mock) as ticker_cls:
            result = await validate_ticker("AAPL")
            ticker_cls.assert_called_once()
            assert result.valid is True


# ---------------------------------------------------------------------------
# validate_ticker_lenient tests
# ---------------------------------------------------------------------------


class TestValidateTickerLenient:
    """Tests for validate_ticker_lenient() — thin wrapper over validate_ticker."""

    @pytest.mark.asyncio
    async def test_lenient_returns_normalized_ticker(self, mock_yf_ticker):
        """Returns the normalized ticker string on success."""
        result = await validate_ticker_lenient("aapl")
        assert result == "AAPL"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lenient_propagates_error(self, mock_yf_ticker_invalid, mock_yf_search):
        """TickerNotFoundError from validate_ticker propagates through."""
        with pytest.raises(TickerNotFoundError) as exc_info:
            await validate_ticker_lenient("XYZZY")
        assert exc_info.value.ticker == "XYZZY"


# ---------------------------------------------------------------------------
# TickerValidationResult tests
# ---------------------------------------------------------------------------


class TestTickerValidationResult:
    """Tests for the TickerValidationResult frozen dataclass."""

    def test_validation_result_frozen(self):
        """Cannot modify fields on a frozen dataclass instance."""
        result = TickerValidationResult(ticker="AAPL", valid=True, name="Apple Inc.")
        with pytest.raises(FrozenInstanceError):
            result.ticker = "MSFT"  # type: ignore[misc]

    def test_validation_result_suggestions_tuple(self):
        """The suggestions field stores a tuple, not a list."""
        result = TickerValidationResult(
            ticker="XYZZY",
            valid=False,
            suggestions=("AAPL", "APLE"),
        )
        assert isinstance(result.suggestions, tuple)
        assert result.suggestions == ("AAPL", "APLE")
