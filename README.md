# 🤖 Crypto Arbitrage Scanner

> Real-time cross-exchange arbitrage opportunity detector with Telegram alerts.
> Monitors **Binance**, **Kraken**, **KuCoin**, **Bybit**, and **OKX** simultaneously, 24/7.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![ccxt](https://img.shields.io/badge/ccxt-4.2%2B-orange)
![asyncio](https://img.shields.io/badge/asyncio-async%2Fawait-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![CI]([![CI](https://img.shields.io/badge/CI-GitHub%20Actions-yellow?logo=github)](https://github.com/eNNN0x/crypto-arbitrage-scanner))

---

## 📋 Table of Contents

- [What Is Arbitrage?](#-what-is-arbitrage)
- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Telegram Setup](#-telegram-setup)
- [Running on a VPS (24/7)](#-running-on-a-vps-247)
- [Alert Format](#-alert-format)
- [Project Structure](#-project-structure)
- [Running Tests](#-running-tests)
- [Disclaimer](#-disclaimer)

---

## 💡 What Is Arbitrage?

Crypto arbitrage is the practice of buying an asset on one exchange where the price is lower, and simultaneously selling it on another exchange where the price is higher — capturing the difference as profit.

**Example:**
```
BTC/USDT on Binance:  $29,800 (ask)
BTC/USDT on Kraken:   $30,100 (bid)

Gross spread: 1.01%
After ~0.2% fees: ~0.81% net profit
```

This scanner automates finding these opportunities the moment they appear.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **5 exchanges** | Binance, Kraken, KuCoin, Bybit, OKX |
| **10 symbols** | BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, DOT, MATIC (configurable) |
| **Async scanning** | All exchanges fetched concurrently — minimal latency |
| **Smart filtering** | Min spread %, max spread (data quality), min volume filter |
| **Alert cooldown** | Prevents Telegram spam for the same opportunity |
| **Telegram alerts** | Rich HTML-formatted messages with full trade details |
| **Periodic stats** | Heartbeat summary every 60 scans |
| **VPS-ready** | systemd service unit included |
| **Graceful shutdown** | Handles SIGINT/SIGTERM cleanly |
| **Rotating logs** | 10 MB max per file, 7-day retention |
| **Full test suite** | pytest + pytest-asyncio, CI via GitHub Actions |

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│                   main.py                        │
│            (startup, shutdown, loop)             │
└───────────────────┬─────────────────────────────┘
                    │
          ┌─────────▼──────────┐
          │  ArbitrageEngine   │
          │  (orchestrator)    │
          └──┬──────────────┬──┘
             │              │
    ┌────────▼────┐   ┌─────▼────────┐
    │ExchangeFetcher│  │ TelegramBot  │
    │ (×5 exchanges)│  │  (alerts)    │
    └────────┬────┘   └─────────────-┘
             │
    ┌────────▼──────────────────────┐
    │         ccxt async            │
    │  Binance / Kraken / KuCoin /  │
    │     Bybit / OKX REST APIs     │
    └───────────────────────────────┘
```

**Scan cycle (every 5 seconds by default):**
1. Fetch all tickers from all 5 exchanges concurrently (bulk where supported)
2. Update in-memory price cache
3. Compare every exchange pair for every symbol → compute spreads
4. Filter by min spread, max spread, min volume
5. Check alert cooldown cache
6. Fire Telegram alerts for actionable opportunities

---

## ⚡ Quick Start

### Prerequisites

- Python 3.10+
- A Telegram bot token (see [Telegram Setup](#-telegram-setup))
- A Telegram chat ID

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/crypto-arbitrage-scanner.git
cd crypto-arbitrage-scanner
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your environment

```bash
cp .env.example .env
nano .env   # Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID at minimum
```

### 5. Run the scanner

```bash
python main.py
```

You should see the ASCII banner, then logs of exchange connections and scan activity. Your Telegram will receive a startup notification within seconds.

---

## ⚙️ Configuration

All settings are controlled via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | **required** | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | **required** | Your Telegram chat/group ID |
| `EXCHANGES` | `binance,kraken,kucoin,bybit,okx` | Comma-separated exchanges |
| `SYMBOLS` | BTC/USDT + 9 others | Comma-separated trading pairs |
| `MIN_SPREAD_PCT` | `0.5` | Min % spread to trigger alert |
| `MAX_SPREAD_PCT` | `20.0` | Max % spread (above = bad data) |
| `MIN_VOLUME_USDT` | `10000` | Min 24h volume to consider |
| `ALERT_COOLDOWN_SEC` | `300` | Seconds between re-alerts for same pair |
| `SCAN_INTERVAL_SEC` | `5.0` | Scan frequency in seconds |
| `REQUEST_TIMEOUT_SEC` | `10` | Per-request HTTP timeout |
| `MAX_RETRIES` | `3` | Retries per exchange on failure |
| `CONCURRENT_FETCHES` | `5` | Max parallel exchange requests |

---

## 📱 Telegram Setup

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** → paste into `TELEGRAM_BOT_TOKEN`
4. Start a chat with your new bot
5. Get your chat ID:
   - Message **@userinfobot** — it replies with your ID
   - Or visit: `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message
6. Paste your chat ID into `TELEGRAM_CHAT_ID`

> **Tip:** You can add the bot to a private group — use the group's chat ID (negative number) to receive alerts there.

---

## 🖥 Running on a VPS (24/7)

### Using systemd (recommended)

```bash
# 1. Clone and set up on your VPS (e.g., Ubuntu 22.04)
git clone https://github.com/yourusername/crypto-arbitrage-scanner.git /home/ubuntu/crypto-arbitrage-scanner
cd /home/ubuntu/crypto-arbitrage-scanner
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

# 2. Install the systemd service
sudo cp crypto-arbitrage.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-arbitrage
sudo systemctl start crypto-arbitrage

# 3. Check status and logs
sudo systemctl status crypto-arbitrage
sudo journalctl -u crypto-arbitrage -f
```

### Using screen (quick & dirty)

```bash
screen -S arbitrage
python main.py
# Ctrl+A, D to detach
# screen -r arbitrage to reattach
```

---

## 📨 Alert Format

```
💰 ARBITRAGE OPPORTUNITY DETECTED
━━━━━━━━━━━━━━━━━━━━━━
🪙 Pair: BTC/USDT
📈 Buy on:  BINANCE  @ $29,800.0000
📉 Sell on: KRAKEN   @ $30,100.0000
━━━━━━━━━━━━━━━━━━━━━━
📊 Gross spread: 1.006%
💸 Est. net (−0.2% fees): 0.806%
[████████░░░░░░░░░░░░]
━━━━━━━━━━━━━━━━━━━━━━
📦 Buy vol 24h:  $1,500,000,000
📦 Sell vol 24h: $320,000,000
🕐 Detected: 14:23:07 UTC
━━━━━━━━━━━━━━━━━━━━━━
✅ PROFITABLE (est.)
⚡ Act fast — spreads close quickly!
```

---

## 📁 Project Structure

```
crypto-arbitrage-scanner/
├── main.py                          # Entry point
├── requirements.txt
├── pytest.ini
├── .env.example                     # Config template
├── .gitignore
├── crypto-arbitrage.service         # systemd unit
│
├── config/
│   ├── __init__.py
│   └── settings.py                  # All configuration
│
├── src/
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── arbitrage_engine.py      # Core detection logic
│   │   └── exchange_fetcher.py      # ccxt wrapper per exchange
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── telegram_bot.py          # Telegram API client
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py                # Coloured + file logging
│       └── banner.py                # ASCII startup banner
│
├── tests/
│   ├── __init__.py
│   ├── test_arbitrage_engine.py
│   └── test_telegram_bot.py
│
├── logs/                            # Auto-created on first run
│
└── .github/
    └── workflows/
        └── ci.yml                   # GitHub Actions CI
```

---

## 🧪 Running Tests

```bash
# Run all tests
pytest

# With coverage report
pytest --cov=src --cov-report=term-missing

# Run a specific test file
pytest tests/test_arbitrage_engine.py -v
```

---

## ⚠️ Disclaimer

This tool is for **informational and educational purposes only**. 

- Arbitrage opportunities close within milliseconds in efficient markets
- Exchange fees, withdrawal fees, and transfer times significantly impact real profitability
- This scanner does **not** execute trades automatically
- **Never invest more than you can afford to lose**
- Always conduct your own due diligence before making any financial decisions

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built by [eNNN0x](https://github.com/eNNN0x) · Python · ccxt · asyncio · Telegram Bot API*

