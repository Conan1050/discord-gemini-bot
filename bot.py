import os
import discord
from discord.ext import commands
from google import genai
from config import MODEL_NAME, ALLOWED_CHANNEL_NAME, get_model_config

# อ่านค่าจาก Environment Variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("กรุณากำหนด DISCORD_TOKEN และ GEMINI_API_KEY ใน Environment Variables")

# สร้าง Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# กำหนด Intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 Antibro (Coding AI) พร้อมทำงานแล้ว! ล็อกอินในชื่อ: {bot.user.name}")
    print(f"🧠 โมเดลที่ใช้งาน: {MODEL_NAME}")
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
    """อ่านเนื้อหาไฟล์โค้ดหรือข้อความที่แนบมาด้วย (เช่น .py, .js, .txt, .log)"""
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

@bot.event
async def on_message(message: discord.Message):
    # ข้ามข้อความจากบอท (ป้องกันบอทคุยกับตัวเอง)
    if message.author.bot:
        return

    # ดึงชื่อห้อง (รองรับทั้ง Text Channel และ Thread)
    channel = message.channel
    channel_name = getattr(channel, "name", "")
    if hasattr(channel, "parent") and channel.parent:
        channel_name = channel.parent.name or channel_name

    # เช็คเงื่อนไขตอบอัตโนมัติ:
    # 1. ชื่อห้องตรงกับ ALLOWED_CHANNEL_NAME หรือมีคำว่า 'anti-bot' อยู่ในชื่อห้อง
    # 2. หรือ ถูกแท็ก / reply บอท ในห้องใดๆ ก็ตาม
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

    # คำสั่งทดสอบ ping ทำงานเสมอถ้าอยู่ในห้องบอท หรือแท็กบอท
    if (is_in_allowed_channel or is_mentioned or is_reply_to_bot) and message.content.strip().lower() in ["ping", "!ping"]:
        latency_ms = round(bot.latency * 1000)
        await message.reply(f"Pong! 🏓 (Latency: {latency_ms}ms)\nห้องปัจจุบัน: `#{channel_name}` บอทพร้อมทำงานครับ!")
        return

    if not (is_in_allowed_channel or is_mentioned or is_reply_to_bot):
        # ถ้าไม่อยู่ในห้อง anti-bot และไม่ได้แท็กบอท ให้ข้ามไป
        await bot.process_commands(message)
        return

    # ดึงข้อความและตัดแท็กบอทออก (ถ้ามี)
    clean_prompt = message.clean_content.replace(f"@{bot.user.name}", "").strip()
    
    # อ่านไฟล์แนบโค้ด/ข้อความ (ถ้ามี)
    attached_files_content = await extract_attachments(message)
    full_prompt = clean_prompt + attached_files_content

    # ถ้าไม่มีข้อความเลย ข้ามไป
    if not full_prompt.strip():
        return

    async with message.channel.typing():
        # รายชื่อโมเดลที่จะลองเรียกตามลำดับ หากตัวแรกติด 503 High Demand
        models_to_try = [MODEL_NAME, "gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
        # กำจัดตัวซ้ำและคงลำดับเดิมไว้
        unique_models = list(dict.fromkeys([m for m in models_to_try if m]))
        
        reply_text = None
        last_error = None

        for model in unique_models:
            try:
                response = ai_client.models.generate_content(
                    model=model,
                    contents=full_prompt,
                    config=get_model_config()
                )
                if response and response.text:
                    reply_text = response.text
                    break
            except Exception as e:
                last_error = e
                print(f"⚠️ โมเดล {model} เกิดข้อผิดพลาด: {e} กำลังลองโมเดลถัดไป...")
                continue

        if reply_text:
            chunks = split_message(reply_text)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply(chunk)
                else:
                    await message.channel.send(chunk)
        else:
            await message.reply(f"ขออภัยครับ ระบบ AI กำลังมีผู้ใช้งานหนาแน่นมาก กรุณาลองใหม่อีกครั้งในอีกสักครู่ (`{last_error}`)")

    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
