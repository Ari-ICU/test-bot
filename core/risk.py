class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) 
        self.max_daily_loss = self.config.get('max_daily_loss', 5.0) 
        self.min_lot = 0.01

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol_type="XAUUSD", equity=None):
        """
        Calculates dynamic lot size based on risk percentage and contract specs.
        """
        # Use Equity if provided (Protects during drawdown)
        base_capital = equity if equity is not None else balance
        
        if base_capital <= 0: return self.min_lot
        
        risk_amount = base_capital * (self.risk_per_trade / 100.0)
        dist_points = abs(entry_price - sl_price)
        
        if dist_points == 0: return self.min_lot

        # Standard Gold (XAUUSD) calculation: 1 lot move of 1.00 = $100 profit/loss
        if "XAU" in symbol_type.upper():
            # Formula: Lot = Risk / (Distance * 100)
            raw_lot = risk_amount / (dist_points * 100)
        else:
            # Standard Forex: 1 lot move of 0.0001 (1 pip) = $10
            raw_lot = risk_amount / (dist_points * 100000)
                
        final_lot = max(self.min_lot, round(raw_lot, 2))
        return min(final_lot, 5.0) # Keep your 5.0 Hard Cap

    def calculate_sl_tp(self, price, action, atr, risk_reward_ratio=2.0):
        """
        Dynamic SL/TP based on Volatility (ATR).
        Returns SL and TP prices.
        """
        # 1. Volatility Filter (Ensure SL isn't too tight)
        volatility = atr if atr > 0 else price * 0.002
        min_sl_dist = price * 0.001 # Minimum 0.1% distance
        
        sl_dist = max(volatility * 1.5, min_sl_dist)
        tp_dist = sl_dist * risk_reward_ratio
        
        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else: # SELL
            sl = price + sl_dist
            tp = price - tp_dist
            
        return round(sl, 2), round(tp, 2)