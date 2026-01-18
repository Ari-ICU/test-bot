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
        """Corrected Wilder's ADX (Trend Strength)"""
        df_copy = df.copy()
        
        # 1. TR and DM components
        high_low = df_copy['high'] - df_copy['low']
        high_close = np.abs(df_copy['high'] - df_copy['close'].shift())
        low_close = np.abs(df_copy['low'] - df_copy['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        up_move = df_copy['high'].diff()
        down_move = df_copy['low'].shift() - df_copy['low']
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        # 2. Smooth TR and DM using Wilder's (EMA-like)
        alpha = 1 / period
        atr_smoothed = tr.ewm(alpha=alpha, adjust=False).mean()
        plus_dm_smoothed = pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean()
        minus_dm_smoothed = pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean()
        
        # 3. DI+ and DI-
        plus_di = 100 * (plus_dm_smoothed / atr_smoothed)
        minus_di = 100 * (minus_dm_smoothed / atr_smoothed)
        
        # 4. DX and ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(alpha=alpha, adjust=False).mean()
        
        return adx

    @staticmethod
    def calculate_supertrend(df, period=10, multiplier=3):
        """SuperTrend Indicator"""
        atr = Indicators.calculate_atr(df, period)
        hl2 = (df['high'] + df['low']) / 2
        
        final_upperband = hl2 + (multiplier * atr)
        final_lowerband = hl2 - (multiplier * atr)
        
        supertrend = [True] * len(df)
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > final_upperband.iloc[i-1]:
                supertrend[i] = True
            elif df['close'].iloc[i] < final_lowerband.iloc[i-1]:
                supertrend[i] = False
            else:
                supertrend[i] = supertrend[i-1]
                if supertrend[i] and final_lowerband.iloc[i] < final_lowerband.iloc[i-1]:
                    final_lowerband.iloc[i] = final_lowerband.iloc[i-1]
                if not supertrend[i] and final_upperband.iloc[i] > final_upperband.iloc[i-1]:
                    final_upperband.iloc[i] = final_upperband.iloc[i-1]
                    
        return pd.Series(supertrend, index=df.index), final_upperband, final_lowerband

    @staticmethod
    def calculate_macd(series, fast=12, slow=26, signal=9):
        """MACD: Moving Average Convergence Divergence"""
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram

    @staticmethod
    def calculate_bollinger_bands(series, period=20, std_dev=2):
        """Bollinger Bands"""
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, lower

    @staticmethod
    def calculate_keltner_channels(df, period=20, multiplier=1.5):
        """Keltner Channels using ATR"""
        ema = Indicators.calculate_ema(df['close'], period)
        atr = Indicators.calculate_atr(df, period)
        upper = ema + (multiplier * atr)
        lower = ema - (multiplier * atr)
        return upper, lower

    @staticmethod
    def is_bollinger_squeeze(df, period=20):
        """Returns True if BB is inside Keltner Channels (The Squeeze)"""
        bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'], period, 2)
        kc_upper, kc_lower = Indicators.calculate_keltner_channels(df, period, 1.5)
    
        # Use bitwise '&' for Series comparison
        squeeze_series = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        
        # Return only the most recent value (last candle)
        return squeeze_series.iloc[-1]

    @staticmethod
    def calculate_stoch(df, period=14, smooth_k=3, smooth_d=3):
        """
        Stochastic Oscillator
        %K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100
        %D = Moving Average of %K
        """
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        
        # Calculate raw %K
        stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
        
        # Apply smoothing to get %K and %D
        k_line = stoch_k.rolling(window=smooth_k).mean()
        d_line = k_line.rolling(window=smooth_d).mean()
        
        return k_line, d_line