import asyncio
import io
import logging
from datetime import datetime, timedelta
import aiosqlite
import httpx
import qrcode
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

# =====================================================================
# ⚙️ SETTINGS - AAPKI DETAILS AUTOMATICALLY SET KAR DI GAYI HAIN
# =====================================================================
BOT_TOKEN = "8426663183:AAGuwB29q55WaphV3Lwm01B5RS529ZaCUDA"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Your_Telegram_Username"   # 👈 Yahan apna personal Telegram username dalein (jaise @Vikas_Support)
YOUR_UPI_ID = "yourupi@paytm"                # 👈 Yahan apna GPay / PhonePe / Paytm UPI ID dalein
YOUR_NAME = "Parivahan Service"
FASTAPI_GATEWAY = "http://127.0.0.1:10000/api/v1/vehicle/" # Local ya Ngrok FastAPI URL
DB_FILE = "bot_database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- DATABASE LOGIC ----------------
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
        expiry_date = datetime.fromisoformat(expiry_str)
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

# ---------------- BOT HANDLERS ----------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    credits, plan_expiry = await get_or_create_user(user_id, username)
    active = is_plan_active(plan_expiry)

    status_text = (
        f"👋 **Welcome to Vehicle Elite Bot!**\n\n"
        f"📊 **Your Account Status:**\n"
        f"• Free Credits Remaining: `{credits}` Search(es)\n"
        f"• Unlimited Pass: `{'ACTIVE ✅' if active else 'INACTIVE ❌'}`\n"
    )
    if active:
        status_text += f"• Expire On: `{plan_expiry}`\n"

    status_text += "\n🔍 **How to use:** Simply send vehicle registration number (e.g., `DL01AB1234`)."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Buy Unlimited Pass", callback_data="buy_plan")]
    ])
    await message.answer(status_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data == "buy_plan")
async def show_plans(callback: types.CallbackQuery):
    text = (
        "⚡ **CHOOSE UNLIMITED SEARCH PLAN** ⚡\n\n"
        "1️⃣ **Daily Unlimited Pass**\n"
        "• Price: **₹30** | Validity: **24 Hours**\n\n"
        "2️⃣ **Weekly Unlimited Pass**\n"
        "• Price: **₹90** | Validity: **7 Days**\n\n"
        "👇 Click below to pay via Dynamic UPI QR:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Buy 1-Day Pass (₹30)", callback_data="pay_30")],
        [InlineKeyboardButton(text="💎 Buy 1-Week Pass (₹90)", callback_data="pay_90")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data.in_({"pay_30", "pay_90"}))
async def process_qr_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    amount = 30 if callback.data == "pay_30" else 90
    plan_name = "1-Day Pass (₹30)" if amount == 30 else "1-Week Pass (₹90)"
    txn_note = f"RC_{user_id}"

    qr_bytes = generate_upi_qr(YOUR_UPI_ID, YOUR_NAME, amount, txn_note)
    input_file = BufferedInputFile(qr_bytes, filename=f"qr_{user_id}.png")

    caption_text = (
        f"⏳ **DYNAMIC PAYMENT QR CODE** (Valid for 4 Minutes)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **Plan:** `{plan_name}`\n"
        f"💵 **Amount:** `₹{amount}`\n"
        f"🆔 **Your Telegram User ID:** `{user_id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 **HOW TO ACTIVATE SUBSCRIPTION:**\n"
        f"1. QR Scan karke Payment complete karein.\n"
        f"2. Payment ka **Screenshot** lein.\n"
        f"3. Screenshot aur apni User ID (`{user_id}`) mujhe directly inbox karein:\n"
        f"👉 **Support Admin:** {ADMIN_USERNAME}\n\n"
        f"⚠️ *Payment milte hi instant plan activate ho jayega!*"
    )

    await callback.answer()
    qr_msg = await callback.message.answer_photo(
        photo=input_file,
        caption=caption_text,
        parse_mode="Markdown"
    )
    asyncio.create_task(auto_expire_qr(qr_msg, 240))

async def auto_expire_qr(msg: types.Message, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
        await msg.answer("⌛ **QR Code Expired!** Time out ho gaya hai. Dobara `/start` karke plan choose karein.")
    except Exception:
        pass

# ---------------- ADMIN PLAN ACTIVATION COMMAND ----------------
@dp.message(Command("activate"))
async def admin_activate(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        args = message.text.split()
        target_user = int(args[1])
        days = int(args[2])
        
        plan_type = "DAILY" if days == 1 else "WEEKLY"
        await activate_plan(target_user, plan_type, days)
        await message.answer(f"✅ User `{target_user}` ka {days}-Day Unlimited Plan active kar diya gaya hai.")
        
        await bot.send_message(
            target_user,
            f"🎉 **CONGRATULATIONS!**\n\n"
            f"Aapka **{days}-Day Unlimited Search Pass** successfully activate ho gaya hai! "
            f"Ab aap kitni bhi gadiyon ke details search kar sakte hain."
        )
    except Exception as e:
        await message.answer("❌ Usage: `/activate <USER_ID> <DAYS>`\nExample: `/activate 8204069256 1`")

# ---------------- VEHICLE SEARCH HANDLER ----------------
@dp.message()
async def search_vehicle(message: types.Message):
    vehicle_no = message.text.replace(" ", "").upper()
    user_id = message.from_user.id
    username = message.from_user.username or "User"

    if vehicle_no.startswith("/"):
        return

    credits, plan_expiry = await get_or_create_user(user_id, username)
    active = is_plan_active(plan_expiry)

    if not active and credits <= 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Buy Pass (Starts @ ₹30)", callback_data="buy_plan")]
        ])
        await message.answer(
            "❌ **Free Limit Ended!**\n\n"
            "Aapke 2 free searches poore ho chuke hain. Unlimited searches ke liye plan buy karein:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    wait_msg = await message.answer("🔎 *Fetching Vehicle Details...*", parse_mode="Markdown")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{FASTAPI_GATEWAY}{vehicle_no}", timeout=15.0)
            if resp.status_code == 200:
                json_data = resp.json()
                rc_data = json_data.get("rc_details", {}).get("data", [])[0]

                res_text = (
                    f"🏎 **PARIVAHAN VEHICLE DETAILS**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 **Owner:** `{rc_data.get('owner_name')}`\n"
                    f"🚗 **Maker/Model:** `{rc_data.get('maker_modal')}`\n"
                    f"📅 **Reg Date:** `{rc_data.get('regn_dt')}` ({rc_data.get('vehicle_age')})\n"
                    f"⛽ **Fuel:** `{rc_data.get('fuel_type')}` | **Norms:** `{rc_data.get('fuel_norms')}`\n"
                    f"🏢 **RTO:** `{rc_data.get('rto')}, {rc_data.get('state')}`\n"
                    f"🏛 **Financer:** `{rc_data.get('financer_name')}`\n"
                    f"🛡 **Insurance Upto:** `{rc_data.get('insUpto')}`\n"
                    f"📋 **Policy No:** `{rc_data.get('policy_no')}`\n"
                    f"🧪 **PUC Upto:** `{rc_data.get('puc_upto')}`\n"
                    f"⚙️ **Engine No:** `{rc_data.get('engine_no')}`\n"
                    f"🔑 **Chassis No:** `{rc_data.get('chasi_no')}`\n"
                    f"🏠 **Address:** `{rc_data.get('address')}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                )

                if not active:
                    await update_user_credits(user_id, credits - 1)
                    res_text += f"\n💡 *Free Searches Left: {credits - 1}*"

                await wait_msg.delete()
                await message.answer(res_text, parse_mode="Markdown")
            else:
                await wait_msg.edit_text("❌ Vehicle details not found.")
    except Exception as e:
        await wait_msg.edit_text("❌ System error or invalid vehicle number.")

# ---------------- MAIN RUNNER ----------------
async def main():
    await init_db()
    print("🤖 Telegram Bot is running live!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
