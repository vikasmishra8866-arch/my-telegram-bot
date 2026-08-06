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
API_BASE_URL = "https://cjpen.vercel.app/vehicle/"

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
            "points": 10,
            "expiry": None,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        user_data[user_id]["first_name"] = first_name
        user_data[user_id]["username"] = username
        if "points" not in user_data[user_id]:
            user_data[user_id]["points"] = user_data[user_id].get("free_searches", 2) * 5
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
        if "data" in raw_json and isinstance(raw_json["data"], dict):
            data = raw_json["data"]

    if not isinstance(data, dict):
        data = {}

    def get_val(keys, default="NA"):
        for k in keys:
            if k in data and data[k] not in [None, "", "null", "None", "N/A", "NA"]:
                return str(data[k]).strip()
        return default

    # 1. REGISTRATION DETAILS
    reg_no = get_val(["regNo", "reg_no", "registration_number"], "NA").upper()
    reg_date = check_compliance_status(get_val(["regDate", "regn_dt", "registration_date"]))
    
    mfg_raw = get_val(["manufacturerMonthYear", "manufactured_month_year", "manu_month_yr", "manufacturing_date", "mfg_date", "manufacture_date", "mfg_yr"])
    mfg_loc = check_compliance_status(mfg_raw)
    
    state = get_val(["regAuthority", "state"])

    # 2. OWNERSHIP ANALYTICS
    owner = get_val(["owner", "owner_name"])
    
    serial = "1st Owner"

    address = get_val(["permAddress", "presentAddress", "address", "permanent_address"])

    # 3. TECHNICAL SPECIFICATIONS
    model = get_val(["vehicle", "vehicle_model"])
    variant = get_val(["variant"])
    model_disp = f"{model} ({variant})" if variant != "NA" and variant != model else model
    
    maker = get_val(["manufacturer", "maker", "maker_modal"])
    v_class = get_val(["vehicleClass", "vh_class", "vehicle_class"])
    body_val = get_val(["vehicle_category", "body_type"], "NA")
    
    fuel = get_val(["fuelType", "fuel_type"])
    emission = get_val(["fuel_norms", "norms_type"], "NA")
    
    cc_raw = get_val(["cubicCapacity", "cubic_capacity"])
    cubic_cap = f"{cc_raw} cc" if cc_raw != "NA" else "NA"
    
    seating = get_val(["seatCapacity", "no_of_seats", "seating_capacity"], "2")
    chassis = get_val(["chassis", "chasi_no", "chassis_no"])
    engine = get_val(["engine", "engine_no"])
    
    # 4. INSURANCE & COMPLIANCE
    ins_company = get_val(["insuranceCompanyName", "insurance_comp", "insurance_company"])
    ins_policy = get_val(["insurancePolicyNumber", "policy_no", "insurance_policy_no"])
    ins_exp = check_compliance_status(get_val(["insuranceUpto", "insUpto", "insurance_upto"]))
    
    raw_fin = get_val(["isCommercial", "is_financed"]).upper()
    fin_status = "Hypothecated" if get_val(["financerName"]) != "NA" else "No"
    financer = get_val(["financerName", "financer_name", "financer"])
    
    fitness_val = check_compliance_status(get_val(["fitness_upto", "regn_upto"], "NA"))
    puc_no = get_val(["puccNumber", "puc_no"], "NA")
    puc_val = check_compliance_status(get_val(["puccValidUpto", "puc_upto"], "NA"))
    
    # 5. LEGAL & PERMIT STATUS
    blacklist = get_val(["blacklist_status"], "Clean")
    permit = "NA"
    
    status = get_val(["status"], "SUCCESS")
    if status.upper() in ["SUCCESS", "100"]:
        status_disp = "✅ SUCCESS"
    else:
        status_disp = status

    report = f"""╭──────────────╮
 🚀 𝙑𝘼𝙃𝘼𝙉 𝘿𝙀𝙀𝙋 𝘼𝙐𝘿𝙄𝙏 𝙎𝙔𝙎𝙏𝙀𝙈     ────────────────────────────┤
 📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒                             
 ┝━━ 𝐑𝐞𝐠.𝐍𝐨.    : `{reg_no}`                                 
 ┝━━ 𝐑𝐞𝐠.𝐃𝐚𝐭𝐞.     : {reg_date}                                   
 ┝━━ 𝐌𝐟𝐠. 𝐌𝐨𝐧𝐭𝐡/𝐘𝐞𝐚𝐫  :   {mfg_loc}                 
 ╰━━ 𝐒𝐭𝐚𝐭𝐞.    : {state}                                     
                                                         
 👤 𝐎𝐖𝐍𝐄𝐑𝐒𝐇𝐈𝐏 𝐀𝐍𝐀🇱🇮𝙏🇮𝘾🇸                             
 ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐍𝐚𝐦𝐞     : {owner}                         
 ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐒𝐞𝐫𝐢𝐚𝐥 𝐍𝐨.  :  {serial}                 
 ╰━━ 𝐀𝐝𝐝𝐫𝐞𝐬𝐬  : {address}                           
                                                         
 🚘 𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊🇳🇸                           
 ┝━━ 𝐌𝐨𝐝𝐞𝐥    : {model_disp}                       
 ┝━━ 𝐌𝐚𝐤𝐞𝐫    : {maker}                           
 ┝━━ 𝐂𝐥𝐚𝐬𝐬    : {v_class}                       
 ┝━━ 𝐁𝐨𝑑𝘆 𝐓𝐲𝐩𝐞 :  {body_val}                                    
 ┝━━ 𝐅𝐮𝐞𝐥 :  {fuel}
 ┝━━ 𝐄𝐦𝐢𝐬𝐬𝐢𝐨𝐧 𝐍𝐨𝐫𝐦 :  {emission}                            
 ┝━━ 𝐂𝐮𝐛𝐢𝐜 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {cubic_cap}
 ┝━━ 𝐒𝐞𝐚𝐭𝐢𝐧𝐠 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {seating}                           
 ┝━━ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : `{chassis}`                                 
 ╰━━ 𝐄𝐧𝐠𝐢𝐧𝐞   : `{engine}` 
                                                                                                                   
 🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼🇳🇨🇪                          
 ┝━━ 𝐈𝐧𝐬𝐮𝐫𝐚𝐧𝐜𝐞 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_company}          
 ┝━━ 𝐏𝐨𝐥𝐢𝐜𝐲 𝐍𝐨.    : {ins_policy}                               
 ┝━━ 𝐄𝐱𝐩𝐢𝐫𝐲    : {ins_exp}
 ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                            
 ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞𝐫  :  {financer}                                                     
 ┝━━ 𝐅𝐢𝐭𝐧𝐞𝐬𝐬   : {fitness_val}
 ┝━━ 𝐏𝐔𝐂 𝐍𝐮𝐦𝐛𝐞𝐫    : {puc_no}                                   
 ╰━━ 𝐏𝐔𝐂 𝐕𝐚𝐥𝐢𝐝🇮𝙩𝙮     : {puc_val}          
                                                         
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
        status_txt = f"🌟 **YOUR AVAILABLE POINTS: {u['points']}** 🌟"
        markup.add(
            InlineKeyboardButton("💳 ADD POINTS / BUY PLAN", callback_data="buy_plan"),
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
        InlineKeyboardButton("⚡ ₹50 (10 Points)", callback_data="gen_qr_50"),
        InlineKeyboardButton("🚀 ₹100 (25 Points)", callback_data="gen_qr_100")
    )
    markup.row(
        InlineKeyboardButton("🔥 ₹150 (40+3 Extra)", callback_data="gen_qr_150")
    )
    markup.row(
        InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )
    
    plan_txt = f"""🚀 **POINTS RECHARGE PLANS**

💎 **SELECT YOUR RECHARGE PLAN:**
1️⃣ **₹50 Plan:** 10 Points
2️⃣ **₹100 Plan:** 25 Points
3️⃣ **₹150 Plan:** 40 Points + 3 Extra Points (Total 43)

*Note: Each search costs 5 points. Points are saved permanently in your account!*

👇 Click on a button below to generate payment QR Code!"""
    await bot.send_message(chat_id, plan_txt, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_plan")
async def callback_buy(call):
    await show_buy_options(call.message.chat.id)

# ==================== DYNAMIC QR & ADMIN ALERT ====================
@bot.callback_query_handler(func=lambda call: call.data in ["gen_qr_50", "gen_qr_100", "gen_qr_150"])
async def handle_qr_generation(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if call.data == "gen_qr_50":
        amount = 50
        points_str = "10 Points"
    elif call.data == "gen_qr_100":
        amount = 100
        points_str = "25 Points"
    else:
        amount = 150
        points_str = "43 Points (40+3)"

    if user_id in user_qr_messages:
        try:
            await bot.delete_message(chat_id, user_qr_messages[user_id])
        except Exception:
            pass

    upi_uri = f"upi://pay?pa={UPI_ID}&pn=VehicleAudit&am={amount}&cu=INR&tn={urllib.parse.quote('Points Recharge')}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_uri)}"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("👑 SEND PAYMENT SCREENSHOT", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
    )

    caption = f"""💳 **PAYMENT QR CODE FOR ₹{amount}**

📌 **Plan Selected:** {points_str}
💰 **Amount to Pay:** ₹{amount}
📲 **UPI ID:** `{UPI_ID}`

⏳ *This QR Code will auto-expire in 5 minutes.*"""

    qr_msg = await bot.send_photo(chat_id, photo=qr_url, caption=caption, parse_mode="Markdown", reply_markup=markup)
    user_qr_messages[user_id] = qr_msg.message_id

    admin_markup = InlineKeyboardMarkup()
    admin_markup.row(
        InlineKeyboardButton("✅ Add 10 Pts", callback_data=f"adm_add_{user_id}_10"),
        InlineKeyboardButton("✅ Add 25 Pts", callback_data=f"adm_add_{user_id}_25"),
        InlineKeyboardButton("✅ Add 43 Pts", callback_data=f"adm_add_{user_id}_43")
    )
    
    admin_alert = f"""🔔 **NEW PAYMENT QR GENERATED!**

👤 **User:** {call.from_user.first_name} (@{call.from_user.username or 'No Username'})
🆔 **User ID:** `{user_id}`
💰 **Plan Selected:** ₹{amount} ({points_str})

👇 *Click below button to give points after verifying payment:*"""
    
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
        status = f"🟢 Points: {uinfo.get('points', 0)}"
        txt += f"👤 **{uinfo['first_name']}** (@{uinfo['username'] or 'N/A'})\n🆔 ID: `{uid}` | Status: {status}\n"
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("➕ 10 Pts", callback_data=f"adm_add_{uid}_10"),
            InlineKeyboardButton("➕ 25 Pts", callback_data=f"adm_add_{uid}_25"),
            InlineKeyboardButton("➕ 43 Pts", callback_data=f"adm_add_{uid}_43")
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

    u = get_user(target_id)

    if action == "add":
        pts = int(parts[3])
        u["points"] = u.get("points", 0) + pts
        user_data[target_id] = u

        await bot.answer_callback_query(call.id, f"✅ Added {pts} points for {target_id}!")
        await bot.send_message(ADMIN_ID, f"🎉 **Successfully added {pts} points to User ID:** `{target_id}`", parse_mode="Markdown")
        
        try:
            await bot.send_message(target_id, f"🎉 **CONGRATULATIONS!**\n\nYour account has been credited with **{pts} Points** by Admin 👑!\nTotal Points: `{u['points']}`", parse_mode="Markdown")
        except Exception:
            pass

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
    if not subscribed and u["points"] < 5:
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("💳 ADD POINTS", callback_data="buy_plan"),
            InlineKeyboardButton("👑 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        )
        msg_text = f"""⚠️ **INSUFFICIENT POINTS!**

You need at least 5 points to perform a search. Your current balance is {u['points']} points. Please recharge to continue."""
        await bot.send_message(message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")
        return

    status_msg = await bot.reply_to(message, "🔍 **Searching Official Vahan Database... Please wait...**", parse_mode="Markdown")
    
    try:
        url = f"{API_BASE_URL}{text}"
        res = await asyncio.to_thread(requests.get, url, timeout=25)
        
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
                u["points"] -= 5
                await bot.send_message(message.chat.id, f"💡 *Notice: 5 points deducted. Remaining Points: {u['points']}*", parse_mode="Markdown")
        else:
            not_found_card = f"""╭───────────────╮
│ ⚠️ 𝙑𝘼𝙃𝘼𝙉 𝘿𝘼𝙏𝘼𝘽𝘼𝙎𝙀 𝙉𝙊𝙏𝙄𝙁𝙄𝘾𝘼𝙏𝙄𝙊𝙉         │
├────────────┤
│                                       │
│  ❌  **DETAIL NOT FOUND**             │
│                                       │
│  `{text}` is not registered or        │
│  records are currently unavailable.   │
│                                       │
│  👉  **CHECK ANOTHER VEHICLE NUMBER** │
│                                       │
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
