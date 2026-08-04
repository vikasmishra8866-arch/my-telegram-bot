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

# Gemini API Key Setup (Environment Variable with Direct Fallback)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6KTdpvqaoByPb4AWLZv0w0JoD6cDWTX5EMVxX_9NMQMaQ")
ai_client = genai.Client(api_key=GEMINI_API_KEY)

bot = AsyncTeleBot(BOT_TOKEN)
app = FastAPI()

# ==================== GEMINI SYSTEM PROMPT ====================
SYSTEM_INSTRUCTION = """
You are an expert, highly accurate Vehicle Data Processing AI. Your role is to merge raw JSON responses from Vehicle RTO APIs into a single, sanitized, and perfectly structured JSON object.

Follow these STRICT rules without exception:

1. OUTPUT FORMAT:
- You must output ONLY a valid, raw JSON object. 
- Do NOT include markdown code blocks (like ```json), commentary, or extra conversational text.

2. OWNER NAME & ADDRESS RESOLUTION RULES:
- Compare the owner serial count/number from the input data.
- If one API/field has a higher owner serial/count (e.g., 2nd Owner vs 1st Owner), use the Owner Name associated with the higher owner count as primary 'owner_name'.
- If owner serial/count is "NA", missing, or equal across inputs:
  - If different owner names exist, join them with a slash: "API1_Owner / API2_Owner".
  - If different addresses exist, join them with a slash: "API1_Address / API2_Address".
  - Remove duplicate values if both inputs report the exact same name or address.
- Always report the highest available owner serial string in 'owner_serial' (e.g., "1st Owner", "2nd Owner", "3rd Owner").

3. AI TECHNICAL SPECIFICATION ENRICHMENT (DO NOT rely only on API):
- The following technical fields MUST be intelligently filled using your internal official database/knowledge based on the vehicle's Maker, Model, Variant, and Registration/Manufacturing Year:
  - 'cubic_capacity' (Append ' cc' if numeric, e.g., '109.0 cc')
  - 'unladen_weight' (Append ' kg' if available, e.g., '105 kg')
  - 'wheelbase' (Append ' mm' if available, e.g., '1260 mm')
  - 'number_of_cylinders' (e.g., "1" or "4")
  - 'emission_norm' (e.g., "BHARAT STAGE VI" or "BS IV")
  - 'seating_capacity'
  - 'fuel_type'
- FALLBACK: If the model is too vague to determine these specs 100% accurately, set their value strictly as "NA". Do NOT hallucinate or guess.

4. DYNAMIC & OFFICIAL RTO DATA PASS-THROUGH (ZERO GUESSING):
- Personal, registration, and legal fields MUST strictly come from the provided API response data. NEVER guess or invent these details:
  - 'reg_no', 'reg_date', 'mfg_date', 'state', 'chassis_no', 'engine_no', 'insurance_company', 'insurance_policy', 'insurance_expiry', 'finance_status', 'financer', 'fitness_upto', 'puc_no', 'puc_expiry', 'blacklist_status', 'permit_no', 'status'
- If any of these fields are missing or empty in the API response, strictly set the value as "NA".

5. DATE & STATUS STANDARDIZATION:
- Format all valid dates strictly as "DD/MM/YYYY" or "MM/YYYY" (for Mfg date if day is missing).
- Set 'status' strictly as "SUCCESS" or "Active" if valid data exists.

6. REQUIRED JSON KEYS SCHEMA (Do not add or omit keys):
{
  "reg_no": "NA",
  "reg_date": "NA",
  "mfg_date": "NA",
  "state": "NA",
  "owner_name": "NA",
  "owner_serial": "NA",
  "address": "NA",
  "model": "NA",
  "maker": "NA",
  "v_class": "NA",
  "body_type": "NA",
  "fuel_type": "NA",
  "emission_norm": "NA",
  "cubic_capacity": "NA",
  "seating_capacity": "NA",
  "unladen_weight": "NA",
  "wheelbase": "NA",
  "number_of_cylinders": "NA",
  "chassis_no": "NA",
  "engine_no": "NA",
  "insurance_company": "NA",
  "insurance_policy": "NA",
  "insurance_expiry": "NA",
  "finance_status": "NA",
  "financer": "NA",
  "fitness_upto": "NA",
  "puc_no": "NA",
  "puc_expiry": "NA",
  "blacklist_status": "NA",
  "permit_no": "NA",
  "status": "SUCCESS"
}
"""

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
    return {"status": "ok", "message": "Vehicle Audit Telegram Bot Admin Panel Active!"}

# ==================== GEMINI AI ENGINE ====================
def process_data_with_gemini(raw_api_response):
    """Passes raw API response to Gemini AI to generate clean normalized JSON"""
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=json.dumps(raw_api_response),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.0,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini API Processing Error: {e}")
        return None

# ==================== REPORT BUILDER ====================
def build_vehicle_report(raw_json):
    # 1. Process raw API via Gemini AI
    ai_data = process_data_with_gemini(raw_json)
    
    # Fallback to direct raw extraction if Gemini fails
    if not ai_data or not isinstance(ai_data, dict):
        ai_data = {}

    def get_val(key, default="NA"):
        val = ai_data.get(key)
        if val in [None, "", "null", "None", "N/A", "NA"]:
            return default
        return str(val).strip()

    # 1. REGISTRATION DETAILS
    reg_no = get_val("reg_no").upper()
    reg_date = get_val("reg_date")
    mfg_loc = get_val("mfg_date")
    state = get_val("state")

    # 2. OWNERSHIP ANALYTICS
    owner = get_val("owner_name")
    serial = get_val("owner_serial")
    address = get_val("address")

    # 3. TECHNICAL SPECIFICATIONS
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

    # 4. ADDITIONAL DETAILS (ENRICHED BY GEMINI)
    unladen_wt = get_val("unladen_weight")
    wheelbase = get_val("wheelbase")
    cylinders = get_val("number_of_cylinders")

    # 5. INSURANCE & COMPLIANCE
    ins_company = get_val("insurance_company")
    ins_policy = get_val("insurance_policy")
    ins_exp = get_val("insurance_expiry")
    fin_status = get_val("finance_status")
    financer = get_val("financer")
    fitness_val = get_val("fitness_upto")
    puc_no = get_val("puc_no")
    puc_val = get_val("puc_expiry")

    # 6. LEGAL & PERMIT STATUS
    blacklist = get_val("blacklist_status")
    permit = get_val("permit_no")
    status = get_val("status")
    status_disp = "✅ SUCCESS" if status.upper() in ["SUCCESS", "ACTIVE"] else status

    # EXACT DISPLAY FORMAT WITH NEW ADDITIONAL DETAILS SECTION
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
                                                          
🚘 𝐓𝐄𝐂𝐇𝐍🇮𝘾𝘼🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊𝙉𝙎                              
┝━━ 𝐌𝐨𝐝𝐞𝐥    : {model_disp}                        
┝━━ 𝐌𝐚𝐤𝐞𝐫    : {maker}                                  
┝━━ 𝐂𝐥𝐚𝐬𝐬    : {v_class}                          
┝━━ 𝐁𝐨𝐝𝐲 𝐓𝐲𝐩𝐞 :  {body_val}                                      
┝━━ 𝐅𝐮𝐞𝐥 :  {fuel}
┝━━ 𝐄𝐦🇮𝙨𝙨🇮𝙤𝙣 𝐍𝐨𝐫𝐦 :  {emission}                                    
┝━━ 𝐂𝐮𝐛🇮𝙘 𝐂𝐚𝐩𝙖𝙘🇮𝙩𝙮 : {cubic_cap}
┝━━ 𝐒𝐞𝙖𝙩🇮𝙣𝙜 𝐂𝐚𝐩𝙖𝙘🇮𝙩𝙮 : {seating}                            
┝━━ 𝐂𝐡𝐚𝐬𝐬🇮𝙨  : `{chassis}`                                  
╰━━ 𝐄𝐧𝐠🇮𝙣𝐞   : `{engine}` 
                                                          
⚙️ 𝐀𝐃𝐃🇮𝙏🇮𝙊𝙉𝘼🇱 𝐃𝐄𝐓𝐀🇮🇱𝐒
┝━━ 𝐔𝐧𝙡𝙖𝙙𝙚𝙣 𝑾𝙚𝙞𝙜𝙝𝙩 : {unladen_wt}
┝━━ 𝑾𝙝𝙚𝙚𝙡𝙗𝙖𝙨𝙚 : {wheelbase}
╰━━ 𝐍𝙪𝙢𝙗𝙚𝙧 𝙊𝙛 𝘾𝙮𝙡𝙞𝙣𝙙𝙚𝙧𝙨 : {cylinders}
                                                          
🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼𝙉🇨🇪                                
┝━━ 𝐈𝐧𝐬𝐮𝐫𝙖𝙣𝙘𝙚 𝐂𝐨𝐦𝙥𝙖𝙣𝙮  : {ins_company}          
┝━━ 𝐏𝐨𝐥🇮𝙘𝙮 𝐍𝐨.   : {ins_policy}                                
┝━━ 𝐄𝐱𝐩🇮𝙧𝙮   : {ins_exp}
┝━━ 𝐅🇮𝙣𝙖𝙣𝙘𝙚 𝐒𝐭𝙖𝐭𝐮𝐬  :  {fin_status}                            
┝━━ 𝐅🇮𝙣𝙖𝙣𝙘𝙚𝙧  :  {financer}                                            
┝━━ 𝐅🇮𝙩𝙣𝙚𝙨𝙨   : {fitness_val}
┝━━ 𝐏𝐔𝐂 𝐍𝙪𝙢𝙗𝙚𝙧   : {puc_no}                                             
╰━━ 𝐏𝐔𝐂 𝐕𝙖𝙡🇮𝙙🇮𝙩𝙮     : {puc_val}          
                                                          
⚖️ 𝐋𝐄𝐆𝐀🇱 & 𝐏𝐄𝐑𝐌🇮𝙏 𝙎𝙏𝘼𝙏𝙐𝙎                                  
┝━━ 𝐁𝐥𝙖𝙘𝙠𝐥🇮𝙨𝙩: {blacklist}                                        
┝━━ 𝐏𝐞𝐫𝙢🇮𝙩   : {permit}                                            
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
                InlineKeyboardButton("👑 CONTACT ADMIN", url=f"[https://t.me/](https://t.me/){ADMIN_USERNAME.replace('@','')}")
            )
    else:
        status_txt = f"🌟 **YOU HAVE {u['free_searches']} FREE SEARCHES AVAILABLE!** 🌟"
        markup.add(
            InlineKeyboardButton("💳 BUY UNLIMITED PLAN", callback_data="buy_plan"),
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"[https://t.me/](https://t.me/){ADMIN_USERNAME.replace('@','')}")
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
        InlineKeyboardButton("👑 CONTACT ADMIN", url=f"[https://t.me/](https://t.me/){ADMIN_USERNAME.replace('@','')}")
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
    qr_url = f"[https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=](https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=){urllib.parse.quote(upi_uri)}"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("👑 SEND PAYMENT SCREENSHOT", url=f"[https://t.me/](https://t.me/){ADMIN_USERNAME.replace('@','')}")
    )

    caption = f"""💳 **PAYMENT QR CODE FOR ₹{amount}**

📌 **Plan Selected:** {plan_name}
💰 **Amount to Pay:** ₹{amount}
📲 **UPI ID:** `{UPI_ID}`

⏳ *This QR Code will auto-expire in 5 minutes.*"""

    qr_msg = await bot.send_photo(chat_id, photo=qr_url, caption=caption, parse_mode="Markdown", reply_markup=markup)
    user_qr_messages[user_id] = qr_msg.message_id

    # INSTANT ALERT TO ADMIN WITH DIRECT APPROVAL BUTTONS
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
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"[https://t.me/](https://t.me/){ADMIN_USERNAME.replace('@','')}")
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
            
            # Asynchronously call Gemini AI Processor
            report = await asyncio.to_thread(build_vehicle_report, json_res)
            
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
