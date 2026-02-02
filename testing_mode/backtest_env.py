import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

class TradingEnv(gym.Env):
    """
    A custom OpenAI Gym-like environment for Financial DRQN testing.
    As per Algorithm 1: Financial DRQN Algorithm.
    """
    def __init__(self, df, window_size=10, initial_balance=10000):
        super(TradingEnv, self).__init__()
        
        self.raw_df = df.reset_index(drop=True)
        self.window_size = window_size
        self.initial_balance = initial_balance
        
        # Feature Engineering: Advanced Indicators
        feature_df = self.raw_df.copy()
        
        if 'time' in feature_df.columns:
            feature_df = feature_df.drop(columns=['time'])

        # 1. Percent Change (Momentum)
        pct_change = feature_df.pct_change().fillna(0) * 100
        
        # 2. RSI (Relative Strength Index)
        delta = feature_df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        feature_df['rsi'] = 100 - (100 / (1 + rs))
        feature_df['rsi'] = feature_df['rsi'].fillna(50) / 100.0  # Normalize 0-1
        
        # 3. SMA Distance (Trend)
        feature_df['sma_50'] = feature_df['close'].rolling(window=50).mean()
        feature_df['dist_sma50'] = (feature_df['close'] - feature_df['sma_50']) / feature_df['sma_50'] * 100
        feature_df['dist_sma50'] = feature_df['dist_sma50'].fillna(0)
        
        # Combine features: Pct Change + RSI + SMA Distance
        self.obs_df = pd.concat([pct_change, feature_df[['rsi', 'dist_sma50']]], axis=1).fillna(0)
        
        # Action space: 0 = Buy, 1 = Sell, 2 = Hold
        self.action_space = spaces.Discrete(3)
        
        # Update feature count based on engineered features
        self.num_features = len(self.obs_df.columns)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, 
            shape=(self.window_size, self.num_features), 
            dtype=np.float32
        )
        
        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = self.window_size
        self.balance = self.initial_balance
        self.shares_held = 0
        self.net_worth = self.initial_balance
        self.history = []
        
        return self._get_observation(), {}

    def _get_observation(self):
        # Return the NORMALIZED window (pct change), not raw prices
        obs = self.obs_df.iloc[self.current_step - self.window_size : self.current_step].values
        return obs.astype(np.float32)

    def step(self, action):
        # Use raw_df for REAL price calculation
        current_price = self.raw_df.iloc[self.current_step]['close']
        
        # Penalties & Costs
        spread_cost = current_price * 0.0002  # 0.02% spread/commission estimate per trade
        trade_penalty = 0
        
        # Limit positions
        max_pos = 1
        
        if action == 0: # Buy
            if self.shares_held < max_pos and self.balance > current_price:
                self.shares_held += 1
                self.balance -= current_price
                trade_penalty = spread_cost # Punish entering
                
        elif action == 1: # Sell
            if self.shares_held > 0:
                self.shares_held -= 1
                self.balance += current_price
                trade_penalty = spread_cost # Punish exiting
        
        # action 2 = Hold
        
        self.current_step += 1
        done = self.current_step >= len(self.raw_df) - 1
        
        new_net_worth = self.balance + (self.shares_held * current_price)
        
        # REWARD CALCULATION
        # 1. Money Made/Lost in this step
        step_pnl = new_net_worth - self.net_worth
        
        # 2. Add Transaction Cost
        reward = step_pnl - trade_penalty
        
        # 3. Holding Reward (Optional: Encourage letting winners run)
        # If we are holding and making money, give a tiny drip of dopamine
        if self.shares_held > 0 and step_pnl > 0:
            reward += 0.1 # Small bonus for holding during uptrend
            
        # 4. Scale for Neural Network (-1 to 1 range is ideal)
        reward = reward / 10.0
        
        self.net_worth = new_net_worth
        
        obs = self._get_observation()
        
        return obs, reward, done, False, {"net_worth": self.net_worth}

    def render(self, mode='human'):
        print(f"Step: {self.current_step}, Net Worth: {self.net_worth:.2f}")
