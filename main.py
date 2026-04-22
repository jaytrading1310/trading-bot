import requests
import time
from datetime import datetime, timedelta
import pytz

# ===== TIMEZONE =====
IST = pytz.timezone('Asia/Kolkata')


# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWU4NDA3YzdjNDE5ZDFjNWQwMGFjNTUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2ODI4NTQwLCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzY4OTUyMDB9.RotC9PiKrYxcrvmukLlmM6JfeHpWRb-NyqVg4NQ6d_4"
BOT_TOKEN = "8726435378:AAEhAviD-pwjF-IY-wYcUVlPBKYZIjpBXB4"
CHAT_ID = "-1003724403519"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# ===== GLOBAL =====
prev_data = {}
fixed_support = None
fixed_resistance = None
prev_price = 0

last_heartbeat = None

# ===== TELEGRAM =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("Telegram error")

# ===== EXPIRY =====
def get_expiry():
    today = datetime.now(IST)
    days_ahead = 1 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    expiry = today + timedelta(days=days_ahead)
    return expiry.strftime("%Y-%m-%d")

# ===== SAFE API =====
def safe_request(url, params=None):
    try:
        res = requests.get(url, headers=HEADERS, params=params)
        json_data = res.json()

        if "data" not in json_data:
            print("❌ API ERROR:", json_data)
            return None

        return json_data["data"]

    except Exception as e:
        print("❌ REQUEST ERROR:", e)
        return None

# ===== LTP =====
def get_ltp():
    url = "https://api.upstox.com/v2/market-quote/ltp"
    params = {"instrument_key": "NSE_INDEX|Nifty 50"}

    data = safe_request(url, params)
    if not data:
        return None

    return list(data.values())[0]['last_price']

# ===== OPTION CHAIN =====
def get_chain():
    url = "https://api.upstox.com/v2/option/chain"

    params = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "expiry_date": get_expiry()
    }

    data = safe_request(url, params)
    if not data:
        return []

    return data

# ===== OPTION LTP =====
def get_option_ltp(strike, signal):
    try:
        opt = "CE" if signal == "BUY CALL" else "PE"
        symbol = f"NSE_FO|NIFTY {strike} {opt}"

        url = "https://api.upstox.com/v2/market-quote/ltp"
        data = safe_request(url, {"instrument_key": symbol})

        if not data:
            return 0

        return list(data.values())[0]['last_price']
    except:
        return 0

# ===== ATM =====
def get_atm(price):
    return int(round(price / 50) * 50)

# ===== DATA =====
def get_data(chain, atm):
    global prev_data
    strikes = list(range(atm-200, atm+201, 50))
    data = []

    for item in chain:
        if item['strike_price'] in strikes:
            strike = item['strike_price']

            ce = item['call_options']['market_data']['oi']
            pe = item['put_options']['market_data']['oi']

            prev_ce = prev_data.get(strike, {}).get("ce", ce)
            prev_pe = prev_data.get(strike, {}).get("pe", pe)

            data.append({
                "strike": strike,
                "ce": ce,
                "pe": pe,
                "ce_chg": ce - prev_ce,
                "pe_chg": pe - prev_pe
            })

            prev_data[strike] = {"ce": ce, "pe": pe}

    return data

# ===== SR =====
def get_sr(data):
    support = max(data, key=lambda x: x['pe'])['strike']
    resistance = max(data, key=lambda x: x['ce'])['strike']
    return support, resistance

# ===== SIGNAL =====
def oi_signal(data):
    bull = sum(1 for d in data if d['pe_chg'] > 0)
    bear = sum(1 for d in data if d['ce_chg'] > 0)
    return bull, bear

def weighted(data, atm):
    w_bull = sum(2 for d in data if d['strike'] < atm and d['pe_chg'] > 0)
    w_bear = sum(2 for d in data if d['strike'] > atm and d['ce_chg'] > 0)
    return w_bull, w_bear

def strength(bull, bear, w_bull, w_bear):
    if w_bull >= 6:
        return "SUPER STRONG BULLISH 🔥"
    if w_bear >= 6:
        return "SUPER STRONG BEARISH 🔥"
    if bull >= 5:
        return "STRONG BULLISH"
    if bear >= 5:
        return "STRONG BEARISH"
    return "WEAK"

def confidence(data):
    score = sum(1 for d in data if d['pe'] > d['ce'])
    return round((score / len(data)) * 100, 2)

def best_strike(data, signal):
    best = None
    max_val = 0
    for d in data:
        val = d['pe_chg'] if signal == "BUY CALL" else d['ce_chg']
        if val > max_val:
            max_val = val
            best = d['strike']
    return best

def sl_target(price):
    return price - 10, price + 20

# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price, last_heartbeat

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            now = datetime.now(IST)
            current_time = now.strftime("%H:%M")

            print(f"\n⏰ TIME: {current_time}")

            # 💓 HEARTBEAT
            if now.minute % 10 == 0 and last_heartbeat != now.minute:
                msg = f"💓 SYSTEM RUNNING {current_time}"
                print(msg)
                send_telegram(msg)
                last_heartbeat = now.minute

            if current_time < "09:30":
                print("⏳ Waiting market...")
                time.sleep(10)
                continue

            ltp = get_ltp()
            if ltp is None:
                time.sleep(5)
                continue

            atm = get_atm(ltp)
            chain = get_chain()

            if not chain:
                print("❌ No data")
                time.sleep(5)
                continue

            print(f"📈 LTP: {ltp}")
            print(f"📊 Chain: {len(chain)} | Expiry: {get_expiry()}")

            data = get_data(chain, atm)

            support, resistance = get_sr(data)

            print(f"📊 LIVE SR → {support} | {resistance}")

            if fixed_support is None:
                fixed_support = support
                fixed_resistance = resistance

            print(f"🔒 FIXED SR → {fixed_support} | {fixed_resistance}")

            if current_time < "10:15":
                print("⏳ Waiting 10:15...")
                time.sleep(10)
                continue

            move = abs(ltp - prev_price)
            prev_price = ltp

            if move < 2:
                print("⚠️ Sideways")
                continue

            bull, bear = oi_signal(data)
            w_bull, w_bear = weighted(data, atm)

            st = strength(bull, bear, w_bull, w_bear)
            conf = confidence(data)

            print(f"📊 Strength: {st} | Confidence: {conf}%")

            if conf < 40:
                continue

            signal = ""
            if "BULLISH" in st and ltp >= fixed_resistance:
                signal = "BUY CALL"
            elif "BEARISH" in st and ltp <= fixed_support:
                signal = "BUY PUT"

            if signal == "":
                continue

            strike = best_strike(data, signal)
            opt_price = get_option_ltp(strike, signal)

            sl, tgt = sl_target(opt_price)

            msg = f"""
🔥 SIGNAL 🔥
Type: {st}
Signal: {signal}
Strike: {strike}
Price: {opt_price}
SL: {sl}
Target: {tgt}
Confidence: {conf}%
Time: {current_time}
"""

            print(msg)
            send_telegram(msg)

            fixed_support = None
            fixed_resistance = None

            time.sleep(10)

        except Exception as e:
            print("❌ ERROR:", e)
            send_telegram(f"ERROR: {e}")
            time.sleep(5)

run()
