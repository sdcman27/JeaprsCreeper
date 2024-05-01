import asyncio
import os
import nextcord
from nextcord.ext import commands
from nextcord import Interaction
from dotenv import load_dotenv
import yt_dlp
from yt_dlp import DownloadError


load_dotenv()

# Get the API token from the .env file.
DISCORD_TOKEN = os.getenv("discord_token")
intents = nextcord.Intents().default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!',intents=intents)


# Song queue dictionary
song_queue = {}

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': False,
    'verbose': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # IPv4
    'extract_flat': False
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',  # These options are good for streaming
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(nextcord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url', '')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL({
                'format': 'bestaudio',
                'noplaylist': True,
                'quiet': True
            }).extract_info(url, download=not stream))
        if 'entries' in data:
                data = data['entries'][0]

        filename = data['url'] if stream else yt_dlp.YoutubeDL({}).prepare_filename(data)
        return cls(nextcord.FFmpegPCMAudio(filename, **{'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}), data=data)

async def play_next_song(interaction):
    guild_id = interaction.guild.id
    if song_queue[guild_id]:
        source = await YTDLSource.from_url(song_queue[guild_id].pop(0), loop=bot.loop, stream=True)
        interaction.guild.voice_client.play(source, after=lambda e: bot.loop.create_task(play_next_song(interaction)))
        await interaction.followup.send(f'Now playing: {source.title}')
    else:
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
    

@bot.slash_command(name='join', description='Tells the bot to join the voice channel')
async def join(interaction: Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message(f"{interaction.user.display_name} has joined the voice channel!")
    else:
        await interaction.response.send_message("You are not connected to a voice channel.")


@bot.slash_command(name='leave', description='To make the bot leave the voice channel')
async def leave(interaction: Interaction):
    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("The bot has disconnected from the voice channel.")
    else:
        await interaction.response.send_message("The bot is not connected to a voice channel.")

@bot.slash_command(name='play', description='To play a song')
async def play(interaction: Interaction, search: str):
    try:
        # Immediately defer the interaction
        await interaction.response.defer()

        if interaction.guild.voice_client is None:
            if interaction.user.voice:
                await interaction.user.voice.channel.connect()
            else:
                await interaction.followup.send("You are not connected to a voice channel.", ephemeral=True)
                return

        guild_id = interaction.guild.id
        if guild_id not in song_queue:
            song_queue[guild_id] = []

        if "http://" in search or "https://" in search:
            url = search
        else:
            search_query = f"ytsearch:{search}"
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL({'format': 'bestaudio'}).extract_info(search_query, download=False))
            video = info['entries'][0] if 'entries' in info and info['entries'] else None
            url = video['webpage_url'] if video else None
            if not url:
                await interaction.followup.send("Could not find the song you requested.", ephemeral=True)
                return

        song_queue[guild_id].append(url)
        position = len(song_queue[guild_id])
        await interaction.followup.send(f'"{search}" is queued at position {position}.')

        if not interaction.guild.voice_client.is_playing():
            await play_next_song(interaction)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.slash_command(name='pause', description='This command pauses the song')
async def pause(interaction: Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used within a server.", ephemeral=True)
        return

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await interaction.response.send_message("Playback has been paused.")
    else:
        await interaction.response.send_message("The bot is not playing anything at the moment.", ephemeral=True)
    
@bot.slash_command(name='resume', description='Resumes the song')
async def resume(interaction: Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used within a server.", ephemeral=True)
        return

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await interaction.response.send_message("Playback has been resumed.")
    else:
        await interaction.response.send_message("There is nothing to resume.", ephemeral=True)

@bot.slash_command(name='remove', description='Stops the song')
async def remove(interaction: Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used within a server.", ephemeral=True)
        return

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("The playback has been stopped.")
    else:
        await interaction.response.send_message("The bot is not playing anything at the moment.", ephemeral=True)


@bot.slash_command(name='skip', description='Skips the current song and plays the next one in the queue.')
async def skip(interaction: Interaction):
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        await interaction.response.send_message("The bot is not connected to any voice channel.", ephemeral=True)
        return

    if not voice_client.is_playing():
        await interaction.response.send_message("No song is currently playing.", ephemeral=True)
        return

    voice_client.stop()
    await interaction.response.send_message("Skipping to the next song...")

    if song_queue.get(guild_id) and song_queue[guild_id]:
        await play_next_song(interaction)
    else:
        song_queue[guild_id] = []  # Ensure the queue is clear if empty
        await interaction.followup.send("The queue is now empty.")

bot.run(DISCORD_TOKEN)