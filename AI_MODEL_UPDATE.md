# AI Model Update - Smart Money Concepts Integration

## Overview
The AI model has been upgraded to incorporate **Smart Money Concepts (SMC)** based on institutional trading strategies. The model now analyzes 9 key components used by professional traders.

## New Features Added

### 1. **Market Structure** (Foundation)
- **Higher Highs (HH) & Higher Lows (HL)**: Uptrend detection
- **Lower Highs (LH) & Lower Lows (LL)**: Downtrend detection
- **Break of Structure (BOS)**: Continuation signal
- **Change of Character (CHoCH)**: Reversal signal
- **Trend vs Range**: Market direction classification

### 2. **Liquidity Detection**
- **Buy-side Liquidity**: Equal highs above price (stop hunts)
- **Sell-side Liquidity**: Equal lows below price (stop hunts)
- **Liquidity Sweeps**: Detection of stop raids before reversals
- Smart money targets liquidity first before major moves

### 3. **Order Blocks (OB)**
- **Bullish Order Blocks**: Last bearish candle before strong rally
- **Bearish Order Blocks**: Last bullish candle before strong drop
- **Valid vs Weak OBs**: Strength scoring based on distance
- **Mitigation vs Breaker Blocks**: Zone invalidation tracking
- Institutional entry zones where big players accumulate

### 4. **Supply & Demand Zones**
- **Fresh vs Tested Zones**: Zone quality assessment
- **Strong Departure & Imbalance**: High-probability reaction areas
- **Zone Refinement**: Precise entry/exit levels
- Used for entries, stops, and targets

### 5. **Fair Value Gaps (FVG) / Imbalance**
- **3-Candle Imbalance Concept**: Price inefficiency detection
- **Premium & Discount FVGs**: Entry using gaps
- **FVG + Order Block Confluence**: High-probability setups
- Price often returns to rebalance these gaps

### 6. **Premium & Discount Zones**
- **50% Equilibrium**: Fibonacci-based range analysis
- **Optimal Trade Entry (OTE) Zone**: 61.8-78.6% retracement
- **Buying at Discount, Selling at Premium**: Risk-to-reward optimization
- **Using Fibonacci Correctly**: Institutional retracement levels

### 7. **Multi-Timeframe Analysis**
- **HTF Bias (Daily/H4)**: Overall trend direction
- **LTF Execution (M15/M5)**: Precise entry timing
- **Timeframe Alignment**: Confluence scoring
- **Avoiding Lower Timeframe Noise**: Trade with the bigger picture

### 8. **Entry Models (Execution)**
- **Liquidity Sweep → CHoCH → OB/FVG Entry**: Complete setup sequence
- **Stopfirmation vs Sniper Entries**: Aggressive vs conservative
- **Stop-Loss Placement**: Below OB or liquidity level
- **Partial Profits & Trailing**: Risk management
- This is where profits are made

### 9. **Session Timing (Kill Zones)**
- **London Session (2-5 AM EST)**: High volatility
- **New York Session (8-11 AM EST)**: Major moves
- **Asian Session (7-10 PM EST)**: Range trading
- Timing increases accuracy

## Technical Implementation

### Feature Vector (38 Features Total)
```python
Traditional Indicators (9):
- RSI, ADX, MACD Histogram, Stochastic K/D
- Price vs EMA200, Bollinger Width, Squeeze
- SuperTrend Active

Smart Money Concepts (29):
- Market Structure (3): structure, BOS, CHoCH
- Liquidity (3): buyside, sellside, sweep
- Order Blocks (3): bullish OB, bearish OB, confluence
- Supply/Demand (3): fresh demand, fresh supply, strength
- FVG (3): bullish FVG, bearish FVG, size
- Premium/Discount (3): discount zone, premium zone, equilibrium distance
- Multi-Timeframe (3): HTF trend, LTF trend, alignment
- Session Timing (2): kill zone, session bias
```

### Model Architecture
- **Algorithm**: Random Forest Classifier
- **Scalp Model**: 150 trees, depth 12
- **Swing Model**: 250 trees, depth 15
- **Training Labels**: Profit-first labeling (checks if profit target hit before stop loss)
- **Confidence Threshold**: 60% for scalp, 65% for swing

## How to Retrain the Model

### Step 1: Ensure MT5 is Running
Make sure MetaTrader 5 is open with the Bridge EA running on your desired symbol and timeframe.

### Step 2: Run Training Script
```bash
cd /Users/thoeurnratha/Documents/ml/mt5-bot/training
python3 train_ai.py
```

### Step 3: Wait for Training
The script will:
1. Connect to MT5 Bridge
2. Download 10,000 candles of historical data
3. Calculate all indicators + SMC features
4. Train both scalp and swing models
5. Save models to `../models/` directory

### Expected Output
```
✅ Received 10000 candles. Starting training...
📊 Processing Features...
🧠 Training AI Model (scalp) for forex...
📈 forex | scalp Profit Hurdle: 0.120% | Stop Hurdle: 0.060% | Horizon: 10
🚀 AI Model for forex (scalp) saved to ../models/trading_model_forex_scalp.joblib
✅ SCALP training complete.
🧠 Training AI Model (swing) for forex...
📈 forex | swing Profit Hurdle: 0.300% | Stop Hurdle: 0.150% | Horizon: 40
🚀 AI Model for forex (swing) saved to ../models/trading_model_forex_swing.joblib
✅ SWING training complete.
🏁 Trainer Finished.
```

## Model Files
After training, you'll have:
- `models/trading_model_forex_scalp.joblib` - For M1-M15 scalping
- `models/trading_model_forex_swing.joblib` - For H1-H4 swing trading
- `models/trading_model_crypto_scalp.joblib` - For crypto scalping (if trained on BTC/ETH)
- `models/trading_model_crypto_swing.joblib` - For crypto swing trading

## Integration with Main Bot
The main bot (`main.py`) will automatically:
1. Detect asset type (forex/crypto/indices)
2. Load the appropriate model (scalp/swing based on timeframe)
3. Calculate all 38 features in real-time
4. Get AI predictions with confidence scores
5. Use predictions to filter trade entries

## Key Advantages

### 1. **Institutional-Grade Analysis**
The bot now "thinks" like smart money, identifying where institutions are likely to enter/exit.

### 2. **Multi-Dimensional Decision Making**
Instead of just RSI/MACD, the AI considers:
- Market structure context
- Liquidity positioning
- Institutional footprints (OBs)
- Price imbalances (FVGs)
- Premium/discount positioning
- Multi-timeframe alignment

### 3. **Adaptive Learning**
The model learns from historical data which combinations of SMC features led to profitable trades.

### 4. **Reduced False Signals**
By requiring confluence of multiple SMC factors, the AI filters out low-probability setups.

## Next Steps

### Immediate Actions:
1. **Retrain the model** with the new SMC features
2. **Test on demo account** to validate performance
3. **Monitor AI confidence scores** in the UI

### Future Enhancements:
1. **Session timing** - Implement actual timezone detection for kill zones
2. **HTF data integration** - Use actual H4/Daily data for multi-timeframe analysis
3. **Volume profile** - Add volume-based liquidity detection
4. **Backtesting** - Create backtesting framework to validate SMC strategies
5. **Feature importance** - Analyze which SMC features are most predictive

## References
- Smart Money Concepts by @kevofx and @Litchfx (from uploaded images)
- ICT (Inner Circle Trader) methodology
- Institutional order flow analysis

---

**Created**: January 20, 2026  
**Version**: 2.0 - Smart Money Concepts Integration
