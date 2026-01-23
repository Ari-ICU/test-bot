import pandas as pd
import logging
from core.indicators import Indicators

logger = logging.getLogger(__name__)

def analyze_scalping_setup(candles, df=None):
    """
    Optimized M1/M5 Scalping Strategy (SAFE VERSION)
    """
    if df is None:
        if not candles or len(candles) < 50:
            return "NEUTRAL", {"reason": "Insufficient data (<50 candles)"}
        df = pd.DataFrame(candles)

    try:
        # -------------------------------
        # FORCE NUMERIC TYPES (CRITICAL)
        # -------------------------------
        numeric_cols = ['open', 'high', 'low', 'close']
        for col in numeric_cols:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # -------------------------------
        # INDICATORS
        # -------------------------------
        if 'ema_50' not in df:
            df['ema_50'] = Indicators.calculate_ema(df['close'], 50)

        if 'rsi' not in df:
            df['rsi'] = Indicators.calculate_rsi(df['close'], 14)

        if 'stoch_k' not in df or 'stoch_d' not in df:
            stoch = Indicators.calculate_stoch(df)
            if not isinstance(stoch, (tuple, list)) or len(stoch) < 2:
                return "NEUTRAL", {"reason": "Stochastic calc failed"}
            df['stoch_k'], df['stoch_d'] = stoch

        # Ensure numeric
        for col in ['ema_50', 'rsi', 'stoch_k', 'stoch_d']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Drop NaNs
        df = df.dropna()
        if len(df) < 2:
            return "NEUTRAL", {"reason": "Insufficient valid data"}

        current = df.iloc[-1]
        prev = df.iloc[-2]

        # -------------------------------
        # LOGIC FILTERS
        # -------------------------------
        is_rsi_buy = current['rsi'] < 50
        is_rsi_sell = current['rsi'] > 50

        bullish_cross = prev['stoch_k'] <= prev['stoch_d'] and current['stoch_k'] > current['stoch_d']
        bearish_cross = prev['stoch_k'] >= prev['stoch_d'] and current['stoch_k'] < current['stoch_d']

        is_near_ema = abs(current['close'] - current['ema_50']) <= (current['close'] * 0.0002)

        # -------------------------------
        # BUY LOGIC
        # -------------------------------
        if current['close'] > current['ema_50'] or (is_near_ema and bullish_cross):
            if is_rsi_buy and bullish_cross and current['stoch_k'] < 40:
                return "BUY", {
                    "reason": "Scalp: Trend Up + Bullish Momentum",
                    "price": float(current['close']),
                    "ema": float(current['ema_50']),
                    "rsi": float(current['rsi']),
                    "stoch": float(current['stoch_k'])
                }

            if current['low'] < current['ema_50'] and bullish_cross:
                return "BUY", {
                    "reason": "Scalp: Dip to EMA + Recovery",
                    "price": float(current['close']),
                    "ema": float(current['ema_50']),
                    "rsi": float(current['rsi']),
                    "stoch": float(current['stoch_k'])
                }

        # -------------------------------
        # SELL LOGIC
        # -------------------------------
        if current['close'] < current['ema_50'] or (is_near_ema and bearish_cross):
            if is_rsi_sell and bearish_cross and current['stoch_k'] > 60:
                return "SELL", {
                    "reason": "Scalp: Trend Down + Bearish Momentum",
                    "price": float(current['close']),
                    "ema": float(current['ema_50']),
                    "rsi": float(current['rsi']),
                    "stoch": float(current['stoch_k'])
                }

            if current['high'] > current['ema_50'] and bearish_cross:
                return "SELL", {
                    "reason": "Scalp: Spike to EMA + Stoch Rejection",
                    "price": float(current['close']),
                    "ema": float(current['ema_50']),
                    "rsi": float(current['rsi']),
                    "stoch": float(current['stoch_k'])
                }

        return "NEUTRAL", {"reason": "No confluence of Trend/RSI/Stochastic"}

    except Exception as e:
        logger.exception("💥 Scalping Strategy Crash")
        return "NEUTRAL", {"reason": f"Scalping failed: {str(e)}"}
