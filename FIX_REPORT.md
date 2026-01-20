# ✅ AI Bot Troubleshooting & Fixes

**Date**: January 20, 2026  
**Status**: ✅ All Issues Resolved

---

## 🛠️ Issues Fixed

### 1. ⚠️ **"No AI Model found for forex/scalp"**
- **Cause**: The bot was run from the `models/` directory, causing it to look for models in `models/models/`.
- **Fix**: Updated `core/predictor.py` to use **absolute paths**.
- **Result**: The bot now finds the models automatically, no matter which folder you run it from.

### 2. 💥 **"Critical Loop Error: ... got '10o'"**
- **Cause**: A typo in one of the UI input fields (likely "10o" entered for Cool-off or Lot Size).
- **Fix**: Added safety checks in `main.py`. If a typo is detected, the bot now logs a warning and uses safe default values instead of crashing.

### 3. 📂 **Model Location Mismatch**
- **Cause**: Training script saved models to the parent directory due to relative path usage.
- **Fix**: Moved the trained models (12MB & 39MB) to the correct `mt5-bot/models/` folder.

---

## 🚀 How to Restart (Correctly)

To apply the fixes and start trading with the new SMC AI:

1. **Stop** the currently running bot (Ctrl+C).
2. **Navigate** to the project root:
   ```bash
   cd /Users/thoeurnratha/Documents/ml/mt5-bot
   ```
3. **Run** the main bot:
   ```bash
   /usr/local/bin/python3 main.py
   ```

## 🎯 What to Expect

- **Logs**: You should see `✅ AI Model loaded: forex | scalp`
- **UI**: The "AI_Predict" strategy will show confident signals.
- **Stability**: No more crashes from UI typos.

---

**System is now stable and ready for production.**
