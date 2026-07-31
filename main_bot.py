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
# ⚙️ CONFIGURATION
# =====================================================================
BOT_TOKEN = "8426663183:AAGuwB29q55WaphV3Lwm01B5RS529ZaCUDA"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Your_Telegram_Username"   # 👈 Apna Telegram Username dalein (e.g. @Vikas_Support)
YOUR_UPI_ID = "yourupi@paytm"                # 👈 Apna UPI ID dalein
YOUR_NAME = "Parivahan Elite Service"
FASTAPI_GATEWAY = "http://127.0.0.1:10000/api/v1/vehicle/"
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

# ---------------- DYNAMIC QR GENERATOR ----------------
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
        "✨ <b>VEHICLE ELITE INTELLIGENCE BOT</b> ✨\n"
        "━━━━━━━ Dashboard ━━━━━━━\n\n"
        "👤 <b>ACCOUNT STATUS</b>\n"
        f"┣ 🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"┣ ⚡ <b>Free Credits:</b> <code>{credits} Searches</code>\n"
        f"┗ 💎 <b>Unlimited Pass:</b> <code>{'ACTIVE ✅' if active else 'INACTIVE ❌'}</code>\n\n"
    )
    if active:
        status_text += f"⏰ <b>Pass Expiry:</b> <code>{plan_expiry}</code>\n\n"

    status_text += (
        "🔍 <b>How to Search:</b>\n"
        "Bas gadi ka registration number type karke bhejein!\n"
        "<i>Example: GJ05CX7222</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Upgrade to Unlimited Pass", callback_data="buy_plan")]
    ])
    await message.answer(status_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "buy_plan")
async def show_plans(callback: types.CallbackQuery):
    text = (
        "💳 <b>SELECT YOUR UNLIMITED VIP PASS</b>\n"
        "━━━━━━━ VIP Pricing ━━━━━━━\n\n"
        "⚡ <b>1-DAY UNLIMITED PASS</b>\n"
        "┣ Price: <b>₹30</b>\n"
        "┗ Validity: <b>24 Hours Access</b>\n\n"
        "💎 <b>7-DAY UNLIMITED PASS</b>\n"
        "┣ Price: <b>₹90</b> (Save 60%)\n"
        "┗ Validity: <b>7 Days Access</b>\n\n"
        "👇 Click below to generate Dynamic Payment QR:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Buy 1-Day Pass (₹30)", callback_data="pay_30")],
        [InlineKeyboardButton(text="💎 Buy 7-Day Pass (₹90)", callback_data="pay_90")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data.in_({"pay_30", "pay_90"}))
async def process_qr_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    amount = 30 if callback.data == "pay_30" else 90
    plan_name = "1-Day Unlimited Pass" if amount == 30 else "7-Day Unlimited Pass"
    txn_note = f"RC_{user_id}"

    qr_bytes = generate_upi_qr(YOUR_UPI_ID, YOUR_NAME, amount, txn_note)
    input_file = BufferedInputFile(qr_bytes, filename=f"qr_{user_id}.png")

    caption_text = (
        "⏳ <b>INSTANT UPI PAYMENT QR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Plan Selected:</b> <code>{plan_name}</code>\n"
        f"💵 <b>Payable Amount:</b> <code>₹{amount}</code>\n"
        f"🆔 <b>Your User ID:</b> <code>{user_id}</code>\n"
        "⏱ <b>QR Validity:</b> <code>4 Minutes</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>HOW TO ACTIVATE INSTANTLY:</b>\n"
        "1️⃣ QR Code scan karke payment complete karein.\n"
        "2️⃣ Payment successful ka <b>Screenshot</b> lein.\n"
        f"3️⃣ Screenshot aur apni User ID (<code>{user_id}</code>) hamare Support Admin ko bhejein:\n\n"
        f"👉 <b>Support Admin:</b> {ADMIN_USERNAME}\n\n"
        "⚡ <i>Verification ke 1 minute me aapka pass activate ho jayega!</i>"
    )

    await callback.answer()
    qr_msg = await callback.message.answer_photo(
        photo=input_file,
        caption=caption_text,
        parse_mode="HTML"
    )
    asyncio.create_task(auto_expire_qr(qr_msg, 240))

async def auto_expire_qr(msg: types.Message, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
        await msg.answer("⌛ <b>QR Code Expired!</b> High speed gateway session complete ho gaya hai. Wapas /start karke naya QR generate karein.", parse_mode="HTML")
    except Exception:
        pass

# ---------------- ADMIN ACTIVATION ----------------
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
        await message.answer(f"✅ User <code>{target_user}</code> ka <b>{days}-Day Unlimited Plan</b> activate ho gaya hai.", parse_mode="HTML")
        
        await bot.send_message(
            target_user,
            f"🎉 <b>VIP PASS ACTIVATED!</b>\n\n"
            f"Aapka <b>{days}-Day Unlimited Search Pass</b> successfully active ho chuka hai! "
            f"Ab aap kitni bhi gadiyon ke details search kar sakte hain.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer("❌ Usage: <code>/activate &lt;USER_ID&gt; &lt;DAYS&gt;</code>\nExample: <code>/activate 8204069256 1</code>", parse_mode="HTML")

# ---------------- ULTRA PREMIUM VEHICLE REPORT HANDLER ----------------
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
            [InlineKeyboardButton(text="💳 Buy Unlimited Pass", callback_data="buy_plan")]
        ])
        await message.answer(
            "❌ <b>FREE CREDIT LIMIT EXHAUSTED!</b>\n\n"
            "Aapke 2 Free Searches khatam ho chuke hain. Unlimited searches ke liye VIP Pass unlock karein:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    wait_msg = await message.answer("🔍 <b>Generating Ultra-Audit Report...</b>\n<i>Connecting to RTO Servers...</i>", parse_mode="HTML")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{FASTAPI_GATEWAY}{vehicle_no}", timeout=15.0)
            if resp.status_code == 200:
                json_data = resp.json()
                rc_data = json_data.get("rc_details", {}).get("data", [])[0]

                # Data Formatting
                v_num = rc_data.get('regn_no', vehicle_no)
                reg_dt = rc_data.get('regn_dt', 'N/A')
                rto_auth = f"{rc_data.get('rto', 'N/A')}, {rc_data.get('state', 'N/A')}"
                rto_code = rc_data.get('rto_code', 'N/A')
                state = rc_data.get('state', 'N/A')

                owner = rc_data.get('owner_name', 'N/A')
                owner_sr = rc_data.get('owner_sr', '1st OWNER')
                address = rc_data.get('address', 'N/A')

                model = rc_data.get('maker_modal', 'N/A')
                maker = rc_data.get('maker', 'N/A')
                v_class = rc_data.get('vclass_desc', 'N/A')
                body = rc_data.get('body_type', 'N/A')
                color = rc_data.get('color', 'N/A')
                fuel = rc_data.get('fuel_type', 'N/A')
                mfg_dt = rc_data.get('mfg_dt', 'N/A')
                chassis = rc_data.get('chasi_no', 'N/A')
                engine = rc_data.get('engine_no', 'N/A')

                ins_comp = rc_data.get('ins_comp', 'N/A')
                policy = rc_data.get('policy_no', 'N/A')
                ins_upto = rc_data.get('insUpto', 'N/A')
                road_tax = rc_data.get('tax_upto', 'LTT')
                fitness = rc_data.get('fit_upto', 'N/A')
                puc = rc_data.get('puc_upto', 'N/A')
                status = rc_data.get('status', 'ACTIVE')

                # Dynamic Status Badges
                status_badge = "✅ ACTIVE" if status.upper() == "ACTIVE" else "🔴 INACTIVE"
                fit_badge = f"✅ {fitness}" if fitness != "N/A" else "⚠️ EXPIRED"
                puc_badge = f"✅ {puc}" if puc != "N/A" else "⚠️ EXPIRED"

                # 💎 ULTRA PREMIUM REPORT TEMPLATE (WITHOUT MOBILE NUMBER)
                ultra_report = f"""📑 <b>𝐕𝐄𝐇𝐈𝐂𝐋𝐄 𝐀𝐔𝐃𝐈𝐓 𝐑𝐄𝐏𝐎𝐑𝐓</b>
╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼

📋 <b>𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐀𝐓𝐈𝐎𝐍 𝐃𝐄𝐓𝐀𝐈𝐋𝐒</b>
┠ <b>𝐍𝐮𝐦𝐛𝐞𝐫</b>   : <code>{v_num}</code>
┠ <b>𝐃𝐚𝐭𝐞</b>     : {reg_dt}
┠ <b>𝐀𝐮𝐭𝐡𝐨𝐫</b>   : {rto_auth}
┠ <b>𝐑𝐓𝐎 𝐂𝐨𝐝𝐞</b> : {rto_code}
┖ <b>𝐒𝐭𝐚𝐭𝐞</b>    : {state}

👤 <b>𝐎𝐖𝐍𝐄𝐑𝐒𝐇𝐈𝐏 𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒</b>
┠ <b>𝐍𝐚𝐦𝐞</b>     : <b>{owner}</b>
┠ <b>𝐒𝐞𝐫𝐢𝐚𝐥</b>   : {owner_sr}
┖ <b>𝐀𝐝𝐝𝐫𝐞𝐬𝐬</b>  : {address}

🚘 <b>𝐓𝐄𝐂𝐇𝐍𝐈𝐂𝐀𝐋 𝐒𝐏𝐄𝐂𝐈𝐅𝐈𝐂𝐀𝐓𝐈𝐎𝐍𝐒</b>
┠ <b>𝐌𝐨𝐝𝐞𝐥</b>    : {model}
┠ <b>𝐌𝐚𝐤𝐞𝐫</b>    : {maker}
┠ <b>𝐂𝐥𝐚𝐬𝐬</b>    : {v_class}
┠ <b>𝐁𝐨𝐝𝐲</b>     : {body}
┠ <b>𝐂𝐨𝐥𝐨𝐫</b>    : {color}
┠ <b>𝐅𝐮𝐞𝐥</b>     : {fuel}
┠ <b>𝐌𝐟𝐠 𝐃𝐚𝐭𝐞</b> : {mfg_dt}
┠ <b>𝐂𝐡𝐚𝐬𝐬𝐢𝐬</b>  : <code>{chassis}</code>
┖ <b>𝐄𝐧𝐠𝐢𝐧𝐞</b>   : <code>{engine}</code>

🛡 <b>𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 &amp; 𝐂𝐎𝐌𝐏𝐋𝐈𝐀𝐍𝐂𝐄</b>
┠ <b>𝐂𝐨𝐦𝐩𝐚𝐧𝐲</b>  : {ins_comp}
┠ <b>𝐏𝐨𝐥𝐢𝐜𝐲</b>   : <code>{policy}</code>
┠ <b>𝐄𝐱Profiles</b>   : {ins_upto}
┠ <b>𝐑𝐨𝐚𝐝 𝐓𝐚𝐱</b> : {road_tax}
┠ <b>𝐅𝐢𝐭𝐧𝐞𝐬𝐬</b>   : {fit_badge}
┖ <b>𝐏𝐔𝐂𝐂</b>     : {puc_badge}

⚖️ <b>𝐋𝐄𝐆𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒</b>
┖ <b>𝐒𝐭𝐚𝐭𝐮𝐬</b>   : {status_badge}

╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼
✅ <b>𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐎𝐅𝐅𝐈𝐂𝐈𝐀𝐋 𝐑𝐄𝐏𝐎𝐑𝐓</b>"""

                if not active:
                    await update_user_credits(user_id, credits - 1)
                    ultra_report += f"\n💡 <i>Remaining Free Credits: {credits - 1}</i>"

                await wait_msg.delete()
                await message.answer(ultra_report, parse_mode="HTML")
            else:
                await wait_msg.edit_text("❌ <b>Vehicle record not found in RTO Database.</b>", parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text("❌ <b>Server Error or Timeout. Please try again.</b>", parse_mode="HTML")

# ---------------- MAIN ----------------
async def main():
    await init_db()
    print("🤖 Ultra-Premium Telegram Bot is Live!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
