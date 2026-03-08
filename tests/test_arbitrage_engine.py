"""
Tests for the Arbitrage Engine
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from src.scanner.arbitrage_engine import ArbitrageEngine, ArbitrageOpportunity
from src.scanner.exchange_fetcher import PriceData
from config.settings import Settings


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def make_settings(**kwargs):
    defaults = dict(
        telegram_token="test_token",
        telegram_chat_id="12345",
        exchanges=["binance", "kraken"],
        symbols=["BTC/USDT", "ETH/USDT"],
        min_spread_pct=0.5,
        max_spread_pct=20.0,
        min_volume_usdt=1000.0,
        alert_cooldown_sec=300,
        scan_interval_sec=5.0,
        request_timeout_sec=10,
        max_retries=3,
        concurrent_fetches=5,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def make_price(symbol, exchange, bid, ask, last=None, volume_usdt=50_000):
    return PriceData(
        symbol=symbol,
        exchange=exchange,
        bid=bid,
        ask=ask,
        last=last or (bid + ask) / 2,
        volume_24h=volume_usdt / ((bid + ask) / 2),
        volume_24h_usdt=volume_usdt,
    )


def make_engine(settings=None):
    settings = settings or make_settings()
    telegram = MagicMock()
    telegram.send_opportunity_alert = AsyncMock()
    telegram.send_stats_update = AsyncMock()
    logger = MagicMock()
    return ArbitrageEngine(settings=settings, telegram=telegram, logger=logger)


# ──────────────────────────────────────────────
# ArbitrageOpportunity Tests
# ──────────────────────────────────────────────

class TestArbitrageOpportunity:
    def test_net_spread_deducts_fees(self):
        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            buy_price=30_000.0,
            sell_price=30_300.0,
            spread_pct=1.0,
            buy_volume_24h=1_000_000,
            sell_volume_24h=500_000,
        )
        assert opp.net_spread_pct == pytest.approx(0.8)

    def test_is_profitable_when_net_positive(self):
        opp = ArbitrageOpportunity(
            symbol="ETH/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            buy_price=2000.0,
            sell_price=2050.0,
            spread_pct=2.5,
            buy_volume_24h=500_000,
            sell_volume_24h=250_000,
        )
        assert opp.is_profitable() is True

    def test_not_profitable_when_net_negative(self):
        opp = ArbitrageOpportunity(
            symbol="ETH/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            buy_price=2000.0,
            sell_price=2001.0,
            spread_pct=0.05,
            buy_volume_24h=500_000,
            sell_volume_24h=250_000,
        )
        assert opp.is_profitable() is False

    def test_str_representation(self):
        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            buy_price=30_000.0,
            sell_price=30_300.0,
            spread_pct=1.0,
            buy_volume_24h=1_000_000,
            sell_volume_24h=500_000,
        )
        s = str(opp)
        assert "BTC/USDT" in s
        assert "BINANCE" in s
        assert "KRAKEN" in s
        assert "1.00%" in s


# ──────────────────────────────────────────────
# ArbitrageEngine._find_opportunities Tests
# ──────────────────────────────────────────────

class TestFindOpportunities:
    def test_detects_basic_opportunity(self):
        engine = make_engine()
        engine.price_cache["BTC/USDT"]["binance"] = make_price(
            "BTC/USDT", "binance", bid=29_900, ask=30_000
        )
        engine.price_cache["BTC/USDT"]["kraken"] = make_price(
            "BTC/USDT", "kraken", bid=30_600, ask=30_700
        )

        opps = engine._find_opportunities()

        # Should find binance→kraken spread
        assert any(
            o.buy_exchange == "binance" and o.sell_exchange == "kraken"
            for o in opps
        )

    def test_no_opportunity_when_spread_too_small(self):
        engine = make_engine(make_settings(min_spread_pct=1.0))
        engine.price_cache["BTC/USDT"]["binance"] = make_price(
            "BTC/USDT", "binance", bid=30_000, ask=30_010
        )
        engine.price_cache["BTC/USDT"]["kraken"] = make_price(
            "BTC/USDT", "kraken", bid=30_020, ask=30_030
        )

        opps = engine._find_opportunities()
        assert len(opps) == 0

    def test_filters_low_volume_exchanges(self):
        engine = make_engine(make_settings(min_volume_usdt=100_000))
        engine.price_cache["ETH/USDT"]["binance"] = make_price(
            "ETH/USDT", "binance", bid=1990, ask=2000, volume_usdt=50_000  # too low
        )
        engine.price_cache["ETH/USDT"]["kraken"] = make_price(
            "ETH/USDT", "kraken", bid=2100, ask=2110, volume_usdt=50_000  # too low
        )

        opps = engine._find_opportunities()
        assert len(opps) == 0

    def test_ignores_suspiciously_high_spread(self):
        engine = make_engine(make_settings(max_spread_pct=20.0))
        engine.price_cache["BTC/USDT"]["binance"] = make_price(
            "BTC/USDT", "binance", bid=30_000, ask=30_100
        )
        engine.price_cache["BTC/USDT"]["kraken"] = make_price(
            "BTC/USDT", "kraken", bid=40_000, ask=40_100  # 33% spread = bad data
        )

        opps = engine._find_opportunities()
        assert all(o.spread_pct <= 20.0 for o in opps)

    def test_results_sorted_by_spread_descending(self):
        engine = make_engine(make_settings(min_spread_pct=0.1))
        engine.price_cache["BTC/USDT"]["binance"] = make_price(
            "BTC/USDT", "binance", bid=30_000, ask=30_100
        )
        engine.price_cache["BTC/USDT"]["kraken"] = make_price(
            "BTC/USDT", "kraken", bid=30_500, ask=30_600  # bigger spread
        )
        engine.price_cache["ETH/USDT"]["binance"] = make_price(
            "ETH/USDT", "binance", bid=2000, ask=2010
        )
        engine.price_cache["ETH/USDT"]["kraken"] = make_price(
            "ETH/USDT", "kraken", bid=2015, ask=2025  # smaller spread
        )

        opps = engine._find_opportunities()
        spreads = [o.spread_pct for o in opps]
        assert spreads == sorted(spreads, reverse=True)

    def test_skips_single_exchange_symbols(self):
        engine = make_engine()
        engine.price_cache["BTC/USDT"]["binance"] = make_price(
            "BTC/USDT", "binance", bid=30_000, ask=30_100
        )
        # Only one exchange — no pair to compare
        opps = engine._find_opportunities()
        assert len(opps) == 0


# ──────────────────────────────────────────────
# Alert Cooldown Tests
# ──────────────────────────────────────────────

class TestAlertCooldown:
    def _make_opp(self, symbol="BTC/USDT", buy="binance", sell="kraken"):
        return ArbitrageOpportunity(
            symbol=symbol,
            buy_exchange=buy,
            sell_exchange=sell,
            buy_price=30_000,
            sell_price=30_300,
            spread_pct=1.0,
            buy_volume_24h=1_000_000,
            sell_volume_24h=500_000,
        )

    def test_should_alert_when_no_previous_alert(self):
        engine = make_engine()
        opp = self._make_opp()
        assert engine._should_alert(opp) is True

    def test_no_alert_within_cooldown_window(self):
        engine = make_engine(make_settings(alert_cooldown_sec=300))
        opp = self._make_opp()
        engine._mark_alerted(opp)
        assert engine._should_alert(opp) is False

    def test_alert_after_cooldown_expires(self):
        engine = make_engine(make_settings(alert_cooldown_sec=1))
        opp = self._make_opp()
        engine._mark_alerted(opp)
        time.sleep(1.1)
        assert engine._should_alert(opp) is True

    def test_different_pairs_have_independent_cooldowns(self):
        engine = make_engine()
        opp1 = self._make_opp("BTC/USDT")
        opp2 = self._make_opp("ETH/USDT")
        engine._mark_alerted(opp1)
        assert engine._should_alert(opp2) is True


# ──────────────────────────────────────────────
# PriceData Tests
# ──────────────────────────────────────────────

class TestPriceData:
    def test_mid_price(self):
        pd = make_price("BTC/USDT", "binance", bid=29_900, ask=30_100)
        assert pd.mid == 30_000.0

    def test_spread_pct_calculation(self):
        pd = make_price("BTC/USDT", "binance", bid=990, ask=1000)
        expected = (10 / 1000) * 100
        assert pd.spread_pct == pytest.approx(expected)

    def test_zero_ask_returns_zero_spread(self):
        pd = PriceData(
            symbol="X", exchange="y", bid=0, ask=0,
            last=0, volume_24h=0, volume_24h_usdt=0
        )
        assert pd.spread_pct == 0.0
