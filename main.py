import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ButtonStyle, ui
import asyncio
import yt_dlp
from youtube_search import YoutubeSearch
import re
import os

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="?", intents=intents)
tree = bot.tree

# === YTDL and FFMPEG Options ===
ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extract_flat': 'in_playlist',
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}
ffmpeg_options = {
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Music classes

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.3):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class Song:
    def __init__(self, source, requester):
        self.source = source
        self.requester = requester
        self.title = source.title
        self.url = source.url

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current = None
        self.voice_client = None
        self.volume = 0.3
        self.play_task = None

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while True:
            self.next.clear()

            try:
                async with asyncio.TimeoutError(300):
                    song = await self.queue.get()
            except asyncio.TimeoutError:
                if self.voice_client and self.voice_client.is_connected():
                    await self.voice_client.disconnect()
                return

            self.current = song
            self.voice_client.play(song.source, after=self.play_next_song)
            embed = Embed(title="🎶 Now Playing", description=f"[{song.title}]({song.url})", color=discord.Color.blurple())
            embed.set_footer(text=f"Requested by {song.requester}")
            await self.channel.send(embed=embed)

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            print(f"Player error: {error}")
        self.bot.loop.call_soon_threadsafe(self.next.set)

    async def add_song(self, ctx, source):
        song = Song(source, ctx.author)
        await self.queue.put(song)
        if not self.play_task or self.play_task.done():
            self.play_task = self.bot.loop.create_task(self.player_loop())

    async def join_voice(self, ctx):
        voice_state = ctx.author.voice
        if voice_state is None:
            await ctx.send("You must be in a voice channel to summon me.")
            return False
        if ctx.voice_client is None:
            self.voice_client = await voice_state.channel.connect()
        else:
            self.voice_client = ctx.voice_client
            if self.voice_client.channel != voice_state.channel:
                await self.voice_client.move_to(voice_state.channel)
        return True

    async def stop(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        self.current = None
        while not self.queue.empty():
            self.queue.get_nowait()
        self.next.set()

players = {}

def get_player(ctx):
    player = players.get(ctx.guild.id)
    if not player:
        player = MusicPlayer(ctx)
        players[ctx.guild.id] = player
    return player

def search_youtube(query):
    results = YoutubeSearch(query, max_results=1).to_dict()
    if results:
        url_suffix = results[0]["url_suffix"]
        return f"https://www.youtube.com{url_suffix}"
    return None

# === Commands ===

@tree.command(name="play", description="Play a song from YouTube URL or search term")
async def play(interaction: Interaction, query: str):
    await interaction.response.defer()
    player = get_player(interaction)
    voice_state = interaction.user.voice
    if not voice_state:
        await interaction.followup.send("You must be in a voice channel to use this command.", ephemeral=True)
        return
    if not await player.join_voice(interaction):
        await interaction.followup.send("Failed to join voice channel.", ephemeral=True)
        return

    url = query
    if not (query.startswith("http://") or query.startswith("https://")):
        url = search_youtube(query)
        if not url:
            await interaction.followup.send("No results found.", ephemeral=True)
            return

    try:
        source = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
    except Exception as e:
        await interaction.followup.send(f"Error processing this song: {e}", ephemeral=True)
        return

    await player.add_song(interaction, source)
    await interaction.followup.send(f"Queued: {source.title}")

@tree.command(name="skip", description="Skip the current song")
async def skip(interaction: Interaction):
    player = get_player(interaction)
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return
    vc.stop()
    await interaction.response.send_message("Skipped the song.", ephemeral=True)

@tree.command(name="stop", description="Stop playback and clear queue")
async def stop(interaction: Interaction):
    player = get_player(interaction)
    await player.stop()
    await interaction.response.send_message("Stopped playback and cleared the queue.", ephemeral=True)

@tree.command(name="pause", description="Pause the current song")
async def pause(interaction: Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return
    vc.pause()
    await interaction.response.send_message("Paused.", ephemeral=True)

@tree.command(name="resume", description="Resume the paused song")
async def resume(interaction: Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_paused():
        await interaction.response.send_message("Nothing is paused.", ephemeral=True)
        return
    vc.resume()
    await interaction.response.send_message("Resumed.", ephemeral=True)

@tree.command(name="np", description="Show now playing")
async def np(interaction: Interaction):
    player = get_player(interaction)
    if not player.current:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return
    song = player.current
    embed = Embed(title="🎵 Now Playing", description=f"[{song.title}]({song.url})", color=discord.Color.blurple())
    embed.set_footer(text=f"Requested by {song.requester}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="queue", description="Show the queue")
async def queue_cmd(interaction: Interaction):
    player = get_player(interaction)
    if player.queue.empty():
        await interaction.response.send_message("Queue is empty.", ephemeral=True)
        return
    upcoming = list(player.queue._queue)
    embed = Embed(title=f"Upcoming songs ({len(upcoming)})", color=discord.Color.blue())
    for i, song in enumerate(upcoming[:10], 1):
        embed.add_field(name=f"{i}. {song.title}", value=f"Requested by {song.requester}", inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="join", description="Join your voice channel")
async def join(interaction: Interaction):
    voice_state = interaction.user.voice
    if not voice_state:
        await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
        return
    vc = interaction.guild.voice_client
    if vc and vc.channel == voice_state.channel:
        await interaction.response.send_message("Already in your voice channel.", ephemeral=True)
        return
    if vc:
        await vc.move_to(voice_state.channel)
    else:
        await voice_state.channel.connect()
    await interaction.response.send_message(f"Joined {voice_state.channel.name}.", ephemeral=True)

@tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return
    await vc.disconnect()
    await interaction.response.send_message("Left the voice channel.", ephemeral=True)

@tree.command(name="volume", description="Set volume (1-100)")
async def volume(interaction: Interaction, volume: int):
    if volume < 1 or volume > 100:
        await interaction.response.send_message("Volume must be between 1 and 100.", ephemeral=True)
        return
    player = get_player(interaction)
    player.volume = volume / 100
    if player.voice_client and player.voice_client.source:
        player.voice_client.source.volume = player.volume
    await interaction.response.send_message(f"Volume set to {volume}%.", ephemeral=True)

# Run bot
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
