import discord
from discord.ext import commands
import asyncio
import os

# Cấu hình cơ bản
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Đang đăng nhập với tên {bot.user}...")
    try:
        # LIÊN KẾT SANG FILE music.py (Bỏ chữ .py khi load)
        await bot.load_extension("music")
        
        # Đồng bộ lệnh Slash (Dấu /)
        synced = await bot.tree.sync()
        print(f"✅ Bot đã sẵn sàng! Đã đồng bộ {len(synced)} lệnh Slash.")
    except Exception as e:
        print(f"❌ Lỗi khi tải file music.py: {e}")

# Chạy bot
bot.run('MTQ4MjU5OTc2NjExNzMxODY2Ng.GqPTnG.-mqI')
