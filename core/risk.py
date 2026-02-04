import time
import logging
from core.asset_detector import detect_asset_type, detect_sector, get_risk_profile
logger = logging.getLogger("RiskManager")
class RiskManager:
    def __init__(self, config):
        self.full_config = config
        self.risk_cfg = config.get('risk', {})
        self.scalp_cfg = config.get('scalping', {})
        self.risk_per_trade = self.risk_cfg.get('risk_per_trade', 1.0)
        self.max_daily_loss = self.risk_cfg.get('daily_loss_limit', 5.0)
        self.max_open_positions = self.risk_cfg.get('max_open_positions', 5)
        self.max_pos_per_symbol = self.risk_cfg.get('max_positions_per_symbol', 1)
        self.max_pos_per_sector = self.risk_cfg.get('max_positions_per_sector', 2)
        self.reputable_brokers = self.risk_cfg.get('reputable_brokers', [])
        self.require_validated = self.risk_cfg.get('require_validated_model', True)
        self.validated_models = ["AI_Predict", "Trend", "Scalp", "ICT_SB", "DRQN"]
        self.max_daily_trades = self.risk_cfg.get('max_trades', 5)
        self.cool_off_period = self.risk_cfg.get('cool_off_seconds', 900)
        self.min_lot = 0.01
        self.max_lot = 10.0
        self.daily_trades_count = 0
        self.last_trade_time = 0
    def can_trade(self, current_drawdown_pct, open_positions=None, symbol=None, broker_name=None, strategy_name=None):
        if open_positions is None: open_positions = []
        open_positions_count = len(open_positions)
        if current_drawdown_pct >= self.max_daily_loss:
            return False, f"Market Risk: Daily loss ({self.max_daily_loss}%) reached."
        if self.daily_trades_count >= self.max_daily_trades:
            return False, f"Psychology: Max daily trades ({self.max_daily_trades}) reached."
        time_since_last = time.time() - self.last_trade_time
        if time_since_last < self.cool_off_period:
            remaining_sec = int(self.cool_off_period - time_since_last)
            return False, f"Psychology: Cool-off {remaining_sec // 60}m {remaining_sec % 60}s remaining."
        return True, "Ready"
        if symbol:
            risk_profile = get_risk_profile(symbol)
            risk_on_count = sum(1 for p in open_positions if get_risk_profile(p.get('symbol', '')) == "risk-on")
            risk_off_count = sum(1 for p in open_positions if get_risk_profile(p.get('symbol', '')) == "risk-off")
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
    def record_trade(self):
        self.daily_trades_count += 1
        self.last_trade_time = time.time()
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
    def calculate_sl_tp(self, price, action, atr, symbol, digits=None, **kwargs):
        asset_type = detect_asset_type(symbol)
        sym_upper = symbol.upper()
        rr_ratio = self.scalp_cfg.get('risk_reward_ratio', 2.5)
        atr_mult = self.scalp_cfg.get(f"{asset_type}_atr_multiplier", 2.0)
        if digits is None:
            digits = 2 if "XAU" in sym_upper else 3 if "JPY" in sym_upper else 5
        sl_dist = (atr * atr_mult) if (atr and atr > 0) else (price * 0.005)
        if "XAU" in sym_upper:
            sl_dist = max(sl_dist, 1.5)
        tp_dist = sl_dist * rr_ratio
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist
        return round(float(sl), digits), round(float(tp), digits)