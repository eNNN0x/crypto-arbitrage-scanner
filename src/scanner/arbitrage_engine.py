"""
Arbitrage Engine
================
Orchestrates exchange fetchers, detects spreads, and fires alerts.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.scanner.exchange_fetcher import ExchangeFetcher, PriceData
from src.alerts.telegram_bot import TelegramBot
from config.settings import Settings


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    buy_volume_24h: float
    sell_volume_24h: float
    timestamp: float = field(default_factory=time.time)

    @property
    def net_spread_pct(self) -> float:
        """Rough estimate after typical 0.1% fee per side."""
        return self.spread_pct - 0.2

    def is_profitable(self) -> bool:
        return self.net_spread_pct > 0

    def __str__(self) -> str:
        return (
            f"{self.symbol} | Buy {self.buy_exchange.upper()} @ ${self.buy_price:,.4f} → "
            f"Sell {self.sell_exchange.upper()} @ ${self.sell_price:,.4f} | "
            f"Spread: {self.spread_pct:.2f}% (net ~{self.net_spread_pct:.2f}%)"
        )


class ArbitrageEngine:
    """
    Core engine that:
    1. Fetches live prices from all configured exchanges concurrently
    2. Compares prices across exchange pairs to find spreads
    3. Filters by minimum spread threshold
    4. Deduplicates alerts using a cooldown cache
    5. Dispatches Telegram alerts for actionable opportunities
    """

    def __init__(self, settings: Settings, telegram: TelegramBot, logger: logging.Logger):
        self.settings = settings
        self.telegram = telegram
        self.logger = logger

        # Exchange fetcher instances
        self.fetchers: Dict[str, ExchangeFetcher] = {}

        # Price cache: {symbol: {exchange: PriceData}}
        self.price_cache: Dict[str, Dict[str, PriceData]] = defaultdict(dict)

        # Alert cooldown cache: {(symbol, buy_ex, sell_ex): last_alert_timestamp}
        self.alert_cache: Dict[Tuple[str, str, str], float] = {}

        # Statistics
        self.stats = {
            "scans_completed": 0,
            "opportunities_found": 0,
            "alerts_sent": 0,
            "errors": 0,
            "start_time": time.time(),
        }

    async def initialize(self):
        """Initialize all exchange fetchers."""
        self.logger.info("🔌 Initializing exchange connections...")
        for exchange_id in self.settings.exchanges:
            fetcher = ExchangeFetcher(
                exchange_id=exchange_id,
                settings=self.settings,
                logger=self.logger,
            )
            await fetcher.initialize()
            self.fetchers[exchange_id] = fetcher
            self.logger.info(f"  ✅ {exchange_id.upper()} connected")

    async def run(self, shutdown_event: asyncio.Event):
        """Main scan loop."""
        await self.initialize()
        self.logger.info("🔍 Starting scan loop...")

        scan_count = 0
        while not shutdown_event.is_set():
            loop_start = time.monotonic()

            try:
                await self._scan_cycle()
                scan_count += 1

                if scan_count % 60 == 0:
                    await self._send_stats_update()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats["errors"] += 1
                self.logger.error(f"⚠️  Error in scan cycle: {e}", exc_info=True)

            # Respect the configured interval
            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.0, self.settings.scan_interval_sec - elapsed)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass

        await self._teardown()

    async def _scan_cycle(self):
        """Single scan iteration: fetch all prices then analyse."""
        # Fetch prices from all exchanges concurrently
        semaphore = asyncio.Semaphore(self.settings.concurrent_fetches)

        async def fetch_with_semaphore(exchange_id: str):
            async with semaphore:
                return await self.fetchers[exchange_id].fetch_all_prices(
                    self.settings.symbols
                )

        tasks = [fetch_with_semaphore(ex) for ex in self.fetchers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update price cache
        for exchange_id, result in zip(self.fetchers.keys(), results):
            if isinstance(result, Exception):
                self.logger.warning(f"⚠️  {exchange_id}: fetch failed — {result}")
                self.stats["errors"] += 1
                continue
            for symbol, price_data in result.items():
                self.price_cache[symbol][exchange_id] = price_data

        # Find arbitrage opportunities
        opportunities = self._find_opportunities()
        self.stats["scans_completed"] += 1

        if opportunities:
            self.logger.info(f"💰 Found {len(opportunities)} opportunity(ies) this scan")
            for opp in opportunities:
                self.stats["opportunities_found"] += 1
                if self._should_alert(opp):
                    await self.telegram.send_opportunity_alert(opp)
                    self._mark_alerted(opp)
                    self.stats["alerts_sent"] += 1
                    self.logger.info(f"📨 Alert sent: {opp}")

    def _find_opportunities(self) -> List[ArbitrageOpportunity]:
        """Compare prices across all exchange pairs for each symbol."""
        opportunities = []

        for symbol, exchange_prices in self.price_cache.items():
            # Need at least 2 exchanges with valid data
            valid = {
                ex: pd for ex, pd in exchange_prices.items()
                if pd and pd.bid > 0 and pd.ask > 0
                and pd.volume_24h_usdt >= self.settings.min_volume_usdt
            }
            if len(valid) < 2:
                continue

            exchanges = list(valid.keys())
            for i in range(len(exchanges)):
                for j in range(len(exchanges)):
                    if i == j:
                        continue
                    buy_ex = exchanges[i]
                    sell_ex = exchanges[j]

                    buy_price = valid[buy_ex].ask   # We buy at ask
                    sell_price = valid[sell_ex].bid  # We sell at bid

                    if buy_price <= 0:
                        continue

                    spread_pct = ((sell_price - buy_price) / buy_price) * 100

                    if spread_pct < self.settings.min_spread_pct:
                        continue
                    if spread_pct > self.settings.max_spread_pct:
                        self.logger.debug(
                            f"Skipping {symbol} {buy_ex}→{sell_ex}: "
                            f"spread {spread_pct:.1f}% looks like bad data"
                        )
                        continue

                    opp = ArbitrageOpportunity(
                        symbol=symbol,
                        buy_exchange=buy_ex,
                        sell_exchange=sell_ex,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        spread_pct=spread_pct,
                        buy_volume_24h=valid[buy_ex].volume_24h_usdt,
                        sell_volume_24h=valid[sell_ex].volume_24h_usdt,
                    )
                    opportunities.append(opp)

        # Sort by spread descending
        return sorted(opportunities, key=lambda o: o.spread_pct, reverse=True)

    def _should_alert(self, opp: ArbitrageOpportunity) -> bool:
        """Check cooldown to prevent alert spam."""
        key = (opp.symbol, opp.buy_exchange, opp.sell_exchange)
        last = self.alert_cache.get(key, 0)
        return (time.time() - last) >= self.settings.alert_cooldown_sec

    def _mark_alerted(self, opp: ArbitrageOpportunity):
        key = (opp.symbol, opp.buy_exchange, opp.sell_exchange)
        self.alert_cache[key] = time.time()

    async def _send_stats_update(self):
        """Periodically push a stats summary to Telegram."""
        uptime_sec = time.time() - self.stats["start_time"]
        uptime_h = uptime_sec / 3600
        await self.telegram.send_stats_update(
            scans=self.stats["scans_completed"],
            opportunities=self.stats["opportunities_found"],
            alerts_sent=self.stats["alerts_sent"],
            errors=self.stats["errors"],
            uptime_hours=uptime_h,
        )

    async def _teardown(self):
        """Close all exchange connections."""
        self.logger.info("🔌 Closing exchange connections...")
        for exchange_id, fetcher in self.fetchers.items():
            try:
                await fetcher.close()
                self.logger.info(f"  ✅ {exchange_id.upper()} disconnected")
            except Exception as e:
                self.logger.warning(f"  ⚠️  Error closing {exchange_id}: {e}")
