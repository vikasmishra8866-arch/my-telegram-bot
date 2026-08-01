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
# Storage structure for free searches and active subscriptions
user_data = {}  # {user_id: {"free_searches": 2, "expiry": timestamp_or_None}}

def get_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {"free_searches": 2, "expiry": None}
    return user_data[user_id]

def is_subscribed(user_id):
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

# ==================== HELPER FUNCTIONS ====================
def format_date(date_str):
    if not date_str or date_str in ["N/A", "NA", "None"]:
        return "N/A"
    try:
        dt = datetime.strptime(str(date_str).split("T")[0], "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")
    except Exception:
        return str(date_str)

def clean_val(val):
    if val is None or str(val).strip() in ["", "None", "null", "N/A", "NA"]:
        return "N/A"
    return str(val).strip()

def build_vehicle_report(data):
    reg_no = clean_val(data.get("registration_number", data.get("rc_number")))
    reg_date = format_date(data.get("registration_date", data.get("rc_regn_dt")))
    author = clean_val(data.get("rto_name", data.get("registered_at")))
    rto_code = clean_val(data.get("rto_code"))
    state = clean_val(data.get("state", data.get("state_name")))
    
    owner = clean_val(data.get("owner_name", data.get("rc_owner_name")))
    serial = clean_val(data.get("owner_serial", data.get("owner_number", "1st OWNER")))
    address = clean_val(data.get("present_address", data.get("permanent_address")))
    
    model = clean_val(data.get("model", data.get("rc_model")))
    maker = clean_val(data.get("maker_name", data.get("rc_maker_desc")))
    v_class = clean_val(data.get("vehicle_class", data.get("rc_vh_class_desc")))
    body = clean_val(data.get("body_type", data.get("rc_body_type_desc")))
    color = clean_val(data.get("color", data.get("rc_color")))
    fuel = clean_val(data.get("fuel_type", data.get("rc_fuel_desc")))
    mfg_date = clean_val(data.get("mfg_date", data.get("rc_manu_month_yr")))
    chassis = clean_val(data.get("chassis_number", data.get("rc_chasi_no")))
    engine = clean_val(data.get("engine_number", data.get("rc_eng_no")))
    
    ins_company = clean_val(data.get("insurance_company", data.get("rc_insurance_comp")))
    ins_policy = clean_val(data.get("insurance_policy", data.get("rc_insurance_policy_no")))
    ins_expiry_raw = data.get("insurance_expiry", data.get("rc_insurance_upto"))
    ins_expiry = format_date(ins_expiry_raw)
    
    # Insurance status logic
    ins_status = "✅ ACTIVE"
    if ins_expiry_raw:
        try:
            exp_dt = datetime.strptime(str(ins_expiry_raw).split("T")[0], "%Y-%m-%d")
            if datetime.now() > exp_dt:
                ins_status = "⚠️ EXPIRED"
        except Exception:
            pass
            
    road_tax = clean_val(data.get("road_tax", "LTT"))
    fitness = clean_val(data.get("fitness_status", "✅ ACTIVE"))
    pucc = clean_val(data.get("pucc_status", "✅ Active"))
    legal_status = clean_val(data.get("status", "✅ ACTIVE"))

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
┠ 𝐄𝐱pixy   : {ins_expiry} {ins_status}
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
Example: `GJ05CX7222` or `DL01AB1234`
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
        # Command Format: /add <user_id> <hours/days> (e.g. /add 123456 24h or /add 123456 7d)
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
    
    # Validate vehicle number format roughly
    if len(text) < 6 or len(text) > 12:
        await bot.reply_to(message, "⚠️ **Invalid Vehicle Number!**\nPlease send a valid number like: `GJ05CX7222`", parse_mode="Markdown")
        return

    # Check Access (Free Searches or Active Subscription)
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
        # API Request
        url = f"{API_BASE_URL}{text}"
        res = requests.get(url, timeout=25)
        
        if res.status_code == 200:
            json_res = res.json()
            data = json_res.get("data", json_res)
            
            # Format and Send Report
            report = build_vehicle_report(data)
            await bot.delete_message(message.chat.id, status_msg.message_id)
            await bot.send_message(message.chat.id, report)
            
            # Deduct Free Search if not subscribed
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

# ==================== RUNNER ====================
async def run_bot():
    print("Bot is starting polling...")
    await bot.polling(non_stop=True, timeout=60)

if __name__ == "__main__":
    # Run Telegram Bot in a separate asyncio loop / thread alongside FastAPI Uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    
    # Start Uvicorn Server
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
