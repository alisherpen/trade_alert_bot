# XAUUSD Zone Alert Bot

24/7 ishlaydigan oltin (XAUUSD) narx kuzatuvchisi. Narx siz belgilagan zonaning
bufer chegarasiga yetganda Telegram orqali **qo'ng'iroq qiladi**, ovozli
ogohlantirish va batafsil xabar yuboradi.

```
MT5 (Exness)  ──►  MonitorLoop  ──►  ZoneManager  ──►  AlertDispatcher  ──►  Telegram
   har 1s          narx oqimi       bufer mantiqi      navbat (queue)      M15 chart + ovozli call
                                          │
                                     zones.json (restartdan keyin tiklanadi)
```

---

## 1. Tez ishga tushirish

```bash
pip install -r requirements.txt
```

`.env` faylini to'ldiring (`.env.example` dan nusxa oling), so'ng:

```bash
python selftest.py     # MT5/Telegram'siz mantiqni tekshiradi
python main.py         # botni ishga tushiradi
```

Birinchi marta Telegram kodi so'ralishi mumkin — `sessions/` papkasida sessiya
saqlanadi va keyingi safar so'ralmaydi.

---

## 2. Buyruqlar

Buyruqlarni **o'z akkauntingizdan** istalgan chatda yozasiz (eng qulayi —
Saved Messages). `.env` dagi `ADMINS` ro'yxatidagilar ham yoza oladi.

| Buyruq | Vazifasi |
|---|---|
| `/addzone 4291 4296` | Yangi zona qo'shish |
| `/addzone 4291-4296, 4310 4315` | Bir nechta zona bir buyruqda |
| `/zones` | Barcha zonalar, masofalar va holatlar |
| `/delzone 3` | `#3` zonani o'chirish |
| `/clear` | Barcha zonalarni o'chirish |
| `/rearm` / `/rearm 3` | Signal bergan zonani qayta yoqish |
| `/price` | Joriy Bid/Ask/Spread |
| `/status` | MT5, Telegram, zonalar va sozlamalar holati |
| `/testcall` | Qo'ng'iroqni sinash |
| `/testalert` | To'liq alert zanjirini sinash |

---

## 3. Zona va bufer mantiqi

`BUFFER_PIPS=60`, `PIP_SIZE=0.1` → bufer **$6.00**.

`/addzone 4291 4296` uchun trigger diapazoni:

```
      4285.00              4291 ──── 4296              4302.00
        │                    └─── zona ───┘               │
        └── pastdan trigger                 yuqoridan trigger ──┘
```

Narx `[4285.00 … 4302.00]` oralig'iga kirishi bilan signal beriladi.

**Anti-spam:** signal berilgan zona `triggered: true` bo'ladi va qayta bezovta
qilmaydi. `REARM_PIPS=30` bo'lsa, narx trigger chegarasidan yana 30 pips
uzoqlashganda zona avtomatik qayta yoqiladi (`REARM_PIPS=0` — faqat `/rearm`
bilan). Holat `zones.json` da saqlanadi, shuning uchun restart signalni
takrorlamaydi.

---

## 4. Qo'ng'iroq: nima ishlaydi, nima yo'q

Bot ikki qatlamli ishlaydi va qatlam ishga tushishda avtomatik tanlanadi.

### Qatlam 1 — ASOSIY: gapiruvchi qo'ng'iroq (`py-tgcalls`)

**Shart: ffmpeg + ffprobe o'rnatilgan bo'lishi kerak.**

`@CBU2025` telefoni jiringlaydi → ko'tarilganda TTS matni **qo'ng'iroq ichida**
eshitiladi → ovoz tugagach aloqa avtomatik uziladi.

Bu `ntgcalls` ning P2P (1-ga-1) qo'llab-quvvatlashi orqali ishlaydi:
`play(user_id, ...)` chaqirilganda `chat_id > 0` bo'lgani uchun guruh emas,
shaxsiy qo'ng'iroq ochiladi.

### Qatlam 2 — ZAXIRA: faqat jiringlatish (raw MTProto)

ffmpeg topilmasa avtomatik shu rejimga o'tadi: telefon jiringlaydi, ko'tarilsa
darhol uziladi, ovozli matn esa alohida voice-message bo'lib keladi.

Joriy rejimni `/status` yoki `/testcall` ko'rsatadi.

### Qo'ng'iroq ishlamasa

`USER_PRIVACY_RESTRICTED` xatosi eng ko'p uchraydi. Yechim:
qabul qiluvchi akkauntda **Settings → Privacy and Security → Calls → Everybody**
(yoki *My Contacts*, bunda ikkala akkaunt bir-birini kontaktga qo'shgan bo'lishi kerak).

---

## 5. ffmpeg — MAJBURIY (gapiruvchi qo'ng'iroq uchun)

```powershell
winget install Gyan.FFmpeg
```

Keyin PowerShell'ni qayta oching va tekshiring: `ffmpeg -version`, `ffprobe -version`.

ffmpeg ikki narsa uchun kerak:
1. **`py-tgcalls` media o'qishi** — ularsiz qo'ng'iroqda ovoz umuman bo'lmaydi;
2. TTS mp3 → ogg/opus (Telegram'da haqiqiy voice message ko'rinishi uchun).

## 6. Chart rasmi

Har alert bilan **M15 candlestick chart** yuboriladi: zona to'rtburchagi,
bufer (trigger) chegaralari va joriy narx chizig'i chizilgan holda.

Sozlash: `.env` da `CHART_TIMEFRAME` (M1/M5/M15/M30/H1/H4/D1) va `CHART_BARS`.

Chart MT5 terminali oynasidan emas, `copy_rates_from_pos` ma'lumotidan chiziladi —
MT5 Python API'da screenshot funksiyasi yo'q (`ChartScreenShot` faqat MQL5'da), va
oyna rasmini olish 24/7 bot uchun ishonchsiz.

---

## 7. Botni MT5 chartida REAL VAQTDA kuzatish

**Muhim texnik fakt:** `MetaTrader5` Python paketida 46 ta funksiya bor va ularning
orasida **chizish funksiyasi yo'q** — `ObjectCreate`, `ChartScreenShot` kabilar faqat
MQL5 tilida mavjud. Ya'ni Python MT5 chartiga to'g'ridan-to'g'ri hech narsa chiza olmaydi.

Shuning uchun **fayl ko'prigi** ishlatiladi:

```
Python  --yozadi-->  MQL5/Files/zone_view.csv  --o'qiydi-->  ZoneViewer.ex5
 (har 1s)                                       (har 400ms)    |
                                                               v
                                                      MT5 chartida chiziladi
```

### O'rnatish (bir marta)

`ZoneViewer.mq5` allaqachon MT5 papkangizga ko'chirilgan va kompilyatsiya qilingan
(`0 errors, 0 warnings`). Qolgani:

1. MT5 da **XAUUSD** chartini oching
2. **Navigator** (Ctrl+N) → **Indicators** → **ZoneViewer** ni chartga tashlang
3. Tamom — bot ishlaganda chart o'zi yangilanib turadi

Qayta kompilyatsiya kerak bo'lsa: MetaEditor'da faylni ochib **F7**.

### Nimani ko'rasiz

| Element | Ma'nosi |
|---|---|
| 🔴 Qizil to'rtburchak | Tasdiqlangan zona |
| 🟡 Sariq to'rtburchak | Nomzod zona (hali tekshirilmoqda) |
| ⚫ Kulrang to'rtburchak | Rad etilgan zona |
| 🟣 Binafsha to'rtburchak | Signal bergan zona (`triggered`) |
| 🟠 Punktir chiziq | Trigger (bufer) chegarasi |
| 🔵 / 🟢 Strelkalar | Bot topgan Swing High / Low nuqtalar |
| Yuqori chap panel | Bot hozir nima qilayotgani + progress bar |

### Ikki rejim

**a) Zona qidiruvini kuzatish** — `python find_zone.py`

Terminaldan ishga tushiring, so'ng MT5 ga o'ting. Bot qadam-baqadam ishlaydi va
har bosqichni chartda chizadi: avval swing nuqtalarni belgilaydi, keyin nomzod
zonalarni sariq rangda quradi, teginishlarni sanab ba'zilarini kulrangga o'tkazadi
(rad etildi), oxirida qolganlarini qizil qiladi.

```bash
python find_zone.py --tf H4 --bars 300 --speed 0.4
```

`--speed` — har qadam orasidagi pauza. Sekinlashtirsangiz jarayon yaxshiroq ko'rinadi.
Oxirida topilgan zonalarni tasdiqlashingiz so'raladi (`hammasi` / `1 3 5` / Enter).

> ⚠️ `find_zone.py` dagi algoritm hozircha **demo** (fraktal swing + teginishlar soni).
> O'z qoidalaringizni aytsangiz, `detect_zones()` funksiyasi to'liq almashtiriladi —
> vizualizatsiya qismi o'zgarmaydi.

**b) Kuzatuvni ko'rish** — `python main.py`

Bot ishlaganda chartda barcha faol zonalar, ularning trigger chegaralari va
joriy narx doimiy yangilanib turadi. Panelda: `Kuzatuvda | narx 4319.54 | faol 3/5`.

O'chirish: `.env` da `BRIDGE_ENABLED=false`.

## 8. Loyiha tuzilishi

```
trade_alert/
├── main.py                 # kirish nuqtasi, barcha qismlarni bog'laydi
├── find_zone.py            # zona qidiruvi (jarayon MT5 chartida ko'rinadi)
├── config.py               # .env dan sozlamalar + validatsiya
├── selftest.py             # MT5/Telegram'siz offline testlar
├── zones.json              # zonalar (avtomatik yaratiladi)
├── core/
│   ├── chart.py            # M15 candlestick chart (Pillow)
│   ├── mt5_bridge.py       # Python -> MQL5/Files -> chartda chizish
│   ├── models.py           # Zone, AlertEvent
│   ├── storage.py          # atomik JSON saqlash (os.replace)
│   ├── zone_manager.py     # CRUD + bufer/anti-spam mantiqi
│   ├── price_feed.py       # MT5, alohida thread, reconnect
│   ├── monitor.py          # 1s sikl + backoff + heartbeat
│   └── alerting.py         # alert navbati: chart + qo'ng'iroq + matn
├── tg/
│   ├── client.py           # Telethon userbot, qayta ulanish, yuborish
│   ├── commands.py         # /addzone /zones /clear ...
│   ├── voice_call.py       # ASOSIY: py-tgcalls P2P call + ovoz
│   ├── calls.py            # ZAXIRA: raw MTProto (faqat jiringlatadi)
│   └── tts.py              # edge-tts + ffmpeg opus
├── mql5/
│   └── ZoneViewer.mq5      # chartda chizuvchi indikator (MQL5)
├── data/                   # TTS va chart keshi
└── sessions/               # Telethon sessiyalari
```

---

## 9. Barqarorlik

- **MT5 uzilsa:** 3 ta ketma-ket xatodan keyin eksponensial backoff (2…60s) bilan
  qayta ulanadi; hisob sikl hech qachon to'xtamaydi.
- **Telegram uzilsa:** Telethon avtomatik qayta ulanadi (`connection_retries=None`),
  qo'shimcha ravishda har siklda `ensure_connected()` tekshiradi.
- **Xatolar:** har bir handler va alert `try/except` ichida — bitta xato botni yiqitmaydi.
- **Zonalar:** har o'zgarishda vaqtinchalik faylga yozilib, `os.replace` bilan atomik
  almashtiriladi — elektr o'chsa ham fayl buzilmaydi.
- **Loglar:** konsolga va `bot.log` fayliga yoziladi.

24/7 ishlashi uchun Windows Task Scheduler'ga `run.bat` ni qo'shing
(trigger: *At startup*, "Run whether user is logged on or not").
#   t r a d e _ a l e r t _ b o t  
 