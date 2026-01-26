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
        """
        Calculates lot size based on equity risk.
        Safety: If balance <= 0 or distance is tiny, returns min_lot.
        """
        try:
            asset_type = detect_asset_type(symbol)
            sym_upper = symbol.upper()
            
            # 1. Use the more conservative value (Equity or Balance)
            effective_balance = min(balance, equity) if equity is not None else balance
            if effective_balance <= 0:
                logger.warning(f"🛑 Risk Error: Insufficient balance/equity (${effective_balance})")
                return 0.0
            
            # 2. Maximum dollar risk for this trade
            risk_amount = effective_balance * (self.risk_per_trade / 100.0)
            
            # 3. Distance in price units (e.g. 1.50 for Gold)
            dist_price = abs(entry_price - sl_price)
            
            # Minimum allowed distance to prevent lot size explosion
            min_safety_gap = 1.0 if "XAU" in sym_upper else (entry_price * 0.0001)
            dist_price = max(dist_price, min_safety_gap)

            if asset_type == "forex":
                if "XAU" in sym_upper or "GOLD" in sym_upper:
                    # Gold: 1.0 move = $100 profit/loss per 1.0 lot
                    per_lot_risk = dist_price * 100.0
                elif "JPY" in sym_upper:
                    # JPY: 0.01 move = ~$7-10 profit/loss
                    per_lot_risk = (dist_price / 0.01) * 7.0
                else:
                    # Standard Forex: 0.0001 move (1 pip) = $10 profit/loss per 1.0 lot
                    per_lot_risk = (dist_price / 0.0001) * 10.0
            else:
                # Crypto: $1 move = $1 profit/loss per 1.0 coin (assuming 1.0 lot = 1 coin)
                per_lot_risk = dist_price

            if per_lot_risk <= 0: return self.min_lot
            
            raw_lot = risk_amount / per_lot_risk
            
            # ROUNDING & CLAMPING
            # Gold/Forex typically 2 decimal lots
            final_lot = round(raw_lot, 2)
            
            # Absolute hard cap for safety (0.20 lots max for small accounts)
            if effective_balance < 2000:
                final_lot = min(final_lot, 0.20)
            
            final_lot = max(self.min_lot, final_lot)
            final_lot = min(final_lot, self.max_lot)
            
            logger.info(f"📊 Risk Calculation: Bal=${effective_balance:,.2f} | RiskVal=${risk_amount:.2f} | P_Dist={dist_price:.4f} | PerLotRisk=${per_lot_risk:.2f} | Result={final_lot}")
            return final_lot
            
        except Exception as e:
            logger.error(f"💥 Lot Size calculation failed: {e}")
            return self.min_lot

    def calculate_sl_tp(self, price, action, atr, symbol, digits=None, risk_reward_ratio=1.5, timeframe="M5"):
        """
        Robust SL/TP calculation with symbol-aware minimum distances.
        """
        asset_type = detect_asset_type(symbol)
        sym_upper = symbol.upper()
        
        # 1. Determine precision
        if digits is None:
            digits = 2 if "XAU" in sym_upper else 3 if "JPY" in sym_upper else 5
            if asset_type == "crypto": digits = 2
        
        # 2. Minimum safe distance (Floor)
        if "XAU" in sym_upper:
            min_sl_dist = 2.0  # Force at least $2.00 gap for XAU
        elif asset_type == "crypto":
            min_sl_dist = price * 0.005 # 0.5%
        else:
            min_sl_dist = price * 0.0005 # ~5 pips

        # 3. Use ATR or Floor
        atr_mult = self.config.get('scalping', {}).get(f"{asset_type}_atr_multiplier", 1.5)
        sl_dist = max((atr * atr_mult) if atr else 0, min_sl_dist)
        tp_dist = sl_dist * risk_reward_ratio

        # 4. Apply to Price
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else: # SELL
            sl = price + sl_dist
            tp = price - tp_dist

        # 5. Final Rounding
        sl = round(float(sl), digits)
        tp = round(float(tp), digits)

        logger.info(f"🎯 SL/TP [{symbol}]: Entry={price:.{digits}f} | SL={sl} | TP={tp} | Gap={sl_dist:.2f}")
        return sl, tp