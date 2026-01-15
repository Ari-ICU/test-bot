class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) 
        self.max_daily_loss = self.config.get('max_daily_loss', 5.0) 
        self.min_lot = 0.01

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol_type="FOREX", equity=None):
        """
        Calculates dynamic lot size based on risk percentage.
        Uses Equity if provided (safer), else Balance.
        """
        # Use Equity for calculation if available (Protects during drawdown)
        base_capital = equity if equity is not None else balance
        
        if base_capital <= 0: return self.min_lot
        
        risk_amount = base_capital * (self.risk_per_trade / 100.0)
        dist = abs(entry_price - sl_price)
        
        if dist == 0: return self.min_lot
        
        # --- Lot Calculation ---
        # Standard Formula: Risk / (Distance * ValuePerPoint)
        # We approximate ValuePerPoint based on symbol type
        
        if "XAU" in symbol_type or "BTC" in symbol_type:
            # Gold/Crypto (Higher volatility/Different contract size)
            # Approximation: 1 Lot Gold ~ $1 per 0.01 tick? 
            # This constant varies wildly by broker. 
            # Safe Fallback: Assume Standard Lot = 100k units
            raw_lot = risk_amount / dist 
        else:
            # Forex Standard
            raw_lot = risk_amount / dist 
            
        final_lot = max(self.min_lot, round(raw_lot, 2))
        return min(final_lot, 5.0) # Hard Cap

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