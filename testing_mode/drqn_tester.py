import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
import random
import numpy as np
from collections import deque
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from testing_mode.backtest_env import TradingEnv
class DRQN(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(DRQN, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, output_size)
    def forward(self, x, hidden=None):
        out, hidden = self.lstm(x, hidden)
        out = self.fc(out[:, -1, :])
        return out, hidden
class DRQNAgent:
    def __init__(self, input_size, output_size):
        self.gamma = 0.95
        self.epsilon = 1.0
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.9995
        self.memory = deque(maxlen=2000)
        self.model = DRQN(input_size, 64, output_size)
        self.target_model = DRQN(input_size, 64, output_size)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.0005)
        self.update_target_model()
    def update_target_model(self):
        self.target_model.load_state_dict(self.model.state_dict())
    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(3)
        state = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            q_values, _ = self.model(state)
        return torch.argmax(q_values).item()
    def train(self, batch_size=32):
        if len(self.memory) < batch_size:
            return
        batch = random.sample(self.memory, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        states = torch.FloatTensor(np.array(states))
        actions = torch.LongTensor(actions)
        rewards = torch.FloatTensor(rewards)
        next_states = torch.FloatTensor(np.array(next_states))
        dones = torch.FloatTensor(dones)
        q_values, _ = self.model(states)
        q_value = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)
        with torch.no_grad():
            next_q_values, _ = self.target_model(next_states)
            next_q_max = next_q_values.max(1)[0]
            target_q_value = rewards + (1 - dones) * self.gamma * next_q_max
        loss = nn.MSELoss()(q_value, target_q_value)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    def save(self, path):
        torch.save(self.model.state_dict(), path)
    def load(self, path):
        if os.path.exists(path):
            self.model.load_state_dict(torch.load(path))
            self.update_target_model()
            print(f"🧠 Loaded saved model from {path}")
            self.epsilon = 0.5 
def run_test_mode(data_path=None):
    print("🚀 Starting DRQN Testing Mode...")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_csv = os.path.join(current_dir, "real_data.csv")
    if data_path and os.path.exists(data_path):
        df = pd.read_csv(data_path)
        print(f"📊 Loading provided data: {data_path}")
    elif os.path.exists(default_csv):
        df = pd.read_csv(default_csv)
        print(f"📊 Loading real history from: {default_csv} ({len(df)} rows)")
    else:
        print("⚠️ No real data found. Using dummy synthetic data...")
        dates = pd.date_range('2023-01-01', periods=200)
        data = {
            'close': np.random.randn(200).cumsum() + 2000,
            'high': np.random.randn(200).cumsum() + 2005,
            'low': np.random.randn(200).cumsum() + 1995,
            'open': np.random.randn(200).cumsum() + 2000,
        }
        df = pd.DataFrame(data, index=dates)
    env = TradingEnv(df)
    agent = DRQNAgent(input_size=env.num_features, output_size=3)
    model_path = os.path.join(current_dir, "drqn_model.pth")
    agent.load(model_path)
    state, _ = env.reset()
    done = False
    episodes = 100
    best_profit = -float('inf')
    for ep in range(episodes):
        state, _ = env.reset()
        done = False
        total_reward = 0
        buy_signals = 0
        sell_signals = 0
        print(f"\n🔄 Episode {ep+1}/{episodes}...")
        while not done:
            action = agent.act(state)
            if action == 0: buy_signals += 1
            elif action == 1: sell_signals += 1
            next_state, reward, done, _, info = env.step(action)
            agent.memory.append((state, action, reward, next_state, done))
            agent.train(batch_size=32)
            state = next_state
            total_reward += reward
            if env.current_step % 500 == 0:
                print(f"   Step: {env.current_step} | Profit: {info['net_worth'] - env.initial_balance:.2f} | Epsilon: {agent.epsilon:.2f}")
        agent.update_target_model()
        final_profit = info['net_worth'] - env.initial_balance
        if final_profit > best_profit and final_profit > 0:
            best_profit = final_profit
            agent.save(model_path)
            print(f"💾 New Best Score! Saved Model. Profit: ${best_profit:.2f}")
        color = "🟢" if final_profit > 0 else "🔴"
        status = "PROFIT" if final_profit > 0 else "LOSS"
        print(f"{color} Ep {ep+1} Finished | P/L: ${final_profit:.2f} | Actions: {buy_signals} Buys, {sell_signals} Sells")
    print("🏁 Testing Mode Finished.")
    print("\nℹ️  To understand these results, read: testing_mode/LOG_EXPLANATION.md")
if __name__ == "__main__":
    run_test_mode()
