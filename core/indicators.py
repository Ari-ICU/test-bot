import pandas as pd
import numpy as np

class Indicators:
    @staticmethod
    def calculate_sma(series, period=14):
        return series.rolling(window=period).mean()

    @staticmethod
    def calculate_ema(series, period=14):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_atr(df, period=14):
        """Average True Range for Volatility"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def calculate_adx(df, period=14):
        """Average Directional Index (Trend Strength)"""
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm = plus_dm.where((plus_dm > 0) & (plus_dm > minus_dm), 0.0)
        minus_dm = -minus_dm.where((minus_dm > 0) & (minus_dm > plus_dm), 0.0)
        
        tr = Indicators.calculate_atr(df, period)
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / tr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / tr)
        dx = 100 * np.abs((plus_di - minus_di) / (plus_di + minus_di))
        return dx.rolling(window=period).mean()

    @staticmethod
    def calculate_supertrend(df, period=10, multiplier=3):
        """SuperTrend Indicator"""
        atr = Indicators.calculate_atr(df, period)
        hl2 = (df['high'] + df['low']) / 2
        
        # Calculate Basic Bands
        final_upperband = hl2 + (multiplier * atr)
        final_lowerband = hl2 - (multiplier * atr)
        
        supertrend = [True] * len(df) # True = Green (Buy), False = Red (Sell)
        
        for i in range(1, len(df)):
            # Trend Logic
            if df['close'].iloc[i] > final_upperband.iloc[i-1]:
                supertrend[i] = True
            elif df['close'].iloc[i] < final_lowerband.iloc[i-1]:
                supertrend[i] = False
            else:
                supertrend[i] = supertrend[i-1]
                
                # Adjust bands to not move against the trend
                if supertrend[i] and final_lowerband.iloc[i] < final_lowerband.iloc[i-1]:
                    final_lowerband.iloc[i] = final_lowerband.iloc[i-1]
                if not supertrend[i] and final_upperband.iloc[i] > final_upperband.iloc[i-1]:
                    final_upperband.iloc[i] = final_upperband.iloc[i-1]
                    
        return pd.Series(supertrend, index=df.index), final_upperband, final_lowerband