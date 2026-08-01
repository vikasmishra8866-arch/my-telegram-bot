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
user_qr_messages = {}

def get_user(user_id, first_name="User", username=""):
    if user_id not in user_data:
        user_data[user_id] = {
            "first_name": first_name,
            "username": username,
            "free_searches": 2,
            "expiry": None,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        # Update name/username dynamically
        user_data[user_id]["first_name"] = first_name
        user_data[user_id]["username"] = username
    return user_data[user_id]

def is_subscribed(user_id):
    if user_id == ADMIN_ID:
        return True
    u = user_data.get(user_id)
    if u and u["expiry"] and datetime.now() < u["expiry"]:
        return True
    return False

# ==================== WEB SERVER ====================
@app.get("/")
def home():
    return {"status": "ok", "message": "Vehicle Audit Telegram Bot Admin Panel Active!"}

# ==================== DATE HELPER ====================
def check_compliance_status(date_str):
    if not date_str or date_str in ["N/A", "NA", "None", "null", ""]:
        return "❌ EXPIRED (N/A)"
    
    clean_date = date_str.split("T")[0].strip()
    parsed_date = None
    
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

    reg_no = get_val(["reg_no", "registration_number", "rc_number", "regNo"], "N/A")
    reg_date = get_val(["regn_dt", "registration_date", "rc_regn_dt", "reg_date"], "N/A")
    rto_code = get_val(["rto_code", "rc_rto_code", "rtoCode"], "N/A")
    state = get_val(["state", "state_name", "state_code"], "N/A")
    
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
    
    model = get_val(["vehicle_model", "maker_modal", "model", "rc_model"], "N/A")
    maker = get_val(["maker", "maker_name", "rc_maker_desc"], "N/A")
    v_class = get_val(["vh_class", "vehicle_class", "rc_vh_class_desc"], "N/A")
    
    body_val = get_val(["body_type", "rc_body_type_desc"])
    body_line = f"┠ 𝐁𝐨𝐝𝐲     : {body_val}\n" if body_val else ""
    
    color = get_val(["vehicle_color", "color", "rc_color"], "N/A")
    fuel = get_val(["fuel_type", "fuel", "rc_fuel_desc"], "N/A")
    mfg_date = get_val(["manufactured_month_year", "mfg_date", "rc_manu_month_yr"], "N/A")
    chassis = get_val(["chasi_no", "chassis_number", "rc_chasi_no"], "N/A")
    engine = get_val(["engine_no", "engine_number", "rc_eng_no"], "N/A")
    
    ins_company = get_val(["insurance_comp", "insurance_company", "rc_insurance_comp"], "N/A")
    ins_policy = get_val(["policy_no", "insurance_policy", "rc_insurance_policy_no"], "N/A")
    ins_status = check_compliance_status(get_val(["insUpto", "insurance_expiry", "rc_insurance_upto"]))
    
    road_tax = get_val(["tax_valid_upto", "road_tax"], "LTT")
    fitness = check_compliance_status(get_val(["fitness_upto", "fitness_status"]))
    pucc = check_compliance_status(get_val(["puc_upto", "pucc_status"]))
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
{body_line}┠ 𝐂𝐨𝐥𝐨𝐫    : {color}
┠ 𝐅𝐮𝐞𝐥     : {fuel}
┠ 𝐌𝐟𝐠 𝐃𝐚𝐭𝐞 : {mfg_date}
┠ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : {chassis}
┖ 𝐄𝐧𝐠𝐢𝐧𝐞   : {engine}

🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏𝐋𝐈𝐀𝐍𝐂𝐄
┠ 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_company}
┠ 𝐏𝐨𝐥𝐢𝐜𝐲   : {ins_policy}
┠ 𝐄𝐱𝐩𝐢𝐫𝐲   : {ins_status}
┠ 𝐑𝐨𝐚𝐝 𝐓𝐚x : {road_tax}
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
    u = get_user(user_id, message.from_user.first_name, message.from_user.username or "")
    
    markup = InlineKeyboardMarkup()
    if user_id == ADMIN_ID:
        status_txt = "👑 **ADMIN ACCESS: UNLIMITED SEARCHES ACTIVE!** 👑"
        markup.add(
            InlineKeyboardButton("👑 ADMIN PANEL (/panel)", callback_data="open_panel")
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

─────────────
📌 **How to use?**
Send any Vehicle Number (e.g. `GJ05HG7801`)
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

💎 **SELECT YOUR PLAN BELOW:**
1️⃣ **24 Hours Pass:** ₹25
2️⃣ **1 Week Pass:** ₹90

👇 Click on a button below to generate payment QR Code!"""
    await bot.send_message(chat_id, plan_txt, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_plan")
async def callback_buy(call):
    await show_buy_options(call.message.chat.id)

# ==================== DYNAMIC QR & ADMIN ALERT ====================
@bot.callback_query_handler(func=lambda call: call.data in ["gen_qr_25", "gen_qr_90"])
async def handle_qr_generation(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    amount = 25 if call.data == "gen_qr_25" else 90
    plan_name = "24 Hour Pass" if amount == 25 else "1 Week Pass"

    if user_id in user_qr_messages:
        try:
            await bot.delete_message(chat_id, user_qr_messages[user_id])
        except Exception:
            pass

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

⏳ *This QR Code will auto-expire in 5 minutes.*"""

    qr_msg = await bot.send_photo(chat_id, photo=qr_url, caption=caption, parse_mode="Markdown", reply_markup=markup)
    user_qr_messages[user_id] = qr_msg.message_id

    # 🚨 INSTANT ALERT TO ADMIN WITH DIRECT APPROVAL BUTTONS
    admin_markup = InlineKeyboardMarkup()
    admin_markup.row(
        InlineKeyboardButton("✅ Give 24h Access", callback_data=f"adm_give_{user_id}_24h"),
        InlineKeyboardButton("✅ Give 7D Access", callback_data=f"adm_give_{user_id}_7d")
    )
    
    admin_alert = f"""🔔 **NEW PAYMENT QR GENERATED!**

👤 **User:** {call.from_user.first_name} (@{call.from_user.username or 'No Username'})
🆔 **User ID:** `{user_id}`
💰 **Plan Selected:** ₹{amount} ({plan_name})

👇 *Click below button to give instant VIP Access after verifying payment:*"""
    
    try:
        await bot.send_message(ADMIN_ID, admin_alert, parse_mode="Markdown", reply_markup=admin_markup)
    except Exception:
        pass

    async def delete_qr_later(c_id, m_id, u_id):
        await asyncio.sleep(300)
        try:
            await bot.delete_message(c_id, m_id)
            if user_qr_messages.get(u_id) == m_id:
                del user_qr_messages[u_id]
        except Exception:
            pass

    asyncio.create_task(delete_qr_later(chat_id, qr_msg.message_id, user_id))

# ==================== ADMIN PANEL COMMANDS ====================
@bot.message_handler(commands=['panel', 'users'])
async def show_admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    if not user_data:
        await bot.reply_to(message, "📊 **No users registered yet!**", parse_mode="Markdown")
        return

    txt = f"👑 **VEHICLE AUDIT BOT ADMIN PANEL**\n\nTotal Registered Users: `{len(user_data)}`\n\n"
    
    for uid, uinfo in list(user_data.items()):
        status = "🟢 VIP Active" if is_subscribed(uid) else f"🔴 Free ({uinfo['free_searches']} left)"
        txt += f"👤 **{uinfo['first_name']}** (@{uinfo['username'] or 'N/A'})\n🆔 ID: `{uid}` | Status: {status}\n"
        
        # Action Buttons for each user
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("⚡ Give 24h", callback_data=f"adm_give_{uid}_24h"),
            InlineKeyboardButton("🚀 Give 7D", callback_data=f"adm_give_{uid}_7d"),
            InlineKeyboardButton("❌ Revoke", callback_data=f"adm_revoke_{uid}")
        )
        await bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=markup)
        txt = "" # Reset text for next iteration

# ==================== ADMIN CALLBACK BUTTON HANDLERS ====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
async def handle_admin_actions(call):
    if call.from_user.id != ADMIN_ID:
        return

    parts = call.data.split("_")
    action = parts[1]
    target_id = int(parts[2])

    u = user_data.get(target_id, {"free_searches": 2, "expiry": None})

    if action == "give":
        duration = parts[3]
        if duration == "24h":
            exp = datetime.now() + timedelta(hours=24)
            p_text = "24 Hours"
        elif duration == "7d":
            exp = datetime.now() + timedelta(days=7)
            p_text = "7 Days"

        u["expiry"] = exp
        user_data[target_id] = u

        await bot.answer_callback_query(call.id, f"✅ VIP Plan Activated for {target_id}!")
        await bot.send_message(ADMIN_ID, f"🎉 **VIP Plan ({p_text}) activated for User ID:** `{target_id}`", parse_mode="Markdown")
        
        # Send Notification to User
        try:
            await bot.send_message(target_id, f"🎉 **CONGRATULATIONS!**\n\nYour Unlimited VIP Plan ({p_text}) has been activated by Admin 👑!\nValid Upto: `{exp.strftime('%d-%b-%Y %I:%M %p')}`", parse_mode="Markdown")
        except Exception:
            pass

    elif action == "revoke":
        u["expiry"] = None
        user_data[target_id] = u
        await bot.answer_callback_query(call.id, f"❌ Access Revoked for {target_id}")
        await bot.send_message(ADMIN_ID, f"❌ **Access Revoked for User ID:** `{target_id}`", parse_mode="Markdown")

# ==================== VEHICLE SEARCH HANDLER ====================
@bot.message_handler(func=lambda message: True)
async def handle_vehicle_search(message):
    user_id = message.from_user.id
    u = get_user(user_id, message.from_user.first_name, message.from_user.username or "")
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

You have used all your free searches. Please buy a plan to continue accessing vehicle reports."""
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
            
            async def delete_report_later(c_id, m_id):
                await asyncio.sleep(600)
                try:
                    await bot.delete_message(c_id, m_id)
                except Exception:
                    pass

            asyncio.create_task(delete_report_later(message.chat.id, report_msg.message_id))
            
            if not subscribed:
                u["free_searches"] -= 1
                if u["free_searches"] > 0:
                    await bot.send_message(message.chat.id, f"💡 *Notice: You have {u['free_searches']} FREE search remaining!*", parse_mode="Markdown")
                else:
                    await bot.send_message(message.chat.id, "💡 *Notice: This was your last FREE search. Buy a plan for unlimited access!*", parse_mode="Markdown")
        else:
            await bot.edit_message_text("❌ **Vehicle Details Not Found!** Please check the vehicle number.", message.chat.id, status_msg.message_id, parse_mode="Markdown")
            
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
