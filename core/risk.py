class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) # Risk 1% of equity per trade
        self.max_daily_loss = self.config.get('max_daily_loss', 5.0) # Max 5% loss per day
        self.min_lot = 0.01

    def calculate_lot_size(self, balance, entry_price, sl_price, symbol_type="FOREX"):
        """
        Calculates dynamic lot size based on risk percentage.
        Risk = (Entry - SL) * Volume * ContractSize
        """
        if balance <= 0: return self.min_lot
        
        # 1. Calculate Risk Amount in Dollars ($10,000 * 1% = $100 risk)
        risk_amount = balance * (self.risk_per_trade / 100.0)
        
        # 2. Calculate Distance
        dist = abs(entry_price - sl_price)
        if dist == 0: return self.min_lot
        
        # 3. Estimate Lot Size (Approximate)
        # Standard Lot (1.00) in Forex ~ $10 per pip
        # For XAUUSD (Gold), 1.00 lot = $1 per 0.01 move? Varies by broker.
        # We use a standard approximation: 1 lot = 100,000 units
        
        # Simplified for MT5 (You might need to adjust contract size per symbol)
        # Formula: Lots = Risk_Amount / (Distance * Value_Per_Point)
        
        # Assuming 1.0 lot pays $1 per point for simplicity (adjust for your broker)
        # Gold: Price 2000 -> 2001 is 1 point ($1 profit for 1.0 lot? Usually $100)
        
        if "XAU" in symbol_type or "BTC" in symbol_type:
            # Crypto/Gold often has different contract sizes
            # Let's assume a safe generic divisor
            raw_lot = risk_amount / dist 
        else:
            # Forex
            raw_lot = risk_amount / dist 
            
        # Normalize
        final_lot = max(self.min_lot, round(raw_lot, 2))
        
        # Safety Cap (e.g., never trade more than 1.0 lot automatically)
        return min(final_lot, 5.0)

    def calculate_sl_tp(self, price, action, atr, risk_reward_ratio=2.0):
        """
        Dynamic SL/TP based on Volatility (ATR).
        Stop Loss is placed 1.5x ATR away from entry (breathing room).
        Take Profit is placed 2x (or user defined) Risk away.
        """
        # Minimum noise filter
        volatility = atr if atr > 0 else price * 0.002
        
        sl_dist = volatility * 1.5
        tp_dist = sl_dist * risk_reward_ratio
        
        # Enforce minimum distances for crypto
        min_dist = price * 0.0005 # 0.05% min distance
        if sl_dist < min_dist: sl_dist = min_dist
        if tp_dist < min_dist * 2: tp_dist = min_dist * 2

        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else: # SELL
            sl = price + sl_dist
            tp = price - tp_dist
            
        return round(sl, 2), round(tp, 2)