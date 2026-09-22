//+------------------------------------------------------------------+
//| ForwardTestEA.mq5                                                 |
//| EA สำหรับ forward test บน demo ตาม journal/FORWARD-TEST-PLAN.md    |
//|                                                                  |
//| รองรับ 3 ค่าตั้งที่ผ่านการ backtest มาแล้ว:                          |
//|   1) Pullback  — กราฟ M5  / เทรนด์ M15                             |
//|   2) Pullback  — กราฟ M1  / เทรนด์ M15                             |
//|   3) FVG       — กราฟ M15 / เทรนด์ H1                              |
//|                                                                  |
//| กฎทั้งหมดตรงกับโค้ด Python ใน research/strategies/                  |
//| ห้ามแก้กฎหรือค่าพารามิเตอร์ระหว่างการทดสอบ (ดูแผน)                    |
//+------------------------------------------------------------------+
#property copyright "AI-EA-forex"
#property version   "1.00"

#include <Trade\Trade.mqh>

enum StrategyMode
  {
   STRATEGY_PULLBACK = 0,  // Pullback: ปิดทะลุโครงสร้าง แล้วรอ retest
   STRATEGY_FVG      = 1   // FVG: ช่องว่าง 3 แท่ง แล้วรอราคากลับมาเติม
  };

input group           "กลยุทธ์"
input StrategyMode    InpStrategy        = STRATEGY_PULLBACK;
input ENUM_TIMEFRAMES InpBiasTF          = PERIOD_M15;  // timeframe ที่ใช้ดูเทรนด์
input int             InpSwingLenBias    = 5;
input int             InpSwingLenEntry   = 3;
input int             InpOrderExpiryBars = 36;
input double          InpSlBufferAtr     = 0.1;
input double          InpTp1MaxR         = 2.0;
input double          InpMinRoomR        = 1.0;
input double          InpMinSlDistance   = 3.0;   // ระยะ SL ขั้นต่ำ (หน่วยราคา)
input int             InpAtrPeriod       = 14;

input group           "ตัวกรอง"
input int             InpSessionStartHour = 7;    // เวลา server (Exness = UTC)
input int             InpSessionEndHour   = 16;
input bool            InpUseNewsFilter    = true; // ปิดเมื่อรันใน Strategy Tester (อ่านปฏิทินไม่ได้)
input int             InpNewsBeforeMin    = 30;
input int             InpNewsAfterMin     = 30;

input group           "ความเสี่ยง"
input double          InpRiskPct           = 1.0;
input double          InpDailyLossLimitPct = 3.0;

input group           "ระบบ"
input int             InpLookbackEntry = 1500;
input int             InpLookbackBias  = 100000;  // ต้องยาวพอให้เห็นโซนเก่าเหมือน backtest (parity 2026-09-21)
input long            InpMagic         = 260921;
input bool            InpLogSignals    = true;

CTrade   g_trade;
int      g_atr_handle = INVALID_HANDLE;
datetime g_last_bar   = 0;
int      g_log        = INVALID_HANDLE;

// สถานะของคำสั่งรอชุดปัจจุบัน (หนึ่ง setup = คำสั่งรอสูงสุด 2 ไม้ ราคาเดียวกัน TP ต่างกัน)
ulong    g_tickets[2];
int      g_ticket_count = 0;
int      g_pending_dir  = 0;
double   g_pending_entry = 0.0;
double   g_pending_tp1   = 0.0;
double   g_pending_cancel = 0.0;
datetime g_pending_since = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);

   g_atr_handle = iATR(_Symbol, _Period, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE)
     {
      Print("cannot create ATR handle");
      return INIT_FAILED;
     }

   if(InpLogSignals)
     {
      FolderCreate("AI-EA");
      string path = StringFormat("AI-EA\\forward_signals_%I64d.csv", InpMagic);
      g_log = FileOpen(path, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
      if(g_log != INVALID_HANDLE)
        {
         if(FileSize(g_log) == 0)
            FileWriteString(g_log, "time_server,strategy,side,entry,sl,tp1,tp2,lots_tp1,lots_tp2,outcome\n");
         FileSeek(g_log, 0, SEEK_END);
        }
     }

   // เริ่มต้นสะอาด: ถ้ามีคำสั่งรอค้างจากรอบก่อนแต่ไม่มีบริบท ให้ยกเลิก
   CancelOrphanOrders();
   PrintFormat("ForwardTestEA started: strategy=%s chart=%s bias=%s magic=%I64d",
               (InpStrategy == STRATEGY_PULLBACK ? "pullback" : "fvg"),
               EnumToString((ENUM_TIMEFRAMES)_Period), EnumToString(InpBiasTF), InpMagic);
   // พิมพ์ค่าตั้งที่ตรวจจากระยะไกลได้ — Strategy Tester และหน้าต่าง EA จำค่า input เก่าไว้ได้
   PrintFormat("ForwardTestEA settings: lookback_bias=%d lookback_entry=%d news_filter=%s risk=%.2f%% daily_limit=%.2f%% "
               "session=%02d-%02d expiry=%d symbol=%s contract=%.2f vol_min=%.2f balance=%.2f %s",
               InpLookbackBias, InpLookbackEntry, (InpUseNewsFilter ? "on" : "off"), InpRiskPct, InpDailyLossLimitPct,
               InpSessionStartHour, InpSessionEndHour, InpOrderExpiryBars, _Symbol,
               SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE), SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
               AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoString(ACCOUNT_CURRENCY));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_log != INVALID_HANDLE)
      FileClose(g_log);
   if(g_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_atr_handle);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   datetime current = iTime(_Symbol, _Period, 0);
   if(current == g_last_bar)
      return;          // ทำงานครั้งเดียวต่อแท่ง ใช้เฉพาะแท่งที่ปิดแล้ว
   g_last_bar = current;

   RefreshPendingState();

   if(g_ticket_count > 0)
     {
      ManagePending();
      return;
     }
   if(HasOpenPosition())
      return;
   // ช่วงเวลาเทรดเช็คจากเวลาของแท่ง signal (แท่งที่เพิ่งปิด) ให้ตรงกับ backtest
   if(!InSession(iTime(_Symbol, _Period, 1)) || (InpUseNewsFilter && InNewsWindow()) || DailyLossReached())
      return;

   TryNewSetup();
  }

//+------------------------------------------------------------------+
//| โครงสร้างตลาด                                                     |
//+------------------------------------------------------------------+
struct StructureState
  {
   int    trend;
   bool   is_break;
   double level;
   double swing_high;
   double swing_low;
  };

bool IsSwingHigh(const MqlRates &r[], const int i, const int len)
  {
   for(int k = 1; k <= len; k++)
      if(r[i].high <= r[i - k].high || r[i].high <= r[i + k].high)
         return false;
   return true;
  }

bool IsSwingLow(const MqlRates &r[], const int i, const int len)
  {
   for(int k = 1; k <= len; k++)
      if(r[i].low >= r[i - k].low || r[i].low >= r[i + k].low)
         return false;
   return true;
  }

// เดินจากอดีตมาปัจจุบัน — swing ถูก "ยืนยัน" หลังผ่านไป len แท่ง เหมือนฝั่ง Python
StructureState ScanStructure(const MqlRates &r[], const int len)
  {
   StructureState out;
   out.trend = 0;
   out.is_break = false;
   out.level = EMPTY_VALUE;
   out.swing_high = EMPTY_VALUE;
   out.swing_low = EMPTY_VALUE;

   int n = ArraySize(r);
   double sh = EMPTY_VALUE, sl = EMPTY_VALUE;
   int sh_bar = -1, sl_bar = -1, broken_high = -1, broken_low = -1;

   for(int i = 0; i < n; i++)
     {
      int pivot = i - len;
      if(pivot >= len && pivot + len < n)
        {
         if(IsSwingHigh(r, pivot, len))
           {
            sh = r[pivot].high;
            sh_bar = pivot;
           }
         if(IsSwingLow(r, pivot, len))
           {
            sl = r[pivot].low;
            sl_bar = pivot;
           }
        }
      bool is_break = false;
      double level = EMPTY_VALUE;
      if(sh != EMPTY_VALUE && r[i].close > sh && sh_bar != broken_high)
        {
         is_break = true;
         level = sh;
         broken_high = sh_bar;
         out.trend = 1;
        }
      else
         if(sl != EMPTY_VALUE && r[i].close < sl && sl_bar != broken_low)
           {
            is_break = true;
            level = sl;
            broken_low = sl_bar;
            out.trend = -1;
           }
      if(i == n - 1)
        {
         out.is_break = is_break;
         out.level = level;
         out.swing_high = sh;
         out.swing_low = sl;
        }
     }
   return out;
  }

// swing ของ timeframe เทรนด์ ที่ใกล้ที่สุดและอยู่เลย level ไปทางเดียวกับไม้
double NearestZone(const MqlRates &r[], const int len, const double level, const int direction)
  {
   double best = EMPTY_VALUE;
   int n = ArraySize(r);
   for(int p = len; p + len < n; p++)
     {
      if(direction > 0 && IsSwingHigh(r, p, len) && r[p].high > level)
         best = (best == EMPTY_VALUE ? r[p].high : MathMin(best, r[p].high));
      if(direction < 0 && IsSwingLow(r, p, len) && r[p].low < level)
         best = (best == EMPTY_VALUE ? r[p].low : MathMax(best, r[p].low));
     }
   return best;
  }

int LoadClosedBars(const ENUM_TIMEFRAMES tf, const int count, MqlRates &rates[])
  {
   ArraySetAsSeries(rates, false);
   return CopyRates(_Symbol, tf, 1, count, rates);   // เริ่มที่ 1 = ข้ามแท่งที่ยังไม่ปิด
  }

//+------------------------------------------------------------------+
//| สร้าง setup                                                       |
//+------------------------------------------------------------------+
bool BuildSetup(int &dir, double &entry, double &sl, double &tp1, double &tp2, double &cancel_price, string &outcome)
  {
   MqlRates entry_bars[], bias_bars[];
   int n = LoadClosedBars(_Period, InpLookbackEntry, entry_bars);
   if(n < InpSwingLenEntry * 2 + 10)
     {
      outcome = "no_data";
      return false;
     }

   double atr_buffer[];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr_buffer) != 1 || atr_buffer[0] <= 0)
     {
      outcome = "atr_not_ready";
      return false;
     }
   double atr = atr_buffer[0];
   double buffer = InpSlBufferAtr * atr;

   double origin = EMPTY_VALUE;
   int last = n - 1;

   if(InpStrategy == STRATEGY_PULLBACK)
     {
      StructureState st = ScanStructure(entry_bars, InpSwingLenEntry);
      if(!st.is_break)
        {
         outcome = "";
         return false;
        }
      dir = st.trend;
      entry = st.level;
      origin = (dir > 0 ? st.swing_low : st.swing_high);
      if(origin == EMPTY_VALUE)
        {
         outcome = "no_structure";
         return false;
        }
     }
   else
     {
      double h2 = entry_bars[last - 2].high, l2 = entry_bars[last - 2].low;
      bool bullish_gap = entry_bars[last].low > h2 && entry_bars[last - 1].close > entry_bars[last - 1].open;
      bool bearish_gap = entry_bars[last].high < l2 && entry_bars[last - 1].close < entry_bars[last - 1].open;
      if(!bullish_gap && !bearish_gap)
        {
         outcome = "";
         return false;
        }
      dir = (bullish_gap ? 1 : -1);
      entry = (bullish_gap ? entry_bars[last].low : entry_bars[last].high);
      origin = (bullish_gap ? MathMin(l2, entry_bars[last - 1].low) : MathMax(h2, entry_bars[last - 1].high));
      cancel_price = (bullish_gap ? h2 : l2);
     }

   // โหลดข้อมูล timeframe เทรนด์เฉพาะตอนเจอ setup — ย้อนหลังยาวมาก โหลดทุกแท่งจะช้า
   int m = LoadClosedBars(InpBiasTF, InpLookbackBias, bias_bars);
   if(m < InpSwingLenBias * 2 + 10)
     {
      outcome = "no_data";
      return false;
     }
   StructureState bias = ScanStructure(bias_bars, InpSwingLenBias);
   if(bias.trend != dir)
     {
      outcome = "against_bias";
      return false;
     }

   sl = origin - dir * buffer;
   double risk = (entry - sl) * dir;
   if(risk <= 0)
     {
      outcome = "sl_on_wrong_side";
      return false;
     }
   if((entry_bars[last].close - entry) * dir <= 0)
     {
      outcome = "price_inside_zone";
      return false;
     }
   if(risk < InpMinSlDistance)
     {
      outcome = "sl_too_tight";
      return false;
     }

   double zone = NearestZone(bias_bars, InpSwingLenBias, entry, dir);
   double cap = entry + dir * InpTp1MaxR * risk;
   if(zone != EMPTY_VALUE)
     {
      double before_zone = zone - dir * buffer;
      if((before_zone - entry) * dir < InpMinRoomR * risk)
        {
         outcome = "no_room";
         return false;
        }
      tp1 = (dir > 0 ? MathMin(before_zone, cap) : MathMax(before_zone, cap));
     }
   else
      tp1 = cap;

   tp2 = entry + 2.0 * (tp1 - entry);
   if(InpStrategy == STRATEGY_PULLBACK)
      cancel_price = origin;
   outcome = "signal";
   return true;
  }

//+------------------------------------------------------------------+
//| ขนาดไม้จากความเสี่ยง — ปัดลงเสมอ                                    |
//+------------------------------------------------------------------+
double LotsForRisk(const double entry, const double sl)
  {
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step       = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tick_value <= 0 || tick_size <= 0)
      return 0.0;

   double loss_per_lot = MathAbs(entry - sl) / tick_size * tick_value;
   if(loss_per_lot <= 0)
      return 0.0;
   double risk_money = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
   double lots = MathFloor(risk_money / loss_per_lot / step + 1e-9) * step;
   lots = MathMin(lots, max_lot);
   if(lots < min_lot - 1e-12)
      return 0.0;
   return NormalizeDouble(lots, 2);
  }

//+------------------------------------------------------------------+
void TryNewSetup()
  {
   int dir = 0;
   double entry = 0, sl = 0, tp1 = 0, tp2 = 0, cancel_price = 0;
   string outcome = "";
   if(!BuildSetup(dir, entry, sl, tp1, tp2, cancel_price, outcome))
     {
      if(outcome != "")
         LogSignal(dir, entry, sl, tp1, tp2, 0, 0, outcome);
      return;
     }

   double total = LotsForRisk(entry, sl);
   if(total <= 0)
     {
      LogSignal(dir, entry, sl, tp1, tp2, 0, 0, "below_min_lot");
      return;
     }

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double first = MathFloor(total / 2.0 / step + 1e-9) * step;
   double rest = NormalizeDouble(total - first, 2);
   bool split = (first >= min_lot - 1e-12 && rest >= min_lot - 1e-12);

   ENUM_ORDER_TYPE type = (dir > 0 ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   entry = NormalizeDouble(entry, digits);
   sl = NormalizeDouble(sl, digits);
   tp1 = NormalizeDouble(tp1, digits);
   tp2 = NormalizeDouble(tp2, digits);

   g_ticket_count = 0;
   if(split)
     {
      if(PlaceLimit(type, first, entry, sl, tp1, "tp1"))
         g_tickets[g_ticket_count++] = g_trade.ResultOrder();
      if(PlaceLimit(type, rest, entry, sl, tp2, "tp2"))
         g_tickets[g_ticket_count++] = g_trade.ResultOrder();
     }
   else
     {
      if(PlaceLimit(type, total, entry, sl, tp1, "single"))
         g_tickets[g_ticket_count++] = g_trade.ResultOrder();
     }

   if(g_ticket_count == 0)
     {
      LogSignal(dir, entry, sl, tp1, tp2, 0, 0, "order_failed");
      return;
     }
   g_pending_dir = dir;
   g_pending_entry = entry;
   g_pending_tp1 = tp1;
   g_pending_cancel = cancel_price;
   g_pending_since = TimeTradeServer();
   LogSignal(dir, entry, sl, tp1, tp2, (split ? first : total), (split ? rest : 0), split ? "signal" : "signal_no_split");
  }

bool PlaceLimit(const ENUM_ORDER_TYPE type, const double volume, const double price,
                const double sl, const double tp, const string tag)
  {
   if(!g_trade.OrderOpen(_Symbol, type, volume, 0.0, price, sl, tp, ORDER_TIME_GTC, 0,
                         StringFormat("%s-%s", (InpStrategy == STRATEGY_PULLBACK ? "pb" : "fvg"), tag)))
     {
      PrintFormat("OrderOpen failed: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| ดูแลคำสั่งรอ                                                       |
//+------------------------------------------------------------------+
void RefreshPendingState()
  {
   int alive = 0;
   for(int i = 0; i < g_ticket_count; i++)
      if(OrderSelect(g_tickets[i]))
         g_tickets[alive++] = g_tickets[i];
   g_ticket_count = alive;
   if(g_ticket_count == 0)
      g_pending_dir = 0;
  }

void ManagePending()
  {
   string reason = "";
   // นับเป็นจำนวนแท่ง ไม่ใช่เวลา (ข้ามวันหยุดแล้วไม่เพี้ยน) — ครบ N แท่งแล้วยกเลิกก่อนแท่งที่ N+1 เหมือน backtest
   int elapsed = iBarShift(_Symbol, _Period, g_pending_since);
   double close_price = iClose(_Symbol, _Period, 1);
   double high_price = iHigh(_Symbol, _Period, 1);
   double low_price = iLow(_Symbol, _Period, 1);

   if(elapsed >= InpOrderExpiryBars)
      reason = "order_expired";
   else
      if(InpUseNewsFilter && InNewsWindow())
         reason = "news_blackout";
      else
         if((g_pending_dir > 0 && high_price >= g_pending_tp1) || (g_pending_dir < 0 && low_price <= g_pending_tp1))
            reason = "missed_move";
         else
            if((g_pending_dir > 0 && close_price < g_pending_cancel) || (g_pending_dir < 0 && close_price > g_pending_cancel))
               reason = "order_invalidated";

   if(reason == "")
      return;
   for(int i = 0; i < g_ticket_count; i++)
      g_trade.OrderDelete(g_tickets[i]);
   LogSignal(g_pending_dir, g_pending_entry, 0, g_pending_tp1, 0, 0, 0, reason);
   g_ticket_count = 0;
   g_pending_dir = 0;
  }

void CancelOrphanOrders()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      if(OrderGetInteger(ORDER_MAGIC) == InpMagic && OrderGetString(ORDER_SYMBOL) == _Symbol)
        {
         g_trade.OrderDelete(ticket);
         PrintFormat("deleted orphan order %I64u", ticket);
        }
     }
  }

bool HasOpenPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
         return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| ตัวกรอง                                                           |
//+------------------------------------------------------------------+
bool InSession(const datetime bar_time)
  {
   MqlDateTime t;
   TimeToStruct(bar_time, t);
   return t.hour >= InpSessionStartHour && t.hour < InpSessionEndHour;
  }

bool InNewsWindow()
  {
   datetime now = TimeTradeServer();
   MqlCalendarValue values[];
   if(!CalendarValueHistory(values, now - InpNewsAfterMin * 60, now + InpNewsBeforeMin * 60, NULL, "USD"))
      return false;
   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id, event))
         continue;
      if(event.importance != CALENDAR_IMPORTANCE_HIGH || event.time_mode != CALENDAR_TIMEMODE_DATETIME)
         continue;
      if(values[i].time >= now - InpNewsAfterMin * 60 && values[i].time <= now + InpNewsBeforeMin * 60)
         return true;
     }
   return false;
  }

bool DailyLossReached()
  {
   if(InpDailyLossLimitPct <= 0)
      return false;
   MqlDateTime now;
   TimeToStruct(TimeTradeServer(), now);
   now.hour = 0;
   now.min = 0;
   now.sec = 0;
   datetime day_start = StructToTime(now);
   if(!HistorySelect(day_start, TimeTradeServer()))
      return false;

   double realized = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0 || HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      realized += HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP)
                  + HistoryDealGetDouble(deal, DEAL_COMMISSION);
     }
   if(realized >= 0)
      return false;
   double day_start_balance = AccountInfoDouble(ACCOUNT_BALANCE) - realized;
   return realized <= -day_start_balance * InpDailyLossLimitPct / 100.0;
  }

//+------------------------------------------------------------------+
void LogSignal(const int dir, const double entry, const double sl, const double tp1, const double tp2,
               const double lots1, const double lots2, const string outcome)
  {
   if(g_log == INVALID_HANDLE)
      return;
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   FileWriteString(g_log, StringFormat("%s,%s,%d,%s,%s,%s,%s,%s,%s,%s\n",
                   TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS),
                   (InpStrategy == STRATEGY_PULLBACK ? "pullback" : "fvg"),
                   dir,
                   DoubleToString(entry, digits), DoubleToString(sl, digits),
                   DoubleToString(tp1, digits), DoubleToString(tp2, digits),
                   DoubleToString(lots1, 2), DoubleToString(lots2, 2), outcome));
   FileFlush(g_log);
  }
//+------------------------------------------------------------------+
