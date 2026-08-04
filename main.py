import os
import json
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
            model='gemini-2.0-flash',
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
                                                          
🚘 𝐓𝐄𝐂𝐇𝐍🇮𝘾𝘼🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊𝐍𝐒                              
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
                                                          
🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼𝐍🇨🇪                                
┝━━ 𝐈𝐧𝐬𝐮𝐫𝙖𝙣𝐜𝐞 𝐂𝐨𝐦𝙥𝙖𝐧𝙮  : {ins_company}          
┝━━ 𝐏𝐨𝐥🇮𝙘𝙮 𝐍𝐨.   : {ins_policy}                                
┝━━ 𝐄𝐱𝐩🇮𝙧𝙮   : {ins_exp}
┝━━ 𝐅🇮𝙣𝙖𝙣𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                            
┝━━ 𝐅🇮```python
import os
import json
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
from google import genai
from google.genai import types

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8426663183:AAG1CFm0PiC7DN1zOsFqjEEEdzi7IcvdC7k"
ADMIN_ID = 8204069256
ADMIN_USERNAME = "@Mrx477"
UPI_ID = "9696159863.wallet@phonepe"
API_BASE_URL = "[https://vehicle-master-api.onrender.com/api/v1/vehicle/](https://vehicle-master-api.onrender.com/api/v1/vehicle/)"

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
            model='gemini-2.0-flash',
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
                                                          
🚘 𝐓𝐄𝐂𝐇𝐍🇮𝘾𝘼🇱 𝐒𝐏𝐄𝐂🇮🇫🇮𝘾𝘼𝙏🇮𝙊𝐍𝐒                              
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
                                                          
🛡 𝐈𝐍𝐒𝐔𝐑𝐀𝐍𝐂𝐄 & 𝐂𝐎𝐌𝐏🇱🇮𝘼Nap🇨🇪                                
┝━━ 𝐈𝐧𝐬𝐮𝐫𝐚𝐧𝐜𝐞 𝐂𝐨𝐦𝐩𝙖𝐧𝙮  : {ins_company}          
┝━━ 𝐏𝐨𝐥🇮𝙘𝙮 𝐍𝐨.   : {ins_policy}                                
┝━━ 𝐄𝐱𝐩🇮𝙧𝙮   : {ins_exp}
┝━━ 𝐅🇮𝙣𝙖𝐧𝐜𝐞 𝐒𝐭𝐚𝐭𝐮𝐬  :  {fin_status}                            
┝━━ 𝐅🇮Aapne jis code (`main.py`) aur `requirements.txt` ki baat ki hai, woh yahan attach ya paste nahi hua hai. 

Kripya apna current `main.py`, `requirements.txt` aur aapko kya kaam karwana hai (kon sa feature add ya fix karna hai) yahan share karein, taaki main poora complete code ready karke de sakoon.
