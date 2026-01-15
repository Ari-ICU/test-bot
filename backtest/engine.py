import sys
import os
import pandas as pd
import MetaTrader5 as mt5

# Fix path to allow importing from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.risk import RiskManager
from core.indicators import Indicators
from core.patterns import detect_patterns
import strategy.trend_following as trend
import strategy.reversal as reversal
import strategy.breakout as breakout

class Backtester:
    def __init__(self, symbol="XAUUSD", timeframe=mt5.TIMEFRAME_H1, n_candles=5000):
        self.symbol = symbol
        self.timeframe = timeframe
        self.n_candles = n_candles
        self.balance = 10000.0  # Initial Balance
        self.equity = 10000.0
        self.positions = []
        self.trade_history = []
        
        # Load Config (Mock)
        self.risk = RiskManager({'risk': {'risk_per_trade': 1.0, 'max_daily_loss': 5.0}})

    def fetch_data(self):
        """Fetch historical data from MT5 for testing."""
        if not mt5.initialize():
            print("❌ MT5 Init Failed")
            return None
        
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, self.n_candles)
        mt5.shutdown()
        
        if rates is None:
            print("❌ No Data Found")
            return None
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def run(self):
        print(f"🔄 Starting Backtest on {self.symbol} ({self.n_candles} candles)...")
        data = self.fetch_data()
        if data is None: return

        # Indicators pre-calculation (Optional speedup, but we simulate real-time loop)
        print("📊 Processing indicators...")
        
        # Simulation Loop
        for i in range(100, len(data)):
            # Slice data to simulate "Live" state (0 to current i)
            # In production we pass a list of dicts, so we convert tail to dict
            window = data.iloc[i-100:i+1] # Lookback 100 candles
            current_candle = window.iloc[-1]
            current_price = current_candle['close']
            
            # Convert to list of dicts for strategy compatibility
            candles_list = window.to_dict('records')
            
            # 1. Manage Open Positions (Check TP/SL)
            self.check_positions(current_candle)
            
            # 2. Get Strategy Signals
            decisions = []
            decisions.append(trend.analyze_trend_setup(candles_list))
            decisions.append(reversal.analyze_reversal_setup(candles_list))
            decisions.append(breakout.analyze_breakout_setup(candles_list))
            
            final_action = "NEUTRAL"
            reason = ""
            
            # Priority: Take first valid signal
            for action, r in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    reason = r
                    break
            
            # 3. Execute Trade
            if final_action in ["BUY", "SELL"]:
                # Only 1 trade at a time for backtest simplicity
                if len(self.positions) == 0: 
                    self.execute_trade(final_action, current_price, reason, candles_list)

        self.print_results()

    def execute_trade(self, action, price, reason, candles):
        # Calculate Volatility for SL
        # We need a quick ATR calc here since we are inside the loop
        # (Or use the RiskManager if it accepts candle data)
        # Using simple ATR proxy for backtest speed
        df = pd.DataFrame(candles)
        atr = Indicators.calculate_atr(df).iloc[-1]
        
        sl, tp = self.risk.calculate_sl_tp(price, action, atr)
        lot = self.risk.calculate_lot_size(self.balance, price, sl)
        
        trade = {
            'action': action,
            'entry_price': price,
            'sl': sl,
            'tp': tp,
            'lot': lot,
            'reason': reason,
            'open_time': candles[-1]['time']
        }
        self.positions.append(trade)
        # print(f"🚀 {action} at {price:.2f} | Reason: {reason}")

    def check_positions(self, candle):
        high = candle['high']
        low = candle['low']
        
        for pos in self.positions[:]:
            pnl = 0
            closed = False
            
            # Check SL/TP
            if pos['action'] == "BUY":
                if low <= pos['sl']: # SL Hit
                    pnl = (pos['sl'] - pos['entry_price']) * pos['lot'] * 100 # Approx multiplier
                    closed = True
                    result = "SL"
                elif high >= pos['tp']: # TP Hit
                    pnl = (pos['tp'] - pos['entry_price']) * pos['lot'] * 100
                    closed = True
                    result = "TP"
                    
            elif pos['action'] == "SELL":
                if high >= pos['sl']: # SL Hit
                    pnl = (pos['entry_price'] - pos['sl']) * pos['lot'] * 100
                    closed = True
                    result = "SL"
                elif low <= pos['tp']: # TP Hit
                    pnl = (pos['entry_price'] - pos['tp']) * pos['lot'] * 100
                    closed = True
                    result = "TP"
            
            if closed:
                self.balance += pnl
                self.positions.remove(pos)
                self.trade_history.append({'pnl': pnl, 'result': result})

    def print_results(self):
        wins = len([t for t in self.trade_history if t['pnl'] > 0])
        losses = len([t for t in self.trade_history if t['pnl'] <= 0])
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum([t['pnl'] for t in self.trade_history])
        
        print("\n" + "="*40)
        print(f"🏁 BACKTEST RESULTS ({self.symbol})")
        print("="*40)
        print(f"Trades Taken : {total}")
        print(f"Wins         : {wins}")
        print(f"Losses       : {losses}")
        print(f"Win Rate     : {win_rate:.2f}%")
        print(f"Final Balance: ${self.balance:,.2f}")
        print(f"Total Profit : ${total_pnl:,.2f}")
        print("="*40)

if __name__ == "__main__":
    # How to run: python3 backtest/engine.py
    bt = Backtester("XAUUSD", mt5.TIMEFRAME_H1, 5000)
    bt.run()