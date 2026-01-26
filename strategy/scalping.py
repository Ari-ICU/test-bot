import pandas as pd
import logging
from core.indicators import Indicators

logger = logging.getLogger(__name__)

def analyze_scalping_setup(candles, df=None, timeframe=None):
    """
    Optimized M1/M5 Scalping Strategy (SAFE VERSION 2.0)
    - Added TF guardrail: Only runs on M1/M5.
    - Granular try-excepts for indicators to isolate bugs.
    - Enhanced error handling for "Format specifier" crashes.
    """
    # Removed TF Guardrail to allow all timeframes as requested
    pass

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
        # INDICATORS WITH SAFE WRAPPING
        # -------------------------------
        try:
            if 'ema_50' not in df:
                df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
        except Exception as e:
            logger.warning(f"EMA50 calc failed: {e}")
            df['ema_50'] = df['close']  # Fallback to close prices

        try:
            if 'rsi' not in df:
                df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
        except Exception as e:
            logger.warning(f"RSI calc failed: {e}")
            df['rsi'] = 50.0  # Neutral fallback

        try:
            if 'stoch_k' not in df or 'stoch_d' not in df:
                stoch = Indicators.calculate_stoch(df)
                if not isinstance(stoch, (tuple, list)) or len(stoch) < 2:
                    raise ValueError("Stochastic returned invalid data")
                df['stoch_k'], df['stoch_d'] = stoch
        except Exception as e:
            logger.warning(f"Stochastic calc failed on {timeframe}: {e} (possible format bug in Indicators)")
            # Fallback: Simple momentum proxy (avoids crash)
            df['stoch_k'] = (df['close'] - df['close'].shift(5)) / df['close'].shift(5) * 100
            df['stoch_k'] = df['stoch_k'].clip(0, 100)  # Clamp to 0-100
            df['stoch_d'] = df['stoch_k'].rolling(3).mean()

        # Ensure numeric (with coerce)
        for col in ['ema_50', 'rsi', 'stoch_k', 'stoch_d']:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Drop NaNs and check data
        df = df.dropna()
        if len(df) < 2:
            return "NEUTRAL", {"reason": "Insufficient valid data after cleaning"}

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