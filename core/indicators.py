import pandas as pd
import numpy as np

def calculate_rsi(candles, period=14):
    try:
        df = pd.DataFrame(candles)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs)).iloc[-1]
    except: return 50.0

def calculate_macd(candles, fast=12, slow=26, signal=9):
    try:
        df = pd.DataFrame(candles)
        short_ema = df['close'].ewm(span=fast, adjust=False).mean()
        long_ema = df['close'].ewm(span=slow, adjust=False).mean()
        macd = short_ema - long_ema
        sig = macd.ewm(span=signal, adjust=False).mean()
        return macd.iloc[-1], sig.iloc[-1]
    except: return 0.0, 0.0

def calculate_atr(candles, period=14):
    try:
        df = pd.DataFrame(candles)
        high_low = df['high'] - df['low']
        high_pc = (df['high'] - df['close'].shift(1)).abs()
        low_pc = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
        return float(tr.rolling(window=period).mean().iloc[-1])
    except: return 0.0

def calculate_bollinger_bands(candles, period=20, dev=2.0):
    try:
        df = pd.DataFrame(candles)
        sma = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        upper = sma + (std * dev)
        lower = sma - (std * dev)
        return upper.iloc[-1], lower.iloc[-1], sma.iloc[-1]
    except: return 0.0, 0.0, 0.0

def calculate_vwap(candles):
    """Calculates Volume Weighted Average Price."""
    try:
        df = pd.DataFrame(candles)
        v = df['volume'] if 'volume' in df else 1 # Fallback if no volume
        tp = (df['high'] + df['low'] + df['close']) / 3
        return (tp * v).cumsum() / v.cumsum()
    except: return 0.0