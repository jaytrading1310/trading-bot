import requests
import time
from datetime import datetime, timedelta

# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWU2ZDk5ODVlZTEyZDdmYTNkYjYwY2EiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2NzM2NjY0LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzY4MDg4MDB9.Czlw_lSqj8EVagEphtkqlyY0wPTPHGrX6VNKxFhGrX4"
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

total_trades = 0
wins = 0

last_heartbeat = None
last_sent_sr = None

# ===== TELEGRAM =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ===== EXPIRY (TUESDAY) =====
def get_expiry():
    today = datetime.now()
    days_ahead = 1 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    expiry = today + timedelta(days=days_ahead)
    return expiry.strftime("%Y-%m-%d")

# ===== LTP =====
def get_ltp():
    url = "https://api.upstox.com/v2/market-quote/ltp"
    params = {"instrument_key": "NSE_INDEX|Nifty 50"}
    res = requests.get(url, headers=HEADERS, params=params)
    return list(res.json()['data'].values())[0]['last_price']

# ===== OPTION LTP =====
def get_option_ltp(strike, signal):
    try:
        opt = "CE" if signal == "BUY CALL" else "PE"
        symbol = f"NSE_FO|NIFTY {strike} {opt}"
        url = "https://api.upstox.com/v2/market-quote/ltp"
        res = requests.get(url, headers=HEADERS, params={"instrument_key": symbol})
        return list(res.json()['data'].values())[0]['last_price']
    except:
        return 0

# ===== ATM =====
def get_atm(price):
    return int(round(price / 50) * 50)

# ===== OPTION CHAIN =====
def get_chain():
    url = "https://api.upstox.com/v2/option/chain"
    params = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "expiry_date": get_expiry()
    }
    res = requests.get(url, headers=HEADERS, params=params)
    return res.json().get("data", [])

# ===== DATA =====
def get_data(chain, atm):
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

# ===== SIGNAL LOGIC =====
def oi_signal(data):
    bull = 0
    bear = 0

    for d in data:
        if d['pe_chg'] > 0:
            bull += 1
        if d['ce_chg'] > 0:
            bear += 1

    return bull, bear

# ===== WEIGHTED =====
def weighted(data, atm):
    w_bull = 0
    w_bear = 0

    for d in data:
        if d['strike'] < atm and d['pe_chg'] > 0:
            w_bull += 2
        if d['strike'] > atm and d['ce_chg'] > 0:
            w_bear += 2

    return w_bull, w_bear

# ===== STRENGTH =====
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

# ===== CONFIDENCE =====
def confidence(data):
    score = 0
    for d in data:
        if d['pe'] > d['ce']:
            score += 1
    return round((score / len(data)) * 100, 2)

# ===== BEST STRIKE =====
def best_strike(data, signal):
    best = None
    max_val = 0
    for d in data:
        val = d['pe_chg'] if signal == "BUY CALL" else d['ce_chg']
        if val > max_val:
            max_val = val
            best = d['strike']
    return best

# ===== SL TARGET =====
def sl_target(price):
    return price - 10, price + 20

# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price
    global last_heartbeat, last_sent_sr, total_trades, wins

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            print(f"\n⏰ TIME: {current_time}")

            # ===== HEARTBEAT =====
            if now.minute % 10 == 0:
                if last_heartbeat != now.minute:
                    send_telegram(f"💓 RUNNING {current_time}")
                    last_heartbeat = now.minute

            # ===== WAIT MARKET =====
            if current_time < "09:30":
                print("⏳ Waiting market...")
                time.sleep(10)
                continue

            ltp = get_ltp()
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

            # ===== SR TELEGRAM =====
            sr_key = f"{support}-{resistance}"
            if sr_key != last_sent_sr:
                send_telegram(f"📊 SR UPDATE\n{support} / {resistance}")
                last_sent_sr = sr_key

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

            total_trades += 1

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
            send_telegram("ERROR:", e)
            time.sleep(5)

run()
