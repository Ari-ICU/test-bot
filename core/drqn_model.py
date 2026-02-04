import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
import os
from collections import deque
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
        self.epsilon = 0.05
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
    def load(self, path):
        if os.path.exists(path):
            self.model.load_state_dict(torch.load(path))
            self.update_target_model()
            print(f"🧠 DRQN: Loaded model from {path}")
        else:
            print(f"⚠️ DRQN: Model file not found at {path}")