import os
import asyncio
import discord
from discord.ext import commands
from google import genai
from config import ACTIVE_MODELS, ALLOWED_CHANNEL_NAME, get_model_config

# อ่านค่าจาก Environment Variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# รองรับหลาย Key คั่นด้วยเครื่องหมายจุลภาค (,)
raw_keys = os.getenv("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

if not DISCORD_TOKEN or not API_KEYS:
    raise ValueError("กรุณากำหนด DISCORD_TOKEN และ GEMINI_API_KEY ใน Environment Variables")

# สร้าง Clients สำหรับแต่ละ Key
clients = [genai.Client(api_key=key) for key in API_KEYS]
current_key_index = 0

def get_next_client():
    """หมุนเวียน API Key ในกรณีที่ Key ปัจจุบันติด Quota หรือมีปัญหา"""
    global current_key_index
    client = clients[current_key_index]
    current_key_index = (current_key_index + 1) % len(clients)
    return client

# กำหนด Intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 Antibro (Coding AI) พร้อมทำงานแล้ว! ล็อกอินในชื่อ: {bot.user.name}")
    print(f"🔑 จำนวน Gemini API Keys: {len(clients)}")
    print(f"🧠 โมเดลที่พร้อมใช้งาน: {ACTIVE_MODELS}")
    print(f"💬 ห้องที่ตอบอัตโนมัติ: #{ALLOWED_CHANNEL_NAME}")
    await bot.change_presence(activity=discord.Game(name=f"คุยได้ทันทีใน #{ALLOWED_CHANNEL_NAME}"))

def split_message(text, limit=1950):
    """แบ่งข้อความหากยาวเกินขีดจำกัดของ Discord (2,000 ตัวอักษร)"""
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks

async def extract_attachments(message: discord.Message) -> str:
    """อ่านเนื้อหาไฟล์โค้ดหรือข้อความที่แนบมาด้วย"""
    extra_text = ""
    for attachment in message.attachments:
        if attachment.size <= 1_000_000:
            try:
                content_bytes = await attachment.read()
                decoded = content_bytes.decode("utf-8")
                extra_text += f"\n\n--- ไฟล์แนบ: `{attachment.filename}` ---\n```\n{decoded}\n```"
            except UnicodeDecodeError:
                extra_text += f"\n\n*(ไฟล์แนบ `{attachment.filename}` ไม่ใช่ text file ข้ามการอ่าน)*"
            except Exception as e:
                extra_text += f"\n\n*(ไม่สามารถอ่านไฟล์ `{attachment.filename}`: {e})*"
    return extra_text

async def call_gemini_with_fallback(prompt: str):
    """เรียกใช้งาน Gemini โดยมีระบบ Fallback ทั้งโมเดลและ Key พร้อมการลองซ้ำ"""
    last_error = None
    
    # วนลูปตามจำนวน Key ที่มี
    for key_attempt in range(len(clients)):
        client = get_next_client()
        
        # วนลูปโมเดลที่ใช้งานได้จริง
        for model in ACTIVE_MODELS:
            # ลองซ้ำสูงสุด 2 ครั้งสำหรับแต่ละโมเดล (กรณีติด 503 Spike ชั่วคราว)
            for retry in range(2):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=get_model_config()
                    )
                    if response and response.text:
                        return response.text, None
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"⚠️ Key #{key_attempt+1} Model {model} (รอบที่ {retry+1}): {err_str}")
                    
                    # ถ้าเจอ 503 รอ 1.5 วินาทีแล้วลองใหม่
                    if "503" in err_str:
                        await asyncio.sleep(1.5)
                        continue
                    # ถ้า 429 Quota เต็ม หรือ 404 ให้ข้ามไปโมเดล/Key ถัดไปทันที
                    break

    return None, last_error

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # ดึงชื่อห้อง (รองรับทั้ง Text Channel และ Thread)
    channel = message.channel
    channel_name = getattr(channel, "name", "")
    if hasattr(channel, "parent") and channel.parent:
        channel_name = channel.parent.name or channel_name

    # เช็คเงื่อนไขตอบอัตโนมัติ
    is_in_allowed_channel = (
        ALLOWED_CHANNEL_NAME.lower() in channel_name.lower() 
        or "anti-bot" in channel_name.lower()
    )
    is_mentioned = bot.user in message.mentions
    is_reply_to_bot = (
        message.reference 
        and message.reference.resolved 
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == bot.user
    )

    # คำสั่งทดสอบ ping
    if (is_in_allowed_channel or is_mentioned or is_reply_to_bot) and message.content.strip().lower() in ["ping", "!ping"]:
        latency_ms = round(bot.latency * 1000)
        await message.reply(f"Pong! 🏓 (Latency: {latency_ms}ms)\nห้องปัจจุบัน: `#{channel_name}` | Antibro พร้อมทำงานครับ!")
        return

    if not (is_in_allowed_channel or is_mentioned or is_reply_to_bot):
        await bot.process_commands(message)
        return

    clean_prompt = message.clean_content.replace(f"@{bot.user.name}", "").strip()
    attached_files_content = await extract_attachments(message)
    full_prompt = clean_prompt + attached_files_content

    if not full_prompt.strip():
        return

    async with message.channel.typing():
        reply_text, err = await call_gemini_with_fallback(full_prompt)

        if reply_text:
            chunks = split_message(reply_text)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply(chunk)
                else:
                    await message.channel.send(chunk)
        else:
            await message.reply(f"ขออภัยครับ ตอนนี้เซิร์ฟเวอร์ AI มีคิวหนาแน่นมาก กรุณาลองใหม่อีกครั้งในอีกสักครู่ (`{err}`)")

    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
