import pandas as pd
import logging
from core.indicators import Indicators
from core.patterns import detect_patterns

logger = logging.getLogger(__name__)

def analyze_trend_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 50:
            return "NEUTRAL", {"reason": "Insufficient data"}
        df = pd.DataFrame(candles)

    try:
        # -------------------------
        # FORCE NUMERIC (CRITICAL)
        # -------------------------
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # -------------------------
        # INDICATORS
        # -------------------------
        if 'ema_200' not in df:
            df['ema_200'] = Indicators.calculate_ema(df['close'], 200)

        if 'adx' not in df:
            df['adx'] = Indicators.calculate_adx(df)

        if 'supertrend' not in df:
            st, _, _ = Indicators.calculate_supertrend(df)
            df['supertrend'] = st

        if 'macd' not in df or 'macd_signal' not in df:
            macd, macd_sig, _ = Indicators.calculate_macd(df['close'])
            df['macd'], df['macd_signal'] = macd, macd_sig

        df = df.dropna()
        if len(df) < 3:
            return "NEUTRAL", {"reason": "Indicators warming up"}

        current = df.iloc[-1]

        # -------------------------
        # PATTERNS
        # -------------------------
        if patterns is None:
            patterns = detect_patterns(candles, df=df)

        # -------------------------
        # TREND DIRECTION
        # -------------------------
        is_uptrend = current['close'] > current['ema_200'] and bool(current['supertrend'])
        is_downtrend = current['close'] < current['ema_200'] and not bool(current['supertrend'])

        if not is_uptrend and not is_downtrend:
            return "NEUTRAL", {"reason": "Sideways / Mixed Trend"}

        # -------------------------
        # BUY LOGIC
        # -------------------------
        if is_uptrend:
            if not (current['macd'] > current['macd_signal'] or (current['macd'] > 0 and current['adx'] > 30)):
                return "NEUTRAL", {"reason": "Bullish trend but weak momentum"}

            trigger = None
            if patterns.get('demand_zone'): trigger = "Demand"
            elif patterns.get('bullish_flag'): trigger = "Flag"
            elif patterns.get('bullish_fvg'): trigger = "FVG"
            elif patterns.get('bullish_engulfing'): trigger = "Engulfing"
            elif patterns.get('double_bottom'): trigger = "Double Bottom"

            if trigger or current['adx'] > 25:
                return "BUY", {
                    "reason": f"Trend Confluence ({trigger or 'High ADX'})",
                    "price": float(current['close']),
                    "ema": float(current['ema_200']),
                    "adx": float(current['adx']),
                    "macd": float(current['macd'])
                }

        # -------------------------
        # SELL LOGIC
        # -------------------------
        if is_downtrend:
            if not (current['macd'] < current['macd_signal'] or (current['macd'] < 0 and current['adx'] > 30)):
                return "NEUTRAL", {"reason": "Bearish trend but weak momentum"}

            trigger = None
            if patterns.get('supply_zone'): trigger = "Supply"
            elif patterns.get('bearish_flag'): trigger = "Flag"
            elif patterns.get('bearish_fvg'): trigger = "FVG"
            elif patterns.get('bearish_engulfing'): trigger = "Engulfing"
            elif patterns.get('double_top'): trigger = "Double Top"

            if trigger or current['adx'] > 25:
                return "SELL", {
                    "reason": f"Trend Confluence ({trigger or 'High ADX'})",
                    "price": float(current['close']),
                    "ema": float(current['ema_200']),
                    "adx": float(current['adx']),
                    "macd": float(current['macd'])
                }

        return "NEUTRAL", {"reason": "No valid trend setup"}

    except Exception as e:
        logger.exception("💥 Trend Strategy Crash")
        return "NEUTRAL", {"reason": str(e)}
