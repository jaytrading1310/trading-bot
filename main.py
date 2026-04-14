import requests
import time
from datetime import datetime, timedelta

# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWRkZmFlMmUwZDZmYjQ5ZDgwNDI2MTAiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2MTU1MzYyLCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzYyMDQwMDB9.BB92qxLjvRWKa0EUFpaqlNHYyEAemo8T6Dofn75h22g"
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

# ===== TELEGRAM =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ===== EXPIRY =====
def get_expiry():
    today = datetime.now()
    days_ahead = 3 - today.weekday()
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

            ce_chg = ce - prev_ce
            pe_chg = pe - prev_pe

            data.append({
                "strike": strike,
                "ce": ce,
                "pe": pe,
                "ce_chg": ce_chg,
                "pe_chg": pe_chg
            })

            prev_data[strike] = {"ce": ce, "pe": pe}

    return data

# ===== SUPPORT RESISTANCE =====
def get_sr(data):
    support = max(data, key=lambda x: x['pe'])['strike']
    resistance = max(data, key=lambda x: x['ce'])['strike']
    return support, resistance

# ===== OI + PRICE SIGNAL =====
def oi_price_signal(data, ltp, prev_price):
    bullish = 0
    bearish = 0

    for d in data:
        if ltp > prev_price:
            if d['pe_chg'] > 0:
                bullish += 1
            if d['ce_chg'] < 0:
                bullish += 1

        elif ltp < prev_price:
            if d['ce_chg'] > 0:
                bearish += 1
            if d['pe_chg'] < 0:
                bearish += 1

    return bullish, bearish

# ===== WEIGHTED MULTI STRIKE =====
def weighted_cluster(data, atm):
    lower_bull = 0
    upper_bear = 0

    for d in data:
        strike = d['strike']

        if strike < atm:
            if d['pe_chg'] > 0:
                lower_bull += 2
            if d['ce_chg'] < 0:
                lower_bull += 1

        elif strike > atm:
            if d['ce_chg'] > 0:
                upper_bear += 2
            if d['pe_chg'] < 0:
                upper_bear += 1

    return lower_bull, upper_bear

# ===== STRENGTH =====
def signal_strength(bullish, bearish, lower_bull, upper_bear):

    if lower_bull >= 6:
        return "SUPER STRONG BULLISH 🔥"

    if upper_bear >= 6:
        return "SUPER STRONG BEARISH 🔥"

    if bullish >= 6:
        return "STRONG BULLISH"

    if bearish >= 6:
        return "STRONG BEARISH"

    if bullish >= 3:
        return "WEAK BULLISH"

    if bearish >= 3:
        return "WEAK BEARISH"

    return "NEUTRAL"

# ===== CONFIDENCE =====
def get_confidence(data):
    score = 0
    for d in data:
        if d['pe'] > d['ce'] and d['pe_chg'] > 0:
            score += 1
        if d['ce'] > d['pe'] and d['ce_chg'] > 0:
            score += 1
    return round((score / (len(data)*2)) * 100, 2)

# ===== ACCURACY =====
def get_accuracy():
    if total_trades == 0:
        return 0
    return round((wins / total_trades) * 100, 2)

# ===== BEST STRIKE =====
def best_strike(data, signal):
    best = None
    max_val = 0

    for d in data:
        if signal == "BUY CALL" and d['pe_chg'] > max_val:
            max_val = d['pe_chg']
            best = d['strike']

        elif signal == "BUY PUT" and d['ce_chg'] > max_val:
            max_val = d['ce_chg']
            best = d['strike']

    return best

# ===== SL TARGET =====
def get_sl_target(price):
    return price - 10, price + 20

# ===== MAIN =====
def run():
    global fixed_support, fixed_resistance, prev_price, total_trades

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            if current_time < "09:30":
                time.sleep(10)
                continue

            ltp = get_ltp()
            atm = get_atm(ltp)
            chain = get_chain()

            if not chain:
                time.sleep(5)
                continue

            data = get_data(chain, atm)
            support, resistance = get_sr(data)

            if fixed_support is None:
                fixed_support = support
                fixed_resistance = resistance

            if current_time < "10:15":
                time.sleep(10)
                continue

            move = abs(ltp - prev_price)
            prev_price = ltp

            if move < 3:
                time.sleep(5)
                continue

            conf = get_confidence(data)
            acc = get_accuracy()

            if conf < 40:
                continue

            bullish, bearish = oi_price_signal(data, ltp, prev_price)

            lower_bull, upper_bear = weighted_cluster(data, atm)

            strength = signal_strength(bullish, bearish, lower_bull, upper_bear)

            signal = ""

            if "BULLISH" in strength and ltp >= fixed_resistance:
                signal = "BUY CALL"

            elif "BEARISH" in strength and ltp <= fixed_support:
                signal = "BUY PUT"

            if signal == "":
                continue

            strike = best_strike(data, signal)
            opt_price = get_option_ltp(strike, signal)

            if opt_price == 0:
                continue

            sl, target = get_sl_target(opt_price)

            total_trades += 1

            msg = f"""
🔥 FINAL SIGNAL 🔥

Type: {strength}
Signal: {signal}
Strike: {strike}
Price: {opt_price}

SL: {sl}
Target: {target}

Confidence: {conf}%
Accuracy: {acc}%

Support: {fixed_support}
Resistance: {fixed_resistance}

Time: {current_time}
"""

            print(msg)
            send_telegram(msg)

            fixed_support = None
            fixed_resistance = None

            time.sleep(10)

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

run()
