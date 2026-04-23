import requests
import time
from datetime import datetime, timedelta
import pytz

# ===== TIMEZONE =====
IST = pytz.timezone('Asia/Kolkata')


# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWU5ODA5OTQ3MDhjYTNkYmZiNDIzNGEiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2OTEwNDg5LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzY5ODE2MDB9.KdZAHiDao0t1erR5JuKq0njDS0W7z_OeXHb3pyo2fsc"
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
last_sr_update = None

active_trade = None
reentry_ready = False
last_direction = None

market_started = False
market_closed_sent = False

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
        data = res.json()
        if "data" not in data:
            return None
        return data["data"]
    except:
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
    return safe_request(url, params) or []

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
                "pe_chg": pe - prev_pe,
                "ce_price": item['call_options']['market_data'].get('ltp', 0),
                "pe_price": item['put_options']['market_data'].get('ltp', 0)
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

def get_option_price(data, strike, signal):
    for d in data:
        if d['strike'] == strike:
            return d['ce_price'] if signal == "BUY CALL" else d['pe_price']
    return 0

def sl_target(price):
    return price - 10, price + 20

# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price
    global last_heartbeat, last_sr_update
    global active_trade, reentry_ready, last_direction
    global market_started, market_closed_sent

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            now = datetime.now(IST)
            current_time = now.strftime("%H:%M")

            print(f"\n⏰ TIME: {current_time}")

            # HEARTBEAT
            if now.minute // 10 != last_heartbeat:
                send_telegram(f"💓 SYSTEM RUNNING {current_time}")
                last_heartbeat = now.minute // 10
                
            # MARKET START
            if current_time >= "09:15" and not market_started:
                send_telegram("🚀 Market Started")
                market_started = True
                market_closed_sent = False

            # BEFORE MARKET
            if current_time < "09:15":
                time.sleep(30)
                continue

            # MARKET CLOSED
            if current_time > "15:30":
                if not market_closed_sent:
                    print("🛑 Market Closed")
                    send_telegram("🛑 Market Closed")
                    market_closed_sent = True
                time.sleep(60)
                continue

            # SR RESET
            if current_time in ["10:20", "13:45"]:
                if last_sr_update != current_time:
                    send_telegram(f"🔄 SR RESET {current_time}")
                    fixed_support = None
                    fixed_resistance = None
                    last_sr_update = current_time

            ltp = get_ltp()
            if not ltp:
                continue

            atm = get_atm(ltp)
            chain = get_chain()

            if not chain:
                continue

            data = get_data(chain, atm)
            support, resistance = get_sr(data)

            if fixed_support is None:
                fixed_support = support
                fixed_resistance = resistance

            print(f"LTP: {ltp}")
            print(f"SR: {fixed_support}/{fixed_resistance}")

            # ===== EXIT =====
            if active_trade:
                strike = active_trade['strike']
                signal = active_trade['signal']
                entry = active_trade['entry']
                sl = active_trade['sl']
                target = active_trade['target']

                price = get_option_price(data, strike, signal)

                if price >= target:
                    send_telegram(f"🎯 TARGET HIT {strike} @ {price}")
                    active_trade = None
                    reentry_ready = True
                    continue

                if price <= sl:
                    send_telegram(f"❌ SL HIT {strike} @ {price}")
                    active_trade = None
                    reentry_ready = True
                    continue

            if current_time < "10:15":
                continue

            move = abs(ltp - prev_price)
            prev_price = ltp

            if move < 1.5:
                continue

            bull, bear = oi_signal(data)
            w_bull, w_bear = weighted(data, atm)

            st = strength(bull, bear, w_bull, w_bear)
            conf = confidence(data)

            if conf < 50:
                continue

            signal = ""

            if "BULLISH" in st and ltp >= fixed_resistance:
                signal = "BUY CALL"
            elif "BEARISH" in st and ltp <= fixed_support:
                signal = "BUY PUT"

            # ===== ENTRY / RE-ENTRY =====
            if signal != "" and active_trade is None:

                # normal entry
                if not reentry_ready:
                    pass

                # re-entry
                elif last_direction == signal:
                    print("🔁 RE-ENTRY SIGNAL")

                else:
                    continue

                strike = best_strike(data, signal)
                price = get_option_price(data, strike, signal)

                if price == 0:
                    continue

                sl, tgt = sl_target(price)

                active_trade = {
                    "strike": strike,
                    "signal": signal,
                    "entry": price,
                    "sl": sl,
                    "target": tgt
                }

                last_direction = signal

                send_telegram(f"""
🔥 {'RE-ENTRY' if reentry_ready else 'ENTRY'}
{signal}
Strike: {strike}
Price: {price}
SL: {sl}
Target: {tgt}
Conf: {conf}%
Time: {current_time}
""")

                reentry_ready = False

                time.sleep(10)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(10)

run()
