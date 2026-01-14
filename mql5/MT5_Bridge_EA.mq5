#property strict
#property version "4.0"
#property description "HTTP Bridge - Optimized High Frequency"

input string ServerURL = "http://127.0.0.1:8001";
input double DefaultLot = 0.01;

int OnInit() { 
   // PERFORMANCE FIX: Increase tick rate to 100ms for faster reaction
   EventSetMillisecondTimer(100); 
   return INIT_SUCCEEDED; 
}

void OnDeinit(const int reason) { EventKillTimer(); ObjectsDeleteAll(0, "Py_"); }

// Helper to calculate history profit
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

void OnTimer() {
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) return;

    // 1. FAST DATA FETCH
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double profit = AccountInfoDouble(ACCOUNT_PROFIT);
    
    // 2. OPTIMIZED POSITIONS LOOP
    int total_pos = PositionsTotal();
    int buy_count = 0; int sell_count = 0;
    string active_trades = "";
    
    for(int i=0; i<total_pos; i++) {
        ulong ticket = PositionGetTicket(i);
        if(ticket > 0) {
            if(PositionGetString(POSITION_SYMBOL) == _Symbol) {
                long type = PositionGetInteger(POSITION_TYPE);
                if(type == POSITION_TYPE_BUY) buy_count++;
                if(type == POSITION_TYPE_SELL) sell_count++;
            }
            
            // Build Trade String
            string type_str = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            string trade_line = IntegerToString(ticket) + "," + 
                                PositionGetString(POSITION_SYMBOL) + "," + 
                                type_str + "," + 
                                DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + "," + 
                                DoubleToString(PositionGetDouble(POSITION_PROFIT), 2);
            if(active_trades != "") active_trades += "|";
            active_trades += trade_line;
        }
    }

    // 3. OPTIMIZED CANDLE HISTORY (Reduced Payload)
    string candle_history = "";
    // Default to 300 (enough for EMA 200), only send 1000 if requested
    int candles_to_send = 300; 
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

    // 4. ACCOUNT STATS
    long acct_login = AccountInfoInteger(ACCOUNT_LOGIN);
    double acct_equity = AccountInfoDouble(ACCOUNT_EQUITY);

    // 5. CONSTRUCT PAYLOAD
    string post_str = "symbol=" + _Symbol + 
                      "&bid=" + DoubleToString(bid, _Digits) + 
                      "&ask=" + DoubleToString(ask, _Digits) +
                      "&balance=" + DoubleToString(balance, 2) +
                      "&profit=" + DoubleToString(profit, 2) +
                      "&acct_name=" + AccountInfoString(ACCOUNT_NAME) +
                      "&acct_login=" + IntegerToString(acct_login) +
                      "&acct_equity=" + DoubleToString(acct_equity, 2) +
                      "&positions=" + IntegerToString(total_pos) +
                      "&buy_count=" + IntegerToString(buy_count) +
                      "&sell_count=" + IntegerToString(sell_count) +
                      "&candles=" + candle_history +
                      "&active_trades=" + active_trades +
                      "&all_symbols=s"; // Removed heavy symbol list

    SendRequest(post_str);
}

void SendRequest(string data_str) {
    char post_char[]; StringToCharArray(data_str, post_char);
    uchar post_uchar[]; ArrayResize(post_uchar, ArraySize(post_char));
    for(int i=0; i<ArraySize(post_char); i++) post_uchar[i] = (uchar)post_char[i];
    
    uchar result_uchar[]; string response_headers;
    int http_res = WebRequest("POST", ServerURL, "Content-Type: application/x-www-form-urlencoded\r\n", 500, post_uchar, result_uchar, response_headers);
    
    if(ArraySize(result_uchar) > 0) {
        string result_str = CharArrayToString(result_uchar);
        if(result_str != "OK" && result_str != "") {
             string commands[];
             int count = StringSplit(result_str, ';', commands);
             for(int i=0; i<count; i++) ProcessCommand(commands[i]);
        }
    }
}

color StringToColorRGB(string rgb_str) {
    string parts[];
    if(StringSplit(rgb_str, ',', parts) == 3) {
        return (color)(StringToInteger(parts[0]) + (StringToInteger(parts[1]) << 8) + (StringToInteger(parts[2]) << 16));
    }
    return (color)StringToInteger(rgb_str);
}

void ProcessCommand(string cmd) {
    string parts[];
    if(StringSplit(cmd, '|', parts) < 2) return;
    string action = parts[0]; string symbol = parts[1];
    
    if(action == "CHANGE_TF") {
        if(ArraySize(parts) < 3) return;
        int tf = (int)StringToInteger(parts[2]);
        ENUM_TIMEFRAMES p = PERIOD_CURRENT;
        if(tf==1) p=PERIOD_M1; else if(tf==5) p=PERIOD_M5; else if(tf==15) p=PERIOD_M15;
        else if(tf==30) p=PERIOD_M30; else if(tf==60) p=PERIOD_H1;
        else if(tf==240) p=PERIOD_H4; else if(tf==1440) p=PERIOD_D1;
        
        if(Period() != p) {
            ChartSetSymbolPeriod(0, symbol, p); 
            GlobalVariableDel("Py_Req_History");
        }
        return;
    }
    
    // Drawing Commands
    if(action == "DRAW_RECT" && ArraySize(parts) >= 7) {
        DrawRect(parts[1], StringToDouble(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), (int)StringToInteger(parts[5]), StringToColorRGB(parts[6]));
        return;
    }
    if(action == "DRAW_LINE" && ArraySize(parts) >= 5) {
        DrawHLine(parts[1], StringToDouble(parts[2]), StringToColorRGB(parts[3]), (int)StringToInteger(parts[4]));
        return;
    }
    
    // Symbol Change
    if(symbol != _Symbol && symbol != "" && action == "CHANGE_SYMBOL") { 
        SymbolSelect(symbol, true);
        ChartSetSymbolPeriod(0, symbol, _Period); 
        GlobalVariableDel("Py_Req_History");
        return; 
    }
    
    // Trading
    double lot = (ArraySize(parts) >= 3) ? StringToDouble(parts[2]) : DefaultLot;
    double sl = (ArraySize(parts) >= 4) ? StringToDouble(parts[3]) : 0;
    double tp = (ArraySize(parts) >= 5) ? StringToDouble(parts[4]) : 0;
    
    if(action == "GET_HISTORY") {
        int count = (int)StringToInteger(parts[2]);
        if(count > 0) GlobalVariableSet("Py_Req_History", count);
        return;
    }

    if(action == "BUY")             TradeMarket(symbol, ORDER_TYPE_BUY, lot, sl, tp);
    else if(action == "SELL")       TradeMarket(symbol, ORDER_TYPE_SELL, lot, sl, tp);
    else if(action == "CLOSE_ALL")  ClosePositions(symbol, "ALL");
    else if(action == "CLOSE_WIN")  ClosePositions(symbol, "WIN");
    else if(action == "CLOSE_LOSS") ClosePositions(symbol, "LOSS");
    else if(action == "CLOSE_TICKET") CloseTicket((long)StringToInteger(parts[1]));
}

// --- TRADE UTILS ---
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
        r.type_filling = GetFillingMode(r.symbol);
        OrderSend(r, res);
    }
}

void TradeMarket(string s, ENUM_ORDER_TYPE t, double v, double sl, double tp) {
    MqlTradeRequest r; MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
    r.action=TRADE_ACTION_DEAL; r.symbol=s; r.volume=v; r.type=t; 
    r.price=(t==ORDER_TYPE_BUY)?SymbolInfoDouble(s,SYMBOL_ASK):SymbolInfoDouble(s,SYMBOL_BID); 
    r.sl=sl; r.tp=tp; r.deviation=20; r.type_filling = GetFillingMode(s); 
    OrderSend(r, res);
}

void ClosePositions(string s, string m) {
    for(int i=PositionsTotal()-1; i>=0; i--) {
        if(PositionGetSymbol(i) == s) {
            double p = PositionGetDouble(POSITION_PROFIT);
            if((m=="WIN" && p<=0) || (m=="LOSS" && p>=0)) continue;
            CloseTicket(PositionGetTicket(i));
        }
    }
}

// --- DRAWING UTILS ---
void DrawRect(string name, double p1, double p2, int b1, int b2, color c) {
    string n = "Py_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_RECTANGLE, 0, 0, 0, 0, 0);
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, iTime(_Symbol, _Period, b1));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, iTime(_Symbol, _Period, b2));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_FILL, true); 
    ChartRedraw();
}

void DrawHLine(string name, double price, color c, int style) {
    string n = "Py_H_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_HLINE, 0, 0, price);
    ObjectSetDouble(0, n, OBJPROP_PRICE, price);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ChartRedraw();
}