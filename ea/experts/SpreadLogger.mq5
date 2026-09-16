//+------------------------------------------------------------------+
//| SpreadLogger.mq5                                                  |
//| EA บันทึกสเปรดจริง — ไม่เปิดออเดอร์ใด ๆ                              |
//|                                                                  |
//| แปะบนกราฟ XAUUSDc แล้วเปิดทิ้งไว้หลายวัน (ให้ครอบวันที่มีข่าวแรง)       |
//| ทุก InpIntervalSec วินาที บันทึกสเปรดล่าสุด/ต่ำสุด/สูงสุดในช่วงนั้น      |
//| สเปรดสูงสุดคือค่าที่สำคัญ — จับช่วงข่าวที่สเปรดกางได้                     |
//|                                                                  |
//| ผลลัพธ์: MQL5/Files/AI-EA/<symbol>_spread_log.csv (เขียนต่อท้ายไฟล์)   |
//+------------------------------------------------------------------+
#property copyright "AI-EA-forex"
#property version   "1.00"

input int InpIntervalSec = 10;  // Sampling interval (seconds)

int    g_file        = INVALID_HANDLE;
double g_min_spread  = DBL_MAX;
double g_max_spread  = 0.0;
double g_last_spread = 0.0;
long   g_ticks       = 0;

int OnInit()
  {
   FolderCreate("AI-EA");
   string path = "AI-EA\\" + _Symbol + "_spread_log.csv";
   g_file = FileOpen(path, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
   if(g_file == INVALID_HANDLE)
     {
      PrintFormat("Cannot open %s (error %d)", path, GetLastError());
      return INIT_FAILED;
     }
   if(FileSize(g_file) == 0)
      FileWriteString(g_file, "time_server,spread_last,spread_min,spread_max,ticks\n");
   FileSeek(g_file, 0, SEEK_END);

   EventSetTimer(InpIntervalSec);
   PrintFormat("SpreadLogger started: %s every %d s", path, InpIntervalSec);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_file != INVALID_HANDLE)
      FileClose(g_file);
  }

void OnTick()
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.bid <= 0 || tick.ask <= 0)
      return;
   // คำนวณจาก bid/ask จริง ไม่ใช้ SYMBOL_SPREAD ซึ่งอาจเป็นค่าปัด
   double spread = tick.ask - tick.bid;
   g_last_spread = spread;
   if(spread < g_min_spread)
      g_min_spread = spread;
   if(spread > g_max_spread)
      g_max_spread = spread;
   g_ticks++;
  }

void OnTimer()
  {
   // ไม่มี tick ในช่วงนี้ (ตลาดปิด/พักรายวัน) → ไม่บันทึก
   if(g_ticks == 0)
      return;

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   FileWriteString(g_file, StringFormat("%s,%s,%s,%s,%I64d\n",
                   TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS),
                   DoubleToString(g_last_spread, digits),
                   DoubleToString(g_min_spread, digits),
                   DoubleToString(g_max_spread, digits),
                   g_ticks));
   FileFlush(g_file);

   g_min_spread = DBL_MAX;
   g_max_spread = 0.0;
   g_ticks = 0;
  }
//+------------------------------------------------------------------+
