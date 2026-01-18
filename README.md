# 🤖 MT5 Algo Terminal - Advanced Auto-Trading Bot

A professional-grade algorithmic trading bot for MetaTrader 5 (MT5) featuring 6 integrated trading strategies, real-time risk management, and a stunning modern Dashboard UI. Built with Python and MQL5.

## 🚀 Key Features

*   **Multi-Strategy Engine**: Simultaneously runs 6 advanced strategies (Trend, Scalp, Breakout, ICT Silver Bullet, TBS Turtle, and Reversal).
*   **Single-Compute Optimization**: High-performance architecture that calculates indicators and patterns once per cycle to minimize CPU load and execution lag.
*   **Modern Dashboard UI**: Real-time monitoring of account stats, symbol synchronization, and a live "Strategy Monitor" showing exactly what the bot is thinking.
*   **Risk Management Gatekeeper**: Built-in protection for daily drawdown, max daily trades, and psychological cool-off periods.
*   **Intelligent News Filter**: Automatically pauses trading during high-impact news events using real-time RSS feeds with caching.
*   **Fast Execution**: Direct communication with MT5 via a custom MQL5 Bridge EA with specialized SL/TP normalization for crypto and forex.

## 📂 Project Structure

```text
├── main.py                # Core bot logic and execution loop
├── ui.py                  # Tkinter-based modern Dashboard UI
├── config.json            # Main configuration (Risk, News, Strategies)
├── mql5/
│   └── MT5_Bridge_EA.mq5 # Custom Bridge for MetaTrader 5
├── core/
│   ├── execution.py       # MT5 Connector & Order Management
│   ├── risk.py            # Daily Discipline & Position Sizing
│   ├── indicators.py      # Technical Analysis (EMA, MACD, ST, etc.)
│   └── patterns.py        # Pattern Detection (FVG, Engulfing, etc.)
└── strategy/
    ├── trend_following.py # EMA 200 + SuperTrend Confluence
    ├── scalping.py        # M5 Stochastic + RSI Momentum
    ├── breakout.py        # 20-Period Range Expansion
    ├── ict_silver_bullet.py # Time-based MSS + FVG (KH Time)
    ├── tbs_turtle.py      # Bollinger Squeeze + Turtle Soup
    └── reversal.py        # RSI Extremes + Candlestick Rejection
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
5.  Copy `mql5/MT5_Bridge_EA.mq5` to your MT5 `MQL5/Experts` folder.
6.  Compile and attach the EA to any chart (e.g., BTCUSDm or XAUUSDm).

### 3. Setup Python Bot
1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install pandas numpy ttkbootstrap feedparser requests
    ```
3.  Configure `config.json` with your desired risk levels and strategies.
4.  Run the bot:
    ```bash
    python main.py
    ```

## 📈 Trading Strategies

1.  **Trend Following**: Operates on M15/H1. Requires price to be above EMA 200 and SuperTrend to be Green (Bullish) combined with a confirmed pattern (FVG/Flag).
2.  **M5 Scalper**: High-frequency momentum strategy. Uses Stochastic crossovers and RSI filtering for quick trades in trending markets.
3.  **ICT Silver Bullet**: Specialized for London and PM sessions (Cambodia Time). Looks for Market Structure Shifts (MSS) and Fair Value Gaps during specific volatility windows.
4.  **TBS Turtle**: Detects Bollinger Band "Squeezes" followed by "Turtle Soup" (20-period price fakeouts) for explosive reversal entries.
5.  **Reversal Engine**: Identifies overextended markets using RSI and Bollinger Band extremes, confirmed by Pinbar or Engulfing patterns.
6.  **Breakout Engine**: Simple but powerful trend-continuation engine that fires when price explodes out of its 20-period High/Low range.

## 🛡️ Risk Management

*   **Daily Drawdown**: Hard stop traded if account balance drops below a set percentage for the day.
*   **Daily Trade Limit**: Controls over-trading by limiting total trades per 24 hours (e.g., 5 trades/day).
*   **Dynamic Lot Sizing**: Automatically calculates position size based on equity risk (e.g., 1-2% per trade).
*   **Cool-off Period**: Prevents revenge trading by enforcing a 1-hour wait after any trade execution.

## ⚠️ Disclaimer
Trading financial markets involves significant risk. This bot is for educational and testing purposes only. Always test thoroughly on a Demo account before using real capital. Use at your own risk.

---
**Developed by Antigravity**
