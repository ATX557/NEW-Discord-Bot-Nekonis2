import discord
from discord.ext import commands
import os
from typing import Optional

# --- Configuration & Intents ---

# IMPORTANT: Enable the following intents in your Discord Developer Portal for your bot:
# 1. MESSAGE CONTENT INTENT (Crucial for reading message content for prefix commands or interacting with messages)
# 2. GUILD MEMBERS INTENT (If you plan to use member-specific events or information, like server join events)

intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
intents.members = True          # Enable member intent for events like on_member_join

# Initialize the bot client. We use a simple prefix for easy in-file testing, 
# but the future-proof slash commands (bot.tree) are also implemented below.
# Default prefix is '!'
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Events ---

@bot.event
async def on_ready():
    """Runs when the bot successfully connects to Discord."""
    print(f'--- Logged in as {bot.user} (ID: {bot.user.id}) ---')
    
    # Sync application commands (slash commands) to Discord
    try:
        synced = await bot.tree.sync()
        print(f'Successfully synced {len(synced)} application command(s).')
    except Exception as e:
        print(f'Failed to sync application commands: {e}')
        
    await bot.change_presence(activity=discord.Game(name="Monitoring the Future | !help"))
    print('Bot is ready and monitoring.')
    print('------------------------------------')

@bot.event
async def on_member_join(member: discord.Member):
    """Sends a welcome message to a new member."""
    # Look for a default welcome channel, or the system channel
    channel: Optional[discord.TextChannel] = member.guild.system_channel
    
    if channel is not None:
        welcome_message = (
            f"Welcome to the server, {member.mention}! "
            f"We're excited to have you join us on our journey into the future! "
            f"Check out the #rules channel."
        )
        await channel.send(welcome_message)

# --- Application Commands (Slash Commands - The Future) ---

@bot.tree.command(name="ping", description="Replies with the bot's current latency.")
async def ping_command(interaction: discord.Interaction):
    """Responds to /ping with latency."""
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency is **{latency_ms}ms** ⚡", ephemeral=False)

@bot.tree.command(name="echo", description="Repeat a message back to you.")
async def echo_command(interaction: discord.Interaction, text: str):
    """Responds with the text provided by the user."""
    await interaction.response.send_message(f"You said: {text}")

@bot.tree.command(name="userinfo", description="Get information about a user.")
async def userinfo_command(interaction: discord.Interaction, member: discord.Member = None):
    """Displays info about the interacting user or a mentioned user."""
    target_member = member or interaction.user
    
    embed = discord.Embed(
        title=f"User Information: {target_member.display_name}",
        color=target_member.color
    )
    embed.set_thumbnail(url=target_member.display_avatar.url)
    embed.add_field(name="ID", value=target_member.id, inline=True)
    embed.add_field(name="Account Created", value=target_member.created_at.strftime("%b %d, %Y @ %H:%M"), inline=True)
    embed.add_field(name="Joined Server", value=target_member.joined_at.strftime("%b %d, %Y @ %H:%M") if target_member.joined_at else "N/A", inline=True)
    embed.add_field(name="Roles", value=len(target_member.roles) - 1, inline=True)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=False)


# --- Prefix Commands (Legacy, for fallback) ---

@bot.command(name="hello", help="Says hello!")
async def hello_command(ctx):
    await ctx.send(f"Hello there, {ctx.author.mention}! This is a legacy command.")

# --- Bot Execution ---

# IMPORTANT: Replace "YOUR_BOT_TOKEN_HERE" with your actual bot token.
# Storing it in an environment variable (os.getenv) is the recommended secure practice.
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") 
if not BOT_TOKEN:
    # Fallback for testing if environment variables are not set
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE" 
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("CRITICAL: BOT_TOKEN is not set. Please set the DISCORD_BOT_TOKEN environment variable or replace 'YOUR_BOT_TOKEN_HERE' in app.py.")
    else:
        print("WARNING: Using hardcoded token. For production, use environment variables.")

if BOT_TOKEN and BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
    try:
        bot.run(BOT_TOKEN)
    except discord.errors.LoginFailure:
        print("\nERROR: Invalid Bot Token provided. Check your token and ensure the bot is not locked.")
    except Exception as e:
        print(f"\nAn unexpected error occurred during bot run: {e}")
else:
    print("\nBot execution halted because no valid token was found.")