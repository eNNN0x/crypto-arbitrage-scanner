"""
Configuration management — loads from .env or environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Telegram
    telegram_token: str
    telegram_chat_id: str

    # Exchanges to monitor
    exchanges: List[str] = field(default_factory=lambda: [
        "binance", "kraken", "kucoin", "bybit", "okx"
    ])

    # Trading pairs to monitor
    symbols: List[str] = field(default_factory=lambda: [
        "BTC/USDT", "ETH/USDT", "BNB/USDT",
        "SOL/USDT", "XRP/USDT", "ADA/USDT",
        "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
    ])

    # Arbitrage thresholds
    min_spread_pct: float = 0.5          # Minimum % spread to trigger alert
    max_spread_pct: float = 20.0         # Above this is likely bad data
    min_volume_usdt: float = 10_000.0    # Minimum 24h volume to consider
    alert_cooldown_sec: int = 300        # Don't re-alert same pair within N sec

    # Scanner behaviour
    scan_interval_sec: float = 5.0       # How often to poll prices (seconds)
    request_timeout_sec: int = 10        # HTTP request timeout
    max_retries: int = 3                 # Retries per exchange on failure
    concurrent_fetches: int = 5          # Max concurrent exchange fetches

    # Exchange API keys (optional — public endpoints used for price data)
    binance_api_key: str = ""
    binance_secret: str = ""
    kraken_api_key: str = ""
    kraken_secret: str = ""
    kucoin_api_key: str = ""
    kucoin_secret: str = ""
    kucoin_passphrase: str = ""
    bybit_api_key: str = ""
    bybit_secret: str = ""
    okx_api_key: str = ""
    okx_secret: str = ""
    okx_passphrase: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required in environment / .env")
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is required in environment / .env")

        # Parse optional symbol override
        symbols_raw = os.getenv("SYMBOLS", "")
        symbols = [s.strip() for s in symbols_raw.split(",")] if symbols_raw else None

        exchanges_raw = os.getenv("EXCHANGES", "")
        exchanges = [e.strip() for e in exchanges_raw.split(",")] if exchanges_raw else None

        return cls(
            telegram_token=token,
            telegram_chat_id=chat_id,
            exchanges=exchanges or cls.__dataclass_fields__["exchanges"].default_factory(),
            symbols=symbols or cls.__dataclass_fields__["symbols"].default_factory(),
            min_spread_pct=float(os.getenv("MIN_SPREAD_PCT", "0.5")),
            max_spread_pct=float(os.getenv("MAX_SPREAD_PCT", "20.0")),
            min_volume_usdt=float(os.getenv("MIN_VOLUME_USDT", "10000")),
            alert_cooldown_sec=int(os.getenv("ALERT_COOLDOWN_SEC", "300")),
            scan_interval_sec=float(os.getenv("SCAN_INTERVAL_SEC", "5.0")),
            request_timeout_sec=int(os.getenv("REQUEST_TIMEOUT_SEC", "10")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            concurrent_fetches=int(os.getenv("CONCURRENT_FETCHES", "5")),
            binance_api_key=os.getenv("BINANCE_API_KEY", ""),
            binance_secret=os.getenv("BINANCE_SECRET", ""),
            kraken_api_key=os.getenv("KRAKEN_API_KEY", ""),
            kraken_secret=os.getenv("KRAKEN_SECRET", ""),
            kucoin_api_key=os.getenv("KUCOIN_API_KEY", ""),
            kucoin_secret=os.getenv("KUCOIN_SECRET", ""),
            kucoin_passphrase=os.getenv("KUCOIN_PASSPHRASE", ""),
            bybit_api_key=os.getenv("BYBIT_API_KEY", ""),
            bybit_secret=os.getenv("BYBIT_SECRET", ""),
            okx_api_key=os.getenv("OKX_API_KEY", ""),
            okx_secret=os.getenv("OKX_SECRET", ""),
            okx_passphrase=os.getenv("OKX_PASSPHRASE", ""),
        )
