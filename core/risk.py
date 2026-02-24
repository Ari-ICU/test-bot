import time
import logging
from core.asset_detector import detect_asset_type, get_risk_profile
logger = logging.getLogger("RiskManager")
class RiskManager:
    def __init__(self, config):
        self.full_config = config
        self.risk_cfg = config.get('risk', {})
        self.scalp_cfg = config.get('scalping', {})
        self.risk_per_trade = self.risk_cfg.get('risk_per_trade', 1.0)
        self.max_daily_loss = self.risk_cfg.get('daily_loss_limit', 5.0)
        self.max_open_positions = self.risk_cfg.get('max_open_positions', 5)
        self.reputable_brokers = self.risk_cfg.get('reputable_brokers', [])
        self.require_validated = self.risk_cfg.get('require_validated_model', True)
        self.validated_models = ["AI_Predict", "Trend", "Scalp", "ICT_SB", "DRQN", "SMC_Master", "CRT_TBS", "PowerTF", "ICT_Master", "Breakout", "TBS_Retest", "TBS_Turtle", "Reversal", "PD_Parameter"]
        self.max_daily_trades = self.risk_cfg.get('max_trades', 5)
        self.cool_off_period = self.risk_cfg.get('cool_off_seconds', 900)
        self.min_lot = 0.01
        self.max_lot = 10.0
        self.daily_trades_count = 0
        self.last_trade_times = {} # Per-timeframe cool-off tracking

    def can_trade(self, current_drawdown_pct, open_positions=None, symbol=None, broker_name=None, strategy_name=None, timeframe="global"):
        if open_positions is None: open_positions = []
        open_positions_count = len(open_positions)
        
        if current_drawdown_pct >= self.max_daily_loss:
            return False, f"Market Risk: Daily loss ({self.max_daily_loss}%) reached."
            
        if self.daily_trades_count >= self.max_daily_trades:
            return False, f"Psychology: Max daily trades ({self.max_daily_trades}) reached."
            
        # Per-TF Cool-off logic
        last_time = self.last_trade_times.get(timeframe, 0)
        time_since_last = time.time() - last_time
        if time_since_last < self.cool_off_period:
            remaining_sec = int(self.cool_off_period - time_since_last)
            return False, f"Psychology: {timeframe} Cool-off {remaining_sec // 60}m {remaining_sec % 60}s remaining."

        if symbol:
            risk_profile = get_risk_profile(symbol)
            risk_on_count = sum(1 for p in open_positions if get_risk_profile(p.get('symbol', '')) == "risk-on")
            risk_off_count = sum(1 for p in open_positions if get_risk_profile(p.get('symbol', '')) == "risk-off")
            if open_positions_count >= self.max_open_positions:
                 return False, f"Exposure: Max open positions ({self.max_open_positions}) reached."
            
            if open_positions_count >= 2:
                if risk_profile == "risk-on" and risk_on_count >= (self.max_open_positions * 0.8):
                    return False, f"Liquidity Risk: Too much risk-on exposure."
                if risk_profile == "risk-off" and risk_off_count >= (self.max_open_positions * 0.8):
                    return False, f"Liquidity Risk: Too much risk-off exposure."

        if broker_name and self.reputable_brokers:
            is_reputable = any(rb.lower() in broker_name.lower() for rb in self.reputable_brokers)
            if not is_reputable:
                return False, f"Credit Risk: Broker '{broker_name}' not in reputable list."

        if self.require_validated and strategy_name:
            if strategy_name not in self.validated_models:
                return False, f"Model Risk: {strategy_name} is not a validated/backtested model."

        return True, "Ready"

    def record_trade(self, timeframe="global"):
        self.daily_trades_count += 1
        self.last_trade_times[timeframe] = time.time()

    def reset_daily_stats(self):
        self.daily_trades_count = 0

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol, equity=None):
        try:
            asset_type = detect_asset_type(symbol)
            sym_upper = symbol.upper()
            effective_balance = min(balance, equity) if equity is not None else balance
            if effective_balance <= 0: return 0.0
            
            risk_amount = effective_balance * (self.risk_per_trade / 100.0)
            dist_price = abs(entry_price - sl_price)
            
            # Safety gap to prevent division by zero or too large lots
            min_safety_gap = 1.0 if "XAU" in sym_upper else (entry_price * 0.0001)
            dist_price = max(dist_price, min_safety_gap)
            
            if asset_type == "forex":
                if "XAU" in sym_upper or "GOLD" in sym_upper:
                    per_lot_risk = dist_price * 100.0
                elif "JPY" in sym_upper:
                    per_lot_risk = (dist_price / 0.01) * 7.5
                else:
                    per_lot_risk = (dist_price / 0.0001) * 10.0
            else:
                per_lot_risk = dist_price
                
            raw_lot = risk_amount / per_lot_risk if per_lot_risk > 0 else self.min_lot
            final_lot = round(raw_lot, 2)
            
            if effective_balance < 2000:
                final_lot = min(final_lot, 0.50)
            return max(self.min_lot, min(final_lot, self.max_lot))
        except Exception as e:
            logger.error(f"💥 Lot Size Error: {e}")
            return self.min_lot

    def calculate_sl_tp(self, price, action, atr, symbol, digits=None, timeframe=None, **kwargs):
        """
        Calculates SL and TP based on ATR and Risk Reward Ratio.
        'timeframe' is used to scale logic for better reachability.
        """
        asset_type = detect_asset_type(symbol)
        sym_upper = symbol.upper()
        
        # Pull settings from config, defaulting to reachable scalping values
        # USER REQUEST: "short tp make sure price can reach and hit" -> Reducing RR default
        rr_ratio = self.scalp_cfg.get('risk_reward_ratio', 1.5)
        
        # Standard ATR multipliers
        sl_mult = self.scalp_cfg.get(f"{asset_type}_atr_multiplier", 2.0)
        
        if digits is None:
            digits = 2 if "XAU" in sym_upper else 3 if "JPY" in sym_upper else 5
            
        # SL calculation
        sl_dist = (atr * sl_mult) if (atr and atr > 0) else (price * 0.005)
        
        # Universal Floor for SL to prevent stop-hunting (at least some breathing room)
        if "XAU" in sym_upper:
            sl_dist = max(sl_dist, 1.5) # Min 15 pips for Gold
        elif asset_type == "forex":
            sl_dist = max(sl_dist, price * 0.0002) # Min 2 pips
            
        # TP calculation - USER REQUEST: "short tp"
        # We use a tighter RR or a fraction of ATR for TP to ensure it "hits"
        tp_dist = sl_dist * rr_ratio
        
        # Dynamic adjustment: if TF is high, TP should be even more conservative relative to SL
        if timeframe in ["H4", "D1", "W1"]:
            tp_dist = sl_dist * min(rr_ratio, 1.2) # High TF trades should be even shorter relative to SL for higher hit rate
            
        # Hard Cap on TP for "Short TP" logic
        if tp_dist > sl_dist * 2.5:
             tp_dist = sl_dist * 1.5

        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist
            
        return round(float(sl), digits), round(float(tp), digits)