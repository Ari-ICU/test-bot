# 🧪 Financial DRQN Testing Mode

This folder contains the implementation and environment for testing the **Financial DRQN (Deep Recurrent Q-Network) Algorithm**, as outlined in the research methodology for reinforcement learning in trading.

## 📁 Contents

- `backtest_env.py`: A custom OpenAI Gym-compatible environment (`TradingEnv`) that simulates trading conditions for the DRQN agent.
- `drqn_tester.py`: The core implementation of the DRQN algorithm, including:
  - LSTM-based Q-Network
  - Target Network for stability
  - Experience Replay mechanism (to be fully implemented)
  - Training and Evaluation loops

## 🚀 How to Run

To start the testing mode demonstration:

```bash
python testing_mode/drqn_tester.py
```

## 🧠 Algorithm Overview (Financial DRQN)

As per Algorithm 1:
1. **Initialize**: Recurrent Q-network $Q_\theta$, target network $Q_{\theta^-}$, and experience memory $\mathcal{D}$.
2. **Observe**: Initial state $s$ from the environment (window of candle data + indicators).
3. **Select Action**: Choose action $a$ (Buy/Sell/Hold) using epsilon-greedy policy.
4. **Reward**: Receive reward $r$ (change in Net Worth) and observe next state $s'$.
5. **Store**: Save transition $(s, a, r, s')$ in memory $\mathcal{D}$.
6. **Train**: Sample sequences from $\mathcal{D}$ and update $Q_\theta$ using the Bellman equation for recurrent networks.
7. **Update**: Periodically soft-update the target network parameters $\theta^-$.

## 🛠 Next Steps

- [ ] Integrate real MT5 historical data export into the `backtest_env`.
- [ ] Implement full experience replay with sequence sampling.
- [ ] Add reward shaping for risk-adjusted returns (Sharpe Ratio).
- [ ] Connect the DRQN predictions to the main bot engine as an optional strategy.
