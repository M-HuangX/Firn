"""Data source layer — fetching, caching, validation, and exceptions."""

from .exceptions import (
    DataSourceError,
    ExternalAPIError,
    NoDataAvailableError,
    RateLimitError,
    TickerNotFoundError,
)
from .fred_source import FREDDataSource
from .validation import TickerValidationResult, normalize_ticker, validate_ticker, validate_ticker_lenient
from .yfinance_source import YFinanceDataSource

__all__ = [
    "DataSourceError",
    "ExternalAPIError",
    "FREDDataSource",
    "NoDataAvailableError",
    "RateLimitError",
    "TickerNotFoundError",
    "TickerValidationResult",
    "YFinanceDataSource",
    "normalize_ticker",
    "validate_ticker",
    "validate_ticker_lenient",
]
