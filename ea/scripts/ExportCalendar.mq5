//+------------------------------------------------------------------+
//| ExportCalendar.mq5                                                |
//| ส่งออกประวัติ Economic Calendar ของ MT5 เป็น CSV สำหรับ news filter  |
//| เวลาในไฟล์เป็นเวลา trade server                                     |
//|                                                                  |
//| ผลลัพธ์: MQL5/Files/AI-EA/calendar.csv + calendar.meta.json          |
//| ถ้าได้ 0 รายการ: เปิดแท็บ Calendar ใน Toolbox สักครั้งให้เทอร์มินัลโหลด  |
//+------------------------------------------------------------------+
#property copyright "AI-EA-forex"
#property version   "1.00"
#property script_show_inputs

input datetime InpFrom       = D'2015.01.01';  // From date
input string   InpCurrencies = "USD";          // Currencies (comma separated, empty = all)

string ImportanceName(const ENUM_CALENDAR_EVENT_IMPORTANCE importance)
  {
   switch(importance)
     {
      case CALENDAR_IMPORTANCE_HIGH:
         return "high";
      case CALENDAR_IMPORTANCE_MODERATE:
         return "moderate";
      case CALENDAR_IMPORTANCE_LOW:
         return "low";
      default:
         return "none";
     }
  }

string TimeModeName(const ENUM_CALENDAR_EVENT_TIMEMODE mode)
  {
   switch(mode)
     {
      case CALENDAR_TIMEMODE_DATETIME:
         return "datetime";
      case CALENDAR_TIMEMODE_DATE:
         return "date";
      case CALENDAR_TIMEMODE_NOTIME:
         return "notime";
      case CALENDAR_TIMEMODE_TENTATIVE:
         return "tentative";
      default:
         return "unknown";
     }
  }

string CsvQuote(string text)
  {
   StringReplace(text, "\"", "\"\"");
   return "\"" + text + "\"";
  }

// currency ว่าง = ทุกสกุล / ดึงทีละปีกันคำขอใหญ่เกิน
int ExportCurrency(const int fh, const string currency, datetime from, datetime to)
  {
   int written = 0;
   datetime chunkStart = from;
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

      MqlCalendarValue values[];
      ResetLastError();
      bool ok;
      if(currency == "")
         ok = CalendarValueHistory(values, chunkStart, chunkEnd - 1);
      else
         ok = CalendarValueHistory(values, chunkStart, chunkEnd - 1, NULL, currency);
      if(!ok)
         PrintFormat("CalendarValueHistory failed for '%s' from %s (error %d)",
                     currency, TimeToString(chunkStart, TIME_DATE), GetLastError());

      int n = ok ? ArraySize(values) : 0;
      for(int k = 0; k < n; k++)
        {
         MqlCalendarEvent event;
         if(!CalendarEventById(values[k].event_id, event))
            continue;
         MqlCalendarCountry country;
         string eventCurrency = CalendarCountryById(event.country_id, country) ? country.currency : "";
         FileWriteString(fh, StringFormat("%s,%s,%s,%s,%I64u,%s\n",
                         TimeToString(values[k].time, TIME_DATE | TIME_MINUTES),
                         eventCurrency,
                         ImportanceName(event.importance),
                         TimeModeName(event.time_mode),
                         event.id,
                         CsvQuote(event.name)));
         written++;
        }
      chunkStart = chunkEnd;
     }
   return written;
  }

void OnStart()
  {
   datetime to = TimeTradeServer();
   FolderCreate("AI-EA");
   int fh = FileOpen("AI-EA\\calendar.csv", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("Cannot open calendar.csv (error %d)", GetLastError());
      return;
     }
   FileWriteString(fh, "time_server,currency,importance,time_mode,event_id,name\n");

   int total = 0;
   string parts[];
   int count = StringSplit(InpCurrencies, ',', parts);
   if(count <= 0)
      total = ExportCurrency(fh, "", InpFrom, to);
   for(int i = 0; i < count; i++)
     {
      string cur = parts[i];
      StringTrimLeft(cur);
      StringTrimRight(cur);
      StringToUpper(cur);
      total += ExportCurrency(fh, cur, InpFrom, to);
     }
   FileClose(fh);

   int mh = FileOpen("AI-EA\\calendar.meta.json", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(mh != INVALID_HANDLE)
     {
      string json = "{\n";
      json += StringFormat("  \"server\": \"%s\",\n", AccountInfoString(ACCOUNT_SERVER));
      json += StringFormat("  \"server_gmt_offset_seconds\": %I64d,\n", (long)(TimeTradeServer() - TimeGMT()));
      json += StringFormat("  \"exported_at_server\": \"%s\",\n", TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS));
      json += StringFormat("  \"from\": \"%s\",\n", TimeToString(InpFrom, TIME_DATE));
      json += StringFormat("  \"currencies\": \"%s\",\n", InpCurrencies);
      json += StringFormat("  \"events\": %d\n", total);
      json += "}\n";
      FileWriteString(mh, json);
      FileClose(mh);
     }

   PrintFormat("Exported %d calendar values to MQL5/Files/AI-EA/calendar.csv", total);
   if(total == 0)
      Print("No events. Open the Calendar tab in Toolbox once so the terminal downloads it, then run again.");
  }
//+------------------------------------------------------------------+
