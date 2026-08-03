import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
API_GATEWAY_URL = os.environ.get(
    "API_GATEWAY_URL", 
    "https://your-api-gateway-url.onrender.com/api/v1/vehicle"
)  # Pass base URL without trailing slash if needed

ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "123456789").split(",") if x.strip()]

# In-Memory VIP Users Storage
# Structure: { user_id: datetime_expiry_object }
vip_users: Dict[int, datetime] = {}

# ==========================================
# FASTAPI APP (WITH HEAD REQUEST FIX)
# ==========================================
app = FastAPI(title="Parivahan Telegram Bot Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.head("/")
def home():
    return {
        "status": "Online",
        "message": "Parivahan Telegram Bot & Ping Service is Active!"
    }

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def clean_vno(vehicle_no: str) -> str:
    """Cleans spaces/hyphens and forces UPPERCASE."""
    return re.sub(r'[^A-ZA-Z0-9]', '', vehicle_no).upper()

def is_vip(user_id: int) -> bool:
    """Checks if user has active VIP access with exact time precision."""
    if user_id in ADMIN_IDS:
        return True
    if user_id in vip_users:
        expiry_time = vip_users[user_id]
        if datetime.now() < expiry_time:
            return True
        else:
            del vip_users[user_id] # Clean up expired user
    return False

def format_vip_response(data: Dict[str, Any], query_no: str) -> str:
    """Formats response according to exact requested UI design without ticks."""
    
    # RTO Manufacturing/Location fallback
    rto = data.get("rto", "NA")
    state = data.get("state", "NA")
    mfg_loc = f"{rto}, {state}" if rto != "NA" else state

    reg_no = data.get("reg_no", query_no)
    reg_dt = data.get("regn_dt", "NA")
    owner_name = data.get("owner_name", "NA")
    owner_sr_no = f"{data.get('owner_sr_no', '1')}st Owner" if str(data.get('owner_sr_no')).isdigit() else data.get('owner_sr_no', 'NA')
    address = data.get("address", "NA")
    
    # Specs
    model = data.get("vehicle_model", "NA")
    maker = data.get("maker", "NA")
    vh_class = data.get("vh_class", "NA")
    body_type = "NA"
    fuel = data.get("fuel_type", "NA")
    emission = data.get("fuel_norms", "NA")
    cubic_cap = f"{data.get('cubic_capacity', 'NA')} cc" if data.get('cubic_capacity') != "NA" else "NA"
    seating = data.get("no_of_seats", "NA")
    chassis = data.get("chasi_no", "NA")
    engine = data.get("engine_no", "NA")

    # Insurance & Compliance
    ins_comp = data.get("insurance_comp", "NA")
    policy_no = data.get("policy_no", "NA")
    ins_exp = data.get("insUpto", "NA")
    
    is_fin = str(data.get("is_financed")).upper()
    fin_status = "Hypothecated" if is_fin in ["TRUE", "1", "YES"] else "No"
    financer = data.get("financer_name", "NA")
    
    road_tax = data.get("tax_valid_upto", "NA")
    fitness = data.get("fitness_upto", "NA")
    puc_no = data.get("puc_no", "NA")
    puc_val = data.get("puc_upto", "NA")

    # Legal
    blacklist = data.get("blacklist_status", "Clean")
    permit = data.get("permit_details", {}).get("permit_number", "NA")
    status = data.get("status", "SUCCESS")

    template = f"""╭───────────────────────────────────────────────────────────╮
│ 🚀 𝙑𝘼𝙃𝘼𝙉 𝘿𝙀𝙀𝙋 𝘼𝙐𝘿𝙄𝗧 𝙎𝙔𝙎𝙏𝙀𝙈                                
├───────────────────────────────────────────────────────────┤
│ 📋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒                                 
│ ┝━━ 𝐑𝐞𝐠.𝐍𝐨.    : `{reg_no}`                                  
│ ┝━━ 𝐑𝐞𝐠.𝐃𝐚𝐭𝐞.     : {reg_dt}                                     
│ ┝━━ 𝐌𝐟𝐠.  : {mfg_loc}                       
│ ╰━━ 𝐒𝐭𝐚𝐭𝐞.    : {state}                                      
│                                                           
│ 👤 𝐎𝐖𝐍𝐄𝐑𝐒𝐇𝐈𝐏 𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒                                  
│ ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐍𝐚𝐦𝐞     : {owner_name}                            
│ ┝━━ 𝐎𝐰𝐧𝐞𝐫 𝐒𝐞𝐫𝐢𝐚𝐥 𝐍𝐨.  :  {owner_sr_no}                       
│ ╰━━ 𝐀𝐝𝐝𝐫𝐞𝐬𝐬  : {address}                              
│                                                           
│ 🚘 𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀𝐋 𝐒𝐏𝐄𝐂𝐈𝐅𝐈𝐂𝐀𝐓𝐈𝐎𝐍𝐒                             
│ ┝━━ 𝐌𝐨𝐝𝐞𝐥    : {model}                        
│ ┝━━ 𝐌𝐚𝐤𝐞𝐫    : {maker}                                 
│ ┝━━ 𝐂𝐥𝐚𝐬𝐬    : {vh_class}                         
│ ┝━━ 𝐁𝐨𝐝𝐲 𝐓𝐲𝐩𝐞 :  {body_type}                                      
│ ┝━━ 𝐅𝐮𝐞𝐥 :  {fuel}
│ ┝━━ 𝐄𝐦𝐢𝐬𝐬𝐢𝐨𝐧 𝐍𝐨𝐫𝐦 :  {emission}                                  
│ ┝━━ 𝐂𝐮𝐛𝐢𝐜 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {cubic_cap}
│ ┝━━ 𝐒𝐞𝐚𝐭𝐢𝐧 𝐂𝐚𝐩𝐚𝐜𝐢𝐭𝐲 : {seating}                           
│ ┝━━ 𝐂𝐡𝐚𝐬𝐬𝐢𝐬  : `{chassis}`                          
│ ╰━━ 𝐄𝐧𝐠𝐢𝐧𝐞   : `{engine}`                              
│                                                           
│ 🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏𝐋𝐈𝐀𝐍𝐂𝐄                                
│ ┝━━ 𝐈𝐧𝐬𝐮𝐫𝐚𝐧𝐜𝐞 𝐂𝐨𝐦𝐩𝐚𝐧𝐲  : {ins_comp}          
│ ┝━━ 𝐏𝐨𝐥𝐢𝐜𝐲 𝐍𝐨.   : {policy_no}                               
│ ┝━━ 𝐄𝐱𝐩𝐢𝐫𝐲   : {ins_exp}
│ ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                           
│ ┝━━ 𝐅𝐢𝐧𝐚𝐧𝐜𝐞𝐫  :  {financer}                   
│ ┝━━ 𝐑𝐨𝐚𝐝 𝐓𝐚𝐱 : {road_tax}                                          
│ ┝━━ 𝐅𝐢𝐭𝐧𝐞𝐬𝐬   : {fitness}
│ ┝━━ 𝐏𝐔𝐂 𝐍𝐮𝐦𝐛𝐞𝐫   : {puc_no}                                            
│ ╰━━ 𝐏𝐔𝐂 𝐕𝐚𝐥𝐢𝐝𝐢𝐭𝐲     : {puc_val}          
│                                                           
│ ⚖️ 𝐋𝐄𝐆𝐀🇱 & 𝐏𝐄𝐑𝐌𝐈𝐓 𝐒𝐓𝐀𝐓𝐔𝐒                                  
│ ┝━━ 𝐁𝐥𝐚𝐜𝐤𝐥𝐢𝐬𝐭: {blacklist}                                       
│ ┝━━ 𝐏𝐞𝐫𝐦𝐢𝐭   : {permit}                                           
│ ╰━━ 𝐒𝐭𝐚𝐭𝐮𝐬    : {status}                                   
├───────────────────────────────────────────────────────────┤
│ 🔒 SECURE ID: #VAHAN-{reg_no}                      
├───────────────────────────────────────────────────────────┤
│                 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐎𝐅𝐅𝐈𝐂𝐈𝐀🇱              
╰───────────────────────────────────────────────────────────╯"""
    return template

# ==========================================
# TELEGRAM BOT HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user_name}! 👋\n\nSend me any vehicle registration number to get full audit details."
    )

async def add_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to grant time-based VIP access: /add <user_id> <days>"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    try:
        args = context.args
        target_user_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else 1

        # Calculate Exact Expiry Time (Hour, Minute, Second)
        expiry_datetime = datetime.now() + timedelta(days=days)
        vip_users[target_user_id] = expiry_datetime

        formatted_expiry = expiry_datetime.strftime("%d/%m/%Y at %I:%M %p")
        await update.message.reply_text(
            f"✅ **VIP Access Granted!**\n\n"
            f"👤 **User ID:** `{target_user_id}`\n"
            f"⏳ **Duration:** {days} Days\n"
            f"📅 **Exact Expiry:** {formatted_expiry}",
            parse_mode="Markdown"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ **Usage:** `/add <user_id> <days>`\nExample: `/add 123456789 1`", parse_mode="Markdown")

async def handle_vehicle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # 1. Access Check
    if not is_vip(user_id):
        await update.message.reply_text(
            "🔒 **Access Denied!**\nYou do not have active VIP access. Please contact the Admin to get access.",
            parse_mode="Markdown"
        )
        return

    raw_text = update.message.text
    # 2. Auto-Capitalization & Cleaning
    v_number = clean_vno(raw_text)

    # Basic regex validation for Indian Vehicle Numbers
    if len(v_number) < 6 or len(v_number) > 13:
        await update.message.reply_text("⚠️ Please enter a valid vehicle registration number.")
        return

    status_msg = await update.message.reply_text("🔍 *Searching Vehicle Database... Please wait*", parse_mode="Markdown")

    # 3. Forced Delay (7 to 10 seconds wait requirement)
    await asyncio.sleep(7)

    # 4. Fetch Details from API
    try:
        async with httpx.AsyncClient() as client:
            url = f"{API_GATEWAY_URL.rstrip('/')}/{v_number}"
            res = await client.get(url, timeout=15.0)

            if res.status_code == 200:
                json_data = res.json()
                rc_details = json_data.get("rc_details", {})
                data_list = rc_details.get("data", [])

                if data_list and len(data_list) > 0:
                    veh_data = data_list[0]
                    
                    # Format output using updated template
                    final_text = format_vip_response(veh_data, v_number)
                    await status_msg.edit_text(final_text, parse_mode="Markdown")
                    return

    except Exception as e:
        print(f"API Fetch Error: {e}")

    # 5. Stylish Premium "DETAIL NOT FOUND" Card Message
    not_found_card = f"""╭────────────────────────────────────────╮
│ ⚠️ 𝙑𝘼𝙃𝘼𝙉 𝘿𝘼𝙏𝘼𝘽𝘼𝙎𝙀 𝙉𝙊𝙏𝙄𝙁𝙄𝘾𝘼𝙏𝙄𝙊𝙉         │
├────────────────────────────────────────┤
│                                        │
│  ❌  **DETAIL NOT FOUND**              │
│                                        │
│  `{v_number}` is not registered or      │
│  records are currently unavailable.    │
│                                        │
│  👉  **CHECK ANOTHER VEHICLE NUMBER**  │
│                                        │
╰────────────────────────────────────────╯"""

    await status_msg.edit_text(not_found_card, parse_mode="Markdown")

# ==========================================
# BOT LIFECYCLE MANAGEMENT FOR FASTAPI
# ==========================================
telegram_app = Application.builder().token(BOT_TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("add", add_vip_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vehicle_query))

@app.on_event("startup")
async def startup_event():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
