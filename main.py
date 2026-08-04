import os
import time
import asyncio
import threading
import urllib.parse
from datetime import datetime, timedelta
import aiohttp
import uvicorn
from fastapi import FastAPI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8426663183:AAG1CFm0PiC7DN1zOsFqjEEEdzi7IcvdC7k")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8204069256))
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

# ==================== DATE HELPER ====================
def check_compliance_status(date_str):
    if not date_str or str(date_str).strip() in ["N/A", "NA", "None", "null", ""]:
        return "NA"
    
    clean_date = str(date_str).split("T")[0].strip()
    parsed_date = None
    
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%Y", "%m-%Y"):
        try:
            parsed_date = datetime.strptime(clean_date, fmt)
            break
        except ValueError:
            pass

    if parsed_date:
        if len(clean_date) <= 7:
            return parsed_date.strftime('%m/%Y')
        return parsed_date.strftime('%d/%m/%Y')
    return clean_date

# ==================== REPORT BUILDER ====================
def build_vehicle_report(raw_json):
    data = raw_json
    if isinstance(raw_json, dict):
        if "rc_details" in raw_json and isinstance(raw_json["rc_details"], dict):
            inner = raw_json["rc_details"].get("data", [])
            data = inner[0] if isinstance(inner, list) and len(inner) > 0 else inner
        elif "data" in raw_json:
            inner = raw_json["data"]
            data = inner[0] if isinstance(inner, list) and len(inner) > 0 else inner

    if not isinstance(data, dict):
        data = {}

    def get_val(keys, default="NA"):
        for k in keys:
            if k in data and data[k] not in [None, "", "null", "None", "N/A", "NA"]:
                return str(data[k]).strip()
        return default

    # 1. REGISTRATION DETAILS
    reg_no = get_val(["reg_no", "registration_number"], "NA").upper()
    reg_date = check_compliance_status(get_val(["regn_dt", "registration_date"]))
    mfg_raw = get_val(["manufactured_month_year", "manu_month_yr", "manufacturing_date", "mfg_date", "manufacture_date", "mfg_yr"])
    mfg_loc = check_compliance_status(mfg_raw)
    state = get_val(["state"])

    # 2. OWNERSHIP ANALYTICS
    owner_1 = get_val(["owner_1_name"])
    owner_2 = get_val(["owner_2_name"])
    main_owner = get_val(["owner_name"])
    
    owners = []
    if owner_1 != "NA": owners.append(owner_1)
    if owner_2 != "NA": owners.append(owner_2)
    if not owners and main_owner != "NA": owners.append(main_owner)
    owner = " / ".join(owners) if owners else "NA"

    addr_1 = get_val(["address_1"])
    addr_2 = get_val(["address_2"])
    main_addr = get_val(["address", "permanent_address"])
    
    addresses = []
    if addr_1 != "NA": addresses.append(addr_1)
    if addr_2 != "NA": addresses.append(addr_2)
    if not addresses and main_addr != "NA": addresses.append(main_addr)
    address = " / ".join(addresses) if addresses else "NA"

    sr_raw = data.get("owner_sr_no") or data.get("owner_serial_no") or data.get("owner_serial") or "1"
    
    import re
    if isinstance(sr_raw, list):
        nums = [int(n) for n in sr_raw if str(n).isdigit()]
        highest_sr = max(nums) if nums else 1
    else:
        found_nums = re.findall(r'\d+', str(sr_raw))
        highest_sr = max([int(n) for n in found_nums]) if found_nums else 1

    serial = f"{highest_sr}st Owner" if highest_sr == 1 else f"{highest_sr}nd Owner" if highest_sr == 2 else f"{highest_sr}rd Owner" if highest_sr == 3 else f"{highest_sr}th Owner"

    # 3. TECHNICAL SPECIFICATIONS
    model = get_val(["vehicle_model"])
    variant = get_val(["variant"])
    model_disp = f"{model} ({variant})" if variant != "NA" and variant != model else model
    
    maker = get_val(["maker", "maker_modal"])
    v_class = get_val(["vh_class", "vehicle_class"])
    body_val = get_val(["vehicle_category", "body_type"])
    fuel = get_val(["fuel_type"])
    emission = get_val(["fuel_norms", "norms_type"])
    
    cc_raw = get_val(["cubic_capacity"])
    cubic_cap = f"{cc_raw} cc" if cc_raw != "NA" else "NA"
    
    seating = get_val(["no_of_seats", "seating_capacity"], "2")
    chassis = get_val(["chasi_no", "chassis_no"])
    engine = get_val(["engine_no"])
    
    # 4. INSURANCE & COMPLIANCE
    ins_company = get_val(["insurance_comp", "insurance_company"])
    ins_policy = get_val(["policy_no", "insurance_policy_no"])
    ins_exp = check_compliance_status(get_val(["insUpto", "insurance_upto"]))
    
    raw_fin = get_val(["is_financed"]).upper()
    fin_status = "Hypothecated" if raw_fin in ["TRUE", "1", "YES"] else "No"
    financer = get_val(["financer_name", "financer"])
    
    fitness_val = check_compliance_status(get_val(["fitness_upto", "regn_upto"]))
    puc_no = get_val(["puc_no"])
    puc_val = check_compliance_status(get_val(["puc_upto"]))
    
    # 5. LEGAL & PERMIT STATUS
    blacklist = get_val(["blacklist_status"], "Clean")
    
    permit_data = data.get("permit_details", {})
    if isinstance(permit_data, dict):
        permit = permit_data.get("permit_number", "NA") or "NA"
    else:
        permit = get_val(["permit_no", "permit_number"], "NA")
        
    status = get_val(["status"], "SUCCESS")
    status_disp = "✅ SUCCESS" if status.upper() == "SUCCESS" else status

    report = f"""╭──────────────╮
 🚀 𝙑𝘼𝙃𝘼𝙉 𝘿𝙀𝙀𝙋 𝘼𝙐𝘿𝙄𝙏 𝙎𝙔𝙎𝙏𝙀𝙈  ────────────────────────────┤
 📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒                                 
 ┝━━ 𝐑𝐞𝐠.𝐍𝐨.    : `{reg_no}`                                  
 ┝━━ 𝐑𝐞𝐠.𝐃𝐚𝐭𝐞.     : {reg_date}                                   
 ┝━━ 𝐌𝐟𝐠. 𝐌𝐨𝐧𝐭𝐡/𝐘𝐞𝐚𝐫  :   {mfg_loc}                       
 ╰━━ 𝐒𝐭𝐚𝐭𝐞.    : {state}                                     
                                                         
 👤 𝐎𝐖𝐍𝐄𝐑𝐒𝐇𝐈𝐏 𝐀𝐍𝐀🇱🇮𝙏🇮𝘾🇸                                  
 ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐍𝐚𝐦𝐞     : {owner}                            
 ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐒𝐞𝐫𝐢𝐚𝐥 𝐍𝐨.  :  {serial}                       
 ╰━━ 𝐀𝐝𝐝𝐫𝐞𝐬𝐬  : {address}                              
                                                         
 🚘 𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊𝙉𝙎                             
 ┝━━ 𝐌𝐨𝐝𝐞𝐥    : {model_disp}                        
 ┝━━ 𝐌𝐚𝐤𝐞𝐫    : {maker}                                 
 ┝━━ 𝐂𝐥𝐚𝐬𝐬    : {v_class}                         
 ┝━━ 𝐁𝐨𝐝𝐲 𝐓𝐲𝐩𝐞 :  {body_val}                                      
 ┝━━ 𝐅𝐮𝐞𝐥 :  {fuel}
 ┝━━ 𝐄𝐦𝐢𝐬𝐬𝐢𝐨𝐧 𝐍𝐨𝐫𝐦 :  {emission}                                   
 ┝━━ 𝐂𝐮𝐛𝐢𝐜 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {cubic_cap}
 ┝━━ 𝐒𝐞𝐚𝐭𝐢𝐧𝐠 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {seating}                           
 ┝━━ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : `{chassis}`                                  
 ╰━━ 𝐄𝐧𝐠𝐢𝐧𝐞   : `{engine}` 
                                                                                
 🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼𝙉🇨🇪                                
 ┝━━ 𝐈𝐧𝐬𝐮𝐫𝐚𝐧𝐜𝐞 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_company}          
 ┝━━ 𝐏𝐨𝐥𝐢𝐜𝐲 𝐍𝐨.   : {ins_policy}                               
 ┝━━ 𝐄𝐱𝐩𝐢𝐫𝐲   : {ins_exp}
 ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                           
 ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞𝐫  :  {financer}                                                           
 ┝━━ 𝐅𝐢𝐭𝐧𝐞𝐬𝐬   : {fitness_val}
 ┝━━ 𝐏𝐔𝐂 𝐍𝐮𝐦𝐛𝐞𝐫   : {puc_no}                                     
 ╰━━ 𝐏𝐔𝐂 𝐕𝐚𝐥🇮𝙙🇮𝙩𝙮     : {puc_val}          
                                                         
 ⚖️ 𝐋𝐄𝐆𝐀𝐋 & 𝐏𝐄𝐑𝐌🇮𝙏 𝙎𝙏𝘼𝙏𝙐𝙎                                  
 ┝━━ 𝐁𝐥𝐚𝐜𝐤𝐥🇮𝙨𝙩: {blacklist}                                      
 ┝━━ 𝐏𝐞𝐫𝐦🇮𝙩   : {permit}                                           
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
            markup.add(InlineKeyboardButton("👑 ADMIN PANEL (/panel)", callback_data="open_panel"))
        else:
            exp_str = u["expiry"].strftime('%d-%b-%Y %I:%M %p') if u.get("expiry") else "Active"
            status_txt = f"💎 **VIP UNLIMITED ACCESS ACTIVE!**\n⏳ Valid Upto: `{exp_str}`"
            markup.add(InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}\"))
    else:
        status_txt = f"🌟 **YOU HAVE {u['free_searches']} FREE SEARCHES AVAILABLE!** 🌟"
        markup.add(
            InlineKeyboardButton("💳 BUY UNLIMITED PLAN", callback_data="buy_plan"),
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}\")
        )
    
    welcome_txt = f"👋 **Welcome to Vehicle Audit Bot!**\n\n🚗 *Instant Vehicle RC & Owner Verification Service.*\n\n🎁 **ACCOUNT STATUS:**\n{status_txt}\n\n─────────────\n📌 **How to use?**\nSend any Vehicle Number (e.g. `GJ05HG7801`)\n─────────────"
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
    markup.row(InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}\"))
    
    plan_txt = "🚀 **UNLIMITED VIP MEMBERSHIP PLANS**\n\n💎 **SELECT YOUR PLAN BELOW:**\n1️⃣ **24 Hours Pass:** ₹25\n2️⃣ **1 Week Pass:** ₹90\n\n👇 Click on a button below to generate payment QR Code!"
    await bot.send_message(chat_id, plan_txt, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_plan")
async def callback_buy(call):
    await show_buy_options(call.message.chat.id)

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
    markup.add(InlineKeyboardButton("👑 SEND PAYMENT SCREENSHOT", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}\"))

    caption = f"💳 **PAYMENT QR CODE FOR ₹{amount}**\n\n📌 **Plan Selected:** {plan_name}\n💰 **Amount to Pay:** ₹{amount}\n📲 **UPI ID:** `{UPI_ID}`\n\n⏳ *This QR Code will auto-expire in 5 minutes.*"

    qr_msg = await bot.send_photo(chat_id, photo=qr_url, caption=caption, parse_mode="Markdown", reply_markup=markup)
    user_qr_messages[user_id] = qr_msg.message_id

    admin_markup = InlineKeyboardMarkup()
    admin_markup.row(
        InlineKeyboardButton("✅ Give 24h Access", callback_data=f"adm_give_{user_id}_24h"),
        InlineKeyboardButton("✅ Give 7D Access", callback_data=f"adm_give_{user_id}_7d")
    )
    
    admin_alert = f"🔔 **NEW PAYMENT QR GENERATED!**\n\n👤 **User:** {call.from_user.first_name} (@{call.from_user.username or 'No Username'})\n🆔 **User ID:** `{user_id}`\n💰 **Plan Selected:** ₹{amount} ({plan_name})\n\n👇 *Click below button to give instant VIP Access after verifying payment:*"
    
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

# ==================== VEHICLE SEARCH HANDLER (ASYNC HTTP FIX) ====================
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
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}\")
        )
        msg_text = "⚠️ **FREE TRIAL EXHAUSTED!**\n\nYou have used all your free searches. Please buy a plan to continue accessing vehicle reports."
        await bot.send_message(message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")
        return

    status_msg = await bot.reply_to(message, "🔍 **Searching Official Vahan Database... Please wait...**", parse_mode="Markdown")
    
    try:
        url = f"{API_BASE_URL}{text}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # Async HTTP Request using aiohttp to prevent API freezing
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as res:
                if res.status == 200:
                    json_res = await res.json()
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
                    not_found_card = f"╭───────────────╮\n│ ⚠️ 𝙑𝘼𝙃𝘼𝙉 𝘿𝘼𝙏𝘼𝘽𝘼𝙎𝙀 𝙉𝙊𝙏𝙄𝙁𝙄𝘾𝘼𝙏𝙄𝙊𝙉         │\n├────────────┤\n│                                         │\n│  ❌  **DETAIL NOT FOUND**               │\n│                                         │\n│  `{text}` is not registered or         │\n│  records are currently unavailable.     │\n│                                         │\n│  👉  **CHECK ANOTHER VEHICLE NUMBER**  │\n│                                         │\n──────────────╯"
                    await bot.edit_message_text(not_found_card, message.chat.id, status_msg.message_id, parse_mode="Markdown")
            
    except Exception as e:
        await bot.edit_message_text("⚠️ **Server Error / Timeout!**\nPlease try again in a few seconds.", message.chat.id, status_msg.message_id, parse_mode="Markdown")

# ==================== BOT RUNNER ====================
def start_bot_thread():
    asyncio.run(bot.polling(non_stop=True, timeout=60))

if __name__ == "__main__":
    t = threading.Thread(target=start_bot_thread, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
