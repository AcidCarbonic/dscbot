import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import datetime
import os

# --- TẠO THƯ MỤC CACHE ---
CACHE_DIR = "music_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# --- BIẾN TOÀN CỤC ---
queues = {}          
current_song = {}    
loop_status = {}     

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': f'{CACHE_DIR}/%(id)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }]
}

ffmpeg_options = {
    'options': '-vn'
}

# --- HÀM HỖ TRỢ ---
def format_duration(seconds):
    if not seconds: return "Unknown"
    return str(datetime.timedelta(seconds=seconds))

async def get_video_info(search_query):
    loop = asyncio.get_event_loop()
    search_opts = {'format': 'bestaudio/best', 'default_search': 'auto', 'noplaylist': True, 'quiet': True}
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
        if 'entries' in info: info = info['entries'][0]
            
    video_id = info['id']
    file_path = f"{CACHE_DIR}/{video_id}.mp3"
    
    if not os.path.exists(file_path):
        with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
            await loop.run_in_executor(None, lambda: ydl.process_info(info))

    return {
        'file_path': file_path,
        'title': info.get('title', 'Unknown Title'),
        'webpage_url': info.get('webpage_url', f'https://youtube.com/watch?v={video_id}'),
        'duration': info.get('duration', 0),
        'uploader': info.get('uploader', 'Unknown')
    }

def play_next(guild_id, voice_client, bot_loop):
    if loop_status.get(guild_id, False) and guild_id in current_song:
        song = current_song[guild_id]
        source = discord.FFmpegPCMAudio(song['file_path'], **ffmpeg_options)
        voice_client.play(source, after=lambda e: play_next(guild_id, voice_client, bot_loop))
        return

    if guild_id in queues and len(queues[guild_id]) > 0:
        next_song = queues[guild_id].pop(0)
        current_song[guild_id] = next_song
        source = discord.FFmpegPCMAudio(next_song['file_path'], **ffmpeg_options)
        voice_client.play(source, after=lambda e: play_next(guild_id, voice_client, bot_loop))
    else:
        if guild_id in queues: del queues[guild_id]
        if guild_id in current_song: del current_song[guild_id]
        if guild_id in loop_status: del loop_status[guild_id]
        
        if voice_client and voice_client.is_connected():
            asyncio.run_coroutine_threadsafe(voice_client.disconnect(), bot_loop)

def get_queue_embed(guild_id):
    if guild_id not in queues or not queues[guild_id]:
        return discord.Embed(description="Hàng đợi hiện tại đang trống!", color=discord.Color.red())
    
    embed = discord.Embed(title="📋 Danh Sách Hàng Đợi", color=discord.Color.blurple())
    q_list = queues[guild_id]
    description = ""
    for i, song in enumerate(q_list[:10]):
        description += f"**{i+1}.** [{song['title']}]({song['webpage_url']}) | `{format_duration(song['duration'])}`\n\n"
    
    if len(q_list) > 10: description += f"*...và {len(q_list) - 10} bài hát khác đang chờ*"
    embed.description = description
    return embed

# --- GIAO DIỆN NÚT BẤM (Tất cả thông báo nút bấm đều Ẩn - ephemeral=True) ---
class MusicControls(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc: return await interaction.response.send_message("Bot không hát!", ephemeral=True)
        if vc.is_playing(): 
            vc.pause()
            await interaction.response.send_message("⏸️ Đã tạm dừng.", ephemeral=True)
        elif vc.is_paused(): 
            vc.resume()
            await interaction.response.send_message("▶️ Đã tiếp tục.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            loop_status[interaction.guild.id] = False 
            vc.stop() 
            await interaction.response.send_message("⏭️ Đã chuyển bài! (Tự động tắt Loop nếu có)", ephemeral=True)
        else: 
            await interaction.response.send_message("Không có bài để bỏ qua.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            guild_id = interaction.guild.id
            if guild_id in queues: queues[guild_id].clear()
            if guild_id in loop_status: loop_status[guild_id] = False
            vc.stop()
            await interaction.response.send_message("⏹️ Đã dừng nhạc, xóa hàng đợi và rời kênh.", ephemeral=True)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.blurple, emoji="📋")
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = get_queue_embed(interaction.guild.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.success, emoji="🔁")
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        current_status = loop_status.get(guild_id, False)
        loop_status[guild_id] = not current_status
        status_text = "BẬT" if loop_status[guild_id] else "TẮT"
        # Bật tắt loop cũng chỉ hiển thị cho người bấm (ephemeral=True)
        await interaction.response.send_message(f"🔁 Chế độ Lặp lại: **{status_text}**", ephemeral=True)

# --- COG NHẠC CHÍNH ---
class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="Phát nhạc từ YouTube")
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        # Trì hoãn ở chế độ ẨN (ephemeral=True) -> Người khác không thấy chữ "Bot đang suy nghĩ..."
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.voice:
            return await interaction.followup.send("❌ Bạn phải vào kênh thoại trước!", ephemeral=True)

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if not voice_client: voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel: await voice_client.move_to(voice_channel)

        guild_id = interaction.guild.id

        try:
            song_info = await get_video_info(query)
            if guild_id not in queues: queues[guild_id] = []
            if guild_id not in loop_status: loop_status[guild_id] = False

            # NẾU ĐANG HÁT -> THÊM VÀO HÀNG ĐỢI (Chỉ người thêm nhìn thấy)
            if voice_client.is_playing() or voice_client.is_paused():
                queues[guild_id].append(song_info)
                return await interaction.followup.send(f"✅ Đã thêm **{song_info['title']}** vào hàng đợi! (Vị trí: {len(queues[guild_id])})", ephemeral=True)

            # NẾU RẢNH -> PHÁT LUÔN
            current_song[guild_id] = song_info
            source = discord.FFmpegPCMAudio(song_info['file_path'], **ffmpeg_options)
            voice_client.play(source, after=lambda e: play_next(guild_id, voice_client, self.bot.loop))

            embed = discord.Embed(title="🎵 Now Playing", description=f"[{song_info['title']}]({song_info['webpage_url']})", color=0xff0000)
            embed.add_field(name="👤 Artist", value=song_info['uploader'], inline=True)
            embed.add_field(name="⏱️ Duration", value=format_duration(song_info['duration']), inline=True)
            embed.add_field(name="🎭 Platform", value="YouTube", inline=True)
            
            q_len = len(queues.get(guild_id, []))
            embed.set_footer(text=f"Controls below • {q_len} songs in queue")

            # Gửi khung Now Playing CÔNG KHAI ra kênh chat
            await interaction.channel.send(embed=embed, view=MusicControls(self.bot))
            
            # Phản hồi ẩn cho người dùng lệnh để kết thúc Interaction (tránh lỗi)
            await interaction.followup.send("▶️ Đã bắt đầu phát nhạc!", ephemeral=True)
            
        except Exception as e:
            print(f"LỖI: {e}")
            await interaction.followup.send("❌ Không thể tải bài này. Có thể do video bị giới hạn.", ephemeral=True)

    @app_commands.command(name="queue", description="Xem danh sách bài hát đang chờ (Chỉ bạn thấy)")
    async def queue(self, interaction: discord.Interaction):
        embed = get_queue_embed(interaction.guild.id)
        # Ẩn danh sách queue
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="loop", description="Bật/Tắt chế độ lặp lại bài hát (Chỉ bạn thấy)")
    async def loop(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            return await interaction.response.send_message("❌ Bot hiện không phát bài nào để lặp lại!", ephemeral=True)

        current_status = loop_status.get(guild_id, False)
        loop_status[guild_id] = not current_status
        status_text = "BẬT" if loop_status[guild_id] else "TẮT"
        # Ẩn thông báo lặp
        await interaction.response.send_message(f"🔁 Chế độ Lặp lại: **{status_text}**", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))