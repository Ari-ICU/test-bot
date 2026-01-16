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
        self.max_daily_trades = self.config.get('max_daily_trades', 5)
        # Reduced cool-off for smoother operational flow if needed
        self.cool_off_period = self.config.get('cool_off_minutes', 15) * 60 
        
        self.daily_trades_count = 0
        self.last_trade_time = 0

    def can_trade(self, current_drawdown_pct):
        """
        Psychological Gatekeeper: Checks if the bot is allowed to trade.
        """
        if current_drawdown_pct > self.max_daily_loss:
            return False, f"Daily drawdown limit ({self.max_daily_loss}%) reached."

        if self.daily_trades_count >= self.max_daily_trades:
            return False, f"Max daily trades ({self.max_daily_trades}) reached."

        time_since_last = time.time() - self.last_trade_time
        if time_since_last < self.cool_off_period:
            remaining_mins = int((self.cool_off_period - time_since_last) / 60)
            return False, f"Psychological cool-off: {remaining_mins} mins remaining."

        return True, "Ready"

    def record_trade(self):
        self.daily_trades_count += 1
        self.last_trade_time = time.time()

    def reset_daily_stats(self):
        self.daily_trades_count = 0

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol_type="XAUUSD", equity=None):
        """
        Calculates dynamic lot size based on risk percentage and contract specs.
        """
        base_capital = equity if equity is not None else balance
        if base_capital <= 0: return self.min_lot
        
        risk_amount = base_capital * (self.risk_per_trade / 100.0)
        dist_points = abs(entry_price - sl_price)
        
        # Prevent division by zero if SL is too tight
        if dist_points < 0.00001: return self.min_lot

        # Standard Gold (XAUUSD) vs Forex Calculation
        if "XAU" in symbol_type.upper():
            raw_lot = risk_amount / (dist_points * 100)
        else:
            # Assumes 1.00000 format; adjust multiplier if using points/pips specifically
            raw_lot = risk_amount / (dist_points * 100000)
                
        final_lot = max(self.min_lot, round(raw_lot, 2))
        return min(final_lot, 5.0) 

    def calculate_sl_tp(self, price, action, atr, digits=2, risk_reward_ratio=1.2):
        """
        FIXED: Enhanced for 'Smooth and Small TP' execution.
        Uses a tighter Risk-Reward ratio (default 1.2) for faster exits.
        """
        # 1. Smoother Volatility calculation
        # If ATR is missing, use a very small 0.05% price buffer for scalping
        volatility = atr if (atr and atr > 0) else price * 0.0005
        
        # 2. Minimum safety distance (StopsLevel protection)
        # Prevents 'Invalid Stops' errors on tight brokers
        min_dist = price * 0.0003 

        # 3. Calculate SL based on 1.2x ATR for a 'snug' fit
        sl_dist = max(volatility * 1.2, min_dist)
        
        # 4. Small TP target: Uses the provided ratio (1.2x the risk)
        # This ensures high win-rate scalping by exiting quickly
        tp_dist = sl_dist * risk_reward_ratio
        
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else: # SELL
            sl = price + sl_dist
            tp = price - tp_dist
            
        # 5. Final validation to ensure SL/TP are on the correct sides of the market
        if action == "SELL":
            if sl <= price: sl = price + min_dist
            if tp >= price: tp = price - min_dist
        else: # BUY
            if sl >= price: sl = price - min_dist
            if tp <= price: tp = price + min_dist

        return round(sl, digits), round(tp, digits)