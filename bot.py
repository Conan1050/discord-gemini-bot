import os
import discord
from discord.ext import commands
from google import genai
from config import MODEL_NAME, get_model_config

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
    await bot.change_presence(activity=discord.Game(name=f"Coding Specialist ({MODEL_NAME}) | แท็ก @ เพื่อถามโค้ด"))

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
        # จำกัดขนาดไฟล์ไม่เกิน 1 MB เพื่อป้องกันหน่วยความจำล้น
        if attachment.size <= 1_000_000:
            try:
                content_bytes = await attachment.read()
                # ลอง decode เป็น utf-8
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

    # ดึงข้อความและตัดแท็กบอทออก (ถ้ามี)
    clean_prompt = message.clean_content.replace(f"@{bot.user.name}", "").strip()
    
    # อ่านไฟล์แนบโค้ด/ข้อความ (ถ้ามี)
    attached_files_content = await extract_attachments(message)
    full_prompt = clean_prompt + attached_files_content

    # ถ้าไม่มีข้อความเลย ข้ามไป
    if not full_prompt.strip():
        return

    async with message.channel.typing():
        try:
            # เรียกใช้งาน Gemini ทันทีโดยไม่ต้องแท็ก
            response = ai_client.models.generate_content(
                model=MODEL_NAME,
                contents=full_prompt,
                config=get_model_config()
            )
            
            reply_text = response.text if response.text else "ขออภัยครับ ไม่สามารถสร้างคำตอบได้ในขณะนี้"
            
            chunks = split_message(reply_text)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply(chunk)
                else:
                    await message.channel.send(chunk)

        except Exception as e:
            print(f"เกิดข้อผิดพลาด: {e}")
            await message.reply(f"เกิดข้อผิดพลาดในการประมวลผลโค้ด: `{e}`")

    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
