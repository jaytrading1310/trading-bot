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
last_signal_time = None
last_sent_sr = None

total_trades = 0
wins = 0

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
    tuesday = today + timedelta((1 - today.weekday()) % 7)
    return tuesday.strftime("%Y-%m-%d")

# ===== LTP =====
def get_ltp():
    url = "https://api.upstox.com/v2/market-quote/ltp"
    params = {"instrument_key": "NSE_INDEX|Nifty 50"}
    res = requests.get(url, headers=HEADERS, params=params)
    return list(res.json()['data'].values())[0]['last_price']

# ===== OPTION LTP =====
def get_option_ltp(strike, signal):
    try:
        opt_type = "CE" if signal == "BUY CALL" else "PE"
        symbol = f"NSE_FO|NIFTY {strike} {opt_type}"
        url = "https://api.upstox.com/v2/market-quote/ltp"
        params = {"instrument_key": symbol}
        res = requests.get(url, headers=HEADERS, params=params)
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

# ===== OI LOGIC =====
def oi_signal(data, ltp, prev_price):
    bullish = 0
    bearish = 0

    for d in data:
        if ltp > prev_price:
            if d['pe_chg'] > 0: bullish += 1
            if d['ce_chg'] < 0: bullish += 1

        elif ltp < prev_price:
            if d['ce_chg'] > 0: bearish += 1
            if d['pe_chg'] < 0: bearish += 1

    return bullish, bearish

# ===== WEIGHTED =====
def weighted(data, atm):
    bull = 0
    bear = 0

    for d in data:
        if d['strike'] < atm:
            if d['pe_chg'] > 0: bull += 2
        elif d['strike'] > atm:
            if d['ce_chg'] > 0: bear += 2

    return bull, bear

# ===== STRENGTH =====
def strength(bull, bear, w_bull, w_bear):
    if w_bull >= 6: return "SUPER BULLISH 🔥"
    if w_bear >= 6: return "SUPER BEARISH 🔥"
    if bull >= 6: return "STRONG BULLISH"
    if bear >= 6: return "STRONG BEARISH"
    if bull >= 3: return "WEAK BULLISH"
    if bear >= 3: return "WEAK BEARISH"
    return "SIDEWAYS"

# ===== CONFIDENCE =====
def confidence(data):
    score = sum(1 for d in data if d['pe_chg'] > 0 or d['ce_chg'] > 0)
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

# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price, last_sent_sr, total_trades

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            print(f"\n⏰ TIME: {current_time}")

            if current_time < "09:30":
                print("⏸ Waiting market...")
                time.sleep(10)
                continue

            ltp = get_ltp()
            atm = get_atm(ltp)

            print(f"📈 LTP: {ltp}")

            chain = get_chain()
            print(f"📊 Chain: {len(chain)} | Expiry: {get_expiry()}")

            if not chain:
                print("❌ NO DATA")
                time.sleep(5)
                continue

            data = get_data(chain, atm)
            support, resistance = get_sr(data)

            print(f"📊 LIVE SR → {support} | {resistance}")
            print(f"🔒 FIXED SR → {fixed_support} | {fixed_resistance}")

            # TELEGRAM SR CONTROL
            sr_key = f"{support}-{resistance}"
            if sr_key != last_sent_sr:
                send_telegram(f"📊 SR → {support} | {resistance}")
                last_sent_sr = sr_key

            if fixed_support is None:
                fixed_support = support
                fixed_resistance = resistance

            if current_time < "10:15":
                print("⏸ Waiting 10:15...")
                time.sleep(10)
                continue

            move = abs(ltp - prev_price)
            prev_price = ltp

            if move < 2:
                print("⏸ Low move")
                continue

            bull, bear = oi_signal(data, ltp, prev_price)
            w_bull, w_bear = weighted(data, atm)

            st = strength(bull, bear, w_bull, w_bear)
            conf = confidence(data)

            print(f"📊 Strength: {st} | Confidence: {conf}%")

            if conf < 40:
                continue

            signal = ""

            if "BULLISH" in st and ltp >= fixed_resistance - 10:
                signal = "BUY CALL"

            elif "BEARISH" in st and ltp <= fixed_support + 10:
                signal = "BUY PUT"

            if signal == "":
                continue

            strike = best_strike(data, signal)
            opt_price = get_option_ltp(strike, signal)

            if opt_price == 0:
                continue

            sl = opt_price - 10
            target = opt_price + 20

            total_trades += 1

            msg = f"""
🔥 FINAL SIGNAL 🔥

{signal}
Strike: {strike}
Price: {opt_price}

SL: {sl}
Target: {target}

Strength: {st}
Confidence: {conf}%

SR: {fixed_support} / {fixed_resistance}
Time: {current_time}
"""

            print(msg)
            send_telegram(msg)

            fixed_support = None
            fixed_resistance = None

            time.sleep(10)

        except Exception as e:
            print("❌ ERROR:", e)
            time.sleep(5)

run()
