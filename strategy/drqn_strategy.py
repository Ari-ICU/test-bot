import pandas as pd
import numpy as np
import os
from core.drqn_model import DRQNAgent
from core.indicators import Indicators

# Singleton instance
_agent = None

def get_agent(input_size=5): # Default input size, will be adjusted on init
    global _agent
    if _agent is None:
        _agent = DRQNAgent(input_size=input_size, output_size=3)
        # Load trained weights
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Path relative to strategy/ -> go up to project root -> testing_mode -> model
        model_path = os.path.abspath(os.path.join(current_dir, "..", "testing_mode", "drqn_model.pth"))
        _agent.load(model_path)
    return _agent

def prepare_features(df):
    """
    Replicates the feature engineering from backtest_env.py EXACTLY.
    Input: df with 'close' column (and others)
    Output: normalized numpy array of shape (window_size, num_features)
    """
    feature_df = df.copy()
    if 'time' in feature_df.columns:
        feature_df = feature_df.drop(columns=['time'])

    # 1. Percent Change (Momentum)
    pct_change = feature_df.pct_change().fillna(0) * 100
    
    # 2. RSI
    # Use Indicators helper if available, or manual calc to match training env exactly
    # Training Env manual calc:
    delta = feature_df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    feature_df['rsi'] = 100 - (100 / (1 + rs))
    feature_df['rsi'] = feature_df['rsi'].fillna(50) / 100.0  # Normalize 0-1
    
    # 3. SMA Distance
    feature_df['sma_50'] = feature_df['close'].rolling(window=50).mean()
    feature_df['dist_sma50'] = (feature_df['close'] - feature_df['sma_50']) / feature_df['sma_50'] * 100
    feature_df['dist_sma50'] = feature_df['dist_sma50'].fillna(0)
    
    # Combine
    obs_df = pd.concat([pct_change, feature_df[['rsi', 'dist_sma50']]], axis=1).fillna(0)
    
    # Take last 10 rows (Window Size)
    window_size = 10
    if len(obs_df) < window_size:
        return None # Not enough data
        
    obs = obs_df.iloc[-window_size:].values.astype(np.float32)
    return obs

def analyze_drqn_setup(candles, df, detected_patterns=None):
    """
    Strategy interface compatible with main.py
    """
    try:
        # Preprocess features
        obs = prepare_features(df)
        if obs is None:
            return "NEUTRAL", "Not enough data for DRQN window (need 10+ bars)"
            
        # Get Agent
        # num_features = columns in obs (e.g., if df has OHLC + 2 extra = 6? Wait, check prepare_features)
        # pct_change of OHLC (4 cols) + RSI + DistSMA = 6 features usually
        # We need to ensure input_size matches the trained model.
        # Logic: Instantiate agent with detected dims
        num_features = obs.shape[1]
        agent = get_agent(input_size=num_features)
        
        # Get Action
        action = agent.act(obs)
        
        # Translate to Signal
        # 0 = Buy, 1 = Sell, 2 = Hold
        if action == 0:
            return "BUY", "DRQN Agent Signal (0)"
        elif action == 1:
            return "SELL", "DRQN Agent Signal (1)"
        else:
            return "NEUTRAL", "DRQN Agent Hold (2)"
            
    except Exception as e:
        return "NEUTRAL", f"DRQN Error: {str(e)}"
