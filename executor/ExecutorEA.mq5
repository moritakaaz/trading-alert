//+------------------------------------------------------------------+
//| ExecutorEA.mq5                                                   |
//| Dumb order executor for the XAUUSD Telegram alert bot (v2.7).    |
//|                                                                  |
//| The strategy lives OUTSIDE MT5 (the Python alert bot). This EA   |
//| contains NO signal logic. It only:                               |
//|   1. Polls a signal queue file (written by bridge.py into the    |
//|      terminal Common Files folder).                              |
//|   2. For each new signal id, opens ONE market order on the chart |
//|      symbol with SL/TP recomputed from the ACTUAL fill price     |
//|      using the distances (in USD) carried by the signal.         |
//|   3. Marks the id as processed (never executes the same signal   |
//|      twice, even across restarts) and appends a result line.     |
//|                                                                  |
//| Queue file format (CSV, one signal per line, header first):      |
//|   id,signal,sl_d,tp1_d,tp2_d,tp3_d                              |
//| Example:                                                         |
//|   2026-10-30T03:05:00Z-SELL,SELL,19,19,29,39                     |
//|                                                                  |
//| TP model: at the broker minimum lot (0.01) a position cannot be  |
//| split, so the order takes profit in full at TP1 distance (1R).   |
//| This matches the journal scoring model (TP1 = +1R). TP2/TP3      |
//| distances are carried in the file for future use and ignored.    |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Dumb executor for the XAUUSD Telegram alert bot. No signal logic."

#include <Trade\Trade.mqh>

input double InpLotSize         = 0.01;    // Lot size (fixed)
input int    InpMaxOpenExecutor = 3;       // Max open positions opened by this EA
input double InpMaxSpreadUSD    = 0.60;    // Skip signal if spread (ask-bid) above this, in price units
input int    InpDeviationPoints = 50;      // Max slippage, points
input long   InpMagic           = 270101;  // Magic number
input int    InpPollSeconds     = 2;       // Queue poll interval, seconds
input string InpSignalFile      = "executor_signals.csv";    // Queue file (Common Files)
input string InpProcessedFile   = "executor_processed.csv";  // Processed ids (Common Files)
input string InpResultsFile     = "executor_results.csv";    // Execution results (Common Files)

CTrade trade;

string g_processed[];   // in-memory list of processed signal ids

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
bool IsProcessed(const string id)
{
   for(int i = 0; i < ArraySize(g_processed); i++)
      if(g_processed[i] == id)
         return true;
   return false;
}

void RememberProcessed(const string id)
{
   int n = ArraySize(g_processed);
   ArrayResize(g_processed, n + 1);
   g_processed[n] = id;
}

void AppendLine(const string filename, const string line)
{
   int h = FileOpen(filename, FILE_READ | FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      Print("ExecutorEA: cannot open ", filename, " err=", GetLastError());
      return;
   }
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
}

void MarkProcessed(const string id)
{
   RememberProcessed(id);
   AppendLine(InpProcessedFile, id);
}

void LoadProcessed()
{
   ArrayResize(g_processed, 0);
   if(!FileIsExist(InpProcessedFile, 1))   // 1 = common files flag for FileIsExist
      return;
   int h = FileOpen(InpProcessedFile, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) > 0)
         RememberProcessed(line);
   }
   FileClose(h);
   Print("ExecutorEA: loaded ", ArraySize(g_processed), " processed signal ids");
}

int CountExecutorPositions()
{
   int cnt = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         cnt++;
   }
   return cnt;
}

//+------------------------------------------------------------------+
//| Execute one signal                                               |
//+------------------------------------------------------------------+
void ExecuteSignal(const string id, const string signal,
                   const double sl_d, const double tp1_d)
{
   string ts = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS);

   if(signal != "BUY" && signal != "SELL")
   {
      AppendLine(InpResultsFile, ts + "," + id + ",0,0,0,0,SKIP-unknown-signal");
      return;
   }
   if(sl_d <= 0.0 || tp1_d <= 0.0)
   {
      AppendLine(InpResultsFile, ts + "," + id + ",0,0,0,0,SKIP-bad-distances");
      return;
   }
   if(CountExecutorPositions() >= InpMaxOpenExecutor)
   {
      AppendLine(InpResultsFile, ts + "," + id + ",0,0,0,0,SKIP-max-positions");
      return;
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
   {
      AppendLine(InpResultsFile, ts + "," + id + ",0,0,0,0,SKIP-no-tick");
      return;
   }
   double spread = tick.ask - tick.bid;
   if(spread > InpMaxSpreadUSD)
   {
      AppendLine(InpResultsFile, ts + "," + id + ",0,0,0,0,SKIP-spread-" +
                 DoubleToString(spread, 2));
      return;
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   bool ok = false;
   double fill = 0.0, sl = 0.0, tp = 0.0;
   string comment = "xauusd-exec " + id;

   if(signal == "BUY")
   {
      fill = tick.ask;
      sl = NormalizeDouble(fill - sl_d, _Digits);
      tp = NormalizeDouble(fill + tp1_d, _Digits);
      ok = trade.Buy(InpLotSize, _Symbol, fill, sl, tp, comment);
   }
   else
   {
      fill = tick.bid;
      sl = NormalizeDouble(fill + sl_d, _Digits);
      tp = NormalizeDouble(fill - tp1_d, _Digits);
      ok = trade.Sell(InpLotSize, _Symbol, fill, sl, tp, comment);
   }

   ulong ticket = trade.ResultOrder();
   double dealt = trade.ResultPrice();
   if(dealt > 0.0)
      fill = dealt;

   string status = ok ? "FILLED" : ("FAIL-" + IntegerToString((int)trade.ResultRetcode()) +
                                     " " + trade.ResultRetcodeDescription());
   AppendLine(InpResultsFile,
              ts + "," + id + "," + IntegerToString((long)ticket) + "," +
              DoubleToString(fill, _Digits) + "," + DoubleToString(sl, _Digits) + "," +
              DoubleToString(tp, _Digits) + "," + status);
   Print("ExecutorEA: ", id, " ", signal, " -> ", status,
         " ticket=", ticket, " fill=", DoubleToString(fill, _Digits));
}

//+------------------------------------------------------------------+
//| Poll the queue file                                              |
//+------------------------------------------------------------------+
void PollQueue()
{
   if(!FileIsExist(InpSignalFile, 1))
      return;
   int h = FileOpen(InpSignalFile, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;

   string lines[];
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0)
         continue;
      int n = ArraySize(lines);
      ArrayResize(lines, n + 1);
      lines[n] = line;
   }
   FileClose(h);

   for(int i = 0; i < ArraySize(lines); i++)
   {
      string parts[];
      int np = StringSplit(lines[i], ',', parts);
      if(np < 6)
         continue;
      string id = parts[0];
      StringTrimLeft(id);
      StringTrimRight(id);
      if(id == "id")          // header row
         continue;
      if(IsProcessed(id))
         continue;

      string signal = parts[1];
      double sl_d   = StringToDouble(parts[2]);
      double tp1_d  = StringToDouble(parts[3]);
      // parts[4], parts[5] = TP2/TP3 distances, carried but unused in v1

      // Mark BEFORE executing: a failed order must never be retried in a
      // loop on every poll. The failure is recorded in the results file.
      MarkProcessed(id);
      ExecuteSignal(id, signal, sl_d, tp1_d);
   }
}

//+------------------------------------------------------------------+
//| EA lifecycle                                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
   {
      Print("ExecutorEA: WARNING - chart symbol ", _Symbol,
            " does not look like gold. Attach me to the XAUUSD chart.");
   }
   LoadProcessed();
   EventSetTimer(InpPollSeconds);
   Print("ExecutorEA: init ok. Symbol=", _Symbol, " lot=", InpLotSize,
         " magic=", InpMagic, " polling ", InpSignalFile, " (Common Files)");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   PollQueue();
}

void OnTick()
{
   // Nothing: execution is timer-driven so signals are picked up even
   // between ticks on quiet charts.
}
//+------------------------------------------------------------------+
