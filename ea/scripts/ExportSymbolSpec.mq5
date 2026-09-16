//+------------------------------------------------------------------+
//| ExportSymbolSpec.mq5                                              |
//| บันทึกสเปก symbol ของกราฟปัจจุบันเป็น JSON                          |
//| ผลลัพธ์: MQL5/Files/AI-EA/<symbol>_spec.json                        |
//+------------------------------------------------------------------+
#property copyright "AI-EA-forex"
#property version   "1.00"

string JStr(const string key, const string value)
  {
   return StringFormat("  \"%s\": \"%s\",\n", key, value);
  }

string JInt(const string key, const long value)
  {
   return StringFormat("  \"%s\": %I64d,\n", key, value);
  }

string JDbl(const string key, const double value, const int digits)
  {
   return StringFormat("  \"%s\": %s,\n", key, DoubleToString(value, digits));
  }

// ช่วงเวลาเทรดแต่ละวัน เป็นนาทีนับจาก 00:00 server เช่น [0, 1258] = 00:00-20:58
string SessionsJson(const string symbol)
  {
   string days[7] = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"};
   string out = "  \"sessions_trade_minutes\": {\n";
   for(int d = 0; d < 7; d++)
     {
      string ranges = "";
      datetime from = 0;
      datetime to = 0;
      for(uint k = 0; SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)d, k, from, to); k++)
        {
         if(k > 0)
            ranges += ", ";
         ranges += StringFormat("[%I64d, %I64d]", (long)from / 60, (long)to / 60);
        }
      out += StringFormat("    \"%s\": [%s]%s\n", days[d], ranges, (d < 6 ? "," : ""));
     }
   out += "  }\n";
   return out;
  }

void OnStart()
  {
   string s = _Symbol;
   int digits = (int)SymbolInfoInteger(s, SYMBOL_DIGITS);

   string j = "{\n";
   j += JStr("symbol", s);
   j += JStr("description", SymbolInfoString(s, SYMBOL_DESCRIPTION));
   j += JStr("account_server", AccountInfoString(ACCOUNT_SERVER));
   j += JStr("account_currency", AccountInfoString(ACCOUNT_CURRENCY));
   j += JInt("account_leverage", AccountInfoInteger(ACCOUNT_LEVERAGE));
   j += JStr("currency_profit", SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT));
   j += JStr("currency_margin", SymbolInfoString(s, SYMBOL_CURRENCY_MARGIN));
   j += JInt("digits", digits);
   j += JDbl("point", SymbolInfoDouble(s, SYMBOL_POINT), digits);
   j += JDbl("contract_size", SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE), 4);
   j += JDbl("tick_size", SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE), digits);
   j += JDbl("tick_value", SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE), 8);
   j += JDbl("volume_min", SymbolInfoDouble(s, SYMBOL_VOLUME_MIN), 4);
   j += JDbl("volume_max", SymbolInfoDouble(s, SYMBOL_VOLUME_MAX), 4);
   j += JDbl("volume_step", SymbolInfoDouble(s, SYMBOL_VOLUME_STEP), 4);
   j += JInt("stops_level_points", SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL));
   j += JInt("freeze_level_points", SymbolInfoInteger(s, SYMBOL_TRADE_FREEZE_LEVEL));
   j += JInt("spread_current_points", SymbolInfoInteger(s, SYMBOL_SPREAD));
   j += JInt("spread_float", SymbolInfoInteger(s, SYMBOL_SPREAD_FLOAT));
   j += JInt("swap_mode", SymbolInfoInteger(s, SYMBOL_SWAP_MODE));
   j += JDbl("swap_long", SymbolInfoDouble(s, SYMBOL_SWAP_LONG), 4);
   j += JDbl("swap_short", SymbolInfoDouble(s, SYMBOL_SWAP_SHORT), 4);
   j += JInt("swap_rollover3days", SymbolInfoInteger(s, SYMBOL_SWAP_ROLLOVER3DAYS));
   j += JInt("trade_calc_mode", SymbolInfoInteger(s, SYMBOL_TRADE_CALC_MODE));
   j += JInt("trade_exe_mode", SymbolInfoInteger(s, SYMBOL_TRADE_EXEMODE));
   j += JInt("filling_mode_flags", SymbolInfoInteger(s, SYMBOL_FILLING_MODE));
   j += JInt("chart_mode", SymbolInfoInteger(s, SYMBOL_CHART_MODE));
   j += JInt("server_gmt_offset_seconds", (long)(TimeTradeServer() - TimeGMT()));
   j += JStr("exported_at_server", TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS));
   j += SessionsJson(s);
   j += "}\n";

   FolderCreate("AI-EA");
   string path = "AI-EA\\" + s + "_spec.json";
   int fh = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("Cannot open %s (error %d)", path, GetLastError());
      return;
     }
   FileWriteString(fh, j);
   FileClose(fh);
   PrintFormat("Saved MQL5/Files/%s", path);
  }
//+------------------------------------------------------------------+
