import time
import logging
from core.asset_detector import detect_asset_type  # New import

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
        self.max_lot = 10.0  # Broker limit
        
        # --- PSYCHOLOGY SETTINGS ---
        self.max_daily_trades = self.config.get('max_trades', 5) # Sync with config.json key
        self.cool_off_period = self.config.get('cool_off_minutes', 1) * 60 # Reduced default to 1 min
        
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

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol, equity=None):
        """
        Calculates dynamic lot size based on risk percentage and contract specs.
        Adjusted for forex (pip-based) vs crypto (point-based, e.g., BTC $1 per point).
        """
        base_capital = equity if equity is not None else balance
        if base_capital <= 0: 
            return self.min_lot
        
        asset_type = detect_asset_type(symbol)
        risk_multiplier = self.config.get(f"{asset_type}_risk_multiplier", 1.0)
        risk_amount = base_capital * (self.risk_per_trade / 100) * risk_multiplier
        
        dist_points = abs(entry_price - sl_price)
        if dist_points < 0.00001: 
            return self.min_lot

        # Forex (e.g., XAUUSD: $1 per 0.01 move, 100 oz contract)
        if asset_type == "forex":
            tick_value = 1.0 if "XAU" in symbol.upper() else 10.0  # Adjust per pair
            raw_lot = risk_amount / (dist_points * tick_value * 100)  # Pip multiplier
        # Crypto (e.g., BTCUSD: $0.01 per point, but volatile – cap lots)
        else:  # crypto
            tick_value = 0.01  # Standard for BTC/ETH
            raw_lot = risk_amount / (dist_points * tick_value)

        final_lot = max(self.min_lot, round(raw_lot, 2))
        logger.info(f"Calculated lot: {final_lot} for {symbol} (type: {asset_type}, risk: ${risk_amount:.2f})")
        return min(final_lot, self.max_lot) 

    def calculate_sl_tp(self, price, action, atr, symbol, digits=5, risk_reward_ratio=1.5):  # Increased RR for crypto
        """
        Dynamic SL/TP: Tighter for forex, wider for crypto volatility.
        """
        asset_type = detect_asset_type(symbol)
        atr_mult = self.config.get('scalping', {}).get(f"{asset_type}_atr_multiplier", 1.0)
        volatility = atr * atr_mult if (atr and atr > 0) else price * 0.001  # 0.1% buffer
        
        min_dist = price * 0.0005 if asset_type == "forex" else price * 0.005  # Wider for crypto
        sl_dist = max(volatility * 1.5, min_dist)  # Snug SL
        tp_dist = sl_dist * risk_reward_ratio  # Balanced RR
        
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:  # SELL
            sl = price + sl_dist
            tp = price - tp_dist
        
        # Validation
        if action == "SELL":
            if sl <= price: sl = price + min_dist
            if tp >= price: tp = price - min_dist
        else:
            if sl >= price: sl = price - min_dist
            if tp <= price: tp = price + min_dist

        logger.info(f"SL/TP for {symbol} ({asset_type}): SL={sl:.{digits}f}, TP={tp:.{digits}f}")
        return round(sl, digits), round(tp, digits)