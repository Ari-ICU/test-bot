import time
import logging

logger = logging.getLogger("RiskManager")

class RiskManager:
    def __init__(self, config):
        """
        Initializes the Risk Manager with safety and psychological parameters.
       
        """
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) 
        self.max_daily_loss = self.config.get('max_daily_loss', 5.0) 
        self.min_lot = 0.01
        
        # --- PSYCHOLOGY SETTINGS ---
        # Limits total trades per day to prevent overtrading
        self.max_daily_trades = self.config.get('max_daily_trades', 5)
        # Time in seconds to wait between trades to prevent revenge trading
        self.cool_off_period = self.config.get('cool_off_minutes', 30) * 60 
        
        # State tracking
        self.daily_trades_count = 0
        self.last_trade_time = 0

    def can_trade(self, current_drawdown_pct):
        """
        Psychological Gatekeeper: Checks if the bot is allowed to trade based on 
        performance and discipline rules.
        """
        # 1. Check Daily Drawdown
        if current_drawdown_pct > self.max_daily_loss:
            return False, f"Daily drawdown limit ({self.max_daily_loss}%) reached."

        # 2. Check Overtrading
        if self.daily_trades_count >= self.max_daily_trades:
            return False, f"Max daily trades ({self.max_daily_trades}) reached. Market rest required."

        # 3. Check Cool-off Period
        time_since_last = time.time() - self.last_trade_time
        if time_since_last < self.cool_off_period:
            remaining_mins = int((self.cool_off_period - time_since_last) / 60)
            return False, f"Psychological cool-off: {remaining_mins} mins remaining."

        return True, "Ready"

    def record_trade(self):
        """
        Updates trackers after a trade is successfully executed.
        """
        self.daily_trades_count += 1
        self.last_trade_time = time.time()

    def reset_daily_stats(self):
        """
        Resets daily counters. Should be called at the start of the trading day.
        """
        self.daily_trades_count = 0

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol_type="XAUUSD", equity=None):
        """
        Calculates dynamic lot size based on risk percentage and contract specs.
       
        """
        # Use Equity if provided to protect during existing drawdowns
        base_capital = equity if equity is not None else balance
        
        if base_capital <= 0: 
            return self.min_lot
        
        risk_amount = base_capital * (self.risk_per_trade / 100.0)
        dist_points = abs(entry_price - sl_price)
        
        if dist_points == 0: 
            return self.min_lot

        # Standard Gold (XAUUSD) calculation: 1 lot move of 1.00 = $100 profit/loss
        if "XAU" in symbol_type.upper():
            raw_lot = risk_amount / (dist_points * 100)
        else:
            # Standard Forex: 1 lot move of 0.0001 (1 pip) = $10
            raw_lot = risk_amount / (dist_points * 100000)
                
        final_lot = max(self.min_lot, round(raw_lot, 2))
        return min(final_lot, 5.0) # Hard cap for safety

    def calculate_sl_tp(self, price, action, atr, digits=2, risk_reward_ratio=2.0):
        """
        Enhanced SL/TP calculation with safety buffers to prevent Error 10016.
       
        """
        # Use 1.5x ATR for volatility or 0.1% of price as a minimum safety distance
        volatility = atr if atr > 0 else price * 0.002
        min_dist = price * 0.001 
        
        sl_dist = max(volatility * 1.5, min_dist)
        tp_dist = sl_dist * risk_reward_ratio
        
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else: # SELL
            sl = price + sl_dist
            tp = price - tp_dist
            
        # Final safety check: ensure SL is on the correct side of the price
        if action == "SELL" and sl <= price:
            sl = price + min_dist
        if action == "BUY" and sl >= price:
            sl = price - min_dist

        return round(sl, digits), round(tp, digits)