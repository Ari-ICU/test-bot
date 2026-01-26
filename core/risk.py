import time
import logging
from core.asset_detector import detect_asset_type

logger = logging.getLogger("RiskManager")

class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) 
        self.max_daily_loss = self.config.get('daily_loss_limit', 5.0)
        self.max_drawdown_limit = self.config.get('max_drawdown', 5.0)
        self.min_lot = 0.01
        self.max_lot = 10.0
        
        # PSYCHOLOGY SETTINGS
        self.max_daily_trades = self.config.get('max_trades', 5) 
        self.cool_off_period = self.config.get('cool_off_seconds', 5)
        
        self.daily_trades_count = 0
        self.last_trade_time = 0
        self.config = config  # Expose for UI

    def can_trade(self, current_drawdown_pct):
        if current_drawdown_pct > self.max_daily_loss:
            return False, f"Daily drawdown limit ({self.max_daily_loss}%) reached."

        time_since_last = time.time() - self.last_trade_time
        if time_since_last < self.cool_off_period:
            remaining_sec = int(self.cool_off_period - time_since_last)
            if remaining_sec < 60:
                return False, f"Psychological cool-off: {remaining_sec}s remaining."
            else:
                return False, f"Psychological cool-off: {remaining_sec // 60}m remaining."

        return True, "Ready"

    def record_trade(self):
        self.daily_trades_count += 1
        self.last_trade_time = time.time()

    def reset_daily_stats(self):
        self.daily_trades_count = 0

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol, equity=None):
        asset_type = detect_asset_type(symbol)
        risk_amount = balance * (self.risk_per_trade / 100)
        dist_points = abs(entry_price - sl_price)
        
        if asset_type == "forex":
            tick_value = 1.0 if "XAU" in symbol.upper() else 10.0
            raw_lot = risk_amount / (dist_points * tick_value * 100)
        else:  # crypto
            tick_value = 0.01
            raw_lot = risk_amount / (dist_points * tick_value)

        final_lot = max(self.min_lot, round(raw_lot, 2))
        logger.info(f"Calculated lot: {final_lot} for {symbol} (type: {asset_type}, risk: ${risk_amount:.2f})")
        return min(final_lot, self.max_lot) 

    def calculate_sl_tp(self, price, action, atr, symbol, digits=5, risk_reward_ratio=1.5, timeframe="M5"):
        asset_type = detect_asset_type(symbol)
        atr_mult = self.config.get('scalping', {}).get(f"{asset_type}_atr_multiplier", 1.0)
        volatility = atr * atr_mult if (atr and atr > 0) else price * 0.001
        
        if timeframe == "M1":
            min_dist = price * 0.0002 if asset_type == "forex" else price * 0.002
        else:
            min_dist = price * 0.0005 if asset_type == "forex" else price * 0.005 
        
        sl_dist = max(volatility * 1.5, min_dist)
        sl_dist = max(sl_dist, min_dist)  
        tp_dist = sl_dist * risk_reward_ratio
        tp_dist = max(tp_dist, min_dist * risk_reward_ratio)  
        
        if sl_dist < min_dist * 1.1:  
            logger.warning(f"⚠️ Small SL dist {sl_dist:.5f} for {symbol} on {timeframe} – using min {min_dist:.5f}")
            sl_dist = min_dist
        
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:  # SELL
            sl = price + sl_dist
            tp = price - tp_dist
        
        if action == "SELL":
            if sl <= price: 
                sl = price + max(min_dist, sl_dist)  
            if tp >= price: 
                tp = price - max(min_dist * risk_reward_ratio, tp_dist)
            if (price - tp) < (min_dist * risk_reward_ratio):
                tp = price - (min_dist * risk_reward_ratio)
                logger.warning(f"⚠️ Adjusted tiny TP for SELL {symbol}: was {tp:.5f}, now {tp:.5f}")
        else:  # BUY
            if sl >= price: 
                sl = price - max(min_dist, sl_dist)
            if tp <= price: 
                tp = price + max(min_dist * risk_reward_ratio, tp_dist)
            if (tp - price) < (min_dist * risk_reward_ratio):
                tp = price + (min_dist * risk_reward_ratio)
                logger.warning(f"⚠️ Adjusted tiny TP for BUY {symbol}: was {tp:.5f}, now {tp:.5f}")

        sl = round(float(sl), digits)
        tp = round(float(tp), digits)

        logger.info(f"SL/TP for {symbol} ({asset_type}) on {timeframe}: SL={sl}, TP={tp} (min_dist={min_dist:.5f})")
        return sl, tp