import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import datetime
import os
import time
import random

# --- TẠO THƯ MỤC CACHE ---
CACHE_DIR = "music_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# --- BIẾN TOÀN CỤC ---
queues = {}          
current_song = {}    
loop_status = {}     
start_times = {}
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
    # Chỉnh noplaylist=False để lấy được cả danh sách phát
    opts = {'format': 'bestaudio/best', 'default_search': 'auto', 'noplaylist': False, 'quiet': True}
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
        
        # Trường hợp là Playlist
        if 'entries' in info:
            songs = []
            for entry in info['entries']:
                if entry and entry.get('duration', 0) <= 420: # Chỉ lấy bài dưới 7p
                    songs.append({
                        'id': entry['id'],
                        'title': entry['title'],
                        'webpage_url': entry.get('webpage_url'),
                        'duration': entry.get('duration', 0),
                        'uploader': entry.get('uploader', 'Unknown')
                    })
            return songs if songs else "NO_VALID_SONGS"

        # Trường hợp bài đơn lẻ
        if info.get('duration', 0) > 420:
            return "TOO_LONG"
            
        video_id = info['id']
        file_path = f"{CACHE_DIR}/{video_id}.mp3"
        
        if not os.path.exists(file_path):
            with yt_dlp.YoutubeDL(ytdl_format_options) as ydl_down:
                await loop.run_in_executor(None, lambda: ydl_down.process_info(info))

        return {
            'file_path': file_path,
            'title': info.get('title', 'Unknown Title'),
            'webpage_url': info.get('webpage_url'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown')
        }
def create_progress_bar(guild_id, total_duration):
    if guild_id not in start_times or total_duration == 0:
        return "▬" * 15
    
    elapsed = time.time() - start_times[guild_id]
    progress = min(elapsed / total_duration, 1.0)
    size = 15
    dot_pos = int(progress * size)
    
    bar = ""
    for i in range(size):
        if i == dot_pos: bar += "🔘"
        else: bar += "▬"
    return f"{bar} ({format_duration(elapsed)}/{format_duration(total_duration)})"
def play_next(guild_id, voice_client, bot_loop):
    # 1. Dọn dẹp cache bài cũ
    if not loop_status.get(guild_id, False) and guild_id in current_song:
        path = current_song[guild_id].get('file_path')
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

    # 2. Lấy bài tiếp theo
    if loop_status.get(guild_id, False) and guild_id in current_song:
        song = current_song[guild_id]
    elif guild_id in queues and len(queues[guild_id]) > 0:
        song = queues[guild_id].pop(0)
    else:
        # Hết nhạc: Dọn dẹp
        for d in [queues, current_song, loop_status, start_times]:
            if guild_id in d: d.pop(guild_id, None)
        if voice_client and voice_client.is_connected():
            asyncio.run_coroutine_threadsafe(voice_client.disconnect(), bot_loop)
        return

    # 3. KIỂM TRA NẾU BÀI HÁT CHƯA TẢI (Dành cho Playlist)
    if 'file_path' not in song:
        # Gọi lại get_video_info để tải file
        async def download_and_play():
            info = await get_video_info(song['webpage_url'])
            if isinstance(info, dict):
                current_song[guild_id] = info
                start_times[guild_id] = time.time()
                source = discord.FFmpegPCMAudio(info['file_path'], **ffmpeg_options)
                voice_client.play(source, after=lambda e: play_next(guild_id, voice_client, bot_loop))
        
        asyncio.run_coroutine_threadsafe(download_and_play(), bot_loop)
        return

    # 4. Phát nhạc bình thường
    current_song[guild_id] = song
    start_times[guild_id] = time.time()
    source = discord.FFmpegPCMAudio(song['file_path'], **ffmpeg_options)
    voice_client.play(source, after=lambda e: play_next(guild_id, voice_client, bot_loop))

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
        self.voters = set()

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc: return
        if vc.is_playing(): 
            vc.pause()
            await interaction.response.send_message("⏸️ Đã tạm dừng.", ephemeral=True)
        elif vc.is_paused(): 
            vc.resume()
            await interaction.response.send_message("▶️ Đã tiếp tục.", ephemeral=True)

    @discord.ui.button(label="Vote Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc: return
        
        # Admin hoặc người có quyền quản lý kênh có thể skip luôn
        if interaction.user.guild_permissions.manage_channels:
            vc.stop()
            return await interaction.response.send_message("⏭️ Admin đã bỏ qua bài hát.", ephemeral=True)

        self.voters.add(interaction.user.id)
        needed = max(1, (len(vc.channel.members) - 1) // 2) # 50% người trong voice
        
        if len(self.voters) >= needed:
            loop_status[interaction.guild.id] = False 
            vc.stop()
            await interaction.response.send_message("⏭️ Đã đủ vote! Chuyển bài.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🗳️ Vote skip: {len(self.voters)}/{needed}", ephemeral=True)

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

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Nếu bot ở trong một kênh
        if before.channel:
            # Nếu chỉ còn mình bot trong kênh đó
            if len(before.channel.members) == 1 and self.bot.user in before.channel.members:
                vc = before.channel.guild.voice_client
                if vc:
                    await vc.disconnect()
                    # Reset data server đó
                    gid = before.channel.guild.id
                    if gid in queues: del queues[gid]

    @app_commands.command(name="play", description="Phát nhạc (Dưới 7p/Playlist)")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        
        # Kiểm tra Voice
        if not interaction.user.voice:
            return await interaction.followup.send("❌ Bạn chưa vào voice!", ephemeral=True)

        res = await get_video_info(query)

        # Xử lý lỗi cụ thể
        if res == "TOO_LONG":
            return await interaction.followup.send("❌ Bài hát dài quá 7 phút. Vui lòng chọn bài khác.", ephemeral=True)
        if res == "NO_VALID_SONGS":
            return await interaction.followup.send("❌ Playlist không có bài nào dưới 7 phút.", ephemeral=True)
        
        guild_id = interaction.guild.id
        if guild_id not in queues: queues[guild_id] = []

        # Xử lý nếu res là một danh sách (Playlist)
        if isinstance(res, list):
            for song in res:
                queues[guild_id].append(song)
            await interaction.followup.send(f"✅ Đã thêm playlist với {len(res)} bài vào hàng đợi.", ephemeral=True)
        else:
            queues[guild_id].append(res)
            await interaction.followup.send(f"✅ Đã thêm **{res['title']}**", ephemeral=True)

        # Logic khởi chạy voice client (giữ nguyên của bạn)
        vc = interaction.guild.voice_client
        if not vc: vc = await interaction.user.voice.channel.connect()

        if not vc.is_playing() and not vc.is_paused():
            # Nếu bài đầu tiên chưa có file_path (do lấy từ playlist chưa download)
            # Bạn nên thêm logic download vào đây hoặc trong play_next
            play_next(guild_id, vc, self.bot.loop)
            
            # Gửi khung Now Playing
            song = current_song.get(guild_id)
            if song:
                embed = discord.Embed(title="🎵 Now Playing", description=f"[{song['title']}]({song['webpage_url']})", color=0xff0000)
                embed.add_field(name="Tiến độ", value=create_progress_bar(guild_id, song['duration']))
                await interaction.channel.send(embed=embed, view=MusicControls(self.bot))

    @app_commands.command(name="shuffle", description="Trộn ngẫu nhiên hàng đợi")
    async def shuffle(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        if gid in queues and len(queues[gid]) > 1:
            random.shuffle(queues[gid])
            await interaction.response.send_message("🔀 Đã trộn hàng đợi!", ephemeral=True)
        else:
            await interaction.response.send_message("Không đủ bài để trộn.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))