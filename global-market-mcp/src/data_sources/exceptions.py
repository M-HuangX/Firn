"""Exception hierarchy for the data source layer.

All data source exceptions carry structured context so MCP tools
can format user-friendly error messages without parsing strings.
"""


class DataSourceError(Exception):
    """Base exception for all data source errors.

    Attributes:
        source: Name of the data source that failed (e.g., "yfinance", "fredapi").
        ticker: The ticker/symbol involved, if applicable.
        message: Human-readable error description.
    """

    def __init__(
        self,
        message: str,
        source: str = "unknown",
        ticker: str | None = None,
    ) -> None:
        self.source = source
        self.ticker = ticker
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        parts = [f"[{self.source}]"]
        if self.ticker:
            parts.append(f"({self.ticker})")
        parts.append(self.message)
        return " ".join(parts)


class TickerNotFoundError(DataSourceError):
    """Raised when a ticker symbol does not exist or returns no data.

    yfinance silently returns empty data for invalid tickers — this exception
    converts that silent failure into an explicit error.

    Attributes:
        suggestions: Alternative tickers the user might have meant.
    """

    def __init__(
        self,
        ticker: str,
        message: str | None = None,
        suggestions: list[str] | None = None,
        source: str = "yfinance",
    ) -> None:
        self.suggestions = suggestions or []
        msg = message or f"Ticker '{ticker}' not found or returned no data."
        if self.suggestions:
            msg += f" Did you mean: {', '.join(self.suggestions)}?"
        super().__init__(message=msg, source=source, ticker=ticker)


class NoDataAvailableError(DataSourceError):
    """Raised when the ticker is valid but the requested data is not available.

    Examples:
    - Requesting quarterly earnings for an ETF (ETFs don't have earnings)
    - Requesting institutional holders for a foreign stock not tracked by SEC
    - FRED series has no data for the requested date range
    """

    def __init__(
        self,
        message: str,
        source: str = "unknown",
        ticker: str | None = None,
    ) -> None:
        super().__init__(message=message, source=source, ticker=ticker)


class RateLimitError(DataSourceError):
    """Raised when an API rate limit is hit.

    Attributes:
        retry_after: Seconds to wait before retrying, if known.
    """

    def __init__(
        self,
        message: str = "API rate limit exceeded.",
        source: str = "unknown",
        retry_after: float | None = None,
    ) -> None:
        self.retry_after = retry_after
        if retry_after:
            message += f" Retry after {retry_after:.0f}s."
        super().__init__(message=message, source=source)


class ExternalAPIError(DataSourceError):
    """Raised when an external API returns an unexpected error (5xx, timeout, etc.).

    This is for transient infrastructure failures, not data-not-found situations.
    """

    def __init__(
        self,
        message: str,
        source: str = "unknown",
        ticker: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.status_code = status_code
        super().__init__(message=message, source=source, ticker=ticker)
