#property strict
#property version "3.3"
#property description "HTTP Bridge - Stable ZigZag & Auto Trade & CRT Monitor"

input string ServerURL = "http://127.0.0.1:8001";
input double DefaultLot = 0.01;

int OnInit() { EventSetMillisecondTimer(500); return INIT_SUCCEEDED; }
void OnDeinit(const int reason) { EventKillTimer(); ObjectsDeleteAll(0, "Py_"); }

double CalculateHistoryProfit(datetime from_date)
{
    double profit = 0;
    if(HistorySelect(from_date, TimeCurrent()))
    {
        int total = HistoryDealsTotal();
        for(int i=0; i<total; i++)
        {
            ulong ticket = HistoryDealGetTicket(i);
            if(ticket > 0)
            {
                profit += HistoryDealGetDouble(ticket, DEAL_PROFIT);
                profit += HistoryDealGetDouble(ticket, DEAL_COMMISSION);
                profit += HistoryDealGetDouble(ticket, DEAL_SWAP);
            }
        }
    }
    return profit;
}

void OnTimer()
{
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) {
        Print("⚠️ Algo Trading is Disabled! Enable 'Algo Trading' button.");
    }

    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double profit = AccountInfoDouble(ACCOUNT_PROFIT);
    string acct_name = AccountInfoString(ACCOUNT_NAME);
    
    int total_pos = PositionsTotal();
    int buy_count = 0; int sell_count = 0;
    double sum_price_vol = 0.0; double sum_vol = 0.0;

    for(int i=0; i<total_pos; i++) {
        if(PositionGetSymbol(i) == _Symbol) {
            double vol = PositionGetDouble(POSITION_VOLUME);
            double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
            long type = PositionGetInteger(POSITION_TYPE);
            sum_price_vol += (open_price * vol);
            sum_vol += vol;
            if(type == POSITION_TYPE_BUY) buy_count++;
            else if(type == POSITION_TYPE_SELL) sell_count++;
        }
    }
    double avg_entry = (sum_vol > 0) ? NormalizeDouble(sum_price_vol / sum_vol, _Digits) : 0.0;

    string symbols_list = "";
    int total_symbols = SymbolsTotal(true);
    for(int i=0; i<total_symbols; i++) symbols_list += SymbolName(i, true) + (i < total_symbols - 1 ? "," : "");

    string candle_history = "";
    int candles_to_send = 200; 
    if(GlobalVariableCheck("Py_Req_History")) {
        candles_to_send = (int)GlobalVariableGet("Py_Req_History");
    }
    
    int available = iBars(_Symbol, _Period);
    if(candles_to_send > available) candles_to_send = available;

    for(int i=0; i<candles_to_send; i++) {
        candle_history += DoubleToString(iHigh(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iLow(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iOpen(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iClose(_Symbol, _Period, i), _Digits) + "," +
                          IntegerToString(iTime(_Symbol, _Period, i)) + 
                          (i < candles_to_send - 1 ? "|" : "");
    }

    // --- NEW: Capture detailed active trades for Telegram ---
    string active_trades = "";
    for(int i=0; i<total_pos; i++) {
        ulong ticket = PositionGetTicket(i); // Select by index
        if(ticket > 0) {
            string p_symbol = PositionGetString(POSITION_SYMBOL);
            long p_type = PositionGetInteger(POSITION_TYPE);
            double p_vol = PositionGetDouble(POSITION_VOLUME);
            double p_profit = PositionGetDouble(POSITION_PROFIT);
            
            string type_str = (p_type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            string trade_line = IntegerToString(ticket) + "," + p_symbol + "," + type_str + "," + DoubleToString(p_vol, 2) + "," + DoubleToString(p_profit, 2);
            
            if(active_trades != "") active_trades += "|";
            active_trades += trade_line;
        }
    }

    // Account Details
    long acct_login = AccountInfoInteger(ACCOUNT_LOGIN);
    string acct_server = AccountInfoString(ACCOUNT_SERVER);
    string acct_company = AccountInfoString(ACCOUNT_COMPANY);
    long acct_leverage = AccountInfoInteger(ACCOUNT_LEVERAGE);
    double acct_equity = AccountInfoDouble(ACCOUNT_EQUITY);

    // History Profits
    MqlDateTime dt; TimeCurrent(dt);
    dt.hour = 0; dt.min = 0; dt.sec = 0;
    datetime day_start = StructToTime(dt);
    
    // Weekend/Weekly start (Monday)
    int days_to_monday = (dt.day_of_week == 0) ? 6 : (dt.day_of_week - 1);
    datetime week_start = day_start - (days_to_monday * 86400);
    
    // Month start
    dt.day = 1;
    datetime month_start = StructToTime(dt);

    double prof_today = CalculateHistoryProfit(day_start);
    double prof_week = CalculateHistoryProfit(week_start);
    double prof_month = CalculateHistoryProfit(month_start);

    string post_str = "symbol=" + _Symbol + 
                      "&bid=" + DoubleToString(bid, _Digits) + 
                      "&ask=" + DoubleToString(ask, _Digits) +
                      "&balance=" + DoubleToString(balance, 2) +
                      "&profit=" + DoubleToString(profit, 2) +
                      "&prof_today=" + DoubleToString(prof_today, 2) +
                      "&prof_week=" + DoubleToString(prof_week, 2) +
                      "&prof_month=" + DoubleToString(prof_month, 2) +
                      "&acct_name=" + acct_name +
                      "&acct_login=" + IntegerToString(acct_login) +
                      "&acct_server=" + acct_server +
                      "&acct_company=" + acct_company +
                      "&acct_leverage=" + IntegerToString(acct_leverage) +
                      "&acct_equity=" + DoubleToString(acct_equity, 2) +
                      "&positions=" + IntegerToString(total_pos) +
                      "&buy_count=" + IntegerToString(buy_count) +
                      "&sell_count=" + IntegerToString(sell_count) +
                      "&avg_entry=" + DoubleToString(avg_entry, _Digits) +
                      "&all_symbols=" + symbols_list +
                      "&candles=" + candle_history +
                      "&active_trades=" + active_trades;
    
    SendRequest(post_str);
}

void SendRequest(string data_str)
{
    char post_char[]; StringToCharArray(data_str, post_char);
    uchar post_uchar[]; ArrayResize(post_uchar, ArraySize(post_char));
    for(int i=0; i<ArraySize(post_char); i++) post_uchar[i] = (uchar)post_char[i];
    
    uchar result_uchar[]; string response_headers;
    int http_res = WebRequest("POST", ServerURL, "Content-Type: application/x-www-form-urlencoded\r\n", 2000, post_uchar, result_uchar, response_headers);
    
    if(http_res == -1 && GetLastError() == 4060) Print("⚠️ ERROR: You must enable WebRequest for ", ServerURL, " in Tools -> Options -> Expert Advisors");
    
    if(ArraySize(result_uchar) > 0) {
        string result_str = CharArrayToString(result_uchar);
        if(result_str != "OK" && result_str != "") {
             string commands[];
             int count = StringSplit(result_str, ';', commands);
             for(int i=0; i<count; i++) ProcessCommand(commands[i]);
        }
    }
}

// --- HELPER: Parse "R,G,B" string to Color Manually ---
color StringToColorRGB(string rgb_str) {
    string parts[];
    // Split by comma
    if(StringSplit(rgb_str, ',', parts) == 3) {
        int r = (int)StringToInteger(parts[0]);
        int g = (int)StringToInteger(parts[1]);
        int b = (int)StringToInteger(parts[2]);
        // Construct MQL5 Color (0x00BBGGRR)
        return (color)(r + (g << 8) + (b << 16));
    }
    return (color)StringToInteger(rgb_str); // Fallback
}

void ProcessCommand(string cmd)
{
    string parts[]; if(StringSplit(cmd, '|', parts) < 2) return;
    string action = parts[0]; string symbol = parts[1]; 

    if(action == "CHANGE_TF") {
        if(ArraySize(parts) < 3) return;
        int tf = (int)StringToInteger(parts[2]);
        ENUM_TIMEFRAMES p = PERIOD_CURRENT;
        if(tf==1) p=PERIOD_M1; else if(tf==5) p=PERIOD_M5; else if(tf==15) p=PERIOD_M15;
        else if(tf==30) p=PERIOD_M30;
        else if(tf==60) p=PERIOD_H1; else if(tf==240) p=PERIOD_H4; else if(tf==1440) p=PERIOD_D1;
        ChartSetSymbolPeriod(0, symbol, p); 
        GlobalVariableDel("Py_Req_History");
        return;
    }
    
    // --- DRAWING COMMANDS ---
    if(action == "DRAW_RECT") {
        if(ArraySize(parts) < 7) return;
        color c = StringToColorRGB(parts[6]); 
        Print("[Py-Visual] DRAW_RECT: ", parts[1], " P1:", parts[2], " P2:", parts[3]);
        DrawRect(parts[1], StringToDouble(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), (int)StringToInteger(parts[5]), c);
        return;
    }

    if(action == "DRAW_LABEL") {
        if(ArraySize(parts) < 5) return;
        color c = StringToColorRGB(parts[3]);
        Print("[Py-Visual] DRAW_LABEL: ", parts[1], " Text:", parts[2]);
        DrawLabel(parts[1], parts[2], c, (int)StringToInteger(parts[4]));
        return;
    }

    if(action == "DRAW_TEXT") {
        if(ArraySize(parts) < 6) return;
        color c = StringToColorRGB(parts[4]);
        DrawText(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), c, parts[5]);
        return;
    }

    if(action == "DRAW_TREND") {
        if(ArraySize(parts) < 8) return;
        color c = StringToColorRGB(parts[6]);
        DrawTrend(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), StringToDouble(parts[5]), c, (int)StringToInteger(parts[7]));
        return;
    }

    if(action == "DRAW_LINE") {
        if(ArraySize(parts) < 5) return;
        color c = StringToColorRGB(parts[3]);
        DrawHLine(parts[1], StringToDouble(parts[2]), c, (int)StringToInteger(parts[4]));
        return;
    }

    if(action == "CLEAN_CHART") { ObjectsDeleteAll(0, "Py_"); return; }
    if(symbol != _Symbol && symbol != "" && action == "CHANGE_SYMBOL") { 
        SymbolSelect(symbol, true); 
        ChartSetSymbolPeriod(0, symbol, _Period); 
        GlobalVariableDel("Py_Req_History");
        return; 
    }
    
    double lot = (ArraySize(parts) >= 3) ? StringToDouble(parts[2]) : DefaultLot;
    double sl = (ArraySize(parts) >= 4) ? StringToDouble(parts[3]) : 0;
    double tp = (ArraySize(parts) >= 5) ? StringToDouble(parts[4]) : 0;
    double price = (ArraySize(parts) >= 6) ? StringToDouble(parts[5]) : 0;
    
    if(action == "GET_HISTORY") {
        if(ArraySize(parts) < 3) return;
        int count = (int)StringToInteger(parts[2]);
        int available = iBars(_Symbol, _Period);
        if(count > available) count = available;
        if(count > 0) GlobalVariableSet("Py_Req_History", count);
        return;
    }

    if(action == "BUY")             TradeMarket(symbol, ORDER_TYPE_BUY, lot, sl, tp);
    else if(action == "SELL")       TradeMarket(symbol, ORDER_TYPE_SELL, lot, sl, tp);
    else if(action == "BUY_LIMIT")   TradePending(symbol, ORDER_TYPE_BUY_LIMIT, lot, price, sl, tp);
    else if(action == "SELL_LIMIT")  TradePending(symbol, ORDER_TYPE_SELL_LIMIT, lot, price, sl, tp);
    else if(action == "CLOSE_ALL")   ClosePositions(symbol, "ALL");
    else if(action == "CLOSE_WIN")   ClosePositions(symbol, "WIN");
    else if(action == "CLOSE_LOSS")  ClosePositions(symbol, "LOSS");
    else if(action == "CLOSE_TICKET") CloseTicket((long)StringToInteger(parts[1]));
}

// --- HELPER: Auto-detect correct filling mode ---
ENUM_ORDER_TYPE_FILLING GetFillingMode(string symbol) {
    long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
    if((mode & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    if((mode & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    return ORDER_FILLING_RETURN;
}

void CloseTicket(long ticket) {
    if(PositionSelectByTicket(ticket)) {
        MqlTradeRequest r; MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
        r.action=TRADE_ACTION_DEAL; r.position=ticket; r.symbol=PositionGetString(POSITION_SYMBOL); 
        r.volume=PositionGetDouble(POSITION_VOLUME);
        r.type=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?ORDER_TYPE_SELL:ORDER_TYPE_BUY; 
        r.price=(r.type==ORDER_TYPE_BUY)?SymbolInfoDouble(r.symbol,SYMBOL_ASK):SymbolInfoDouble(r.symbol,SYMBOL_BID);
        r.deviation = 20;
        r.type_filling = GetFillingMode(r.symbol); 
        if(!OrderSend(r, res)) Print("Close Ticket Fail: ", res.retcode);
        else Print("Closed Ticket #", ticket);
    } else {
        Print("Ticket not found: ", ticket);
    }
}

void DrawRect(string name, double p1, double p2, int b1, int b2, color c) {
    string n = "Py_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_RECTANGLE, 0, 0, 0, 0, 0);
    
    datetime t1 = iTime(_Symbol, _Period, b1);
    datetime t2 = iTime(_Symbol, _Period, b2);
    if(t1 <= 0) t1 = iTime(_Symbol, _Period, iBars(_Symbol, _Period)-1);
    
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, t1);
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, t2);
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c); 
    ObjectSetInteger(0, n, OBJPROP_FILL, false); // Outline only for clarity
    ObjectSetInteger(0, n, OBJPROP_WIDTH, 1);
    ObjectSetInteger(0, n, OBJPROP_BACK, true);
    ChartRedraw();
}

void DrawHLine(string name, double price, color c, int style) {
    string n = "Py_H_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_HLINE, 0, 0, price);
    ObjectSetDouble(0, n, OBJPROP_PRICE, price);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_STYLE, style);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, 2);
    ObjectSetInteger(0, n, OBJPROP_BACK, false); 
    ChartRedraw();
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
    ObjectSetInteger(0, n, OBJPROP_BACK, false); // Keep labels on top
    ChartRedraw();
}

void DrawText(string name, int b, double p, color c, string t) {
    string n = "Py_Txt_" + name;
    if(ObjectFind(0, n) >= 0) ObjectDelete(0, n); 
    ObjectCreate(0, n, OBJ_TEXT, 0, iTime(_Symbol, _Period, b), p);
    ObjectSetString(0, n, OBJPROP_TEXT, t);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_FONTSIZE, 10);
    ObjectSetInteger(0, n, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
}

void DrawTrend(string name, int b1, double p1, int b2, double p2, color c, int w) {
    string n = "Py_Tr_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_TREND, 0, 0, 0, 0, 0);
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, iTime(_Symbol, _Period, b1));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, iTime(_Symbol, _Period, b2));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, w);
    ObjectSetInteger(0, n, OBJPROP_RAY_RIGHT, true);
}




void TradeMarket(string s, ENUM_ORDER_TYPE t, double v, double sl, double tp) {
    MqlTradeRequest r;
    MqlTradeResult res;
    ZeroMemory(r); ZeroMemory(res);
    r.action=TRADE_ACTION_DEAL; r.symbol=s; r.volume=v; r.type=t; 
    r.price=(t==ORDER_TYPE_BUY)?SymbolInfoDouble(s,SYMBOL_ASK):SymbolInfoDouble(s,SYMBOL_BID); 
    r.sl=sl; r.tp=tp; 
    r.deviation = 20;
    r.type_filling = GetFillingMode(s); 
    if(!OrderSend(r, res)) Print("Trade Fail: ", res.retcode);
}

void TradePending(string s, ENUM_ORDER_TYPE t, double v, double p, double sl, double tp) {
    MqlTradeRequest r;
    MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
    r.action=TRADE_ACTION_PENDING; r.symbol=s; r.volume=v; r.type=t; r.price=p; r.sl=sl; r.tp=tp; 
    r.deviation = 20;
    r.type_filling = GetFillingMode(s); 
    if(!OrderSend(r, res)) Print("Pending Fail: ", res.retcode);
}

void ClosePositions(string s, string m) {
    for(int i=PositionsTotal()-1; i>=0; i--) {
        if(PositionGetSymbol(i) == s) {
            double p = PositionGetDouble(POSITION_PROFIT);
            if((m=="WIN" && p<=0) || (m=="LOSS" && p>=0)) continue;
            MqlTradeRequest r; MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
            r.action=TRADE_ACTION_DEAL; r.position=PositionGetTicket(i); r.symbol=s; r.volume=PositionGetDouble(POSITION_VOLUME);
            r.type=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?ORDER_TYPE_SELL:ORDER_TYPE_BUY; 
            r.price=(r.type==ORDER_TYPE_BUY)?SymbolInfoDouble(s,SYMBOL_ASK):SymbolInfoDouble(s,SYMBOL_BID);
            r.deviation = 20;
            r.type_filling = GetFillingMode(s); 
            
            // Check return value to fix compiler warning
            if(!OrderSend(r, res)) Print("Close Fail: ", res.retcode);
        }
    }
}