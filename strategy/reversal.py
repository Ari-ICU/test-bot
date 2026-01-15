from core.patterns import detect_fvg, detect_fractals

def analyze_reversal_setup(candles, bid, ask):
    # Logic extracted from _detect_crt_signal in original strategy.py
    fvg_type, _, _ = detect_fvg(candles)
    
    if fvg_type == "BULLISH":
        return "BUY", ["FVG_Reclaim"]
    elif fvg_type == "BEARISH":
        return "SELL", ["FVG_Reject"]
        
    return "NEUTRAL", []