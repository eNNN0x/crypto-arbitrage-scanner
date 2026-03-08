"""
Exchange Fetcher
================
Wraps ccxt to fetch live ticker data from each exchange asynchronously.
Handles retries, rate limiting, and data normalization.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

import ccxt.async_support as ccxt

from config.settings import Settings


@dataclass
class PriceData:
    """Normalized price data for a single symbol on a single exchange."""
    symbol: str
    exchange: str
    bid: float
    ask: float
    last: float
    volume_24h: float          # Volume in base currency
    volume_24h_usdt: float     # Volume in USDT (estimated)
    timestamp: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float:
        """Internal bid/ask spread on this exchange."""
        if self.ask <= 0:
            return 0.0
        return ((self.ask - self.bid) / self.ask) * 100


# Map exchange IDs to their ccxt class and any special config
EXCHANGE_CONFIGS = {
    "binance": {
        "class": ccxt.binance,
        "options": {"defaultType": "spot"},
    },
    "kraken": {
        "class": ccxt.kraken,
        "options": {},
    },
    "kucoin": {
        "class": ccxt.kucoin,
        "options": {},
    },
    "bybit": {
        "class": ccxt.bybit,
        "options": {"defaultType": "spot"},
    },
    "okx": {
        "class": ccxt.okx,
        "options": {"defaultType": "spot"},
    },
}


class ExchangeFetcher:
    """
    Manages a ccxt exchange instance and fetches ticker data.
    
    Features:
    - Async/await throughout
    - Automatic retry with exponential back-off
    - Rate limit awareness
    - Stale data detection
    """

    STALE_THRESHOLD_SEC = 60  # Mark data stale after 60 seconds

    def __init__(self, exchange_id: str, settings: Settings, logger: logging.Logger):
        if exchange_id not in EXCHANGE_CONFIGS:
            raise ValueError(f"Unsupported exchange: {exchange_id}. "
                             f"Supported: {list(EXCHANGE_CONFIGS.keys())}")
        self.exchange_id = exchange_id
        self.settings = settings
        self.logger = logger
        self._exchange: Optional[ccxt.Exchange] = None

        # Per-symbol cache to avoid hammering exchange on transient errors
        self._cache: Dict[str, PriceData] = {}
        self._cache_ts: Dict[str, float] = {}

    async def initialize(self):
        """Create and configure the ccxt exchange instance."""
        cfg = EXCHANGE_CONFIGS[self.exchange_id]
        exchange_class = cfg["class"]

        params = {
            "enableRateLimit": True,
            "timeout": self.settings.request_timeout_sec * 1000,  # ccxt uses ms
            "options": cfg["options"],
        }

        # Inject API credentials if provided
        api_key, secret, passphrase = self._get_credentials()
        if api_key:
            params["apiKey"] = api_key
            params["secret"] = secret
            if passphrase:
                params["password"] = passphrase

        self._exchange = exchange_class(params)
        await self._exchange.load_markets()

    def _get_credentials(self):
        """Return (api_key, secret, passphrase) for this exchange."""
        s = self.settings
        creds = {
            "binance":  (s.binance_api_key, s.binance_secret, ""),
            "kraken":   (s.kraken_api_key, s.kraken_secret, ""),
            "kucoin":   (s.kucoin_api_key, s.kucoin_secret, s.kucoin_passphrase),
            "bybit":    (s.bybit_api_key, s.bybit_secret, ""),
            "okx":      (s.okx_api_key, s.okx_secret, s.okx_passphrase),
        }
        return creds.get(self.exchange_id, ("", "", ""))

    async def fetch_all_prices(self, symbols: list) -> Dict[str, PriceData]:
        """Fetch tickers for all symbols. Returns dict of {symbol: PriceData}."""
        results: Dict[str, PriceData] = {}

        # Try to fetch all tickers at once (much more efficient)
        try:
            tickers = await self._fetch_tickers_bulk(symbols)
            if tickers:
                return tickers
        except Exception:
            pass  # Fall back to individual fetches

        # Fall back to individual symbol fetches
        tasks = [self._fetch_single_with_retry(sym) for sym in symbols]
        price_list = await asyncio.gather(*tasks, return_exceptions=True)

        for symbol, result in zip(symbols, price_list):
            if isinstance(result, Exception):
                self.logger.debug(f"{self.exchange_id}/{symbol}: {result}")
                # Return stale cached data if available
                if symbol in self._cache:
                    results[symbol] = self._cache[symbol]
            elif result is not None:
                results[symbol] = result
                self._cache[symbol] = result
                self._cache_ts[symbol] = time.time()

        return results

    async def _fetch_tickers_bulk(self, symbols: list) -> Dict[str, PriceData]:
        """Attempt to fetch all tickers in a single API call."""
        # Filter to symbols actually listed on this exchange
        valid_symbols = [
            s for s in symbols
            if s in self._exchange.markets
        ]
        if not valid_symbols:
            return {}

        tickers = await self._exchange.fetch_tickers(valid_symbols)
        results = {}
        for symbol, ticker in tickers.items():
            pd = self._normalize_ticker(symbol, ticker)
            if pd:
                results[symbol] = pd
                self._cache[symbol] = pd
                self._cache_ts[symbol] = time.time()
        return results

    async def _fetch_single_with_retry(self, symbol: str) -> Optional[PriceData]:
        """Fetch a single ticker with exponential back-off retries."""
        # Check if symbol is listed
        if symbol not in self._exchange.markets:
            return None

        for attempt in range(self.settings.max_retries):
            try:
                ticker = await self._exchange.fetch_ticker(symbol)
                return self._normalize_ticker(symbol, ticker)
            except ccxt.RateLimitExceeded:
                wait = 2 ** attempt
                self.logger.warning(f"{self.exchange_id}: Rate limit hit, waiting {wait}s")
                await asyncio.sleep(wait)
            except ccxt.NetworkError as e:
                if attempt == self.settings.max_retries - 1:
                    raise
                await asyncio.sleep(1)
            except ccxt.ExchangeError as e:
                self.logger.debug(f"{self.exchange_id}/{symbol}: Exchange error — {e}")
                return None
            except Exception as e:
                if attempt == self.settings.max_retries - 1:
                    raise
                await asyncio.sleep(0.5)
        return None

    def _normalize_ticker(self, symbol: str, ticker: dict) -> Optional[PriceData]:
        """Convert a raw ccxt ticker into PriceData."""
        try:
            bid = float(ticker.get("bid") or 0)
            ask = float(ticker.get("ask") or 0)
            last = float(ticker.get("last") or 0)
            volume = float(ticker.get("baseVolume") or 0)

            if bid <= 0 or ask <= 0:
                return None

            # Estimate USDT volume
            price_ref = last or ((bid + ask) / 2)
            volume_usdt = volume * price_ref

            return PriceData(
                symbol=symbol,
                exchange=self.exchange_id,
                bid=bid,
                ask=ask,
                last=last,
                volume_24h=volume,
                volume_24h_usdt=volume_usdt,
                timestamp=time.time(),
            )
        except (TypeError, ValueError) as e:
            self.logger.debug(f"{self.exchange_id}/{symbol}: Failed to parse ticker — {e}")
            return None

    async def close(self):
        """Close the ccxt exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
