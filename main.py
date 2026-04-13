import requests
import time
from datetime import datetime, timedelta

# ===== CONFIG =====
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiJFVTkzNDciLCJqdGkiOiI2OWRjNjc1MDhmNDVmNDU3Y2EwNzMzYTgiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2MDUyMDQ4LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzYxMTc2MDB9.O-tu4MQpEkst0EXZyfPZPZ9bSdcViigsyyJxcU91i0Y"
BOT_TOKEN = "8726435378:AAEhAviD-pwjF-IY-wYcUVlPBKYZIjpBXB4"
CHAT_ID = "-1003724403519"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# ===== GLOBAL =====
prev_data = {}
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
def get_option_ltp(strike, option_type):
    try:
        symbol = f"NSE_FO|NIFTY {strike} {option_type}"
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
    strikes = [atm-100, atm-50, atm, atm+50, atm+100]
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

# ===== TREND =====
def oi_trend(data):
    ce = sum(d['ce_chg'] for d in data)
    pe = sum(d['pe_chg'] for d in data)

    if pe > ce:
        return "BULLISH"
    elif ce > pe:
        return "BEARISH"
    return "NEUTRAL"

# ===== CONFIDENCE =====
def confidence(data):
    score = 0
    for d in data:
        if d['pe'] > d['ce'] and d['pe_chg'] > 0:
            score += 1
        if d['ce'] > d['pe'] and d['ce_chg'] > 0:
            score += 1
    return round((score / 10) * 100, 2)

# ===== ACCURACY =====
def get_accuracy():
    if total_trades == 0:
        return 0
    return round((wins / total_trades) * 100, 2)

# ===== BEST STRIKE =====
def best_strike(data, signal):
    best = None
    max_change = 0

    for d in data:
        if "CALL" in signal and d['pe_chg'] > max_change:
            max_change = d['pe_chg']
            best = d['strike']

        elif "PUT" in signal and d['ce_chg'] > max_change:
            max_change = d['ce_chg']
            best = d['strike']

    return best

# ===== SL TARGET =====
def get_trade_levels(price):
    return price - 10, price + 20

# ===== MAIN =====
def run():
    global prev_price, total_trades

    print("🚀 SYSTEM STARTED")
    send_telegram("✅ SYSTEM STARTED")

    while True:
        try:
            ltp = get_ltp()
            atm = get_atm(ltp)
            chain = get_chain()

            if not chain:
                time.sleep(3)
                continue

            data = get_data(chain, atm)
            support, resistance = get_sr(data)

            print(f"LTP: {ltp} | S: {support} | R: {resistance}")

            # SIDEWAYS
            price_move = abs(ltp - prev_price)
            prev_price = ltp

            if price_move < 3:
                print("SIDEWAYS")
                time.sleep(5)
                continue

            trend = oi_trend(data)
            conf = confidence(data)
            acc = get_accuracy()

            print(f"Trend: {trend} | Conf: {conf} | Acc: {acc}")

            # 🔥 ACCURACY FILTER
            if acc < 50 and total_trades > 5:
                print("Low Accuracy - Skip Trade")
                time.sleep(5)
                continue

            if conf < 35:
                print("Low Confidence")
                time.sleep(5)
                continue

            signal = ""

            if trend == "BULLISH" and ltp >= resistance - 5:
                signal = "BUY CALL"

            elif trend == "BEARISH" and ltp <= support + 5:
                signal = "BUY PUT"

            if signal == "":
                time.sleep(5)
                continue

            strike = best_strike(data, signal)

            if not strike:
                continue

            opt_ltp = get_option_ltp(strike, "CE" if "CALL" in signal else "PE")
            sl, target = get_trade_levels(opt_ltp)

            total_trades += 1

            msg = f"""
🔥 SIGNAL ALERT 🔥
Signal: {signal}
Strike: {strike}
Price: {opt_ltp}
SL: {sl}
Target: {target}
Confidence: {conf}%
Accuracy: {acc}%
"""

            print(msg)
            send_telegram(msg)

            time.sleep(10)

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

run()
