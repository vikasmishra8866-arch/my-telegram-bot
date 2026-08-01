import os
import time
import asyncio
import threading
import urllib.parse
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
user_data = {}
# Stores active QR message info: {user_id: msg_id}
user_qr_messages = {}

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

# ==================== DATE HELPER FUNCTION ====================
def check_compliance_status(date_str):
    if not date_str or date_str in ["N/A", "NA", "None", "null", ""]:
        return "❌ EXPIRED (N/A)"
    
    clean_date = date_str.split("T")[0].strip()
    parsed_date = None
    
    # Try parsing common formats
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            parsed_date = datetime.strptime(clean_date, fmt)
            break
        except ValueError:
            pass

    if parsed_date:
        if parsed_date < datetime.now():
            return f"❌ EXPIRED ({parsed_date.strftime('%d/%m/%Y')})"
        else:
            return f"✅ ACTIVE ({parsed_date.strftime('%d/%m/%Y')})"
    
    # Fallback status check
    if "EXPIRE" in str(date_str).upper():
        return f"❌ EXPIRED ({clean_date})"
    return f"✅ ACTIVE ({clean_date})"

# ==================== REPORT BUILDER ====================
def build_vehicle_report(raw_json):
    data = raw_json
    if isinstance(raw_json, dict):
        if "rc_details" in raw_json and isinstance(raw_json["rc_details"], dict):
            inner = raw_json["rc_details"].get("data", raw_json["rc_details"])
            data = inner[0] if isinstance(inner, list) and len(inner) > 0 else inner
        elif "data" in raw_json:
            inner = raw_json["data"]
            data = inner[0] if isinstance(inner, list) and len(inner) > 0 else inner

    if not isinstance(data, dict):
        data = {}

    def get_val(keys, default=None):
        for k in keys:
            if k in data and data[k] not in [None, "", "null", "None", "N/A", "NA"]:
                return str(data[k]).strip()
        return default

    # 1. Registration Details (Author removed)
    reg_no = get_val(["reg_no", "registration_number", "rc_number", "regNo"], "N/A")
    reg_date = get_val(["regn_dt", "registration_date", "rc_regn_dt", "reg_date"], "N/A")
    rto_code = get_val(["rto_code", "rc_rto_code", "rtoCode"], "N/A")
    state = get_val(["state", "state_name", "state_code"], "N/A")
    
    # 2. Ownership Analytics
    owner_1 = get_val(["owner_1_name"])
    owner_2 = get_val(["owner_2_name"])
    if owner_1 and owner_2:
        owner = f"{owner_1} | 2nd Owner: {owner_2}"
    elif owner_1:
        owner = owner_1
    else:
        owner = get_val(["owner_name", "rc_owner_name", "owner"], "N/A")
        
    sr_no = get_val(["owner_sr_no", "owner_serial", "owner_number"], "1")
    serial = f"{sr_no}st OWNER" if sr_no in ["1", "1st"] else f"{sr_no}nd OWNER" if sr_no in ["2", "2nd"] else f"{sr_no} OWNER"
    address = get_val(["address_1", "present_address", "address", "permanent_address"], "N/A")
    
    # 3. Technical Specifications
    model = get_val(["vehicle_model", "maker_modal", "model", "rc_model"], "N/A")
    maker = get_val(["maker", "maker_name", "rc_maker_desc"], "N/A")
    v_class = get_val(["vh_class", "vehicle_class", "rc_vh_class_desc"], "N/A")
    
    # Body Type: Show ONLY if returned validly from API
    body_val = get_val(["body_type", "rc_body_type_desc"])
    body_line = f"┠ 𝐁𝐨𝐝𝐲     : {body_val}\n" if body_val else ""
    
    color = get_val(["vehicle_color", "color", "rc_color"], "N/A")
    fuel = get_val(["fuel_type", "fuel", "rc_fuel_desc"], "N/A")
    mfg_date = get_val(["manufactured_month_year", "mfg_date", "rc_manu_month_yr"], "N/A")
    chassis = get_val(["chasi_no", "chassis_number", "rc_chasi_no"], "N/A")
    engine = get_val(["engine_no", "engine_number", "rc_eng_no"], "N/A")
    
    # 4. Insurance & Compliance (Old Date Check Logic Applied)
    ins_company = get_val(["insurance_comp", "insurance_company", "rc_insurance_comp"], "N/A")
    ins_policy = get_val(["policy_no", "insurance_policy", "rc_insurance_policy_no"], "N/A")
    ins_expiry_raw = get_val(["insUpto", "insurance_expiry", "rc_insurance_upto"])
    ins_status = check_compliance_status(ins_expiry_raw)
    
    road_tax = get_val(["tax_valid_upto", "road_tax"], "LTT")
    
    fitness_raw = get_val(["fitness_upto", "fitness_status"])
    fitness = check_compliance_status(fitness_raw)
    
    puc_raw = get_val(["puc_upto", "pucc_status"])
    pucc = check_compliance_status(puc_raw)
    
    legal_status = get_val(["status", "blacklist_status"], "SUCCESS")

    report = f"""📑 𝐕𝐄𝐇𝐈𝐂𝐋𝐄 𝐀𝐔𝐃𝐈𝐓 𝐑𝐄𝐏𝐎𝐑𝐓
╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼

📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒
┠ 𝐍𝐮𝐦𝐛𝐞𝐫   : {reg_no}
┠ 𝐃𝐚𝐭𝐞     : {reg_date}
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
{body_line}┠ 𝐁𝐨𝐝𝐲     : {color}
┠ 𝐅𝐮𝐞𝐥     : {fuel}
┠ 𝐌𝐟𝐠 𝐃𝐚𝐭𝐞 : {mfg_date}
┠ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : {chassis}
┖ 𝐄𝐧𝐠𝐢𝐧𝐞   : {engine}

🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏𝐋𝐈𝐀𝐍𝐂𝐄
┠ 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_company}
┠ 𝐏𝐨𝐥𝐢𝐜𝐲   : {ins_policy}
┠ 𝐄𝐱𝐩𝐢𝐫𝐲   : {ins_status}
┠ 𝐑𝐨𝐚𝐝 𝐓𝐚𝐱 : {road_tax}
┠ 𝐅𝐢𝐭𝐧𝐞𝐬𝐬   : {fitness}
┖ 𝐏𝐔𝐂𝐂     : {pucc}

⚖️ 𝐋𝐄𝐆𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒
┖ 𝐒𝐭𝐚𝐭𝐞    : {legal_status}

╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
✅ 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐎𝐅𝐅𝐈𝐂𝐈𝐀𝐋.

⏳ *Note: This message will self-destruct in 10 minutes.*"""
    return report

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_id = message.from_user.id
    u = get_user(user_id)
    
    markup = InlineKeyboardMarkup()
    if user_id == ADMIN_ID:
        status_txt = "👑 **ADMIN ACCESS: UNLIMITED SEARCHES ACTIVE!** 👑"
        markup.add(
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        )
    else:
        status_txt = f"🌟 **YOU HAVE {u['free_searches']} FREE SEARCHES AVAILABLE!** 🌟"
        markup.add(
            InlineKeyboardButton("💳 BUY UNLIMITED PLAN", callback_data="buy_plan"),
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        )
    
    welcome_txt = f"""👋 **Welcome to Vehicle Audit Bot!**

🚗 *Instant Vehicle RC & Owner Verification Service.*

🎁 **ACCOUNT STATUS:**
{status_txt}
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
    markup.row(
        InlineKeyboardButton("⚡ 24 Hour Pass (₹25)", callback_data="gen_qr_25"),
        InlineKeyboardButton("🚀 1 Week Pass (₹90)", callback_data="gen_qr_90")
    )
    markup.row(
        InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )
    
    plan_txt = f"""🚀 **UNLIMITED VIP MEMBERSHIP PLANS**

🔥 *Enjoy Unlimited Vehicle Searches with Instant Speed!*

💎 **SELECT YOUR PLAN BELOW:**
1️⃣ **24 Hours Pass:** ₹25 (Unlimited Searches)
2️⃣ **1 Week Pass:** ₹90 (Unlimited Searches)

👇 Click on a button below to generate payment QR Code!"""
    await bot.send_message(chat_id, plan_txt, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_plan")
async def callback_buy(call):
    await show_buy_options(call.message.chat.id)

# ==================== DYNAMIC QR GENERATOR HANDLER ====================
@bot.callback_query_handler(func=lambda call: call.data in ["gen_qr_25", "gen_qr_90"])
async def handle_qr_generation(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    amount = 25 if call.data == "gen_qr_25" else 90
    plan_name = "24 Hour Pass" if amount == 25 else "1 Week Pass"

    # 1. Delete previous QR message if user selects another plan
    if user_id in user_qr_messages:
        try:
            await bot.delete_message(chat_id, user_qr_messages[user_id])
        except Exception:
            pass

    # 2. Build UPI Payment String & QR Image URL
    upi_uri = f"upi://pay?pa={UPI_ID}&pn=VehicleAudit&am={amount}&cu=INR&tn={urllib.parse.quote('VIP Plan Access')}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_uri)}"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("👑 SEND PAYMENT SCREENSHOT", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )

    caption = f"""💳 **PAYMENT QR CODE FOR ₹{amount}**

📌 **Plan Selected:** {plan_name}
💰 **Amount to Pay:** ₹{amount}
📲 **UPI ID:** `{UPI_ID}`

⚠️ *Scan & Pay within 5 minutes. Take a screenshot after payment and send it to Admin ({ADMIN_USERNAME}) for instant activation.*

⏳ *This QR Code will auto-expire in 5 minutes.*"""

    # Send QR Code photo
    qr_msg = await bot.send_photo(chat_id, photo=qr_url, caption=caption, parse_mode="Markdown", reply_markup=markup)
    user_qr_messages[user_id] = qr_msg.message_id

    # Background task: Auto-delete QR code after 5 minutes (300 seconds)
    async def delete_qr_later(c_id, m_id, u_id):
        await asyncio.sleep(300)
        try:
            await bot.delete_message(c_id, m_id)
            if user_qr_messages.get(u_id) == m_id:
                del user_qr_messages[u_id]
        except Exception:
            pass

    asyncio.create_task(delete_qr_later(chat_id, qr_msg.message_id, user_id))

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
        
        await bot.reply_to(message, f"👑 **[ADMIN]** User `{target_id}` active till: {exp.strftime('%Y-%m-%d %H:%M:%S')}")
        await bot.send_message(target_id, f"🎉 **CONGRATULATIONS!**\n\nYour Unlimited VIP Plan has been activated by Admin 👑!\nValid Upto: `{exp.strftime('%d-%b-%Y %I:%M %p')}`", parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Usage: `/add <user_id> <24h/7d>`\nError: {e}")

# ==================== VEHICLE SEARCH HANDLER ====================
@bot.message_handler(func=lambda message: True)
async def handle_vehicle_search(message):
    user_id = message.from_user.id
    u = get_user(user_id)
    text = message.text.strip().upper().replace(" ", "").replace("-", "")
    
    if len(text) < 6 or len(text) > 12:
        await bot.reply_to(message, "⚠️ **Invalid Vehicle Number!**\nPlease send a valid number like: `GJ05HG7801`", parse_mode="Markdown")
        return

    subscribed = is_subscribed(user_id)
    if not subscribed and u["free_searches"] <= 0:
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("💳 BUY VIP PLAN (₹25)", callback_data="buy_plan"),
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
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
            report_msg = await bot.send_message(message.chat.id, report, parse_mode="Markdown")
            
            # Auto-delete audit report after 10 minutes (600 seconds)
            async def delete_report_later(c_id, m_id):
                await asyncio.sleep(600)
                try:
                    await bot.delete_message(c_id, m_id)
                except Exception:
                    pass

            asyncio.create_task(delete_report_later(message.chat.id, report_msg.message_id))
            
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
    t = threading.Thread(target=start_bot_thread, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
