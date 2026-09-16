//+------------------------------------------------------------------+
//| ExportBars.mq5                                                    |
//| ส่งออกแท่งราคา (OHLC + spread) ของกราฟปัจจุบันเป็น CSV              |
//| สำหรับ research ใน Python                                          |
//|                                                                  |
//| ผลลัพธ์: MQL5/Files/AI-EA/<symbol>_<tf>.csv + .meta.json           |
//| ก่อนรัน: Tools → Options → Charts → Max bars in chart = Unlimited  |
//+------------------------------------------------------------------+
#property copyright "AI-EA-forex"
#property version   "1.00"
#property script_show_inputs

input string   InpTimeframes = "M1,M5,H1,H4";  // Timeframes (comma separated)
input datetime InpFrom       = D'2015.01.01';  // From date
input datetime InpTo         = 0;              // To date (0 = now)

ENUM_TIMEFRAMES ParseTimeframe(string name)
  {
   StringTrimLeft(name);
   StringTrimRight(name);
   StringToUpper(name);
   if(name == "M1")  return PERIOD_M1;
   if(name == "M5")  return PERIOD_M5;
   if(name == "M15") return PERIOD_M15;
   if(name == "M30") return PERIOD_M30;
   if(name == "H1")  return PERIOD_H1;
   if(name == "H4")  return PERIOD_H4;
   if(name == "D1")  return PERIOD_D1;
   return PERIOD_CURRENT;
  }

// เทอร์มินัลอาจกำลังดาวน์โหลด history จากเซิร์ฟเวอร์ → ลองซ้ำ
int CopyRatesWithRetry(const string symbol, ENUM_TIMEFRAMES tf,
                       datetime from, datetime to, MqlRates &rates[])
  {
   for(int attempt = 0; attempt < 5; attempt++)
     {
      ResetLastError();
      int n = CopyRates(symbol, tf, from, to, rates);
      if(n >= 0)
         return n;
      Sleep(1000);
     }
   return -1;
  }

bool ExportTimeframe(const string symbol, ENUM_TIMEFRAMES tf, const string tfName,
                     datetime from, datetime to)
  {
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   string base = "AI-EA\\" + symbol + "_" + tfName;

   // เริ่มจากวันแรกที่เซิร์ฟเวอร์มีข้อมูลจริง ไม่ต้องไล่ปีที่ว่างเปล่า
   datetime serverFirst = (datetime)SeriesInfoInteger(symbol, tf, SERIES_SERVER_FIRSTDATE);
   datetime start = (serverFirst > from) ? serverFirst : from;

   int fh = FileOpen(base + ".csv", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("Cannot open %s.csv (error %d)", base, GetLastError());
      return false;
     }
   FileWriteString(fh, "time,open,high,low,close,tick_volume,spread,real_volume\n");

   long     total = 0;
   datetime first = 0;
   datetime last  = 0;
   datetime chunkStart = start;

   // แบ่งทีละปี กันอาร์เรย์ M1 ใหญ่เกินหน่วยความจำ
   while(chunkStart < to)
     {
      MqlDateTime dt;
      TimeToStruct(chunkStart, dt);
      dt.year += 1;
      dt.mon = 1;
      dt.day = 1;
      dt.hour = 0;
      dt.min = 0;
      dt.sec = 0;
      datetime chunkEnd = StructToTime(dt);
      if(chunkEnd > to)
         chunkEnd = to;

      MqlRates rates[];
      int n = CopyRatesWithRetry(symbol, tf, chunkStart, chunkEnd - 1, rates);
      if(n < 0)
         PrintFormat("CopyRates failed %s %s from %s (error %d)",
                     symbol, tfName, TimeToString(chunkStart), GetLastError());

      for(int k = 0; k < n; k++)
        {
         FileWriteString(fh, StringFormat("%s,%s,%s,%s,%s,%I64d,%d,%I64d\n",
                         TimeToString(rates[k].time, TIME_DATE | TIME_MINUTES),
                         DoubleToString(rates[k].open, digits),
                         DoubleToString(rates[k].high, digits),
                         DoubleToString(rates[k].low, digits),
                         DoubleToString(rates[k].close, digits),
                         rates[k].tick_volume,
                         rates[k].spread,
                         rates[k].real_volume));
         if(first == 0)
            first = rates[k].time;
         last = rates[k].time;
        }
      if(n > 0)
         total += n;
      chunkStart = chunkEnd;
     }
   FileClose(fh);

   string priceSide = (SymbolInfoInteger(symbol, SYMBOL_CHART_MODE) == SYMBOL_CHART_MODE_BID) ? "bid" : "last";

   int mh = FileOpen(base + ".meta.json", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(mh != INVALID_HANDLE)
     {
      string json = "{\n";
      json += StringFormat("  \"symbol\": \"%s\",\n", symbol);
      json += StringFormat("  \"timeframe\": \"%s\",\n", tfName);
      json += StringFormat("  \"digits\": %d,\n", digits);
      json += StringFormat("  \"point\": %s,\n", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_POINT), digits));
      json += StringFormat("  \"contract_size\": %s,\n", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE), 4));
      json += StringFormat("  \"price_side\": \"%s\",\n", priceSide);
      json += StringFormat("  \"server\": \"%s\",\n", AccountInfoString(ACCOUNT_SERVER));
      json += StringFormat("  \"server_gmt_offset_seconds\": %I64d,\n", (long)(TimeTradeServer() - TimeGMT()));
      json += StringFormat("  \"exported_at_server\": \"%s\",\n", TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS));
      json += StringFormat("  \"server_first_date\": \"%s\",\n", TimeToString(serverFirst, TIME_DATE | TIME_MINUTES));
      json += StringFormat("  \"terminal_maxbars\": %I64d,\n", (long)TerminalInfoInteger(TERMINAL_MAXBARS));
      json += StringFormat("  \"bars\": %I64d,\n", total);
      json += StringFormat("  \"first_bar\": \"%s\",\n", TimeToString(first, TIME_DATE | TIME_MINUTES));
      json += StringFormat("  \"last_bar\": \"%s\"\n", TimeToString(last, TIME_DATE | TIME_MINUTES));
      json += "}\n";
      FileWriteString(mh, json);
      FileClose(mh);
     }

   PrintFormat("%s %s: %I64d bars (%s -> %s)", symbol, tfName, total,
               TimeToString(first, TIME_DATE), TimeToString(last, TIME_DATE));
   return true;
  }

void OnStart()
  {
   string symbol = _Symbol;
   datetime to = (InpTo == 0) ? TimeTradeServer() : InpTo;
   FolderCreate("AI-EA");

   long maxBars = TerminalInfoInteger(TERMINAL_MAXBARS);
   if(maxBars < 10000000)
      PrintFormat("WARNING: Max bars in chart = %I64d. Set it to Unlimited for full history.", maxBars);

   string parts[];
   int count = StringSplit(InpTimeframes, ',', parts);
   for(int i = 0; i < count; i++)
     {
      string name = parts[i];
      StringTrimLeft(name);
      StringTrimRight(name);
      StringToUpper(name);
      ENUM_TIMEFRAMES tf = ParseTimeframe(name);
      if(tf == PERIOD_CURRENT)
        {
         PrintFormat("Skipping unknown timeframe: %s", name);
         continue;
        }
      ExportTimeframe(symbol, tf, name, InpFrom, to);
     }
   Print("Done. Files are in MQL5/Files/AI-EA/");
  }
//+------------------------------------------------------------------+
