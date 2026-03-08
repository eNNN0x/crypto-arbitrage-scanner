"""
Tests for the Telegram Bot
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import aiohttp

from src.alerts.telegram_bot import TelegramBot
from src.scanner.arbitrage_engine import ArbitrageOpportunity


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def make_bot():
    return TelegramBot(token="test_token_123", chat_id="987654321")


def make_opportunity(**kwargs):
    defaults = dict(
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=30_000.0,
        sell_price=30_300.0,
        spread_pct=1.0,
        buy_volume_24h=1_000_000,
        sell_volume_24h=500_000,
    )
    defaults.update(kwargs)
    return ArbitrageOpportunity(**defaults)


# ──────────────────────────────────────────────
# Message Sending Tests
# ──────────────────────────────────────────────

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_sends_message_successfully(self):
        bot = make_bot()
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={"ok": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with patch.object(bot, "_get_session") as mock_session:
            session = AsyncMock()
            session.post.return_value = mock_resp
            mock_session.return_value = session

            result = await bot.send_message("Hello, World!")
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self):
        bot = make_bot()
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "ok": False, "description": "Bad Request"
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with patch.object(bot, "_get_session") as mock_session:
            session = AsyncMock()
            session.post.return_value = mock_resp
            mock_session.return_value = session

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await bot.send_message("Test")
                assert result is False

    @pytest.mark.asyncio
    async def test_stops_retrying_on_chat_not_found(self):
        bot = make_bot()
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "ok": False, "description": "chat not found"
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        call_count = 0

        with patch.object(bot, "_get_session") as mock_session:
            session = AsyncMock()

            async def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_resp

            session.post.side_effect = mock_post
            mock_session.return_value = session

            result = await bot.send_message("Test")
            assert result is False
            assert call_count == 1  # Should not retry


# ──────────────────────────────────────────────
# Message Content Tests
# ──────────────────────────────────────────────

class TestMessageContent:
    @pytest.mark.asyncio
    async def test_opportunity_alert_contains_key_info(self):
        bot = make_bot()
        opp = make_opportunity()
        sent_texts = []

        async def capture_send(text, **kwargs):
            sent_texts.append(text)
            return True

        bot.send_message = capture_send
        await bot.send_opportunity_alert(opp)

        assert len(sent_texts) == 1
        text = sent_texts[0]
        assert "BTC/USDT" in text
        assert "BINANCE" in text
        assert "KRAKEN" in text
        assert "1.0" in text or "1.00" in text  # spread

    @pytest.mark.asyncio
    async def test_startup_message_contains_exchange_list(self):
        bot = make_bot()
        sent_texts = []

        async def capture_send(text, **kwargs):
            sent_texts.append(text)
            return True

        bot.send_message = capture_send
        await bot.send_startup_message(
            exchanges=["binance", "kraken"],
            symbols=["BTC/USDT"],
            min_spread=0.5,
        )

        text = sent_texts[0]
        assert "BINANCE" in text
        assert "KRAKEN" in text
        assert "0.5" in text

    @pytest.mark.asyncio
    async def test_stats_message_contains_metrics(self):
        bot = make_bot()
        sent_texts = []

        async def capture_send(text, **kwargs):
            sent_texts.append(text)
            return True

        bot.send_message = capture_send
        await bot.send_stats_update(
            scans=1000,
            opportunities=25,
            alerts_sent=10,
            errors=2,
            uptime_hours=5.5,
        )

        text = sent_texts[0]
        assert "1,000" in text or "1000" in text
        assert "25" in text
        assert "10" in text
        assert "5.5" in text

    @pytest.mark.asyncio
    async def test_profitable_opportunity_flagged(self):
        bot = make_bot()
        opp = make_opportunity(spread_pct=5.0)  # Clearly profitable after fees
        sent_texts = []

        async def capture_send(text, **kwargs):
            sent_texts.append(text)
            return True

        bot.send_message = capture_send
        await bot.send_opportunity_alert(opp)

        assert "PROFITABLE" in sent_texts[0].upper() or "profitable" in sent_texts[0].lower()
