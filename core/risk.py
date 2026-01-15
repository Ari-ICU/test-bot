class RiskManager:
    def __init__(self, config):
        self.config = config
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.max_positions = config.get('auto_trading', {}).get('max_positions', 1)
        self.break_even_active = False

    def get_lot_size(self, balance):
        # Could implement dynamic sizing based on balance here
        return self.lot_size

    def calculate_sl_tp(self, entry_price, direction, atr, reward_ratio=1.5):
        # ATR based SL/TP
        sl_dist = atr * 1.5
        if direction == "BUY":
            sl = entry_price - sl_dist
            tp = entry_price + (sl_dist * reward_ratio)
        else:
            sl = entry_price + sl_dist
            tp = entry_price - (sl_dist * reward_ratio)
        return sl, tp

    def check_break_even(self, current_profit, activation_threshold=0.5):
        if not self.break_even_active and current_profit >= activation_threshold:
            self.break_even_active = True
            return True, "Break-even Activated"
        return False, ""