//+------------------------------------------------------------------+
//|  ZoneViewer.mq5                                                  |
//|  Python bot topayotgan zonalarni MT5 chartida REAL VAQTDA chizadi |
//+------------------------------------------------------------------+
//  O'RNATISH:
//    1. Bu faylni MQL5/Indicators/ papkasiga ko'chiring
//    2. MetaEditor'da oching va F7 (Compile) bosing
//    3. MT5 da XAUUSD chartini oching -> Navigator -> Indicators -> ZoneViewer
//
//  ISHLASH PRINSIPI:
//    Python  ->  MQL5/Files/zone_view.csv  ->  shu indikator  ->  chart
//    Fayl har InpRefreshMs millisekundda o'qiladi va chart qayta chiziladi.
//+------------------------------------------------------------------+
#property copyright "XAUUSD Zone Alert Bot"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

input string InpFile        = "zone_view.csv"; // Python yozadigan fayl nomi
input int    InpRefreshMs   = 400;             // Yangilash oralig'i (ms)
input int    InpRightBars   = 30;              // Zona o'ngga necha svecha cho'zilsin
input bool   InpShowStatus  = true;            // Yuqori chap burchakda holat paneli
input color  InpActive      = clrTomato;       // Tasdiqlangan zona
input color  InpCandidate   = clrGold;         // Nomzod zona (tekshirilmoqda)
input color  InpRejected    = clrDimGray;      // Rad etilgan zona
input color  InpTriggered   = clrMediumOrchid; // Signal bergan zona
input color  InpTrigger     = clrOrange;       // Trigger chizig'i
input color  InpMarkHigh    = clrDeepSkyBlue;  // Swing High belgisi
input color  InpMarkLow     = clrSpringGreen;  // Swing Low belgisi

#define PFX "ZV_"   // barcha obyektlar shu prefiks bilan (tozalash uchun)

string g_last_payload = "";
int    g_zone_count   = 0;
int    g_mark_count   = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetMillisecondTimer(InpRefreshMs < 100 ? 100 : InpRefreshMs);
   IndicatorSetString(INDICATOR_SHORTNAME, "ZoneViewer");
   ReadAndDraw();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   ReadAndDraw();
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   return(rates_total);
  }

//+------------------------------------------------------------------+
//| Faylni o'qish. O'zgarmagan bo'lsa qayta chizmaymiz.              |
//+------------------------------------------------------------------+
void ReadAndDraw()
  {
   string payload = ReadFeed();
   if(payload == "")
      return;
   if(payload == g_last_payload)
      return;              // o'zgarmadi - chartni bezovta qilmaymiz
   g_last_payload = payload;

   ObjectsDeleteAll(0, PFX);
   g_zone_count = 0;
   g_mark_count = 0;

   string lines[];
   int n = StringSplit(payload, '\n', lines);
   for(int i = 0; i < n; i++)
     {
      string line = lines[i];
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0 || StringGetCharacter(line, 0) == '#')
         continue;
      ParseLine(line);
     }
   ChartRedraw();
  }

//+------------------------------------------------------------------+
string ReadFeed()
  {
   // FILE_SHARE_* muhim: Python ayni paytda shu faylga yozayotgan bo'lishi mumkin
   int h = FileOpen(InpFile, FILE_READ | FILE_TXT | FILE_ANSI |
                    FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return("");

   string content = "";
   while(!FileIsEnding(h))
      content += FileReadString(h) + "\n";
   FileClose(h);
   return(content);
  }

//+------------------------------------------------------------------+
void ParseLine(const string line)
  {
   string f[];
   int c = StringSplit(line, '|', f);
   if(c < 2)
      return;

   if(f[0] == "STATUS" && InpShowStatus && c >= 3)
      DrawStatus(f[1], (int)StringToInteger(f[2]));
   else if(f[0] == "ZONE" && c >= 5)
      DrawZone((int)StringToInteger(f[1]), StringToDouble(f[2]),
               StringToDouble(f[3]), f[4], c >= 6 ? f[5] : "");
   else if(f[0] == "LINE" && c >= 3)
      DrawLine(StringToDouble(f[1]), f[2], c >= 4 ? f[3] : "");
   else if(f[0] == "MARK" && c >= 4)
      DrawMark((datetime)StringToInteger(f[1]), StringToDouble(f[2]),
               f[3], c >= 5 ? f[4] : "");
  }

//+------------------------------------------------------------------+
color ZoneColor(const string state)
  {
   if(state == "candidate") return(InpCandidate);
   if(state == "rejected")  return(InpRejected);
   if(state == "triggered") return(InpTriggered);
   return(InpActive);
  }

//+------------------------------------------------------------------+
//| Zona = to'ldirilgan to'rtburchak + izoh matni                    |
//+------------------------------------------------------------------+
void DrawZone(const int id, const double lo, const double hi,
              const string state, const string note)
  {
   datetime t1 = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_FIRSTDATE);
   datetime t2 = TimeCurrent() + PeriodSeconds(_Period) * InpRightBars;
   color    col = ZoneColor(state);

   string name = PFX + "zone_" + IntegerToString(id);
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, hi, t2, lo))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);

   // Chegaralarini aniqroq ko'rsatish uchun ikkita ingichka chiziq
   DrawEdge(name + "_t", hi, col);
   DrawEdge(name + "_b", lo, col);

   string caption = "#" + IntegerToString(id) + "  " +
                    DoubleToString(lo, _Digits) + " - " + DoubleToString(hi, _Digits);
   if(note != "")
      caption += "   " + note;

   string tn = name + "_txt";
   if(ObjectCreate(0, tn, OBJ_TEXT, 0, t2, hi))
     {
      ObjectSetString(0, tn, OBJPROP_TEXT, caption);
      ObjectSetInteger(0, tn, OBJPROP_COLOR, col);
      ObjectSetInteger(0, tn, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, tn, OBJPROP_ANCHOR, ANCHOR_RIGHT_LOWER);
      ObjectSetInteger(0, tn, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, tn, OBJPROP_HIDDEN, true);
     }
   g_zone_count++;
  }

//+------------------------------------------------------------------+
void DrawEdge(const string name, const double price, const color col)
  {
   if(!ObjectCreate(0, name, OBJ_HLINE, 0, 0, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

//+------------------------------------------------------------------+
//| Trigger / daraja chizig'i (punktir)                              |
//+------------------------------------------------------------------+
void DrawLine(const double price, const string kind, const string note)
  {
   static int counter = 0;
   string name = PFX + "line_" + kind + "_" + DoubleToString(price, 3);
   if(ObjectFind(0, name) >= 0)
      return;

   if(!ObjectCreate(0, name, OBJ_HLINE, 0, 0, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, InpTrigger);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetString(0, name, OBJPROP_TEXT, note);
  }

//+------------------------------------------------------------------+
//| Swing High/Low belgisi - bot nimani topganini ko'rsatadi         |
//+------------------------------------------------------------------+
void DrawMark(const datetime ts, const double price,
              const string kind, const string note)
  {
   string name = PFX + "mark_" + IntegerToString(g_mark_count);
   bool   is_high = (kind == "high");
   int    arrow   = is_high ? 234 : 233;   // Wingdings: pastga / yuqoriga strelka

   if(!ObjectCreate(0, name, OBJ_ARROW, 0, ts, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, arrow);
   ObjectSetInteger(0, name, OBJPROP_COLOR, is_high ? InpMarkHigh : InpMarkLow);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,
                    is_high ? ANCHOR_BOTTOM : ANCHOR_TOP);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   if(note != "")
      ObjectSetString(0, name, OBJPROP_TEXT, note);
   g_mark_count++;
  }

//+------------------------------------------------------------------+
//| Yuqori chap burchakdagi holat paneli                             |
//+------------------------------------------------------------------+
void DrawStatus(const string text, const int progress)
  {
   string bar = "";
   int filled = (int)MathRound(progress / 5.0);   // 20 ta bo'lak
   for(int i = 0; i < 20; i++)
      bar += (i < filled ? "█" : "░");

   Panel(PFX + "st1", 10, 18, "BOT: " + text, clrWhite, 10);
   Panel(PFX + "st2", 10, 36, bar + "  " + IntegerToString(progress) + "%",
         progress >= 100 ? clrSpringGreen : InpCandidate, 10);
   Panel(PFX + "st3", 10, 54,
         "Zonalar: " + IntegerToString(g_zone_count) +
         "   Belgilar: " + IntegerToString(g_mark_count),
         clrSilver, 9);
  }

//+------------------------------------------------------------------+
void Panel(const string name, const int x, const int y,
           const string text, const color col, const int size)
  {
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0))
         return;
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
     }
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
  }
//+------------------------------------------------------------------+
