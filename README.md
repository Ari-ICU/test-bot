# 🤖 MT5 Algo Terminal - Advanced Auto-Trading Bot

A professional-grade algorithmic trading bot for MetaTrader 5 (MT5) featuring 6 integrated trading strategies, real-time risk management, and a stunning modern Dashboard UI. Built with Python and MQL5.

## 🚀 Key Features

*   **⚡ Multi-Strategy Engine**: Simultaneously runs 6 advanced strategies:
    *   **Trend Following** (EMA 200 + SuperTrend)
    *   **M5 Scalper** (Stochastic + RSI Momentum)
    *   **Breakout Engine** (Donchian Range Expansion)
    *   **ICT Silver Bullet** (Time-based MSS/FVG)
    *   **TBS Turtle** (Bollinger Squeeze + Turtle Soup)
    *   **Reversal Engine** (RSI Extremes + Candlestick Rejection)
*   **🏎️ Single-Compute Architecture**: High-performance optimization that calculates all indicators and patterns **once** per cycle. This reduces CPU load by ~70% and ensures zero-lag execution.
*   **📱 Interactive Telegram Bot**: full bi-directional control using a command menu:
    *   `/menu` - Main control panel
    *   `/status` - Real-time account health (Balance, Equity, Drawdown)
    *   `/positions` - Live list of all open MT5 trades
    *   `/analysis` - Technical snapshot of the active symbol
    *   `/settings` - Review active strategy and risk parameters
*   **📺 Modern Dashboard UI**: Real-time monitoring with a live "Strategy Engine" monitor showing the exact decision-making process for all 6 strategies.
*   **🛡️ Risk Management Gatekeeper**: Built-in protection for daily drawdown, max daily trades, and psychological cool-off periods.
*   **📰 Intelligent News Filter**: Automatically pauses trading during high-impact news events using real-time RSS feeds.

## 📂 Project Structure

```text
├── main.py                # Core bot logic and execution loop
├── ui.py                  # Tkinter-based modern Dashboard UI
├── config.json            # Main configuration (Risk, News, Strategies)
├── bot_settings.py        # Centralized .env and JSON config handler
├── mql5/
│   └── MT5_Bridge_EA.mq5  # Custom Bridge for MetaTrader 5
├── core/
│   ├── execution.py       # MT5 Connector & Order Management
│   ├── risk.py            # Daily Discipline & Position Sizing
│   ├── indicators.py      # Optimized Technical Analysis
│   ├── patterns.py        # Advanced Pattern Detection (MSS, FVG, etc.)
│   └── telegram_bot.py    # Interactive Command & Alert Handler
└── strategy/              # Plug-and-play Strategy Modules
    ├── trend_following.py 
    ├── scalping.py        
    ├── breakout.py        
    ├── ict_silver_bullet.py 
    ├── tbs_turtle.py      
    └── reversal.py        
```

## 🛠️ Installation & Setup

### 1. Requirements
*   Python 3.9+
*   MetaTrader 5 (Windows or Mac with Wine/Parallels)
*   Python Packages: `pandas`, `numpy`, `ttkbootstrap`, `feedparser`, `requests`

### 2. Setup MetaTrader 5
1.  Open MetaTrader 5.
2.  Go to `Tools` -> `Options` -> `Expert Advisors`.
3.  Check "Allow WebRequest for listed URL:".
4.  Add: `http://127.0.0.1:8001`
5.  Attach the `MT5_Bridge_EA.mq5` to any chart.

### 3. Setup Python Bot
1.  Clone the repository and install dependencies:
    ```bash
    pip install pandas numpy ttkbootstrap feedparser requests
    ```
2.  Add your `TELEGRAM_TOKEN` and `CHAT_ID` to your `.env` file.
3.  Run the bot:
    ```bash
    python main.py
    ```

## 📈 Trading Strategies

1.  **Trend Following**: Operates on M15/H1. Requires price to be above EMA 200 and SuperTrend to be Green (Bullish) combined with a confirmed pattern (FVG/Flag).
2.  **M5 Scalper**: High-frequency momentum strategy. Uses Stochastic crossovers and RSI filtering for quick trades in trending markets.
3.  **ICT Silver Bullet**: Specialized for London and PM sessions (Cambodia Time). Looks for Market Structure Shifts (MSS) and Fair Value Gaps.
4.  **TBS Turtle**: Detects Bollinger Band "Squeezes" followed by "Turtle Soup" (20-period price fakeouts) for explosive reversal entries.
5.  **Reversal Engine**: Identifies overextended markets using RSI and Bollinger Band extremes, confirmed by Pinbar or Engulfing patterns.
6.  **Breakout Engine**: Simple but powerful trend-continuation engine that fires when price explodes out of its 20-period High/Low range.

## 🛡️ Risk Management

*   **Daily Drawdown**: Hard stop if account balance drops below a set percentage.
*   **Daily Trade Limit**: Prevents over-trading by limiting total trades per 24 hours.
*   **Dynamic Lot Sizing**: Automatically calculates position size based on equity risk (e.g., 1-2% per trade).
*   **Cool-off Period**: Enforces a wait period after any trade execution to prevent revenge trading.

## ⚠️ Disclaimer
Trading financial markets involves significant risk. This bot is for educational and testing purposes only. Always test thoroughly on a Demo account before using real capital.

---
**Developed by Antigravity**
