class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) # percent
        self.stop_loss_pips = self.config.get('stop_loss_pips', 50)
        self.take_profit_pips = self.config.get('take_profit_pips', 100)

    def get_lot_size(self, balance):
        # Default to min lot
        return self.config.get('lot_size', 0.01)

    def calculate_sl_tp(self, price, action, atr):
        """
        Calculates SL and TP levels with validation for Crypto & Forex.
        Enforces a minimum distance to avoid Error 10016 (Invalid Stops).
        """
        
        # 1. Base Distance Calculation
        if atr > 0:
            # Use ATR for dynamic volatility-based stops
            sl_dist = atr * 1.5
            tp_dist = atr * 3.0
        else:
            # Fallback if ATR is 0 (e.g., first run or error)
            # Default to 0.1% of price (Safe for both Forex and Crypto)
            sl_dist = price * 0.001 
            tp_dist = price * 0.002

        # 2. SAFETY CHECK: Enforce Minimum Distance
        # Brokers reject stops that are too close (Error 10016).
        # We enforce a minimum distance of 0.05% of the price.
        # Example: BTC $96,000 -> Min Stop $48.
        min_dist = price * 0.0005 
        
        if sl_dist < min_dist:
            sl_dist = min_dist
            # Adjust TP to ensure we still aim for at least 1:2 Risk/Reward
            if tp_dist < sl_dist * 2:
                tp_dist = sl_dist * 2

        # 3. Calculate Levels
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        elif action == "SELL":
            sl = price + sl_dist
            tp = price - tp_dist
        else:
            return 0.0, 0.0

        # 4. Rounding
        # Rounding to 2 decimal places is standard/safe for most MT5 symbols
        return round(sl, 2), round(tp, 2)