import os
import time
import json
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
from google import genai
from google.genai import types

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8426663183:AAG1CFm0PiC7DN1zOsFqjEEEdzi7IcvdC7k"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Mrx477"
UPI_ID = "9696159863.wallet@phonepe"
API_BASE_URL = "https://vehicle-master-api.onrender.com/api/v1/vehicle/"

# Gemini API Key (Environment variable set on Render)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6KTdpvqaoByPb4AWLZv0w0JoD6cDWTX5EMVxX_9NMQMaQ")
ai_client = genai.Client(api_key=GEMINI_API_KEY)

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
        user_data[user_id]["first_name"] = first_name
        user_data[user_id]["username"] = username
    return user_data[user_id]

def is_subscribed(user_id):
    if user_id == ADMIN_ID:
        return True
    u = user_data.get(user_id)
    if u and u.get("expiry") and datetime.now() < u["expiry"]:
        return True
    return False

# ==================== WEB SERVER ====================
@app.get("/")
@app.head("/")
def home():
    return {"status": "ok", "message": "Vehicle Audit Telegram Bot Active!"}

# ==================== GEMINI AI ENGINE ====================
async def process_data_with_gemini_async(raw_api_response):
    """
    Passes raw API response to Gemini AI asynchronously with a 15-second timeout 
    and strictly enforced JSON schema structure.
    """
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "reg_no": {"type": "STRING"},
            "reg_date": {"type": "STRING"},
            "mfg_date": {"type": "STRING"},
            "state": {"type": "STRING"},
            "owner_name": {"type": "STRING"},
            "owner_serial": {"type": "STRING"},
            "address": {"type": "STRING"},
            "model": {"type": "STRING"},
            "maker": {"type": "STRING"},
            "v_class": {"type": "STRING"},
            "body_type": {"type": "STRING"},
            "fuel_type": {"type": "STRING"},
            "emission_norm": {"type": "STRING"},
            "cubic_capacity": {"type": "STRING"},
            "seating_capacity": {"type": "STRING"},
            "unladen_weight": {"type": "STRING"},
            "wheelbase": {"type": "STRING"},
            "number_of_cylinders": {"type": "STRING"},
            "chassis_no": {"type": "STRING"},
            "engine_no": {"type": "STRING"},
            "insurance_company": {"type": "STRING"},
            "insurance_policy": {"type": "STRING"},
            "insurance_expiry": {"type": "STRING"},
            "finance_status": {"type": "STRING"},
            "financer": {"type": "STRING"},
            "fitness_upto": {"type": "STRING"},
            "puc_no": {"type": "STRING"},
            "puc_expiry": {"type": "STRING"},
            "blacklist_status": {"type": "STRING"},
            "permit_no": {"type": "STRING"},
            "status": {"type": "STRING"}
        },
        "required": ["reg_no", "owner_name", "status"]
    }

    prompt = f"""
You are an expert Vehicle Data Extractor and Automotive Knowledge System.
Analyze the raw vehicle JSON below and fill all fields in the JSON schema accurately.

RAW VEHICLE API RESPONSE:
{json.dumps(raw_api_response)}

RULES:
1. Extract all available data from the input JSON regardless of key name variations (e.g. 'ownerName', 'owner_name', 'rc_owner_name').
2. Dynamic Owner/Address Handling: If owner serial exists, pick the highest count owner name. If missing/equal, combine distinct names or addresses using '/'.
3. Smart Specification Enrichment: For missing technical specs ('cubic_capacity', 'unladen_weight', 'wheelbase', 'number_of_cylinders', 'emission_norm'), supply precise values based on Maker & Model from your official automotive database.
4. If any field is truly unavailable or unknown, set its value strictly to "NA".
5. Set 'status' strictly as "SUCCESS" or "Active" if valid vehicle data exists.
"""

    def call_gemini():
        return ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )

    try:
        # 15 Seconds strict timeout
        response = await asyncio.wait_for(
            asyncio.to_thread(call_gemini), 
            timeout=15.0
        )
        return json.loads(response.text)
    except asyncio.TimeoutError:
        print("⚠️ Gemini API Call Timed Out (> 15 seconds)!")
        return None
    except Exception as e:
        print(f"❌ Error during Gemini processing: {e}")
        return None

# ==================== REPORT BUILDER ====================
async def build_vehicle_report(raw_json):
    ai_data = await process_data_with_gemini_async(raw_json)
    
    # Fallback to empty dict if Gemini fails or times out
    if not ai_data or not isinstance(ai_data, dict):
        ai_data = {}

    def get_val(key, default="NA"):
        val = ai_data.get(key)
        if val in [None, "", "null", "None", "N/A", "NA"]:
            return default
        return str(val).strip()

    # Field Extraction
    reg_no = get_val("reg_no").upper()
    reg_date = get_val("reg_date")
    mfg_loc = get_val("mfg_date")
    state = get_val("state")

    owner = get_val("owner_name")
    serial = get_val("owner_serial")
    address = get_val("address")

    model_disp = get_val("model")
    maker = get_val("maker")
    v_class = get_val("v_class")
    body_val = get_val("body_type")
    fuel = get_val("fuel_type")
    emission = get_val("emission_norm")
    cubic_cap = get_val("cubic_capacity")
    seating = get_val("seating_capacity")
    chassis = get_val("chassis_no")
    engine = get_val("engine_no")

    unladen_wt = get_val("unladen_weight")
    wheelbase = get_val("wheelbase")
    cylinders = get_val("number_of_cylinders")

    ins_company = get_val("insurance_company")
    ins_policy = get_val("insurance_policy")
    ins_exp = get_val("insurance_expiry")
    fin_status = get_val("finance_status")
    financer = get_val("financer")
    fitness_val = get_val("fitness_upto")
    puc_no = get_val("puc_no")
    puc_val = get_val("puc_expiry")

    blacklist = get_val("blacklist_status")
    permit = get_val("permit_no")
    status = get_val("status")
    status_disp = "✅ SUCCESS" if status.upper() in ["SUCCESS", "ACTIVE"] else status

    # REPORT TEMPLATE
    report = f"""╭──────────────╮
🚀 𝙑𝘼𝙃𝘼𝙉 𝘿𝙀𝙀𝙋 𝘼𝙐𝘿𝙄𝙏 𝙎𝙔𝙎𝙏𝙀𝙈    ────────────────────────────┤
📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓🇮𝙊𝙉 𝐃𝐄𝐓𝐀🇮🇱𝐒                                  
┝━━ 𝐑𝐞𝐠.𝐍𝐨.    : `{reg_no}`                                  
┝━━ 𝐑𝐞𝐠.𝐃𝐚𝐭𝐞.     : {reg_date}                                      
┝━━ 𝐌𝐟𝐠. 𝐌𝐨𝐧𝐭𝐡/𝐘𝐞𝐚𝐫  :   {mfg_loc}                       
╰━━ 𝐒𝐭𝐚𝐭𝐞.    : {state}                                      
                                                          
👤 𝐎𝐖𝐍𝐄𝐑𝐒𝐇🇮🇵 𝘼𝙉𝘼🇱🇮𝙏🇮𝘾🇸                                  
┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐍𝐚𝐦𝐞     : {owner}                            
┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐒𝐞𝐫🇮𝙖𝐥 𝐍𝐨.  :  {serial}                        
╰━━ 𝐀𝐝𝐝𝐫𝐞𝐬𝐬  : {address}                              
                                                          
🚘 𝐓𝐄𝐂𝐇𝐍🇮𝘾𝘼🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊𝙉𝐒                              
┝━━ 𝐌𝐨𝐝𝐞𝐥    : {model_disp}                        
┝━━ 𝐌𝐚𝐤𝐞𝐫    : {maker}                                  
┝━━ 𝐂𝐥𝐚𝐬𝐬    : {v_class}                          
┝━━ 𝐁𝐨𝐝𝐲 𝐓𝐲𝐩𝐞 :  {body_val}                                      
┝━━ 𝐅𝐮𝐞𝐥 :  {fuel}
┝━━ 𝐄𝐦🇮𝙨𝙨🇮𝙤𝙣 𝐍𝐨𝐫𝐦 :  {emission}                                    
┝━━ 𝐂𝐮𝐛🇮𝙘 𝐂𝐚𝐩𝙖𝙘🇮𝙩𝙮 : {cubic_cap}
┝━━ 𝐒𝐞𝐚𝐭🇮𝙣𝙜 𝐂𝐚𝐩𝙖𝙘🇮𝙩𝙮 : {seating}                            
┝━━ 𝐂𝐡𝐚𝐬𝐬🇮𝙨  : `{chassis}`                                  
╰━━ 𝐄𝐧𝐠🇮𝙣𝐞   : `{engine}` 
                                                          
⚙️ 𝐀𝐃𝐃🇮𝙏🇮𝙊𝙉𝘼🇱 𝐃𝐄𝐓𝐀🇮🇱𝐒
┝━━ 𝐔𝐧𝙡𝙖𝙙𝙚𝙣 𝑾𝙚𝙞𝙜𝙝𝙩 : {unladen_wt}
┝━━ 𝑾𝙝𝙚𝙚𝙡𝙗𝙖𝙨𝙚 : {wheelbase}
╰━━ 𝐍𝙪𝙢𝙗𝙚𝙧 𝙊𝙛 𝘾𝙮𝙡𝙞𝙣𝙙𝙚𝙧𝙨 : {cylinders}
                                                          
🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼𝙉🇨🇪                                
┝━━ 𝐈𝐧𝐬𝐮𝐫𝙖𝙣𝙘𝙚 𝐂𝐨𝐦𝙥𝙖𝐧𝙮  : {ins_company}          
┝━━ 𝐏𝐨𝐥🇮𝙘𝙮 𝐍𝐨.   : {ins_policy}                                
┝━━ 𝐄𝐱𝐩🇮𝙧𝙮   : {ins_exp}
┝━━ 𝐅🇮𝙣𝙖𝙣𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                            
┝━━ 𝐅🇮𝙣𝙖𝙣𝐜𝐞𝐫  :  {financer}                                            
┝━━ 𝐅🇮𝙩𝙣𝐞𝐬𝐬   : {fitness_val}
┝━━ 𝐏𝐔𝐂 𝐍𝙪𝙢𝙗𝙚𝙧   : {puc_no}                                             
╰━━ 𝐏𝐔𝐂 𝐕𝙖𝙡🇮𝙙🇮𝙩𝙮     : {puc_val}          
                                                          
⚖️ 𝐋𝐄𝐆𝐀🇱 & 𝐏𝐄𝐑𝐌🇮𝙏 𝙎𝙏𝘼𝙏𝙐𝙎                                  
┝━━ 𝐁𝐥𝙖𝙘𝙠𝐥🇮𝙨𝙩: {blacklist}                                        
┝━━ 𝐏𝐞𝐫𝐦🇮𝙏   : {permit}                                            
╰━━ 𝐒𝐭𝐚𝐭𝐮𝐬    : {status_disp}                                    
├────────┤
│ ✅ 𝐕𝐄𝐑🇮🇫🇮🇪𝐃 𝐎𝐅🇫🇮𝘾🇮𝘼🇱                        
├────────┤"""
    return report

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_id = message.from_user.id
    u = get_user(user_id, message.from_user.first_name, message.from_user.username or "")
    
    markup = InlineKeyboardMarkup()
    if is_subscribed(user_id):
        if user_id == ADMIN_ID:
            status_txt = "👑 **ADMIN ACCESS: UNLIMITED SEARCHES ACTIVE!** 👑"
            markup.add(
                InlineKeyboardButton("👑 ADMIN PANEL (/panel)", callback_data="open_panel")
            )
        else:
            exp_str = u["expiry"].strftime('%d-%b-%Y %I:%M %p') if u.get("expiry") else "Active"
            status_txt = f"💎 **VIP UNLIMITED ACCESS ACTIVE!**\n⏳ Valid Upto: `{exp_str}`"
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

    # Alert Admin
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
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("⚡ Give 24h", callback_data=f"adm_give_{uid}_24h"),
            InlineKeyboardButton("🚀 Give 7D", callback_data=f"adm_give_{uid}_7d"),
            InlineKeyboardButton("❌ Revoke", callback_data=f"adm_revoke_{uid}")
        )
        await bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=markup)
        txt = ""

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
        res = await asyncio.to_thread(requests.get, url, timeout=25)
        
        if res.status_code == 200:
            json_res = res.json()
            
            # Asynchronous Gemini AI Processing
            report = await build_vehicle_report(json_res)
            
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
            not_found_card = f"""╭───────────────╮
│ ⚠️ 𝙑𝘼𝙃𝘼𝙉 𝘿𝘼𝙏𝘼𝘽𝘼𝙎𝙀 𝙉𝙊𝙏𝙄𝙁𝙄𝘾𝘼𝙏𝙄𝙊𝙉         │
├────────────┤
│                                         │
│  ❌  **DETAIL NOT FOUND**               │
│                                         │
│  `{text}` is not registered or         │
│  records are currently unavailable.     │
│                                         │
│  👉  **CHECK ANOTHER VEHICLE NUMBER**  │
│                                         │
──────────────╯"""
            await bot.edit_message_text(not_found_card, message.chat.id, status_msg.message_id, parse_mode="Markdown")
            
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
