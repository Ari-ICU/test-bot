#property strict
#property version "3.0"
#property description "HTTP Bridge - Stable ZigZag & Auto Trade"

input string ServerURL = "http://127.0.0.1:8001";
input double DefaultLot = 0.01;

int OnInit() { EventSetMillisecondTimer(250); return INIT_SUCCEEDED; }
void OnDeinit(const int reason) { EventKillTimer(); ObjectsDeleteAll(0, "Py_"); }

void OnTimer()
{
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) {
        Print("⚠️ Algo Trading is Disabled!");
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
    int candles_to_send = 300;
    for(int i=0; i<candles_to_send; i++) {
        // ADDED: Timestamp (IntegerToString(iTime...)) at the end
        candle_history += DoubleToString(iHigh(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iLow(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iOpen(_Symbol, _Period, i), _Digits) + "," +
                          DoubleToString(iClose(_Symbol, _Period, i), _Digits) + "," +
                          IntegerToString(iTime(_Symbol, _Period, i)) + 
                          (i < candles_to_send - 1 ? "|" : "");
    }

    string post_str = "symbol=" + _Symbol + 
                      "&bid=" + DoubleToString(bid, _Digits) + 
                      "&ask=" + DoubleToString(ask, _Digits) +
                      "&balance=" + DoubleToString(balance, 2) +
                      "&profit=" + DoubleToString(profit, 2) +
                      "&acct_name=" + acct_name +
                      "&positions=" + IntegerToString(total_pos) +
                      "&buy_count=" + IntegerToString(buy_count) +
                      "&sell_count=" + IntegerToString(sell_count) +
                      "&avg_entry=" + DoubleToString(avg_entry, _Digits) +
                      "&all_symbols=" + symbols_list +
                      "&candles=" + candle_history;
    SendRequest(post_str);
}

void SendRequest(string data_str)
{
    char post_char[]; StringToCharArray(data_str, post_char);
    uchar post_uchar[]; ArrayResize(post_uchar, ArraySize(post_char));
    for(int i=0; i<ArraySize(post_char); i++) post_uchar[i] = (uchar)post_char[i];
    uchar result_uchar[]; string response_headers;
    int http_res = WebRequest("POST", ServerURL, "Content-Type: application/x-www-form-urlencoded\r\n", 2000, post_uchar, result_uchar, response_headers);
    
    if(http_res == -1 && GetLastError() == 4060) Print("⚠️ ALLOW WEBREQUEST FOR: ", ServerURL);
    if(ArraySize(result_uchar) > 0) {
        string result_str = CharArrayToString(result_uchar);
        if(result_str != "OK" && result_str != "") {
             string commands[];
             int count = StringSplit(result_str, ';', commands);
             for(int i=0; i<count; i++) ProcessCommand(commands[i]);
        }
    }
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
        ChartSetSymbolPeriod(0, symbol, p); return;
    }
    
    // --- DRAWING COMMANDS ---
    if(action == "DRAW_RECT") {
        if(ArraySize(parts) < 7) return;
        DrawRect(parts[1], StringToDouble(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), (int)StringToInteger(parts[5]), (color)StringToInteger(parts[6]));
        return;
    }

    if(action == "DRAW_TEXT") {
        if(ArraySize(parts) < 6) return;
        DrawText(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), (color)StringToInteger(parts[4]), parts[5]);
        return;
    }

    if(action == "DRAW_TREND") {
        // DRAW_TREND|Name|Bar1|Price1|Bar2|Price2|Color|Width
        if(ArraySize(parts) < 8) return;
        DrawTrend(parts[1], (int)StringToInteger(parts[2]), StringToDouble(parts[3]), (int)StringToInteger(parts[4]), StringToDouble(parts[5]), (color)StringToInteger(parts[6]), (int)StringToInteger(parts[7]));
        return;
    }

    if(action == "DRAW_LINE") {
        // DRAW_LINE|Name|Price|Color|Style
        if(ArraySize(parts) < 5) return;
        DrawHLine(parts[1], StringToDouble(parts[2]), (color)StringToInteger(parts[3]), (int)StringToInteger(parts[4]));
        return;
    }
    // ------------------------

    if(action == "CLEAN_CHART") { ObjectsDeleteAll(0, "Py_"); return; }
    if(symbol != _Symbol && symbol != "" && action == "CHANGE_SYMBOL") { SymbolSelect(symbol, true); ChartSetSymbolPeriod(0, symbol, _Period); return; }
    
    double lot = (ArraySize(parts) >= 3) ? StringToDouble(parts[2]) : DefaultLot;
    double sl = (ArraySize(parts) >= 4) ? StringToDouble(parts[3]) : 0;
    double tp = (ArraySize(parts) >= 5) ? StringToDouble(parts[4]) : 0;
    double price = (ArraySize(parts) >= 6) ? StringToDouble(parts[5]) : 0;

    if(action == "BUY")             TradeMarket(symbol, ORDER_TYPE_BUY, lot, sl, tp);
    else if(action == "SELL")        TradeMarket(symbol, ORDER_TYPE_SELL, lot, sl, tp);
    else if(action == "BUY_LIMIT")   TradePending(symbol, ORDER_TYPE_BUY_LIMIT, lot, price, sl, tp);
    else if(action == "SELL_LIMIT")  TradePending(symbol, ORDER_TYPE_SELL_LIMIT, lot, price, sl, tp);
    else if(action == "CLOSE_ALL")   ClosePositions(symbol, "ALL");
    else if(action == "CLOSE_WIN")   ClosePositions(symbol, "WIN");
    else if(action == "CLOSE_LOSS")  ClosePositions(symbol, "LOSS");
}

// --- VISUAL FUNCTIONS ---
void DrawRect(string name, double p1, double p2, int b1, int b2, color c) {
    string n = "Py_" + name;
    if(ObjectFind(0, n) >= 0) ObjectDelete(0, n); 
    ObjectCreate(0, n, OBJ_RECTANGLE, 0, iTime(_Symbol, _Period, b1), p1, iTime(_Symbol, _Period, b2), p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c); ObjectSetInteger(0, n, OBJPROP_FILL, true); ObjectSetInteger(0, n, OBJPROP_BACK, true);
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
    // Update existing or new object
    ObjectSetInteger(0, n, OBJPROP_TIME, 0, iTime(_Symbol, _Period, b1));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 0, p1);
    ObjectSetInteger(0, n, OBJPROP_TIME, 1, iTime(_Symbol, _Period, b2));
    ObjectSetDouble(0, n, OBJPROP_PRICE, 1, p2);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_WIDTH, w);
    ObjectSetInteger(0, n, OBJPROP_RAY_RIGHT, false); 
}

void DrawHLine(string name, double price, color c, int style) {
    string n = "Py_Ln_" + name;
    if(ObjectFind(0, n) < 0) ObjectCreate(0, n, OBJ_HLINE, 0, 0, 0);
    ObjectSetDouble(0, n, OBJPROP_PRICE, price);
    ObjectSetInteger(0, n, OBJPROP_COLOR, c);
    ObjectSetInteger(0, n, OBJPROP_STYLE, style); 
}

void TradeMarket(string s, ENUM_ORDER_TYPE t, double v, double sl, double tp) {
    MqlTradeRequest r; MqlTradeResult res;
    ZeroMemory(r); ZeroMemory(res);
    r.action=TRADE_ACTION_DEAL; r.symbol=s; r.volume=v; r.type=t; r.price=(t==ORDER_TYPE_BUY)?SymbolInfoDouble(s,SYMBOL_ASK):SymbolInfoDouble(s,SYMBOL_BID); r.sl=sl; r.tp=tp; 
    if(!OrderSend(r, res)) Print("Trade Fail: ", res.retcode);
}
void TradePending(string s, ENUM_ORDER_TYPE t, double v, double p, double sl, double tp) {
    MqlTradeRequest r; MqlTradeResult res; ZeroMemory(r); ZeroMemory(res);
    r.action=TRADE_ACTION_PENDING; r.symbol=s; r.volume=v; r.type=t; r.price=p; r.sl=sl; r.tp=tp; 
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
            OrderSend(r, res);
        }
    }
}