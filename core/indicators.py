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
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    @staticmethod
    def calculate_adx(df, period=14):
        df_copy = df.copy()
        high_low = df_copy['high'] - df_copy['low']
        high_close = np.abs(df_copy['high'] - df_copy['close'].shift())
        low_close = np.abs(df_copy['low'] - df_copy['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        up_move = df_copy['high'].diff()
        down_move = df_copy['low'].shift() - df_copy['low']
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        alpha = 1 / period
        atr_smoothed = tr.ewm(alpha=alpha, adjust=False).mean()
        plus_dm_smoothed = pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean()
        minus_dm_smoothed = pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean()
        plus_di = 100 * (plus_dm_smoothed / atr_smoothed)
        minus_di = 100 * (minus_dm_smoothed / atr_smoothed)
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(alpha=alpha, adjust=False).mean()
        return adx
    @staticmethod
    def calculate_supertrend(df, period=10, multiplier=3):
        atr = Indicators.calculate_atr(df, period)
        hl2 = (df['high'] + df['low']) / 2
        upper_vals = (hl2 + (multiplier * atr)).values
        lower_vals = (hl2 - (multiplier * atr)).values
        close_vals = df['close'].values
        final_upperband = upper_vals.copy()
        final_lowerband = lower_vals.copy()
        supertrend = [True] * len(df)
        for i in range(1, len(df)):
            if upper_vals[i] < final_upperband[i-1] or close_vals[i-1] > final_upperband[i-1]:
                final_upperband[i] = upper_vals[i]
            else:
                final_upperband[i] = final_upperband[i-1]
            if lower_vals[i] > final_lowerband[i-1] or close_vals[i-1] < final_lowerband[i-1]:
                final_lowerband[i] = lower_vals[i]
            else:
                final_lowerband[i] = final_lowerband[i-1]
            if close_vals[i] > final_upperband[i]:
                supertrend[i] = True
            elif close_vals[i] < final_lowerband[i]:
                supertrend[i] = False
            else:
                supertrend[i] = supertrend[i-1]
        return pd.Series(supertrend, index=df.index), pd.Series(final_upperband, index=df.index), pd.Series(final_lowerband, index=df.index)
    @staticmethod
    def calculate_macd(series, fast=12, slow=26, signal=9):
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram
    @staticmethod
    def calculate_bollinger_bands(series, period=20, std_dev=2):
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, lower
    @staticmethod
    def calculate_keltner_channels(df, period=20, multiplier=1.5):
        ema = Indicators.calculate_ema(df['close'], period)
        atr = Indicators.calculate_atr(df, period)
        upper = ema + (multiplier * atr)
        lower = ema - (multiplier * atr)
        return upper, lower
    @staticmethod
    def is_bollinger_squeeze(df, period=20):
        bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'], period, 2)
        kc_upper, kc_lower = Indicators.calculate_keltner_channels(df, period, 1.5)
        squeeze_series = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        return squeeze_series.iloc[-1]
    @staticmethod
    def calculate_stoch(df, period=14, smooth_k=3, smooth_d=3):
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        range_val = high_max - low_min
        range_val = range_val.where(range_val > 0, 1e-10)
        stoch_k = 100 * (df['close'] - low_min) / range_val
        stoch_k = stoch_k.clip(0, 100).fillna(50)
        k_line = stoch_k.rolling(window=smooth_k).mean().fillna(50)
        d_line = k_line.rolling(window=smooth_d).mean().fillna(50)
        return k_line, d_line