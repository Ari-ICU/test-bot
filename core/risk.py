class RiskManager:
    def __init__(self, config):
        self.config = config.get('risk', {})
        self.risk_per_trade = self.config.get('risk_per_trade', 1.0) # percent
        self.stop_loss_pips = self.config.get('stop_loss_pips', 50)
        self.take_profit_pips = self.config.get('take_profit_pips', 100)

    def get_lot_size(self, balance):
        # Simplified lot calculation
        lot = self.config.get('lot_size', 0.01)
        return lot

    def calculate_sl_tp(self, price, action, atr):
        """
        Calculates SL and TP levels based on action and price.
        Assumes 'price' is the entry price.
        """
        # Convert pips to points (assuming 1 pip = 10 points for standard 5-digit broker)
        # For XAUUSD, 1 pip usually = $0.10 or $1.00 depending on contract. 
        # Here we use a simpler points mapping: 1.00 price movement ~ 100 points
        
        sl_dist = 5.0 # $5 move in Gold
        tp_dist = 10.0 # $10 move in Gold
        
        # If ATR provided, use it for dynamic stops
        if atr > 0:
            sl_dist = atr * 1.5
            tp_dist = atr * 3.0

        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        elif action == "SELL":
            sl = price + sl_dist
            tp = price - tp_dist
        else:
            sl, tp = 0, 0
            
        return round(sl, 3), round(tp, 3)