import os
import discord
from discord.ext import commands
from google import genai

# อ่านค่าจาก Environment Variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("กรุณากำหนด DISCORD_TOKEN และ GEMINI_API_KEY ใน Environment Variables")

# สร้าง Gemini Client โดยใช้ SDK ทางการตัวล่าสุด (google-genai)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# กำหนด Intents
intents = discord.Intents.default()
intents.message_content = True  # สิทธิ์อ่านเนื้อหาข้อความ

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 บอทพร้อมทำงานแล้ว! ล็อกอินในชื่อ: {bot.user.name} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="แท็ก @ฉัน เพื่อคุยกันได้เลย!"))

def split_message(text, limit=1950):
    """ฟังก์ชันแบ่งข้อความหากคำตอบยาวเกินขีดจำกัดของ Discord (2,000 ตัวอักษร)"""
    chunks = []
    while len(text) > limit:
        # ตัดตรงบรรทัดใหม่ที่ใกล้ที่สุดเพื่อความสวยงาม
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks

@bot.event
async def on_message(message: discord.Message):
    # ไม่ตอบข้อความตัวเอง หรือข้อความจากบอทตัวอื่น
    if message.author.bot:
        return

    # เช็คว่ามีคนแท็กบอท หรือตอบกลับ (reply) ข้อความของบอทหรือไม่
    is_mentioned = bot.user in message.mentions
    is_reply_to_bot = (
        message.reference 
        and message.reference.resolved 
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == bot.user
    )

    if is_mentioned or is_reply_to_bot:
        # ดึงข้อความของผู้ใช้ โดยตัดแท็ก @บอท ออก
        clean_prompt = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        
        if not clean_prompt:
            await message.reply("สวัสดีครับ! มีอะไรให้ผมช่วยไหมครับ?")
            return

        # แสดงสถานะ typing... ระหว่างรอ Gemini ประมวลผล
        async with message.channel.typing():
            try:
                # เรียกใช้งาน Gemini 2.5 Flash ซึ่งเร็วและฉลาดมาก
                response = ai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=clean_prompt,
                )
                
                reply_text = response.text if response.text else "ขออภัยครับ ไม่สามารถสร้างคำตอบได้ในขณะนี้"
                
                # แบ่งส่งข้อความหากคำตอบยาวเกิน 2000 ตัวอักษร
                chunks = split_message(reply_text)
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await message.reply(chunk)
                    else:
                        await message.channel.send(chunk)

            except Exception as e:
                print(f"เกิดข้อผิดพลาด: {e}")
                await message.reply(f"เกิดข้อผิดพลาดในการประมวลผล: `{e}`")

    # อนุญาตให้คำสั่ง prefix อื่นๆ ทำงานได้ด้วย
    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

