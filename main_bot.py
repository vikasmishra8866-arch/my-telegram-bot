import asyncio
import io
import logging
import os
import re
import threading
from datetime import datetime, timedelta

import aiosqlite
import fastapi
import httpx
import qrcode
import uvicorn
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

# =====================================================================
# ⚙️ CONFIGURATION & CREDENTIALS
# =====================================================================
BOT_TOKEN = "8426663183:AAEkVlkL4qIZz6srseuHiSi2QyoXUEt-0mk"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Mrx477"   # Apna Telegram Username yahan daalein
YOUR_UPI_ID = "9696159863.wallet@phonepe"                # Apni UPI ID yahan daalein
YOUR_NAME = "Parivahan Elite Service"

# External RTO Source API Config
REMOTE_RTO_URL = "http://103.241.139.112:8000/rc"
API_AUTH_TOKEN = "Bearer token-gemini-parivahan-998877665544332211"

DB_FILE = "bot_database.db"

# Memory State Trackers
user_active_qrs = {}       # {user_id: message_id}
user_state = {}            # {user_id: "AWAITING_VEHICLE" or "AWAITING_IFSC"}

logging.basicConfig(level=logging.INFO)

# =====================================================================
# 🚀 PART 1: FASTAPI BACKEND GATEWAY (FOR RENDER HEALTH CHECK)
# =====================================================================
app = fastapi.FastAPI(title="Parivahan Unified Gateway")

@app.get("/")
def home():
    return {"status": "Online", "service": "Parivahan & Bank Intelligence Server"}

@app.get("/api/v1/vehicle/{vehicle_no}")
async def get_vehicle_details(vehicle_no: str):
    clean_v_num = vehicle_no.replace(" ", "").upper()
    headers = {
        "Authorization": API_AUTH_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"rc_number": clean_v_num}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(REMOTE_RTO_URL, json=payload, headers=headers, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "rc_details": data}
            else:
                raise fastapi.HTTPException(status_code=response.status_code, detail="Vehicle record not found")
        except Exception as e:
            raise fastapi.HTTPException(status_code=500, detail=str(e))

def run_fastapi():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)


# =====================================================================
# 🤖 PART 2: TELEGRAM BOT LOGIC
# =====================================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- DATABASE CONTROLLER ----------------

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                free_credits INTEGER DEFAULT 2,
                plan_type TEXT DEFAULT 'NONE',
                plan_expiry TIMESTAMP,
                joined_at TIMESTAMP
            )
        """)
        await db.commit()

async def get_or_create_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT free_credits, plan_expiry FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                now = datetime.now()
                await db.execute(
                    "INSERT INTO users (user_id, username, free_credits, joined_at) VALUES (?, ?, 2, ?)",
                    (user_id, username, now)
                )
                await db.commit()
                return 2, None
            return row[0], row[1]

async def update_user_credits(user_id: int, new_credits: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET free_credits = ? WHERE user_id = ?", (new_credits, user_id))
        await db.commit()

async def activate_plan(user_id: int, plan_type: str, days: int):
    async with aiosqlite.connect(DB_FILE) as db:
        expiry_date = datetime.now() + timedelta(days=days)
        await db.execute(
            "UPDATE users SET plan_type = ?, plan_expiry = ? WHERE user_id = ?",
            (plan_type, expiry_date, user_id)
        )
        await db.commit()

def is_plan_active(expiry_str: str) -> bool:
    if not expiry_str:
        return False
    try:
        expiry_date = datetime.fromisoformat(str(expiry_str))
        return expiry_date > datetime.now()
    except Exception:
        return False

# ---------------- QR CODE GENERATOR ----------------

def generate_upi_qr(upi_id: str, name: str, amount: int, note: str) -> bytes:
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR&tn={note}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()


# ---------------- TELEGRAM UI & COMMANDS ----------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    credits, plan_expiry = await get_or_create_user(user_id, username)
    active = is_plan_active(plan_expiry)
    
    user_state.pop(user_id, None)

    status_text = (
        "✨ <b>VEHICLE & BANK INTELLIGENCE BOT</b> ✨\n"
        "━━━━━━━ Dashboard ━━━━━━━\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"⚡ <b>Free Credits:</b> <code>{credits} Searches</code>\n"
        f"┗ 💎 <b>Unlimited Pass:</b> <code>{'ACTIVE ✅' if active else 'INACTIVE ❌'}</code>\n\n"
    )
    if active:
        status_text += f"⏰ <b>Expiry:</b> <code>{plan_expiry}</code>\n\n"

    status_text += "📌 <b>Neeche diye gaye options me se select karein:</b>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Get Vehicle Details", callback_data="prompt_vehicle_input"),
            InlineKeyboardButton(text="🏦 Fetch IFSC Code", callback_data="prompt_ifsc_input")
        ],
        [
            InlineKeyboardButton(text="💎 Upgrade to Unlimited Pass", callback_data="buy_plan")
        ]
    ])
    await message.answer(status_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "prompt_vehicle_input")
async def ask_vehicle_number(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_state[user_id] = "AWAITING_VEHICLE"
    
    prompt_text = (
        "🚗 <b>ENTER VEHICLE REGISTRATION NUMBER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kripya gadi ka registration number type karke send karein.\n\n"
        "📌 <b>Example:</b> <code>GJ05CX7222</code> ya <code>MH12AB1234</code>"
    )
    await callback.answer()
    await callback.message.answer(prompt_text, parse_mode="HTML")

@dp.callback_query(F.data == "prompt_ifsc_input")
async def ask_ifsc_code(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_state[user_id] = "AWAITING_IFSC"
    
    prompt_text = (
        "🏦 <b>ENTER BANK IFSC CODE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kripya 11-digit ka bank IFSC code type karke send karein.\n\n"
        "📌 <b>Example:</b> <code>SBIN0000300</code> ya <code>HDFC0000060</code>"
    )
    await callback.answer()
    await callback.message.answer(prompt_text, parse_mode="HTML")

@dp.callback_query(F.data == "buy_plan")
async def show_plans(callback: types.CallbackQuery):
    text = (
        "💳 <b>SELECT UNLIMITED VIP PASS</b>\n"
        "━━━━━━━ Pricing ━━━━━━━\n\n"
        "⚡ <b>1-DAY PASS:</b> ₹30\n"
        "💎 <b>7-DAY PASS:</b> ₹90\n\n"
        "👇 Plan select karein:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Buy 1-Day Pass (₹30)", callback_data="pay_30")],
        [InlineKeyboardButton(text="💎 Buy 7-Day Pass (₹90)", callback_data="pay_90")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data.in_({"pay_30", "pay_90"}))
async def process_qr_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in user_active_qrs:
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=user_active_qrs[user_id])
        except Exception:
            pass

    amount = 30 if callback.data == "pay_30" else 90
    plan_name = "1-Day Pass" if amount == 30 else "7-Day Pass"
    
    qr_bytes = generate_upi_qr(YOUR_UPI_ID, YOUR_NAME, amount, f"RC_{user_id}")
    input_file = BufferedInputFile(qr_bytes, filename=f"qr_{user_id}.png")

    caption_text = (
        "⏳ <b>UPI PAYMENT QR CODE</b>\n"
        f"📦 Plan: <b>{plan_name}</b> | Amount: <b>₹{amount}</b>\n\n"
        "1️⃣ Scan karke payment karein.\n"
        "2️⃣ Screenshot aur User ID niche admin ko bhejein:\n"
        f"👉 <b>Admin:</b> {ADMIN_USERNAME}"
    )

    await callback.answer()
    qr_msg = await callback.message.answer_photo(photo=input_file, caption=caption_text, parse_mode="HTML")
    user_active_qrs[user_id] = qr_msg.message_id
    asyncio.create_task(auto_expire_qr(qr_msg, user_id, 240))

async def auto_expire_qr(msg: types.Message, user_id: int, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        if user_active_qrs.get(user_id) == msg.message_id:
            del user_active_qrs[user_id]
            await msg.delete()
    except Exception:
        pass

@dp.message(Command("activate"))
async def admin_activate(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        target_user = int(args[1])
        days = int(args[2])
        await activate_plan(target_user, "VIP", days)
        await message.answer(f"✅ User <code>{target_user}</code> ka plan active ho gaya hai.", parse_mode="HTML")
        await bot.send_message(target_user, f"🎉 <b>VIP PASS ACTIVATED!</b> Aapka {days}-day pass chalu ho gaya hai.", parse_mode="HTML")
    except Exception:
        await message.answer("❌ Format: `/activate USER_ID DAYS`", parse_mode="HTML")


# ---------------- FETCHERS (VEHICLE & IFSC) ----------------

async def fetch_ifsc_details(message: types.Message, ifsc_code: str):
    clean_ifsc = ifsc_code.strip().upper()
    wait_msg = await message.answer("🔍 <b>Searching Bank IFSC Details...</b>", parse_mode="HTML")
    
    url = f"https://ifsc.razorpay.com/{clean_ifsc}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                
                bank_name = data.get("BANK", "N/A")
                branch = data.get("BRANCH", "N/A")
                address = data.get("ADDRESS", "N/A")
                city = data.get("CITY", "N/A")
                district = data.get("DISTRICT", "N/A")
                state = data.get("STATE", "N/A")
                micr = data.get("MICR", "N/A")
                
                upi = "✅ Supported" if data.get("UPI") else "❌ Not Supported"
                neft = "✅ Supported" if data.get("NEFT") else "❌ Not Supported"
                imps = "✅ Supported" if data.get("IMPS") else "❌ Not Supported"
                rtgs = "✅ Supported" if data.get("RTGS") else "❌ Not Supported"

                report = f"""🏦 <b>𝐁𝐀𝐍𝐊 𝐈𝐅𝐒𝐂 𝐃𝐄𝐓𝐀𝐈𝐋𝐒</b>
╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼

🏛 <b>𝐁𝐀𝐍𝐊 𝐈𝐍𝐅𝐎𝐑𝐌𝐀𝐓𝐈𝐎𝐍</b>
┠ <b>Bank Name</b> : {bank_name}
┠ <b>IFSC Code</b> : <code>{clean_ifsc}</code>
┠ <b>Branch</b>    : {branch}
┖ <b>MICR Code</b>  : {micr}

📍 <b>𝐋𝐎𝐂𝐀𝐓𝐈𝐎𝐍 & ADDRESS</b>
┠ <b>Address</b>   : {address}
┠ <b>City</b>      : {city}
┠ <b>District</b>  : {district}
┖ <b>State</b>     : {state}

⚡ <b>𝐒𝐄𝐑𝐕𝐈𝐂𝐄 𝐒𝐔𝐏𝐏𝐎𝐑𝐓</b>
┠ <b>UPI</b>       : {upi}
┠ <b>NEFT</b>      : {neft}
┠ <b>IMPS</b>      : {imps}
┖ <b>RTGS</b>      : {rtgs}

╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
✅ <b>VERIFIED BANK DATA</b>"""

                await wait_msg.delete()
                await message.answer(report, parse_mode="HTML")
            else:
                await wait_msg.edit_text("❌ <b>Invalid IFSC Code!</b> Kripya sahi 11-digit IFSC code daalein.", parse_mode="HTML")
        except Exception as e:
            await wait_msg.edit_text(f"❌ <b>IFSC Error:</b> <code>{str(e)}</code>", parse_mode="HTML")

async def fetch_vehicle_details(message: types.Message, vehicle_no: str):
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    credits, plan_expiry = await get_or_create_user(user_id, username)
    active = is_plan_active(plan_expiry)

    if not active and credits <= 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Buy Unlimited Pass", callback_data="buy_plan")]
        ])
        await message.answer("❌ Free credits khatam ho chuke hain! Pass buy karein:", parse_mode="HTML", reply_markup=keyboard)
        return

    wait_msg = await message.answer("🔍 <b>Fetching RTO Records...</b>", parse_mode="HTML")

    try:
        async with httpx.AsyncClient() as client:
            port = os.environ.get("PORT", 10000)
            local_api_url = f"http://127.0.0.1:{port}/api/v1/vehicle/{vehicle_no}"
            resp = await client.get(local_api_url, timeout=20.0)

            if resp.status_code == 200:
                json_data = resp.json()
                rc_container = json_data.get("rc_details", {})
                rc_data = rc_container.get("data", [{}])[0] if isinstance(rc_container, dict) and "data" in rc_container else rc_container

                v_num = rc_data.get('regn_no', vehicle_no)
                reg_dt = rc_data.get('regn_dt', 'N/A')
                rto_auth = f"{rc_data.get('rto', 'N/A')}, {rc_data.get('state', 'N/A')}"
                owner = rc_data.get('owner_name', 'N/A')
                owner_sr = rc_data.get('owner_sr', '1st OWNER')
                address = rc_data.get('address', 'N/A')
                model = rc_data.get('maker_modal', 'N/A')
                maker = rc_data.get('maker', 'N/A')
                v_class = rc_data.get('vclass_desc', 'N/A')
                fuel = rc_data.get('fuel_type', 'N/A')
                chassis = rc_data.get('chasi_no', 'N/A')
                engine = rc_data.get('engine_no', 'N/A')
                status = rc_data.get('status', 'ACTIVE')

                ultra_report = f"""📑 <b>𝐕𝐄𝐇𝐈𝐂𝐋𝐄 𝐀𝐔𝐃𝐈𝐓 𝐑𝐄𝐏𝐎𝐑𝐓</b>
╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
📋 <b>REGISTRATION:</b> <code>{v_num}</code>
📅 <b>Date:</b> {reg_dt}
🏛 <b>RTO:</b> {rto_auth}

👤 <b>OWNERSHIP:</b>
• <b>Name:</b> <b>{owner}</b>
• <b>Serial:</b> {owner_sr}
• <b>Address:</b> {address}

🚘 <b>SPECIFICATIONS:</b>
• <b>Model:</b> {model}
• <b>Maker:</b> {maker}
• <b>Class:</b> {v_class}
• <b>Fuel:</b> {fuel}
• <b>Chassis:</b> <code>{chassis}</code>
• <b>Engine:</b> <code>{engine}</code>

⚖️ <b>STATUS:</b> {status}

╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
⏳ <b>SECURITY NOTICE</b>
⚠️ <i>Ye report privacy ke chalte <b>10 minute</b> me auto-delete ho jayegi. Kripya screenshot lein.</i>"""

                if not active:
                    await update_user_credits(user_id, credits - 1)

                await wait_msg.delete()
                report_msg = await message.answer(ultra_report, parse_mode="HTML")
                asyncio.create_task(auto_delete_report(report_msg, 600))
            else:
                await wait_msg.edit_text("❌ Vehicle record not found.", parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error: {str(e)}", parse_mode="HTML")

async def auto_delete_report(msg: types.Message, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
    except Exception:
        pass


# ---------------- MASTER MESSAGE ROUTER ----------------

@dp.message()
async def master_message_router(message: types.Message):
    text = message.text.strip()
    if text.startswith("/"):
        return

    user_id = message.from_user.id
    current_state = user_state.get(user_id)

    # State-based direct handling or Auto-detection fallback
    if current_state == "AWAITING_IFSC":
        user_state.pop(user_id, None)
        await fetch_ifsc_details(message, text)
    elif current_state == "AWAITING_VEHICLE":
        user_state.pop(user_id, None)
        await fetch_vehicle_details(message, text.replace(" ", "").upper())
    else:
        # Smart Auto-Detection fallback if user inputs directly without clicking buttons
        clean_text = text.replace(" ", "").upper()
        ifsc_pattern = r'^[A-Z]{4}0[A-Z0-9]{6}$'
        
        if re.match(ifsc_pattern, clean_text):
            await fetch_ifsc_details(message, clean_text)
        else:
            await fetch_vehicle_details(message, clean_text)


# =====================================================================
# 🌐 MAIN ENTRY POINT
# =====================================================================
async def start_bot_polling():
    await init_db()
    logging.info("🤖 Telegram Bot Started Polling...")
    await dp.start_polling(bot)

def run_bot_thread():
    asyncio.run(start_bot_polling())

if __name__ == "__main__":
    # Start Telegram Bot in a separate daemon thread
    bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()

    # Start FastAPI Web Server on main thread for Render Port Check
    run_fastapi()
