import time
import MetaTrader5 as mt5

# Exness MT5 hisobingiz ma'lumotlari
ACCOUNT = 474617772          # Exness MT5 login raqamingiz
PASSWORD = "Alex0221@!"  # Exness MT5 parolingiz
SERVER = "Exness-MT5Trial15" # Masalan: Exness-MT5Real, Exness-MT5Trial6 yoki boshqasi

def connect_to_exness():
    """Exness MT5 terminaliga ulanish funksiyasi"""
    if not mt5.initialize():
        print("MT5 init xatosi:", mt5.last_error())
        return False

    authorized = mt5.login(login=ACCOUNT, password=PASSWORD, server=SERVER)
    if authorized:
        print("Exness serveriga muvaffaqiyatli ulandi!")
        return True
    else:
        print("Ulanishda xatolik yuz berdi:", mt5.last_error())
        return False

def stream_xauusd_prices():
    """XAUUSD narxini har soniyada ko'rsatib turuvchi sikl"""
    symbol = "XAUUSD"

    # Simvolni bozor kuzatuviga qo'shish
    if not mt5.symbol_select(symbol, True):
        print(f"{symbol} simvoli topilmadi!")
        return

    print(f"\n--- {symbol} Real-Time Narxlari (Exness) ---")
    try:
        while True:
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                current_time = time.strftime('%H:%M:%S', time.localtime(tick.time))
                ask_price = tick.ask
                bid_price = tick.bid
                spread = round(ask_price - bid_price, 2)

                print(f"[{current_time}] XAUUSD | Ask: {ask_price:.2f} | Bid: {bid_price:.2f} | Spread: {spread}")
            else:
                print("Narx ma'lumotlarini olib bo'lmadi.")

            time.sleep(1)  # Har 1 soniyada qaytaradi
    except KeyboardInterrupt:
        print("\nDastur foydalanuvchi tomonidan to'xtatildi.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    if connect_to_exness():
        stream_xauusd_prices()