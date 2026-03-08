"""
Telegram Bot
============
Sends formatted alerts, status updates, and error notifications via Telegram.
Uses the Bot API directly with aiohttp (no heavy library required).
"""

import aiohttp
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.scanner.arbitrage_engine import ArbitrageOpportunity


TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    """
    Lightweight async Telegram Bot client.
    
    All messages use HTML parse mode for rich formatting.
    Failed sends are retried up to 3 times before logging and moving on.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._session: aiohttp.ClientSession = None
        self.logger = logging.getLogger("telegram")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def send_message(self, text: str, silent: bool = False) -> bool:
        """Send a message with retry logic."""
        url = TELEGRAM_API_BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
            "disable_web_page_preview": True,
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return True
                    error = data.get("description", "Unknown error")
                    self.logger.warning(f"Telegram API error: {error}")
                    if "chat not found" in error.lower():
                        return False  # No point retrying
            except asyncio.TimeoutError:
                self.logger.warning(f"Telegram send timeout (attempt {attempt + 1})")
            except Exception as e:
                self.logger.warning(f"Telegram send error: {e} (attempt {attempt + 1})")

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))

        self.logger.error("❌ Failed to send Telegram message after all retries")
        return False

    # ──────────────────────────────────────────────
    # Formatted message templates
    # ──────────────────────────────────────────────

    async def send_startup_message(
        self, exchanges: list, symbols: list, min_spread: float
    ):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        ex_list = " | ".join(e.upper() for e in exchanges)
        sym_count = len(symbols)
        text = (
            "🤖 <b>Crypto Arbitrage Scanner — ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Started: <code>{now}</code>\n"
            f"📡 Exchanges: <code>{ex_list}</code>\n"
            f"🪙 Symbols: <code>{sym_count} pairs</code>\n"
            f"📊 Min spread threshold: <code>{min_spread}%</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Scanner running — alerts will appear below."
        )
        await self.send_message(text)

    async def send_opportunity_alert(self, opp: "ArbitrageOpportunity"):
        """Send a rich alert for a detected arbitrage opportunity."""
        ts = datetime.fromtimestamp(opp.timestamp, tz=timezone.utc).strftime("%H:%M:%S UTC")
        profitable_tag = "✅ PROFITABLE (est.)" if opp.is_profitable() else "⚠️ Check fees"

        # Emoji bar to visually represent spread size
        bar_len = min(int(opp.spread_pct * 2), 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)

        text = (
            f"💰 <b>ARBITRAGE OPPORTUNITY DETECTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Pair: <b>{opp.symbol}</b>\n"
            f"📈 Buy on:  <b>{opp.buy_exchange.upper()}</b> @ <code>${opp.buy_price:,.6f}</code>\n"
            f"📉 Sell on: <b>{opp.sell_exchange.upper()}</b> @ <code>${opp.sell_price:,.6f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Gross spread: <b>{opp.spread_pct:.3f}%</b>\n"
            f"💸 Est. net (−0.2% fees): <b>{opp.net_spread_pct:.3f}%</b>\n"
            f"<code>[{bar}]</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Buy vol 24h:  <code>${opp.buy_volume_24h:,.0f}</code>\n"
            f"📦 Sell vol 24h: <code>${opp.sell_volume_24h:,.0f}</code>\n"
            f"🕐 Detected: <code>{ts}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{profitable_tag}\n"
            f"⚡ Act fast — spreads close quickly!"
        )
        await self.send_message(text)

    async def send_stats_update(
        self,
        scans: int,
        opportunities: int,
        alerts_sent: int,
        errors: int,
        uptime_hours: float,
    ):
        """Periodic heartbeat / stats message (sent silently)."""
        hit_rate = (opportunities / scans * 100) if scans > 0 else 0
        text = (
            "📊 <b>Scanner Status Update</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ Uptime: <code>{uptime_hours:.1f}h</code>\n"
            f"🔍 Scans completed: <code>{scans:,}</code>\n"
            f"💰 Opportunities found: <code>{opportunities:,}</code>\n"
            f"📨 Alerts sent: <code>{alerts_sent:,}</code>\n"
            f"📈 Hit rate: <code>{hit_rate:.2f}%</code>\n"
            f"⚠️  Errors: <code>{errors:,}</code>\n"
        )
        await self.send_message(text, silent=True)

    async def send_error_alert(self, error_msg: str):
        text = (
            "🚨 <b>SCANNER ERROR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{error_msg[:500]}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Scanner may need to be restarted."
        )
        await self.send_message(text)

    async def send_shutdown_message(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text = (
            "🛑 <b>Crypto Arbitrage Scanner — OFFLINE</b>\n"
            f"🕐 Stopped: <code>{now}</code>"
        )
        await self.send_message(text)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
