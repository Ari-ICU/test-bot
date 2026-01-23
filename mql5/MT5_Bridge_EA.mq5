#property strict
#property version "3.6" // Bumped for performance optimizations
#property description "HTTP Bridge - Optimized: Caching, Reduced String Ops, Efficient Polling"


input string ServerURL = "http://127.0.0.1:8001";
input double DefaultLot = 0.01;
input int TimerInterval = 100; // Configurable timer interval (ms) for tuning responsiveness vs performance

// Cache variables for performance
string g_symbols_list = "";
datetime g_last_symbols_update = 0;
string g_candle_history = "";
datetime g_last_candle_update = 0;
int g_candles_to_send = 5000;
string g_tf_string = "";
ENUM_TIMEFRAMES g_current_period = PERIOD_CURRENT;
double g_last_bid = 0, g_last_ask = 0;
double g_cached_balance = 0, g_cached_profit = 0, g_cached_equity = 0;
int g_cached_buy_count = 0, g_cached_sell_count = 0;
double g_cached_avg_entry = 0;
string g_cached_active_trades = "";
datetime g_last_positions_update = 0;
datetime g_last_account_update = 0;
int g_trade_mode = -1; // -1 forces initial calc
datetime g_day_start = 0, g_week_start = 0, g_month_start = 0;
double g_prof_today = 0, g_prof_week = 0, g_prof_month = 0;
datetime g_last_profit_update = 0;
bool g_force_candle_reload = false;

ENUM_TIMEFRAMES g_auto_tfs[] = {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4, PERIOD_D1};

int OnInit() {
   EventSetMillisecondTimer(TimerInterval);
   g_current_period = _Period;
   g_tf_string = GetTFString();
   
   // --- NEW: Auto-open timeframe tabs if they don't exist ---
   for(int i=0; i<ArraySize(g_auto_tfs); i++) {
      OpenUniqueChart(_Symbol, g_auto_tfs[i]);
   }
   // ---------------------------------------------------------

   UpdateSymbolsCache(); 
   UpdateAccountCache();
   UpdatePositionsCache(); 
   UpdateProfitCache();
   
   return INIT_SUCCEEDED;
}

// Helper function to prevent opening the same tab twice
void OpenUniqueChart(string symbol, ENUM_TIMEFRAMES tf) {
   long chartID = ChartFirst();
   bool exists = false;
   
   while(chartID >= 0) {
      if(ChartSymbol(chartID) == symbol && ChartPeriod(chartID) == tf) {
         exists = true;
         break;
      }
      chartID = ChartNext(chartID);
   }
   
   if(!exists) {
      ChartOpen(symbol, tf);
   }
}

void OnDeinit(const int reason) {
   EventKillTimer();
   ObjectsDeleteAll(0, "Py_");
}

double CalculateHistoryProfit(datetime from_date) {
    double profit = 0;
    if(HistorySelect(from_date, TimeCurrent())) {
        int total = HistoryDealsTotal();
        for(int i=0; i<total; i++) {
            ulong ticket = HistoryDealGetTicket(i);
            if(ticket > 0) {
                profit += HistoryDealGetDouble(ticket, DEAL_PROFIT);
                profit += HistoryDealGetDouble(ticket, DEAL_COMMISSION);
                profit += HistoryDealGetDouble(ticket, DEAL_SWAP);
            }
        }
    }
    return profit;
}

// Cache-aware profit update (call only when needed, e.g., daily/weekly boundaries crossed)
void UpdateProfitCache() {
    MqlDateTime dt; TimeCurrent(dt);
    dt.hour = 0; dt.min = 0; dt.sec = 0;
    datetime day_start = StructToTime(dt);
    int days_to_monday = (dt.day_of_week == 0) ? 6 : (dt.day_of_week - 1);
    datetime week_start = day_start - (days_to_monday * 86400);
    dt.day = 1;
    datetime month_start = StructToTime(dt);

    bool needs_update = (day_start != g_day_start) || (week_start != g_week_start) || (month_start != g_month_start) || (g_last_profit_update == 0);
    if(needs_update) {
        g_prof_today = CalculateHistoryProfit(day_start);
        g_prof_week = CalculateHistoryProfit(week_start);
        g_prof_month = CalculateHistoryProfit(month_start);
        g_day_start = day_start;
        g_week_start = week_start;
        g_month_start = month_start;
        g_last_profit_update = TimeCurrent();
    }
}

string GetTFString() {
    if(_Period == PERIOD_M1) return "M1";
    if(_Period == PERIOD_M5) return "M5";
    if(_Period == PERIOD_M15) return "M15";
    if(_Period == PERIOD_M30) return "M30";
    if(_Period == PERIOD_H1) return "H1";
    if(_Period == PERIOD_H4) return "H4";
    if(_Period == PERIOD_D1) return "D1";
    if(_Period == PERIOD_W1) return "W1";
    if(_Period == PERIOD_MN1) return "MN";
    return "M5";
}

int GetTFMinutes(string tf_str) {
    if(tf_str == "M1") return 1;
    if(tf_str == "M5") return 5;
    if(tf_str == "M15") return 15;
    if(tf_str == "M30") return 30;
    if(tf_str == "H1") return 60;
    if(tf_str == "H4") return 240;
    if(tf_str == "D1") return 1440;
    if(tf_str == "W1") return 10080;
    if(tf_str == "MN") return 43200;
    return 5;
}

// Efficient symbols cache update (only if Market Watch changed or every 5min)
void UpdateSymbolsCache() {
    datetime now = TimeCurrent();
    if(now - g_last_symbols_update < 300 || SymbolsTotal(true) == 0) return; // Skip if recent or empty

    StringFreezer freezer; // Use StringFreezer for efficient concatenation
    int total_symbols = SymbolsTotal(true);
    for(int i=0; i<total_symbols; i++) {
        string sym = SymbolName(i, true);
        if(freezer.Len() > 0) freezer.Add("|");
        freezer.Add(sym);
    }
    g_symbols_list = freezer.String();
    g_last_symbols_update = now;
}

// Efficient candle history builder using StringFreezer
void UpdateCandleHistory() {
    datetime now = TimeCurrent();
    if(!g_force_candle_reload && now - g_last_candle_update < TimerInterval * 0.001) return; // Skip if recent

    StringFreezer freezer;
    int available = iBars(_Symbol, g_current_period);
    int count = MathMin(g_candles_to_send, available);

    for(int i=0; i<count; i++) {
        if(i > 0) freezer.Add("|");
        freezer.Add(DoubleToString(iHigh(_Symbol, g_current_period, i), _Digits) + "," +
                    DoubleToString(iLow(_Symbol, g_current_period, i), _Digits) + "," +
                    DoubleToString(iOpen(_Symbol, g_current_period, i), _Digits) + "," +
                    DoubleToString(iClose(_Symbol, g_current_period, i), _Digits) + "," +
                    IntegerToString(iTime(_Symbol, g_current_period, i)));
    }
    g_candle_history = freezer.String();
    g_last_candle_update = now;
    g_force_candle_reload = false;
}

// Efficient positions cache (update only if positions changed or every 1s)
void UpdatePositionsCache() {
    datetime now = TimeCurrent();
    if(now - g_last_positions_update < 1) return; // 1s throttle

    int total_pos = PositionsTotal();
    int buy_count = 0, sell_count = 0;
    double sum_price_vol = 0.0, sum_vol = 0.0;
    StringFreezer trades_freezer;

    for(int i=0; i<total_pos; i++) {
        // IMPORTANT: Must select position by ticket/index before accessing properties
        ulong ticket = PositionGetTicket(i); 
        if(ticket <= 0) continue;
        
        if(PositionGetString(POSITION_SYMBOL) == _Symbol) {
            double vol = PositionGetDouble(POSITION_VOLUME);
            double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
            long type = PositionGetInteger(POSITION_TYPE);
            double profit = PositionGetDouble(POSITION_PROFIT);
            
            sum_price_vol += (open_price * vol);
            sum_vol += vol;
            
            if(type == POSITION_TYPE_BUY) buy_count++;
            else if(type == POSITION_TYPE_SELL) sell_count++;

            string type_str = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            double sl = PositionGetDouble(POSITION_SL);
            double tp = PositionGetDouble(POSITION_TP);
            string trade_line = IntegerToString(ticket) + "," + _Symbol + "," + type_str + "," + DoubleToString(vol, 2) + "," + DoubleToString(profit, 2) + "," + DoubleToString(open_price, _Digits) + "," + DoubleToString(sl, _Digits) + "," + DoubleToString(tp, _Digits);
            
            if(trades_freezer.Len() > 0) trades_freezer.Add("|");
            trades_freezer.Add(trade_line);
        }
    }
    g_cached_avg_entry = (sum_vol > 0) ? NormalizeDouble(sum_price_vol / sum_vol, _Digits) : 0.0;
    g_cached_buy_count = buy_count;
    g_cached_sell_count = sell_count;
    g_cached_active_trades = trades_freezer.String();
    g_last_positions_update = now;
}

// Efficient account cache (update every 2s or on change)
void UpdateAccountCache() {
    datetime now = TimeCurrent();
    if(now - g_last_account_update < 2) return;

    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double profit = AccountInfoDouble(ACCOUNT_PROFIT);
    double equity = AccountInfoDouble(ACCOUNT_EQUITY);
    string acct_name = AccountInfoString(ACCOUNT_NAME);
    string acct_server = AccountInfoString(ACCOUNT_SERVER);

    // Update trade_mode only if changed
    int new_trade_mode = (StringFind(acct_server, "Demo") >= 0 || StringFind(acct_name, "Demo") >= 0) ? 1 : 0;
    if(new_trade_mode != g_trade_mode) {
        g_trade_mode = new_trade_mode;
    }

    g_cached_balance = balance;
    g_cached_profit = profit;
    g_cached_equity = equity;
    g_last_account_update = now;
}

void OnTimer() {
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) {
        static datetime last_warn = 0;
        if(TimeCurrent() - last_warn > 60) { // Throttle warning
            Print("⚠️ Algo Trading is Disabled! Enable 'Algo Trading' button.");
            last_warn = TimeCurrent();
        }
        return; // Early exit if trading disabled
    }

    // Update caches as needed
    UpdateAccountCache();
    UpdatePositionsCache();
    UpdateProfitCache();
    UpdateSymbolsCache();
    UpdateCandleHistory();

    // Check for TF change
    if(g_current_period != _Period) {
        g_current_period = _Period;
        g_tf_string = GetTFString();
        g_force_candle_reload = true; // Force reload on TF change
        Print("🔄 TF Changed - Forcing Candle Reload");
    }

    // Check for symbol change (less frequent)
    static string last_symbol = "";
    if(last_symbol != _Symbol) {
        last_symbol = _Symbol;
        g_force_candle_reload = true;
        Print("🔄 Symbol Changed - Forcing Candle Reload");
    }

    // Get fresh bid/ask (volatile, update every tick-like)
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    bool prices_changed = (bid != g_last_bid || ask != g_last_ask);
    g_last_bid = bid;
    g_last_ask = ask;

    // Build dashboard (lightweight)
    string dashboard = "=== ⚡ PYTHON BRIDGE ACTIVE (v3.6 - Optimized) ===\n";
    dashboard += "💰 Balance: " + DoubleToString(g_cached_balance, 2) + "\n";
    dashboard += "📆 Today: " + DoubleToString(g_prof_today, 2) + "\n";
    dashboard += "📅 Week: " + DoubleToString(g_prof_week, 2) + "\n";
    dashboard += "🗓️ Month: " + DoubleToString(g_prof_month, 2) + "\n";
    dashboard += "🔄 Symbols Synced: " + IntegerToString(SymbolsTotal(true)) + "\n";
    dashboard += "-----------------------------";
    Comment(dashboard);

    // Build POST data efficiently with StringFreezer
    StringFreezer post_freezer;
    post_freezer.Add("command=POLL");
    post_freezer.Add("&symbol=" + _Symbol);
    post_freezer.Add("&symbols=" + g_symbols_list);
    post_freezer.Add("&tf=" + g_tf_string);
    post_freezer.Add("&bid=" + DoubleToString(bid, _Digits));
    post_freezer.Add("&ask=" + DoubleToString(ask, _Digits));
    post_freezer.Add("&balance=" + DoubleToString(g_cached_balance, 2));
    post_freezer.Add("&profit=" + DoubleToString(g_cached_profit, 2));
    post_freezer.Add("&prof_today=" + DoubleToString(g_prof_today, 2));
    post_freezer.Add("&prof_week=" + DoubleToString(g_prof_week, 2));
    post_freezer.Add("&acct_equity=" + DoubleToString(g_cached_equity, 2));
    post_freezer.Add("&trade_mode=" + IntegerToString(g_trade_mode));
    post_freezer.Add("&buy_count=" + IntegerToString(g_cached_buy_count));
    post_freezer.Add("&sell_count=" + IntegerToString(g_cached_sell_count));
    post_freezer.Add("&candles=" + g_candle_history);
    
    // Always send last 5 M1 candles for profit protection
    StringFreezer m1_freezer;
    int m1_count = MathMin(5, iBars(_Symbol, PERIOD_M1));
    for(int i=0; i<m1_count; i++) {
        if(i > 0) m1_freezer.Add("|");
        m1_freezer.Add(DoubleToString(iHigh(_Symbol, PERIOD_M1, i), _Digits) + "," +
                     DoubleToString(iLow(_Symbol, PERIOD_M1, i), _Digits) + "," +
                     DoubleToString(iOpen(_Symbol, PERIOD_M1, i), _Digits) + "," +
                     DoubleToString(iClose(_Symbol, PERIOD_M1, i), _Digits) + "," +
                     IntegerToString(iTime(_Symbol, PERIOD_M1, i)));
    }
    post_freezer.Add("&m1_candles=" + m1_freezer.String());

    // --- FULLY FIXED: Always send all required timeframes for strategy sync ---
    StringFreezer htf_freezer;
    ENUM_TIMEFRAMES htf_list[] = {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4, PERIOD_D1};
    
    // Updated loop count to 7 to match the htf_list size
    for(int h=0; h<7; h++) {
        ENUM_TIMEFRAMES htf = htf_list[h];
        if(htf == g_current_period) continue; // Skip if it's the main chart timeframe

        // Map every timeframe to a string label that Python expects
        string tf_label = "";
        if(htf == PERIOD_M1) tf_label = "M1";
        else if(htf == PERIOD_M5) tf_label = "M5";
        else if(htf == PERIOD_M15) tf_label = "M15";
        else if(htf == PERIOD_M30) tf_label = "M30";
        else if(htf == PERIOD_H1) tf_label = "H1";
        else if(htf == PERIOD_H4) tf_label = "H4";
        else if(htf == PERIOD_D1) tf_label = "D1";

        int bars = MathMin(300, iBars(_Symbol, htf)); 
        StringFreezer sub_freezer;
        for(int i=0; i<bars; i++) {
            if(i > 0) sub_freezer.Add("|");
            sub_freezer.Add(DoubleToString(iHigh(_Symbol, htf, i), _Digits) + "," +
                         DoubleToString(iLow(_Symbol, htf, i), _Digits) + "," +
                         DoubleToString(iOpen(_Symbol, htf, i), _Digits) + "," +
                         DoubleToString(iClose(_Symbol, htf, i), _Digits) + "," +
                         IntegerToString(iTime(_Symbol, htf, i)));
        }
        
        // This sends the data as &htf_M1, &htf_M5, &htf_M15, etc.
        post_freezer.Add("&htf_" + tf_label + "=" + sub_freezer.String());
    }
    
    post_freezer.Add("&active_trades=" + g_cached_active_trades);

    string post_str = post_freezer.String();
    SendRequest(post_str);
}

// Custom StringFreezer class for efficient string building (avoids repeated allocations)
class StringFreezer {
private:
    string m_buffer;
public:
    void Add(string s) { m_buffer += s; }
    int Len() { return StringLen(m_buffer); }
    string String() { return m_buffer; }
};

void SendRequest(string data_str) {
    char post_char[]; StringToCharArray(data_str, post_char);
    uchar post_uchar[]; ArrayResize(post_uchar, ArraySize(post_char));
    for(int i=0; i<ArraySize(post_char); i++) post_uchar[i] = (uchar)post_char[i];
   
    uchar result_uchar[]; string response_headers;
    int http_res = WebRequest("POST", ServerURL, "Content-Type: application/x-www-form-urlencoded\r\n", 2000, post_uchar, result_uchar, response_headers);
   
    if(http_res == -1 && GetLastError() == 4060) {
        static datetime last_error = 0;
        if(TimeCurrent() - last_error > 300) { // Throttle error print
            Print("⚠️ ERROR: Enable WebRequest for ", ServerURL, " in Tools -> Options -> Expert Advisors");
            last_error = TimeCurrent();
        }
    }
   
    if(ArraySize(result_uchar) > 0) {
        string result_str = CharArrayToString(result_uchar);
        if(result_str != "OK" && result_str != "") {
             string commands[];
             int count = StringSplit(result_str, ';', commands);
             for(int i=0; i<count; i++) {
                 ProcessCommand(commands[i]);
             }
        }
    }
}

color StringToColorRGB(string rgb_str) {
    string parts[];
    if(StringSplit(rgb_str, ',', parts) == 3) {
        int r = (int)StringToInteger(parts[0]);
        int g = (int)StringToInteger(parts[1]);
        int b = (int)StringToInteger(parts[2]);
        return (color)(r + (g << 8) + (b << 16));
    }
    return (color)StringToInteger(rgb_str);
}

ENUM_ORDER_TYPE_FILLING GetFillingMode(string symbol) {
    long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
    if((mode & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    if((mode & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    return ORDER_FILLING_RETURN;
}

// Helper function to convert string timeframe to ENUM_TIMEFRAMES
ENUM_TIMEFRAMES StringToTF(string tf_str) {
    if(tf_str == "M1")  return PERIOD_M1;
    if(tf_str == "M5")  return PERIOD_M5;
    if(tf_str == "M15") return PERIOD_M15;
    if(tf_str == "M30") return PERIOD_M30;
    if(tf_str == "H1")  return PERIOD_H1;
    if(tf_str == "H4")  return PERIOD_H4;
    if(tf_str == "D1")  return PERIOD_D1;
    return PERIOD_CURRENT;
}


void ProcessCommand(string cmd) {
    string parts[];
    if(StringSplit(cmd, '|', parts) < 2) return;
   
    string action = parts[0];
    string symbol = parts[1];


    // Handle opening multiple timeframe tabs
    if(action == "OPEN_CHART") {
      string sym = parts[1];
      ENUM_TIMEFRAMES tf = StringToTF(parts[2]);
      
      // Prevent opening duplicate tabs
      long chartID = ChartFirst();
      bool exists = false;
      while(chartID >= 0) {
         if(ChartSymbol(chartID) == sym && ChartPeriod(chartID) == tf) {
            exists = true;
            break;
         }
         chartID = ChartNext(chartID);
      }
      
      if(!exists) {
         ChartOpen(sym, tf);
      }
      return;
    }
    
    if(!SymbolSelect(symbol, true)) {
        Print("⚠️ Symbol '", symbol, "' not found! Defaulting to chart symbol: ", _Symbol);
        symbol = _Symbol;
    }
   
    if(action == "GET_SYMBOLS") {
        Print("📋 GET_SYMBOLS Received – Symbols already sent in next poll (", SymbolsTotal(true), " total)");
        return;
    }
   
    if(action == "TF_CHANGE") {
        if(ArraySize(parts) < 3) return;
        string new_tf = parts[1];
        int tf_minutes = GetTFMinutes(new_tf);
        ENUM_TIMEFRAMES p = PERIOD_CURRENT;
        if(tf_minutes==1) p=PERIOD_M1; else if(tf_minutes==5) p=PERIOD_M5; else if(tf_minutes==15) p=PERIOD_M15;
        else if(tf_minutes==30) p=PERIOD_M30; else if(tf_minutes==60) p=PERIOD_H1;
        else if(tf_minutes==240) p=PERIOD_H4; else if(tf_minutes==1440) p=PERIOD_D1;
        else if(tf_minutes==10080) p=PERIOD_W1; else if(tf_minutes==43200) p=PERIOD_MN1;
        ChartSetSymbolPeriod(0, symbol, p);
        g_current_period = p;
        g_tf_string = new_tf;
        g_force_candle_reload = true; // Trigger reload
        GlobalVariableDel("Py_Req_History");
        Print("🔄 TF Changed to ", new_tf, " (", tf_minutes, "min) for ", symbol);
        return;
    }
   
    if(action == "SYMBOL_CHANGE") {
        if(ArraySize(parts) < 2) return;
        string new_symbol = parts[1];
        if(SymbolSelect(new_symbol, true)) {
            ChartSetSymbolPeriod(0, new_symbol, g_current_period);
            Print("🔄 Symbol Changed to ", new_symbol, " on TF ", g_tf_string);
            g_force_candle_reload = true; // Trigger reload
        } else {
            Print("❌ Failed to change to invalid symbol: ", new_symbol);
        }
        GlobalVariableDel("Py_Req_History");
        return;
    }
   
    if(action == "RELOAD_CANDLES") {
        g_candles_to_send = 300;
        g_force_candle_reload = true;
        Print("🔄 RELOAD_CANDLES Requested – Will send fresh ", g_candles_to_send, " bars next poll");
        return;
    }
   
    if(action == "GET_HISTORY") {
        if(ArraySize(parts) < 3) return;
        g_candles_to_send = (int)StringToInteger(parts[2]);
        g_force_candle_reload = true;
        
        // POKE: Force MT5 to fetch history if available
        MqlRates dummy[]; 
        CopyRates(_Symbol, g_current_period, 0, g_candles_to_send, dummy);
        
        Print("📥 GET_HISTORY Requested: ", g_candles_to_send, " bars. Poked MT5 memory.");
        return;
    }
   
    // Visual Commands (batch redraw at end if multiple, but for smoothness, redraw only if needed)
    static bool needs_redraw = false;
    if(action == "DRAW_RECT") {
        if(ArraySize(parts) < 7) return;
        color c = StringToColorRGB(parts[6]);
        DrawRect(parts[1], StringToDouble(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), (int)StringToInteger(parts[5]), c);
        needs_redraw = true;
        return;
    }
    if(action == "DRAW_LABEL") {
        if(ArraySize(parts) < 5) return;
        color c = StringToColorRGB(parts[3]);
        DrawLabel(parts[1], parts[2], c, (int)StringToInteger(parts[4]));
        needs_redraw = true;
        return;
    }
    if(action == "DRAW_TEXT") {
        if(ArraySize(parts) < 6) return;
        color c = StringToColorRGB(parts[4]);
        DrawText(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), c, parts[5]);
        needs_redraw = true;
        return;
    }
    if(action == "DRAW_TREND") {
        if(ArraySize(parts) < 8) return;
        color c = StringToColorRGB(parts[6]);
        DrawTrend(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), StringToDouble(parts[5]), c, (int)StringToInteger(parts[7]));
        needs_redraw = true;
        return;
    }
    if(action == "DRAW_LINE") {
        if(ArraySize(parts) < 5) return;
        color c = StringToColorRGB(parts[3]);
        DrawHLine(parts[1], StringToDouble(parts[2]), c, (int)StringToInteger(parts[4]));
        needs_redraw = true;
        return;
    }
    if(action == "CLEAN_CHART") { 
        ObjectsDeleteAll(0, "Py_"); 
        needs_redraw = true;
        return; 
    }

    // Legacy TF change (deprecated but kept)
    if(action == "CHANGE_TF") {
        if(ArraySize(parts) < 3) return;
        int tf = (int)StringToInteger(parts[2]);
        ENUM_TIMEFRAMES p = PERIOD_CURRENT;
        if(tf==1) p=PERIOD_M1; else if(tf==5) p=PERIOD_M5; else if(tf==15) p=PERIOD_M15;
        else if(tf==30) p=PERIOD_M30; else if(tf==60) p=PERIOD_H1;
        else if(tf==240) p=PERIOD_H4; else if(tf==1440) p=PERIOD_D1;
        ChartSetSymbolPeriod(0, symbol, p);
        g_current_period = p;
        g_tf_string = GetTFString();
        g_force_candle_reload = true;
        GlobalVariableDel("Py_Req_History");
        return;
    }
   
    if(symbol != _Symbol && symbol != "" && action == "CHANGE_SYMBOL") {
        SymbolSelect(symbol, true);
        ChartSetSymbolPeriod(0, symbol, g_current_period);
        g_force_candle_reload = true;
        GlobalVariableDel("Py_Req_History");
        return;
    }
   
    double lot = (ArraySize(parts) >= 3) ? StringToDouble(parts[2]) : DefaultLot;
    double sl = (ArraySize(parts) >= 4) ? StringToDouble(parts[3]) : 0;
    double tp = (ArraySize(parts) >= 5) ? StringToDouble(parts[4]) : 0;
    double price = (ArraySize(parts) >= 6) ? StringToDouble(parts[5]) : 0;

    if(action == "BUY") {
        PrintFormat("📥 BUY Request Received: Sym=%s, Lot=%.2f, SL=%.5f, TP=%.5f", symbol, lot, sl, tp);
        TradeMarket(symbol, ORDER_TYPE_BUY, lot, sl, tp);
    }
    else if(action == "SELL") {
        PrintFormat("📥 SELL Request Received: Sym=%s, Lot=%.2f, SL=%.5f, TP=%.5f", symbol, lot, sl, tp);
        TradeMarket(symbol, ORDER_TYPE_SELL, lot, sl, tp);
    }
    else if(action == "BUY_LIMIT") {
        TradePending(symbol, ORDER_TYPE_BUY_LIMIT, lot, price, sl, tp);
    }
    else if(action == "SELL_LIMIT") {
        TradePending(symbol, ORDER_TYPE_SELL_LIMIT, lot, price, sl, tp);
    }
    else if(action == "ORDER_MODIFY") {
        long ticket = (long)StringToInteger(parts[1]);
        double new_sl = StringToDouble(parts[2]);
        double new_tp = StringToDouble(parts[3]);
        ModifyOrder(ticket, new_sl, new_tp);
    }
    else if(action == "CLOSE_ALL") {
        ClosePositions(symbol, "ALL");
    }
    else if(action == "CLOSE_WIN") {
        ClosePositions(symbol, "WIN");
    }
    else if(action == "CLOSE_LOSS") {
        ClosePositions(symbol, "LOSS");
    }
    else if(action == "CLOSE_TICKET") {
        CloseTicket((long)StringToInteger(parts[1]));
    }

    // Batch redraw at end of processing
    if(needs_redraw) {
        ChartRedraw();
        needs_redraw = false;
    }
}

void TradeMarket(string s, ENUM_ORDER_TYPE t, double v, double sl, double tp) {
    MqlTradeRequest r;
    MqlTradeResult res;
    ZeroMemory(r); ZeroMemory(res);
   
    string tradeAction = (t == ORDER_TYPE_BUY) ? "BUY" : "SELL"; 
    double tick_size = SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE);
    double stops_level_pts = (double)SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL);
    double point = SymbolInfoDouble(s, SYMBOL_POINT);
    double stops_level = stops_level_pts * point;
    // Add a small 2-point buffer to stops_level to avoid boundary errors
    double safety_buffer = 2.0 * point;
    double min_dist = (stops_level + safety_buffer);
   
    double ask = SymbolInfoDouble(s, SYMBOL_ASK);
    double bid = SymbolInfoDouble(s, SYMBOL_BID);
    double entry_price = (t == ORDER_TYPE_BUY) ? ask : bid;

    r.action = TRADE_ACTION_DEAL;
    r.symbol = s;
    r.volume = v;
    r.type = t;
    
    // Normalize to TICK SIZE (more robust than NormalizeDouble)
    r.price = MathRound(entry_price / tick_size) * tick_size;
    r.deviation = 20; // Increased for crypto volatility

    // Validate SL/TP
    if(sl > 0) {
        if(t == ORDER_TYPE_BUY && sl > (bid - min_dist)) sl = bid - min_dist;
        if(t == ORDER_TYPE_SELL && sl < (ask + min_dist)) sl = ask + min_dist;
        r.sl = MathRound(sl / tick_size) * tick_size;
    } else {
        r.sl = 0;
    }
    
    if(tp > 0) {
        if(t == ORDER_TYPE_BUY && tp < (ask + min_dist)) tp = ask + min_dist;
        if(t == ORDER_TYPE_SELL && tp > (bid - min_dist)) tp = bid - min_dist;
        r.tp = MathRound(tp / tick_size) * tick_size;
    } else {
        r.tp = 0;
    }

    r.type_filling = GetFillingMode(s);
    if(r.type_filling == ORDER_FILLING_RETURN) r.type_filling = ORDER_FILLING_IOC; 
    
    if(!OrderSend(r, res)) {
        PrintFormat("❌ Trade Fail: %d | %s %s | Price: %f, SL: %f, TP: %f | StopsDist: %f, Mode: %d", 
                    res.retcode, tradeAction, s, r.price, r.sl, r.tp, min_dist, (int)r.type_filling);
        
        // AUTO-RECOVERY: If 10017, try without stops as fallback
        if(res.retcode == 10017) {
            Print("⚠️ 10017 Detected - Retrying without SL/TP for safety...");
            r.sl = 0; r.tp = 0;
            if(OrderSend(r, res)) Print("✅ Fallback Trade Success (No Stops)");
            else Print("❌ Fallback Fail: ", res.retcode);
        }
    } else {
        PrintFormat("🚀 Trade Executed: %s %s Ticket: %d (SL: %f, TP: %f)", tradeAction, s, res.order, r.sl, r.tp);
    }
}

void TradePending(string s, ENUM_ORDER_TYPE t, double v, double p, double sl, double tp) {
    MqlTradeRequest r; MqlTradeResult res;
    ZeroMemory(r); ZeroMemory(res);
   
    int digits = (int)SymbolInfoInteger(s, SYMBOL_DIGITS);
    r.action = TRADE_ACTION_PENDING;
    r.symbol = s;
    r.volume = v;
    r.type = t;
    r.price = NormalizeDouble(p, digits);
    if(sl > 0) r.sl = NormalizeDouble(sl, digits);
    if(tp > 0) r.tp = NormalizeDouble(tp, digits);
    r.deviation = 20;
    r.type_filling = GetFillingMode(s);
    if(!OrderSend(r, res)) Print("❌ Pending Fail: ", res.retcode);
}

void ClosePositions(string s, string m) {
    for(int i=PositionsTotal()-1; i>=0; i--) {
        if(PositionGetSymbol(i) == s) {
            double p = PositionGetDouble(POSITION_PROFIT);
            if((m=="WIN" && p<=0) || (m=="LOSS" && p>=0)) continue;
           
            MqlTradeRequest r; MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
            r.action=TRADE_ACTION_DEAL;
            r.position=PositionGetTicket(i);
            r.symbol=s;
            r.volume=PositionGetDouble(POSITION_VOLUME);
            r.type=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?ORDER_TYPE_SELL:ORDER_TYPE_BUY;
            r.price=(r.type==ORDER_TYPE_BUY)?SymbolInfoDouble(s,SYMBOL_ASK):SymbolInfoDouble(s,SYMBOL_BID);
            r.deviation = 20;
            r.type_filling = GetFillingMode(s);
           
            if(!OrderSend(r, res)) Print("❌ Close Fail: ", res.retcode);
            else Print("✅ Closed Position: ", r.position);
        }
    }
}

void CloseTicket(long ticket) {
    if(PositionSelectByTicket(ticket)) {
        MqlTradeRequest r; MqlTradeResult res;
        ZeroMemory(r); ZeroMemory(res);
        r.action=TRADE_ACTION_DEAL;
        r.position=ticket;
        r.symbol=PositionGetString(POSITION_SYMBOL);
        r.volume=PositionGetDouble(POSITION_VOLUME);
        r.type=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?ORDER_TYPE_SELL:ORDER_TYPE_BUY;
        r.price=(r.type==ORDER_TYPE_BUY)?SymbolInfoDouble(r.symbol,SYMBOL_ASK):SymbolInfoDouble(r.symbol,SYMBOL_BID);
        r.deviation = 20;
        r.type_filling = GetFillingMode(r.symbol);
       
        if(!OrderSend(r, res)) Print("❌ Close Ticket Fail: ", res.retcode);
        else Print("✅ Closed Ticket #", ticket);
    } else {
        Print("⚠️ Ticket not found: ", ticket);
    }
}
void ModifyOrder(long ticket, double sl, double tp) {
    if(PositionSelectByTicket(ticket)) {
        MqlTradeRequest r; MqlTradeResult res;
        ZeroMemory(r); ZeroMemory(res);
        r.action = TRADE_ACTION_SLTP;
        r.position = ticket;
        r.symbol = PositionGetString(POSITION_SYMBOL);
        
        double tick_size = SymbolInfoDouble(r.symbol, SYMBOL_TRADE_TICK_SIZE);
        r.sl = MathRound(sl / tick_size) * tick_size;
        r.tp = MathRound(tp / tick_size) * tick_size;
        
        if(!OrderSend(r, res)) Print("❌ Modify Fail: ", res.retcode, " Ticket #", ticket);
        else Print("✅ Modified Ticket #", ticket, " SL: ", r.sl, " TP: ", r.tp);
    } else {
        Print("⚠️ Modify: Ticket not found: ", ticket);
    }
}

// Drawing Functions (optimized: no redundant redraws)
void DrawRect(string name, double p1, double p2, int b1, int b2, color c) {
    string n = "Py_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_RECTANGLE, 0, 0, 0, 0, 0);
    datetime t1 = iTime(_Symbol, g_current_period, b1);
    datetime t2 = iTime(_Symbol, g_current_period, b2);
    if(t1 <= 0) t1 = iTime(_Symbol, g_current_period, iBars(_Symbol, g_current_period)-1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, t1);
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, t2);
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_FILL, false);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, 1);
    ObjectSetInteger(0, n, OBJPROP_BACK, true);
    // Redraw deferred
}

void DrawHLine(string name, double price, color c, int style) {
    string n = "Py_H_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_HLINE, 0, 0, price);
    ObjectSetDouble(0, n, OBJPROP_PRICE, price);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_STYLE, style);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, 2);
    ObjectSetInteger(0, n, OBJPROP_BACK, false);
    // Redraw deferred
}

void DrawLabel(string name, string text, color c, int y) {
    string n = "Py_Lbl_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
    ObjectSetString(0, n, OBJPROP_TEXT, text);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 20);
    ObjectSetInteger(0, n, OBJPROP_YDISTANCE, y);
    ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
    ObjectSetInteger(0, n, OBJPROP_FONTSIZE, 10);
    ObjectSetInteger(0, n, OBJPROP_BACK, false);
    // Redraw deferred
}

void DrawText(string name, int b, double p, color c, string t) {
    string n = "Py_Txt_" + name;
    if(ObjectFind(0, n) >= 0) ObjectDelete(0, n);
    ObjectCreate(0, n, OBJ_TEXT, 0, iTime(_Symbol, g_current_period, b), p);
    ObjectSetString(0, n, OBJPROP_TEXT, t);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_FONTSIZE, 10);
    ObjectSetInteger(0, n, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
    // Redraw deferred
}

void DrawTrend(string name, int b1, double p1, int b2, double p2, color c, int w) {
    string n = "Py_Tr_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_TREND, 0, 0, 0, 0, 0);
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, iTime(_Symbol, g_current_period, b1));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, iTime(_Symbol, g_current_period, b2));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, w);
    ObjectSetInteger(0, n, OBJPROP_RAY_RIGHT, true);
    // Redraw deferred
}