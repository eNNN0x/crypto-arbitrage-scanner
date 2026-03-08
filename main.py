#!/usr/bin/env python3
"""
Crypto Arbitrage Scanner
========================
Real-time arbitrage opportunity detector across 5 major exchanges.
Sends Telegram alerts when profitable spreads are found.

Author: Your Name
License: MIT
"""

import asyncio
import signal
import sys
import logging
from pathlib import Path

from src.scanner.arbitrage_engine import ArbitrageEngine
from src.alerts.telegram_bot import TelegramBot
from src.utils.logger import setup_logger
from src.utils.banner import print_banner
from config.settings import Settings


async def main():
    """Main entry point for the arbitrage scanner."""
    print_banner()

    # Setup logging
    logger = setup_logger("main", log_file="logs/scanner.log")
    logger.info("🚀 Crypto Arbitrage Scanner starting up...")

    # Load settings
    try:
        settings = Settings.from_env()
        logger.info(f"✅ Configuration loaded — monitoring {len(settings.symbols)} symbols across {len(settings.exchanges)} exchanges")
    except Exception as e:
        logger.critical(f"❌ Failed to load configuration: {e}")
        sys.exit(1)

    # Initialize Telegram bot
    telegram = TelegramBot(
        token=settings.telegram_token,
        chat_id=settings.telegram_chat_id,
    )

    # Initialize arbitrage engine
    engine = ArbitrageEngine(
        settings=settings,
        telegram=telegram,
        logger=logger,
    )

    # Graceful shutdown handler
    shutdown_event = asyncio.Event()

    def _handle_shutdown(signum, frame):
        logger.info("🛑 Shutdown signal received — cleaning up...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    # Send startup notification
    await telegram.send_startup_message(
        exchanges=settings.exchanges,
        symbols=settings.symbols,
        min_spread=settings.min_spread_pct,
    )

    # Run the scanner
    try:
        await engine.run(shutdown_event)
    except Exception as e:
        logger.critical(f"💥 Fatal error in engine: {e}", exc_info=True)
        await telegram.send_error_alert(str(e))
    finally:
        logger.info("👋 Scanner shut down gracefully.")
        await telegram.send_shutdown_message()


if __name__ == "__main__":
    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)
    asyncio.run(main())
