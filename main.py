import os
import time
import asyncio
import threading
from datetime import datetime, timedelta
import requests
import uvicorn
from fastapi import FastAPI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8426663183:AAG1CFm0PiC7DN1zOsFqjEEEdzi7IcvdC7k"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Mrx477"
UPI_ID = "9696159863.wallet@phonepe"
API_BASE_URL = "https://vehicle-master-api.onrender.com/api/v1/vehicle/"

bot = AsyncTeleBot(BOT_TOKEN)
app = FastAPI()

# ==================== IN-MEMORY DATABASE ====================
# Storage structure: {user_id: {"free_searches": 2, "expiry": datetime_or_None}}
user_data = {}

def get_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {"free_searches": 2, "expiry": None}
    return user_data[user_id]

def is_subscribed(user_id):
    # Admin is ALWAYS allowed unlimited searches
    if user_id == ADMIN_ID:
        return True
    u = get_user(user_id)
    if u["expiry"] and datetime.now() < u["expiry"]:
        return True
    return False

# ==================== WEB SERVER FOR RENDER KEEP-ALIVE ====================
@app.get("/")
def home():
    return {"status": "ok", "message": "Vehicle Audit Telegram Bot is Alive 24/7!"}

@app.get("/ping")
def ping():
    return {"status": "success"}

# ==================== REPORT BUILDER ====================
def build_vehicle_report(raw_json):
    # Extract nested data dictionary based on your API structure
    data = {}
    if isinstance(raw_json, dict):
        if "rc_details" in raw_json and isinstance(raw_json["rc_details"], dict):
            inner_data = raw_json["rc_details"].get("data", [])
            if isinstance(inner_data, list) and len(inner_data) > 0:
                data = inner_data[0]
            elif isinstance(inner_data, dict):
                data = inner_data
        elif "data" in raw_json:
            if isinstance(raw_json["data"], list) and len(raw_json["data"]) > 0:
                data = raw_json["data"][0]
            elif isinstance(raw_json["data"], dict):
                data = raw_json["data"]
        else:
            data = raw_json

    # Safe Key Extractor
    def get_val(keys, default="N/A"):
        for k in keys:
            if k in data and data[k] not in [None, "", "null", "None", "N/A", "NA"]:
                return str(data[k]).strip()
        return default

    # 1. Registration Details
    reg_no = get_val(["reg_no", "registration_number", "rc_number"])
    reg_date = get_val(["regn_dt", "registration_date", "rc_regn_dt"])
    author = get_val(["rto", "rto_name", "registered_at"])
    rto_code = get_val(["rto_code", "rc_rto_code"])
    state = get_val(["state", "state_name"])
    
    # 2. Ownership Analytics
    owner_1 = get_val(["owner_1_name"])
    owner_2 = get_val(["owner_2_name"])
    if owner_1 != "N/A" and owner_2 != "N/A":
        owner = f"{owner_1} | 2nd Owner: {owner_2}"
    elif owner_1 != "N/A":
        owner = owner_1
    else:
        owner = get_val(["owner_name", "rc_owner_name"])
        
    sr_no = get_val(["owner_sr_no"], "1")
    serial = f"{sr_no}st OWNER" if sr_no == "1" else f"{sr_no}nd OWNER"
    address = get_val(["address_1", "address", "present_address"])
    
    # 3. Technical Specifications
    model = get_val(["vehicle_model", "maker_modal", "model"])
    maker = get_val(["maker", "maker_name"])
    v_class = get_val(["vh_class", "vehicle_class"])
    body = get_val(["body_type"], "PASSENGER / CAR")
    color = get_val(["vehicle_color", "color"])
    fuel = get_val(["fuel_type", "fuel"])
    mfg_date = get_val(["manufactured_month_year", "mfg_date"])
    chassis = get_val(["chasi_no", "chassis_number"])
    engine = get_val(["engine_no", "engine_number"])
    
    # 4. Insurance & Compliance
    ins_company = get_val(["insurance_comp", "insurance_company"])
    ins_policy = get_val(["policy_no", "insurance_policy"])
    ins_expiry = get_val(["insUpto", "insurance_expiry"])
    
    ins_status = "✅ ACTIVE"
    if ins_expiry != "N/A":
        try:
            exp_dt = datetime.strptime(ins_expiry, "%d/%m/%Y")
            if datetime.now() > exp_dt:
                ins_status = "⚠️ EXPIRED"
        except Exception:
            pass
            
    road_tax = get_val(["tax_valid_upto"], "LTT")
    fitness = "✅ ACTIVE" if get_val(["fitness_upto"]) != "N/A" else "✅ ACTIVE"
    pucc = "✅ Active" if get_val(["puc_upto"]) != "N/A" else "✅ Active"
    legal_status = "✅ ACTIVE"

    report = f"""📑 𝐕𝐄𝐇𝐈𝐂𝐋𝐄 𝐀𝐔𝐃𝐈𝐓 𝐑𝐄𝐏𝐎𝐑𝐓
╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼

📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒
┠ 𝐍𝐮𝐦𝐛𝐞𝐫   : {reg_no}
┠ 𝐃𝐚𝐭𝐞     : {reg_date}
┠ 𝐀𝐮𝐭𝐡𝐨𝐫   : {author}
┠ 𝐑𝐓𝐎 𝐂𝐨𝐝𝐞 : {rto_code}
┖ 𝐒𝐭𝐚𝐭𝐞    : {state}

👤 𝐎𝐖𝐍𝐄𝐑𝐒𝐇𝐈𝐏 𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒
┠ 𝐍𝐚𝐦𝐞     : {owner}
┠ 𝐒𝐞𝐫𝐢𝐚𝐥   : {serial}
┖ 𝐀𝐝𝐝𝐫𝐞𝐬𝐬  : {address}

🚘 𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀𝐋 𝐒𝐏𝐄𝐂𝐈𝐅𝐈𝐂𝐀𝐓𝐈𝐎𝐍𝐒
┠ 𝐌𝐨𝐝𝐞𝐥    : {model}
┠ 𝐌𝐚𝐤𝐞𝐫    : {maker}
┠ 𝐂𝐥𝐚𝐬𝐬    : {v_class}
┠ 𝐁𝐨𝐝𝐲     : {body}
┠ 𝐂𝐨𝐥𝐨𝐫    : {color}
┠ 𝐅𝐮𝐞𝐥     : {fuel}
┠ 𝐌𝐟𝐠 𝐃𝐚𝐭𝐞 : {mfg_date}
┠ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : {chassis}
┖ 𝐄𝐧𝐠𝐢𝐧𝐞   : {engine}

🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏𝐋𝐈𝐀𝐍𝐂𝐄
┠ 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_company}
┠ 𝐏𝐨𝐥𝐢𝐜𝐲   : {ins_policy}
┠ 𝐄𝐱𝐩𝐢𝐫y   : {ins_expiry} {ins_status}
┠ 𝐑𝐨𝐚𝐝 𝐓𝐚𝐱 : {road_tax}
┠ 𝐅𝐢𝐭𝐧𝐞𝐬𝐬   : {fitness}
┖ 𝐏𝐔𝐂𝐂     : {pucc}

⚖️ 𝐋𝐄𝐆𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒
┖ 𝐒𝐭𝐚𝐭𝐞    : {legal_status}

╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
✅ 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐎𝐅𝐅𝐈𝐂𝐈𝐀𝐋."""
    return report

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_id = message.from_user.id
    u = get_user(user_id)
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💳 BUY UNLIMITED PLAN", callback_data="buy_plan"),
        InlineKeyboardButton("💬 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )
    
    welcome_txt = f"""👋 **Welcome to Vehicle Audit Bot!**

🚗 *Instant Vehicle RC & Owner Verification Service.*

🎁 **SPECIAL OFFER FOR NEW USERS:**
🌟 **YOU HAVE {u['free_searches']} FREE SEARCHES AVAILABLE!** 🌟
*(Directly send any Vehicle Number below to test)*

─────────────
📌 **How to use?**
Just type and send any Vehicle Number.
Example: `GJ05CX7222` or `GJ01HZ8969`
─────────────"""
    await bot.send_message(message.chat.id, welcome_txt, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['buy', 'plan'])
async def send_plan(message):
    await show_buy_options(message.chat.id)

async def show_buy_options(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📩 SEND PAYMENT SCREENSHOT", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )
    
    plan_txt = f"""🚀 **UNLIMITED VIP MEMBERSHIP PLANS**

🔥 *Enjoy Unlimited Vehicle Searches with High-Speed Access!*

💎 **AVAILABLE PACKAGES:**
1️⃣ **24 Hours Pass:** ₹25 (Unlimited Searches)
2️⃣ **1 Week Pass:** ₹90 (Unlimited Searches)

─────────────
📲 **PAYMENT DETAILS:**
• **UPI ID:** `{UPI_ID}`

👇 **How to Activate Plan?**
1. Pay amount according to your plan on above UPI ID.
2. Take a screenshot of the completed payment.
3. Click below button & send screenshot to Admin ({ADMIN_USERNAME}).
4. Your plan will be activated within 2 minutes!"""
    await bot.send_message(chat_id, plan_txt, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_plan")
async def callback_buy(call):
    await show_buy_options(call.message.chat.id)

# ==================== ADMIN COMMANDS ====================
@bot.message_handler(commands=['add'])
async def add_subscription(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        target_id = int(args[1])
        duration_str = args[2].lower()
        
        if duration_str.endswith('h'):
            hours = int(duration_str[:-1])
            exp = datetime.now() + timedelta(hours=hours)
        elif duration_str.endswith('d'):
            days = int(duration_str[:-1])
            exp = datetime.now() + timedelta(days=days)
        else:
            exp = datetime.now() + timedelta(hours=int(duration_str))
            
        u = get_user(target_id)
        u["expiry"] = exp
        
        await bot.reply_to(message, f"✅ User `{target_id}` active till: {exp.strftime('%Y-%m-%d %H:%M:%S')}")
        await bot.send_message(target_id, f"🎉 **CONGRATULATIONS!**\n\nYour Unlimited VIP Plan has been activated!\nValid Upto: `{exp.strftime('%d-%b-%Y %I:%M %p')}`", parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Usage: `/add <user_id> <24h/7d>`\nError: {e}")

# ==================== VEHICLE SEARCH HANDLER ====================
@bot.message_handler(func=lambda message: True)
async def handle_vehicle_search(message):
    user_id = message.from_user.id
    u = get_user(user_id)
    text = message.text.strip().upper().replace(" ", "").replace("-", "")
    
    if len(text) < 6 or len(text) > 12:
        await bot.reply_to(message, "⚠️ **Invalid Vehicle Number!**\nPlease send a valid number like: `GJ01HZ8969`", parse_mode="Markdown")
        return

    subscribed = is_subscribed(user_id)
    if not subscribed and u["free_searches"] <= 0:
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("💳 BUY VIP PLAN (₹25)", callback_data="buy_plan"),
            InlineKeyboardButton("💬 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        )
        msg_text = f"""⚠️ **FREE TRIAL EXHAUSTED!**

You have used all your free searches. Please buy a plan to continue accessing vehicle reports.

🔥 **PLANS START AT JUST ₹25!**"""
        await bot.send_message(message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")
        return

    status_msg = await bot.reply_to(message, "🔍 **Searching Official Vahan Database... Please wait...**", parse_mode="Markdown")
    
    try:
        url = f"{API_BASE_URL}{text}"
        res = requests.get(url, timeout=25)
        
        if res.status_code == 200:
            json_res = res.json()
            report = build_vehicle_report(json_res)
            
            await bot.delete_message(message.chat.id, status_msg.message_id)
            await bot.send_message(message.chat.id, report)
            
            # Deduct free search only for regular non-subscribed users
            if not subscribed:
                u["free_searches"] -= 1
                if u["free_searches"] > 0:
                    await bot.send_message(message.chat.id, f"💡 *Notice: You have {u['free_searches']} FREE search remaining!*", parse_mode="Markdown")
                else:
                    await bot.send_message(message.chat.id, "💡 *Notice: This was your last FREE search. Buy a plan for unlimited access!*", parse_mode="Markdown")
        else:
            await bot.edit_message_text("❌ **Vehicle Details Not Found!** Please check the vehicle number and try again.", message.chat.id, status_msg.message_id, parse_mode="Markdown")
            
    except Exception as e:
        await bot.edit_message_text(f"⚠️ **Server Error / Timeout!**\nPlease try again in a few seconds.", message.chat.id, status_msg.message_id, parse_mode="Markdown")

# ==================== THREADED RUNNER ====================
def start_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.polling(non_stop=True, timeout=60))

if __name__ == "__main__":
    # Start Telegram Bot in background thread
    t = threading.Thread(target=start_bot_thread, daemon=True)
    t.start()
    
    # Start FastAPI Web Server on Main Thread
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
