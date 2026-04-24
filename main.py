import requests
import time
from datetime import datetime, timedelta
import pytz

# ===== TIMEZONE =====
IST = pytz.timezone('Asia/Kolkata')


# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWVhZTBlYzUwYzQyZjM4MmUzODQ1ODciLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc3MDAwNjg0LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzcwNjgwMDB9.jUqSohxiNa_B9pu9eEpA6cddgB9YubC2m6GY5ruA9_M"
BOT_TOKEN = "8726435378:AAEhAviD-pwjF-IY-wYcUVlPBKYZIjpBXB4"
CHAT_ID = "-1003724403519"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

prev_data = {}
fixed_support = None
fixed_resistance = None
prev_price = 0

last_heartbeat = None
active_trade = None
market_closed_sent = False


# ===== TELEGRAM =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("❌ Telegram error")


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

        if not data or "data" not in data or not data["data"]:
            print("❌ Empty API data")
            return None

        return data["data"]

    except Exception as e:
        print("❌ API ERROR:", e)
        return None


# ===== LTP =====
def get_ltp():
    url = "https://api.upstox.com/v2/market-quote/ltp"
    params = {"instrument_key": "NSE_INDEX|Nifty 50"}

    for _ in range(3):
        data = safe_request(url, params)

        if data:
            try:
                key = list(data.keys())[0]
                return data[key]["last_price"]
            except:
                pass

        time.sleep(1)

    return None


# ===== OPTION CHAIN =====
def get_chain():
    url = "https://api.upstox.com/v2/option/chain"
    params = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "expiry_date": get_expiry()
    }
    return safe_request(url, params) or []


# ===== HELPERS =====
def get_atm(price):
    return int(round(price / 50) * 50)


def get_data(chain, atm):
    global prev_data
    strikes = list(range(atm-150, atm+150, 50))
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


# ===== LOGIC =====
def get_sr(data):
    support = max(data, key=lambda x: x['pe'])['strike']
    resistance = max(data, key=lambda x: x['ce'])['strike']
    return support, resistance


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
        return "🔥 BULLISH"
    if w_bear >= 6:
        return "🔻 BEARISH"
    return "⚪ WEAK"


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


# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price
    global last_heartbeat, active_trade, market_closed_sent

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

            # MARKET CLOSE
            if current_time > "15:30":
                if not market_closed_sent:
                    print("🛑 Market Closed")
                    send_telegram("🛑 Market Closed")
                    market_closed_sent = True
                time.sleep(60)
                continue

            ltp = get_ltp()
            if not ltp:
                print("❌ LTP missing")
                continue

            atm = get_atm(ltp)
            chain = get_chain()

            if not chain:
                print("❌ Chain missing")
                continue

            data = get_data(chain, atm)
            support, resistance = get_sr(data)

            if fixed_support is None:
                fixed_support = support
                fixed_resistance = resistance

            print(f"📈 LTP: {ltp}")
            print(f"📊 Chain: {len(chain)} | Expiry: {get_expiry()}")
            print(f"📊 LIVE SR → {support} | {resistance}")
            print(f"🔒 FIXED SR → {fixed_support} | {fixed_resistance}")

            bull, bear = oi_signal(data)
            w_bull, w_bear = weighted(data, atm)

            st = strength(bull, bear, w_bull, w_bear)
            conf = confidence(data)

            print(f"📊 Strength: {st} | Confidence: {conf}%")

            move = abs(ltp - prev_price)
            prev_price = ltp

            if move < 1.5:
                print("⚠️ Sideways")
                time.sleep(3)
                continue

            if conf < 50:
                continue

            signal = ""

            if "BULLISH" in st and ltp >= fixed_resistance:
                signal = "BUY CALL"
            elif "BEARISH" in st and ltp <= fixed_support:
                signal = "BUY PUT"

            if signal and active_trade is None:
                strike = best_strike(data, signal)
                price = get_option_price(data, strike, signal)

                if price == 0:
                    continue

                send_telegram(f"""
🔥 ENTRY SIGNAL
{signal}
Strike: {strike}
Price: {price}
Conf: {conf}%
Time: {current_time}
""")

                active_trade = True

            time.sleep(3)

        except Exception as e:
            print("❌ ERROR:", e)
            time.sleep(5)


run()
