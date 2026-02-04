import pandas as pd
import numpy as np
import os
from core.drqn_model import DRQNAgent
from core.indicators import Indicators
_agent = None
def get_agent(input_size=5):
    global _agent
    if _agent is None:
        _agent = DRQNAgent(input_size=input_size, output_size=3)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.abspath(os.path.join(current_dir, "..", "testing_mode", "drqn_model.pth"))
        _agent.load(model_path)
    return _agent
def prepare_features(df):
    feature_df = df.copy()
    if 'time' in feature_df.columns:
        feature_df = feature_df.drop(columns=['time'])
    pct_change = feature_df.pct_change().fillna(0) * 100
    delta = feature_df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    feature_df['rsi'] = 100 - (100 / (1 + rs))
    feature_df['rsi'] = feature_df['rsi'].fillna(50) / 100.0
    feature_df['sma_50'] = feature_df['close'].rolling(window=50).mean()
    feature_df['dist_sma50'] = (feature_df['close'] - feature_df['sma_50']) / feature_df['sma_50'] * 100
    feature_df['dist_sma50'] = feature_df['dist_sma50'].fillna(0)
    obs_df = pd.concat([pct_change, feature_df[['rsi', 'dist_sma50']]], axis=1).fillna(0)
    window_size = 10
    if len(obs_df) < window_size:
        return None
    obs = obs_df.iloc[-window_size:].values.astype(np.float32)
    return obs
def analyze_drqn_setup(candles, df, detected_patterns=None):
    try:
        obs = prepare_features(df)
        if obs is None:
            return "NEUTRAL", "Not enough data for DRQN window (need 10+ bars)"
        num_features = obs.shape[1]
        agent = get_agent(input_size=num_features)
        action = agent.act(obs)
        if action == 0:
            return "BUY", "DRQN Agent Signal (0)"
        elif action == 1:
            return "SELL", "DRQN Agent Signal (1)"
        else:
            return "NEUTRAL", "DRQN Agent Hold (2)"
    except Exception as e:
        return "NEUTRAL", f"DRQN Error: {str(e)}"