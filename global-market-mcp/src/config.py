"""Configuration constants for the MCP data server — cache TTLs, index symbols, exchanges."""

from __future__ import annotations


class CacheTTL:
    """Cache TTL constants in seconds.

    Rationale for each value is documented inline.
    """

    # Stock info (Ticker.info) — 3 agents hit this for the same ticker.
    # Data changes at most once per trading session.
    # 5 min = long enough to dedup parallel agent calls, short enough for live trading.
    STOCK_INFO: int = 300  # 5 minutes

    # Financial statements — change only quarterly when new 10-Q/10-K is filed.
    FINANCIAL_STATEMENTS: int = 86400  # 24 hours

    # Financial metrics — derived from Ticker.info, same cadence as stock info
    # but this data changes less frequently (quarterly ratios).
    FINANCIAL_METRICS: int = 3600  # 1 hour

    # Historical prices — during market hours, new candles appear every interval.
    # After hours, data is static until next session.
    PRICE_HISTORY_MARKET_OPEN: int = 900  # 15 minutes
    PRICE_HISTORY_MARKET_CLOSED: int = 86400  # 24 hours

    # Dividends — changes only on ex-dividend dates (a few times per year).
    DIVIDENDS: int = 86400  # 24 hours

    # Analyst data — updated a few times per day at most.
    ANALYST_DATA: int = 3600  # 1 hour

    # Earnings data — updated around earnings season.
    EARNINGS_DATA: int = 3600  # 1 hour

    # Institutional holders — SEC filings are quarterly.
    INSTITUTIONAL_HOLDERS: int = 86400  # 24 hours

    # Search results — relatively stable.
    SEARCH_RESULTS: int = 3600  # 1 hour

    # Ticker validation — valid tickers don't change within a session.
    TICKER_VALIDATION: int = 86400  # 24 hours

    # FRED macroeconomic data — released monthly/weekly.
    FRED_DATA: int = 3600  # 1 hour

    # Exchange calendar — completely static for any given year.
    CALENDAR: int = 86400  # 24 hours

    # Insider transactions — SEC filings, updated infrequently.
    INSIDER_TRANSACTIONS: int = 3600  # 1 hour

    # Upgrades/downgrades — analyst actions, a few per day at most.
    UPGRADES_DOWNGRADES: int = 3600  # 1 hour

    # Earnings dates — calendar view, changes around earnings season.
    EARNINGS_DATES: int = 3600  # 1 hour

    # Stock news — refreshes frequently.
    STOCK_NEWS: int = 900  # 15 minutes

    # Social sentiment (StockTwits, Reddit) — fast-changing social data.
    SOCIAL_SENTIMENT: int = 300  # 5 minutes

    # Index data — same cadence as price history.
    INDEX_DATA_MARKET_OPEN: int = 900  # 15 minutes
    INDEX_DATA_MARKET_CLOSED: int = 86400  # 24 hours


# Index symbol mapping
INDEX_SYMBOLS: dict[str, str] = {
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "VIX": "^VIX",
    "RUSSELL2000": "^RUT",
}

# Supported exchanges for calendar operations
SUPPORTED_EXCHANGES: dict[str, str] = {
    "XNYS": "New York Stock Exchange",
    "XNAS": "NASDAQ",
    "XSWX": "SIX Swiss Exchange",
    "XLON": "London Stock Exchange",
}
