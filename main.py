# main.py
# Single-file Discord Bot — In-Discord Dashboard + Features (one-file)
# Requirements: discord.py v2.x, aiohttp
# Optional for music: yt_dlp, ffmpeg
# pip install -U "discord.py" aiohttp
# pip install -U yt_dlp  (optional for music)

import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle, TextStyle
import aiohttp
import json, os, time, asyncio, random, traceback
from typing import Optional, Dict, List, Any
from datetime import datetime

# ===========================
# ZONE 1: CONFIG / UTILITIES
# ===========================
TOKEN = os.getenv("DISCORD_TOKEN") or "YOUR_TOKEN_HERE"  # <<-- replace or set env var
DEFAULT_PREFIX = "&"
DATA_FILE = "guild_settings.json"
LOGS_DIR = "logs"
ANIME_API_BASE = "https://nekos.life/api/v2/img/"  # for fun gifs

os.makedirs(LOGS_DIR, exist_ok=True)

INTENTS = discord.Intents.all()
THEME_COLOR = 0x8A2BE2

def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

settings: Dict[str, Dict[str, Any]] = load_json(DATA_FILE, {})

def ensure_guild(gid: int) -> Dict[str, Any]:
    key = str(gid)
    if key not in settings:
        settings[key] = {
            "prefix": DEFAULT_PREFIX,
            "auto_welcome": False,
            "welcome_channel": None,
            "welcome_embed": "Welcome {user} to {server}! You are member #{count}.",
            "auto_leave": False,
            "leave_channel": None,
            "automod_enabled": False,
            "automod_badwords": [],
            "automod_action": "warn",  # warn/kick/ban
            "mod_log_channel": None,
            "logging_enabled": True,
            "afk": {},  # user_id -> {"reason": str, "since": float}
            "role_panels": {},  # id -> {title, roles:list}
            "ticket_category": None,
            "ticket_log_channel": None,
            "suggestion_channel": None,
            "starboard_channel": None,
            "starboard_threshold": 5,
            "giveaways": {}
        }
        save_json(DATA_FILE, settings)
    return settings[key]

def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

def log_file_write(guild_id: int, line: str):
    path = os.path.join(LOGS_DIR, f"{guild_id}.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print("log write error:", e)

async def safe_send(channel: discord.TextChannel, *, content: Optional[str] = None, embed: Optional[discord.Embed] = None):
    try:
        await channel.send(content=content, embed=embed)
    except Exception:
        pass

def record_action(guild: discord.Guild, action: str, moderator: discord.User, target: Optional[discord.User], reason: str = ""):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    tstr = f"{target} ({getattr(target,'id','N/A')})" if target else "N/A"
    mstr = f"{moderator} ({moderator.id})"
    line = f"[{ts}] [{action}] by {mstr} target: {tstr} reason: {reason}"
    log_file_write(guild.id, line)
    # mod-log channel
    g = ensure_guild(guild.id)
    ch_id = g.get("mod_log_channel")
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            emb = discord.Embed(title=f"Mod Log: {action}", color=discord.Color.dark_red())
            emb.add_field(name="Moderator", value=mstr)
            emb.add_field(name="Target", value=tstr)
            if reason:
                emb.add_field(name="Reason", value=reason, inline=False)
            emb.set_footer(text=ts)
            asyncio.create_task(safe_send(ch, embed=emb))

# -----------------------------
# ZONE 2: BOT SETUP & PRESENCE
# -----------------------------
def get_prefix(bot, message):
    if not message.guild:
        return DEFAULT_PREFIX
    cfg = ensure_guild(message.guild.id)
    return cfg.get("prefix", DEFAULT_PREFIX)

bot = commands.Bot(command_prefix=get_prefix, intents=INTENTS, help_command=None)
start_time = time.time()

@tasks.loop(minutes=5)
async def presence_task():
    try:
        await bot.change_presence(activity=discord.Game(name=f"{DEFAULT_PREFIX}helpme | {len(bot.guilds)} servers"))
    except:
        pass

@bot.event
async def on_ready():
    print(f"Bot online as {bot.user} (ID: {bot.user.id})")
    # ensure persistent views re-added (fixes buttons not working after restart)
    bot.add_view(MainSetupPersistent())
    bot.add_view(SetupOpenButtonPersistent())
    presence_task.start()

@bot.event
async def on_guild_join(guild):
    ensure_guild(guild.id)
    try:
        await bot.change_presence(activity=discord.Game(name=f"{DEFAULT_PREFIX}helpme | {len(bot.guilds)} servers"))
    except:
        pass

# -----------------------------
# ZONE 3: Utility / Fetch anime gif
# -----------------------------
async def fetch_anime_gif(action: str) -> Optional[str]:
    url = ANIME_API_BASE + action
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("url")
    except Exception:
        return None

# -----------------------------
# ZONE 4: PERSISTENT VIEWS (fix button problem)
# -----------------------------
# We add two persistent views:
# 1) MainSetupPersistent - used if we post a persistent dashboard message (not ephemeral)
# 2) SetupOpenButtonPersistent - a small "Open Setup" button creators can place

class MainSetupPersistent(ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent
    @ui.button(label="Open Dashboard", style=ButtonStyle.primary, custom_id="dash:open")
    async def open_dashboard(self, interaction: discord.Interaction, button: ui.Button):
        # permission check
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You must be an administrator to open the dashboard.", ephemeral=True)
        view = MainSetupView(interaction.user.id, interaction.guild)
        emb = discord.Embed(title="Server Dashboard", description="Use the buttons to configure server features. (Admin only)", color=THEME_COLOR)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

class SetupOpenButtonPersistent(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @ui.button(label="Setup (Admin)", style=ButtonStyle.primary, custom_id="dash:open_small")
    async def open_small(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        view = MainSetupView(interaction.user.id, interaction.guild)
        emb = discord.Embed(title="Server Dashboard (Quick)", description="Configure server features", color=THEME_COLOR)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

# -----------------------------
# ZONE 5: Main Dashboard Views (ephemeral) — Buttons + Modals
# -----------------------------
class MainSetupView(ui.View):
    def __init__(self, author_id: int, guild: discord.Guild):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # allow author or admins
        if interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("You are not allowed to use this setup UI.", ephemeral=True)
        return False

    @ui.button(label="Prefix", style=ButtonStyle.primary)
    async def prefix_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PrefixModal("Set Prefix", self.guild, self.author_id))

    @ui.button(label="Welcome", style=ButtonStyle.success)
    async def welcome_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(WelcomeView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="AutoMod", style=ButtonStyle.danger)
    async def automod_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(AutoModView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="Logs", style=ButtonStyle.secondary)
    async def logs_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(LogsView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="Tickets", style=ButtonStyle.primary)
    async def tickets_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(TicketSetupView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="Giveaways", style=ButtonStyle.success)
    async def giveaways_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(GiveawaySetupView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="Role Panels", style=ButtonStyle.secondary)
    async def rolepanels_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_view(RolesSetupView(self.author_id, self.guild), ephemeral=True)

    @ui.button(label="Close", style=ButtonStyle.gray)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Closed dashboard.", ephemeral=True)
        self.stop()

class PrefixModal(ui.Modal, title="Set Prefix"):
    new_prefix = ui.TextInput(label="Prefix", style=TextStyle.short, placeholder="e.g. & or -", required=True, max_length=5)
    def __init__(self, title: str, guild: discord.Guild, author_id: int):
        super().__init__(title=title)
        self.guild = guild
        self.author_id = author_id
    async def on_submit(self, interaction: discord.Interaction):
        if not (interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Not allowed", ephemeral=True)
        g = ensure_guild(self.guild.id)
        g["prefix"] = self.new_prefix.value
        save_json(DATA_FILE, settings)
        await interaction.response.send_message(f"✅ Prefix set to `{self.new_prefix.value}`", ephemeral=True)

class WelcomeView(ui.View):
    def __init__(self, author_id: int, guild: discord.Guild):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild
    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id == self.author_id or i.user.guild_permissions.administrator:
            return True
        await i.response.send_message("Not allowed.", ephemeral=True)
        return False
    @ui.button(label="Toggle Welcome", style=ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        g = ensure_guild(self.guild.id)
        g["auto_welcome"] = not g.get("auto_welcome", False)
        save_json(DATA_FILE, settings)
        await interaction.response.send_message(f"✅ Auto-welcome {'enabled' if g['auto_welcome'] else 'disabled'}.", ephemeral=True)
    @ui.button(label="Set Welcome Channel", style=ButtonStyle.secondary)
    async def set_ch(self, interaction: discord.Interaction, button: ui.Button):
        opts = [discord.SelectOption(label=c.name, value=str(c.id)) for c in self.guild.text_channels]
        if not opts:
            return await interaction.response.send_message("No text channels.", ephemeral=True)
        await interaction.response.send_message("Choose channel:", view=ChannelSelect(opts, self.guild, self.author_id, key="welcome_channel"), ephemeral=True)
    @ui.button(label="Edit Welcome Message", style=ButtonStyle.success)
    async def edit_msg(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeModal("Welcome Message", self.guild, self.author_id))

class WelcomeModal(ui.Modal, title="Welcome Message"):
    msg = ui.TextInput(label="Message", style=TextStyle.paragraph, placeholder="Use {user}, {server}, {count}", required=True, max_length=1000)
    def __init__(self, title: str, guild: discord.Guild, author_id: int):
        super().__init__(title=title)
        self.guild = guild
        self.author_id = author_id
    async def on_submit(self, interaction: discord.Interaction):
        if not (interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Not allowed", ephemeral=True)
        g = ensure_guild(self.guild.id)
        g["welcome_embed"] = self.msg.value
        save_json(DATA_FILE, settings)
        await interaction.response.send_message("✅ Welcome message saved.", ephemeral=True)

class AutoModView(ui.View):
    def __init__(self, author_id: int, guild: discord.Guild):
        super().__init__(timeout=300); self.author_id=author_id; self.guild=guild
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("Not allowed.", ephemeral=True); return False
    @ui.button(label="Toggle AutoMod", style=ButtonStyle.danger)
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        g = ensure_guild(self.guild.id)
        g["automod_enabled"] = not g.get("automod_enabled", False)
        save_json(DATA_FILE, settings)
        await interaction.response.send_message(f"✅ AutoMod {'enabled' if g['automod_enabled'] else 'disabled'}.", ephemeral=True)
    @ui.button(label="Add Bad Word", style=ButtonStyle.secondary)
    async def add_bad(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(BadWordModal("Add Bad Word", self.guild, "add", self.author_id))
    @ui.button(label="Remove Bad Word", style=ButtonStyle.secondary)
    async def remove_bad(self, interaction: discord.Interaction, button: ui.Button):
        g = ensure_guild(self.guild.id); bads = g.get("automod_badwords", [])
        if not bads: return await interaction.response.send_message("No bad words listed.", ephemeral=True)
        opts = [discord.SelectOption(label=b, value=b) for b in bads]
        await interaction.response.send_message("Choose word to remove:", view=BadWordSelect(opts, self.guild, self.author_id), ephemeral=True)

class BadWordModal(ui.Modal, title="Add Bad Word"):
    word = ui.TextInput(label="Bad word", style=TextStyle.short, required=True, max_length=100)
    def __init__(self, title: str, guild: discord.Guild, action: str, author_id: int):
        super().__init__(title=title); self.guild=guild; self.action=action; self.author_id=author_id
    async def on_submit(self, interaction: discord.Interaction):
        if not (interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Not allowed", ephemeral=True)
        w = self.word.value.lower().strip()
        g = ensure_guild(self.guild.id)
        arr = g.setdefault("automod_badwords", [])
        if self.action == "add":
            if w in arr: return await interaction.response.send_message("Already exists.", ephemeral=True)
            arr.append(w); g["automod_badwords"]=arr; save_json(DATA_FILE, settings)
            await interaction.response.send_message(f"✅ Added `{w}`", ephemeral=True)

class BadWordSelect(ui.View):
    def __init__(self, options, guild: discord.Guild, author_id: int):
        super().__init__(timeout=120); self.add_item(BadWordDropdown(options=options, guild=guild, author_id=author_id))

class BadWordDropdown(ui.Select):
    def __init__(self, options, guild: discord.Guild, author_id: int):
        super().__init__(placeholder="Choose bad word...", min_values=1, max_values=1, options=options)
        self.guild=guild; self.author_id=author_id
    async def callback(self, interaction: discord.Interaction):
        if not (interaction.user.id == self.author_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        w = self.values[0]
        g = ensure_guild(self.guild.id)
        arr = g.get("automod_badwords", [])
        if w in arr: arr.remove(w); g["automod_badwords"]=arr; save_json(DATA_FILE, settings); await interaction.response.send_message(f"✅ Removed `{w}`", ephemeral=True)
        else: await interaction.response.send_message("Not found.", ephemeral=True)
        self.view.stop()

class LogsView(ui.View):
    def __init__(self, author_id:int, guild:discord.Guild):
        super().__init__(timeout=300); self.author_id=author_id; self.guild=guild
    async def interaction_check(self, i:discord.Interaction)->bool:
        if i.user.id==self.author_id or i.user.guild_permissions.administrator: return True
        await i.response.send_message("Not allowed.", ephemeral=True); return False
    @ui.button(label="Set Mod Log Channel", style=ButtonStyle.secondary)
    async def set_mod_log(self, interaction: discord.Interaction, button: ui.Button):
        opts=[discord.SelectOption(label=c.name, value=str(c.id)) for c in self.guild.text_channels]
        if not opts: return await interaction.response.send_message("No channels", ephemeral=True)
        await interaction.response.send_message("Select channel:", view=ChannelSelect(opts, self.guild, self.author_id, key="mod_log_channel"), ephemeral=True)
    @ui.button(label="Toggle File Logging", style=ButtonStyle.primary)
    async def toggle_file(self, interaction: discord.Interaction, button: ui.Button):
        g = ensure_guild(self.guild.id); g["logging_enabled"]=not g.get("logging_enabled", True); save_json(DATA_FILE, settings)
        await interaction.response.send_message(f"✅ File logging {'enabled' if g['logging_enabled'] else 'disabled'}.", ephemeral=True)

class ChannelSelect(ui.View):
    def __init__(self, options, guild:discord.Guild, author_id:int, key:str):
        super().__init__(timeout=120); self.add_item(ChannelDropdown(options=options, guild=guild, author_id=author_id, key=key))

class ChannelDropdown(ui.Select):
    def __init__(self, options, guild:discord.Guild, author_id:int, key:str):
        super().__init__(placeholder="Choose channel...", min_values=1, max_values=1, options=options)
        self.guild=guild; self.author_id=author_id; self.key=key
    async def callback(self, interaction: discord.Interaction):
        if not (interaction.user.id==self.author_id or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        val=int(self.values[0]); g=ensure_guild(self.guild.id); g[self.key]=val; save_json(DATA_FILE, settings)
        await interaction.response.send_message(f"✅ Set `{self.key}` to <#{val}>", ephemeral=True); self.view.stop()

# -----------------------------
# ZONE 6: AFK (guild-based)
# -----------------------------
@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    g = ensure_guild(ctx.guild.id)
    g_afk = g.setdefault("afk", {})
    g_afk[str(ctx.author.id)] = {"reason": reason, "since": time.time()}
    save_json(DATA_FILE, settings)
    emb = discord.Embed(title="💤 AFK Enabled", description=f"{ctx.author.mention} is now AFK\nReason: {reason}", color=discord.Color.orange())
    emb.set_footer(text="AFK will be removed when you send a message.")
    await ctx.send(embed=emb)

@bot.command(name="afk_status")
async def afk_status(ctx, member: Optional[discord.Member]=None):
    member = member or ctx.author
    g = ensure_guild(ctx.guild.id)
    info = g.get("afk", {}).get(str(member.id))
    if not info:
        return await ctx.send(embed=discord.Embed(description=f"{member.mention} is not AFK.", color=discord.Color.green()))
    since = info.get("since", time.time())
    elapsed = fmt_duration(time.time() - since)
    emb = discord.Embed(title="AFK Status", color=discord.Color.orange())
    emb.add_field(name="User", value=member.mention)
    emb.add_field(name="Reason", value=info.get("reason"))
    emb.add_field(name="Since", value=elapsed)
    await ctx.send(embed=emb)

# -----------------------------
# ZONE 7: EVENTS — AFK notify + Automod check + Starboard etc.
# -----------------------------
@bot.event
async def on_message(message):
    # keep a single on_message that handles all logic and then processes commands
    if message.author.bot:
        return

    # AFK removal on message by owner
    if message.guild:
        g = ensure_guild(message.guild.id)
        if str(message.author.id) in g.get("afk", {}):
            g["afk"].pop(str(message.author.id), None)
            save_json(DATA_FILE, settings)
            try:
                await message.channel.send(embed=discord.Embed(title="Welcome back!", description=f"{message.author.mention}, your AFK status was removed.", color=discord.Color.green()))
            except:
                pass

        # notify mentions
        if message.mentions:
            for u in message.mentions:
                info = g.get("afk", {}).get(str(u.id))
                if info:
                    elapsed = fmt_duration(time.time() - info.get("since", time.time()))
                    emb = discord.Embed(title=f"🛌 {u.display_name} is AFK", description=f"**Reason:** {info.get('reason')}\n**Since:** {elapsed} ago", color=discord.Color.red())
                    try:
                        await message.channel.send(embed=emb)
                    except:
                        pass

        # AutoMod enforcement
        if g.get("automod_enabled", False):
            content = message.content.lower()
            for bad in g.get("automod_badwords", []):
                if bad in content:
                    reason = f"AutoMod triggered word: {bad}"
                    # try delete message
                    try: await message.delete()
                    except: pass
                    action = g.get("automod_action", "warn")
                    if action == "warn":
                        try: await message.channel.send(f"⚠️ {message.author.mention}, your message contained a prohibited word.")
                        except: pass
                    elif action == "kick":
                        try:
                            await message.author.kick(reason=reason)
                            await message.channel.send(f"👢 {message.author.mention} was kicked by AutoMod.")
                            record_action(message.guild, "AUTOMOD_KICK", bot.user, message.author, reason=reason)
                        except:
                            await message.channel.send("❌ Could not kick user (missing perms).")
                    elif action == "ban":
                        try:
                            await message.author.ban(reason=reason)
                            await message.channel.send(f"🔨 {message.author.mention} was banned by AutoMod.")
                            record_action(message.guild, "AUTOMOD_BAN", bot.user, message.author, reason=reason)
                        except:
                            await message.channel.send("❌ Could not ban user (missing perms).")
                    break

    await bot.process_commands(message)

# -----------------------------
# ZONE 8: Moderation Commands
# -----------------------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.send(embed=discord.Embed(title="You were kicked", description=f"Server: {ctx.guild.name}\nReason: {reason}", color=discord.Color.red()))
    except: pass
    try:
        await member.kick(reason=reason)
        await ctx.send(embed=discord.Embed(description=f"✅ {member.mention} kicked.", color=discord.Color.red()))
        record_action(ctx.guild, "KICK", ctx.author, member, reason=reason)
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.send(embed=discord.Embed(title="You were banned", description=f"Server: {ctx.guild.name}\nReason: {reason}", color=discord.Color.dark_red()))
    except: pass
    try:
        await member.ban(reason=reason)
        await ctx.send(embed=discord.Embed(description=f"🔨 {member.mention} banned.", color=discord.Color.dark_red()))
        record_action(ctx.guild, "BAN", ctx.author, member, reason=reason)
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, username: str):
    try:
        name, discrim = username.split("#")
    except ValueError:
        return await ctx.send("Usage: &unban username#1234")
    banned = await ctx.guild.bans()
    for entry in banned:
        user = entry.user
        if user.name == name and user.discriminator == discrim:
            try:
                await ctx.guild.unban(user)
                await ctx.send(embed=discord.Embed(description=f"✅ Unbanned {user}", color=discord.Color.green()))
                record_action(ctx.guild, "UNBAN", ctx.author, user, reason="Manual unban")
                return
            except Exception as e:
                return await ctx.send(f"❌ Failed: {e}")
    await ctx.send("❌ User not found in ban list.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, note: str = "No reason provided"):
    try:
        await member.send(embed=discord.Embed(title="You were warned", description=f"Server: {ctx.guild.name}\nReason: {note}", color=discord.Color.gold()))
    except: pass
    await ctx.send(embed=discord.Embed(description=f"⚠️ {member.mention} has been warned.\nReason: {note}", color=discord.Color.gold()))
    record_action(ctx.guild, "WARN", ctx.author, member, reason=note)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int):
    try:
        until = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
        await member.timeout(until)
        await ctx.send(f"🔇 Muted {member.mention} for {minutes} minutes.")
        record_action(ctx.guild, "MUTE", ctx.author, member, reason=f"Timeout {minutes}m")
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f"🔊 Unmuted {member.mention}.")
        record_action(ctx.guild, "UNMUTE", ctx.author, member, reason="Manual unmute")
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 1000:
        return await ctx.send("❌ Amount must be between 1 and 1000.")
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 Deleted {len(deleted)} messages.", delete_after=5)
    record_action(ctx.guild, "PURGE", ctx.author, None, reason=f"Deleted {len(deleted)} messages")

# -----------------------------
# ZONE 9: Info / Utility Commands
# -----------------------------
@bot.command()
async def helpme(ctx):
    emb = discord.Embed(title="Help — Commands", color=THEME_COLOR)
    emb.add_field(name="Dashboard", value="`&setup` (Admin) open dashboard or use posted Setup button", inline=False)
    emb.add_field(name="General", value="`&ping` `&invite` `&botinfo` `&serverinfo` `&userinfo`", inline=False)
    emb.add_field(name="AFK", value="`&afk <reason>` `&afk_status [@user]`", inline=False)
    emb.add_field(name="Moderation", value="`&kick` `&ban` `&unban` `&warn` `&mute` `&unmute` `&purge`", inline=False)
    emb.add_field(name="Fun", value="`&hug &kiss &pat &cry` (anime GIF API)", inline=False)
    await ctx.send(embed=emb)

@bot.command()
async def ping(ctx):
    start = time.time()
    m = await ctx.send("Pinging...")
    elapsed = int((time.time() - start) * 1000)
    await m.edit(content=None, embed=discord.Embed(title="Pong!", description=f"API Latency: {round(bot.latency*1000)}ms\nMsg Latency: {elapsed}ms", color=discord.Color.green()))

@bot.command()
async def botinfo(ctx):
    total_guilds = len(bot.guilds)
    total_users = sum(g.member_count for g in bot.guilds)
    uptime = fmt_duration(time.time() - start_time)
    emb = discord.Embed(title="Bot Info", color=THEME_COLOR)
    emb.add_field(name="Uptime", value=uptime)
    emb.add_field(name="Servers", value=str(total_guilds))
    emb.add_field(name="Users", value=str(total_users))
    emb.add_field(name="Latency", value=f"{round(bot.latency*1000)}ms")
    await ctx.send(embed=emb)

@bot.command()
async def serverinfo(ctx):
    g = ctx.guild
    emb = discord.Embed(title=f"Server Info — {g.name}", color=THEME_COLOR)
    emb.add_field(name="Server ID", value=str(g.id))
    emb.add_field(name="Owner", value=str(g.owner))
    emb.add_field(name="Members", value=str(g.member_count))
    emb.add_field(name="Channels", value=str(len(g.channels)))
    await ctx.send(embed=emb)

@bot.command()
async def userinfo(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    emb = discord.Embed(title=f"User Info — {member}", color=THEME_COLOR)
    emb.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    emb.add_field(name="ID", value=str(member.id))
    emb.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"))
    emb.add_field(name="Joined", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "N/A")
    emb.add_field(name="Roles", value=", ".join([r.name for r in member.roles if r.name != "@everyone"]) or "None", inline=False)
    # AFK indicator
    g = ensure_guild(ctx.guild.id)
    if str(member.id) in g.get("afk", {}):
        emb.add_field(name="AFK", value="Yes (use &afk_status to view)")
    await ctx.send(embed=emb)

@bot.command()
async def invite(ctx):
    try:
        perms = discord.Permissions.all()
        url = discord.utils.oauth_url(bot.user.id, permissions=perms, scopes=("bot","applications.commands"))
        await ctx.send(embed=discord.Embed(title="Invite Link", description=f"[Click to invite]({url})", color=THEME_COLOR))
    except Exception:
        await ctx.send("Cannot generate invite link automatically. Use Developer Portal.")

# -----------------------------
# ZONE 10: Fun (anime actions)
# -----------------------------
@bot.command()
async def hug(ctx, member: discord.Member):
    url = await fetch_anime_gif("hug")
    if not url: return await ctx.send("Failed to fetch gif.")
    emb = discord.Embed(description=f"{ctx.author.mention} hugs {member.mention} 💞", color=THEME_COLOR); emb.set_image(url=url)
    await ctx.send(embed=emb)

@bot.command()
async def kiss(ctx, member: discord.Member):
    url = await fetch_anime_gif("kiss")
    if not url: return await ctx.send("Failed to fetch gif.")
    emb = discord.Embed(description=f"{ctx.author.mention} kisses {member.mention} 💋", color=THEME_COLOR); emb.set_image(url=url)
    await ctx.send(embed=emb)

@bot.command()
async def pat(ctx, member: discord.Member):
    url = await fetch_anime_gif("pat")
    if not url: return await ctx.send("Failed to fetch gif.")
    emb = discord.Embed(description=f"{ctx.author.mention} pats {member.mention} ✨", color=THEME_COLOR); emb.set_image(url=url)
    await ctx.send(embed=emb)

@bot.command()
async def cry(ctx):
    url = await fetch_anime_gif("cry")
    if not url: return await ctx.send("Failed to fetch gif.")
    emb = discord.Embed(description=f"{ctx.author.mention} is crying 😭", color=THEME_COLOR); emb.set_image(url=url)
    await ctx.send(embed=emb)

# -----------------------------
# ZONE 11: Tickets / Giveaways / Starboard / Suggestions / Role Panels (basic)
# -----------------------------
# Ticket: post panel & open ticket
class TicketSetupView(ui.View):
    def __init__(self, author_id:int, guild:discord.Guild):
        super().__init__(timeout=300); self.author_id=author_id; self.guild=guild
    async def interaction_check(self, interaction:discord.Interaction)->bool:
        if interaction.user.id==self.author_id or interaction.user.guild_permissions.administrator: return True
        await interaction.response.send_message("Not allowed.", ephemeral=True); return False
    @ui.button(label="Post Ticket Panel", style=ButtonStyle.primary)
    async def post_panel(self, interaction:discord.Interaction, button:ui.Button):
        # publish a ticket panel
        v=ui.View(timeout=None)
        async def open_ticket_cb(i:discord.Interaction):
            gset=ensure_guild(self.guild.id)
            cat_id=gset.get("ticket_category")
            if cat_id:
                cat=self.guild.get_channel(cat_id)
                channel=await self.guild.create_text_channel(name=f"ticket-{i.user.id}", category=cat)
            else:
                channel=await self.guild.create_text_channel(name=f"ticket-{i.user.id}")
            await channel.set_permissions(self.guild.default_role, view_channel=False)
            await channel.set_permissions(i.user, view_channel=True, send_messages=True)
            await channel.send(f"🎫 {i.user.mention} — Ticket created.", view=TicketCloseView(channel.id))
            await i.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
        b=ui.Button(label="🎫 Open Ticket", style=ButtonStyle.success)
        b.callback = open_ticket_cb
        v.add_item(b)
        await interaction.response.send_message("Ticket panel posted.", view=v)

class TicketCloseView(ui.View):
    def __init__(self, channel_id:int):
        super().__init__(timeout=None); self.channel_id=channel_id
    @ui.button(label="Close Ticket", style=ButtonStyle.danger)
    async def close_ticket(self, interaction:discord.Interaction, button:ui.Button):
        ch = interaction.client.get_channel(self.channel_id)
        if ch:
            msgs=[m async for m in ch.history(limit=500, oldest_first=True)]
            text="\n".join(f"[{m.created_at}] {m.author}: {m.content}" for m in msgs if m.content)[:1900]
            g = ensure_guild(interaction.guild.id)
            log_ch_id = g.get("ticket_log_channel")
            if log_ch_id:
                logch = interaction.guild.get_channel(log_ch_id)
                if logch:
                    try: await logch.send(f"Transcript for {ch.name}:\n```{text}```")
                    except: pass
            try: await ch.delete(); await interaction.response.send_message("Ticket closed and transcript saved.", ephemeral=True)
            except: await interaction.response.send_message("Failed to close ticket.", ephemeral=True)

class GiveawaySetupView(ui.View):
    def __init__(self, author_id:int, guild:discord.Guild):
        super().__init__(timeout=300); self.author_id=author_id; self.guild=guild
    async def interaction_check(self, interaction:discord.Interaction)->bool:
        if interaction.user.id==self.author_id or interaction.user.guild_permissions.administrator: return True
        await interaction.response.send_message("Not allowed.", ephemeral=True); return False
    @ui.button(label="Start Giveaway (command)", style=ButtonStyle.primary)
    async def start_cmd(self, interaction:discord.Interaction, button:ui.Button):
        await interaction.response.send_message("Use &giveaway <time> <winners> <prize>", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def giveaway(ctx, time_str: str, winners: int, *, prize: str):
    # supports 10s 5m 1h 1d
    def parse(t):
        u=t[-1]; v=t[:-1]
        try: n=int(v)
        except: return -1
        if u=='s': return n
        if u=='m': return n*60
        if u=='h': return n*3600
        if u=='d': return n*86400
        return -1
    seconds=parse(time_str)
    if seconds<0: return await ctx.send("Invalid time (e.g. 10s 5m 1h 1d)")
    ends=time.time()+seconds
    emb=discord.Embed(title="🎉 Giveaway", description=prize, color=THEME_COLOR)
    emb.add_field(name="Ends in", value=time_str); emb.add_field(name="Winners", value=str(winners))
    m=await ctx.send(embed=emb)
    v=ui.View(timeout=None)
    async def join_cb(i:discord.Interaction):
        gid=str(ctx.guild.id); gset=ensure_guild(ctx.guild.id)
        gset_g= gset.setdefault("giveaways", {})
        entry = gset_g.setdefault(str(m.id), {"entries": [], "ends_at": ends, "winners": winners, "prize": prize, "channel": ctx.channel.id})
        if i.user.id not in entry["entries"]:
            entry["entries"].append(i.user.id); save_json(DATA_FILE, settings)
            await i.response.send_message("You joined the giveaway!", ephemeral=True)
        else:
            await i.response.send_message("You already joined!", ephemeral=True)
    b=ui.Button(label="🎉 Join", style=ButtonStyle.success); b.callback=join_cb; v.add_item(b)
    await m.edit(view=v); await ctx.send("Giveaway started!")

# giveaways checker
@tasks.loop(seconds=15)
async def giveaway_check():
    now=time.time()
    for gid, gcfg in list(settings.items()):
        gset=gcfg.get("giveaways", {})
        for msgid, data in list(gset.items()):
            try:
                if now>=data.get("ends_at",0) and not data.get("finished"):
                    guild=bot.get_guild(int(gid))
                    if not guild: continue
                    ch=guild.get_channel(data["channel"])
                    if not ch: continue
                    entries=data.get("entries",[])
                    winners_n=max(1,int(data.get("winners",1)))
                    winners=[]
                    if entries:
                        pool=list(set(entries)); random.shuffle(pool); winners=pool[:min(winners_n,len(pool))]
                    if winners:
                        mention=", ".join(f"<@{uid}>" for uid in winners)
                        await ch.send(f"🎉 Giveaway ended! Prize: **{data.get('prize')}**\nWinner(s): {mention}")
                    else:
                        await ch.send(f"🎉 Giveaway ended! Prize: **{data.get('prize')}**\nNo participants.")
                    data["finished"]=True; save_json(DATA_FILE, settings)
            except Exception:
                print("giveaway_check error", traceback.format_exc())

giveaway_check.start()

# Starboard (very basic: watch reactions)
@bot.event
async def on_raw_reaction_add(payload):
    try:
        if payload.emoji.name != "⭐": return
        guild = bot.get_guild(payload.guild_id)
        g = ensure_guild(payload.guild_id)
        threshold = int(g.get("starboard_threshold",5))
        msg_channel = guild.get_channel(payload.channel_id)
        msg = await msg_channel.fetch_message(payload.message_id)
        # count stars
        count = 0
        for r in msg.reactions:
            if str(r.emoji) == "⭐":
                count = r.count
        if count >= threshold:
            star_chid = g.get("starboard_channel")
            if star_chid:
                sc = guild.get_channel(star_chid)
                if sc:
                    emb = discord.Embed(title="⭐ Starboard", description=msg.content or "Embed/attachment", color=THEME_COLOR)
                    emb.add_field(name="Author", value=str(msg.author))
                    emb.add_field(name="Count", value=str(count))
                    emb.set_footer(text=f"Original: {msg.id}")
                    await safe_send(sc, embed=emb)
    except Exception:
        pass

# Suggestions
@bot.command()
async def suggest(ctx, *, idea: str):
    g = ensure_guild(ctx.guild.id)
    ch_id = g.get("suggestion_channel")
    emb = discord.Embed(title="New Suggestion", description=idea, color=THEME_COLOR)
    emb.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None)
    if ch_id:
        ch = ctx.guild.get_channel(ch_id)
        if ch:
            m = await ch.send(embed=emb)
            await ctx.send("✅ Suggestion submitted.")
            return
    m = await ctx.send(embed=emb)
    await ctx.send("✅ Suggestion submitted (posted locally).")

# Role Panels — create/add/publish
@bot.command()
@commands.has_permissions(manage_roles=True)
async def create_role_panel(ctx, panel_name: str):
    g = ensure_guild(ctx.guild.id)
    pid = str(int(time.time()))
    panels = g.setdefault("role_panels", {})
    panels[pid] = {"title": panel_name, "roles": []}
    save_json(DATA_FILE, settings)
    await ctx.send(f"✅ Role panel '{panel_name}' created (id `{pid}`). Use `&add_role_to_panel {pid} @role`.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def add_role_to_panel(ctx, panel_id: str, role: discord.Role):
    g = ensure_guild(ctx.guild.id)
    panels = g.setdefault("role_panels", {})
    if panel_id not in panels: return await ctx.send("Panel not found.")
    if role.id in panels[panel_id]["roles"]: return await ctx.send("Role already in panel.")
    panels[panel_id]["roles"].append(role.id); save_json(DATA_FILE, settings)
    await ctx.send(f"✅ Added role {role.name} to panel {panels[panel_id]['title']}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def publish_role_panel(ctx, panel_id: str):
    g = ensure_guild(ctx.guild.id)
    panels = g.get("role_panels", {})
    if panel_id not in panels: return await ctx.send("Panel not found.")
    panel = panels[panel_id]
    roles = [ctx.guild.get_role(rid) for rid in panel.get("roles",[])]
    options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles if r]
    if not options: return await ctx.send("No roles in panel.")
    async def select_cb(i:discord.Interaction):
        selected = [int(v) for v in i.data.get("values",[])]
        member = i.user
        added=[]; removed=[]
        for rid in selected:
            role = i.guild.get_role(rid)
            if not role: continue
            if role in member.roles:
                await member.remove_roles(role); removed.append(role.name)
            else:
                await member.add_roles(role); added.append(role.name)
        await i.response.send_message(f"Roles updated. Added: {', '.join(added) or 'None'}. Removed: {', '.join(removed) or 'None'}.", ephemeral=True)
        record_action(i.guild, "ROLE_PANEL", bot.user, member, reason=f"Panel {panel.get('title')}")
    view = ui.View(timeout=None)
    select = discord.ui.Select(placeholder=panel.get("title"), options=options, min_values=0, max_values=len(options))
    select.callback = select_cb; view.add_item(select)
    await ctx.send(embed=discord.Embed(title=panel.get("title"), color=THEME_COLOR), view=view)

# -----------------------------
# ZONE 12: Music (stub + simple join/play using yt_dlp if installed)
# -----------------------------
# Note: playing music requires ffmpeg installed and voice support.
YTDLP_AVAILABLE = True
try:
    import yt_dlp as ytdl
except Exception:
    YTDLP_AVAILABLE = False

@bot.command()
async def join24(ctx):
    """Join author's voice channel and stay (24/7 style)"""
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("You must be in a voice channel.")
    ch = ctx.author.voice.channel
    try:
        await ch.connect(reconnect=True)
        await ctx.send(f"Joined {ch.name} (24/7).")
    except Exception as e:
        await ctx.send(f"Failed to join: {e}")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        try:
            await ctx.voice_client.disconnect()
            await ctx.send("Left voice channel.")
        except Exception as e:
            await ctx.send(f"Failed to leave: {e}")
    else:
        await ctx.send("I am not in a voice channel.")

@bot.command()
async def play(ctx, url: str):
    """Play audio from YouTube URL (requires yt_dlp and ffmpeg)."""
    if not YTDLP_AVAILABLE:
        return await ctx.send("Music requires yt_dlp. Install: pip install -U yt_dlp and ensure ffmpeg is available.")
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("You must be in a voice channel.")
    voice = ctx.voice_client
    if not voice:
        try:
            voice = await ctx.author.voice.channel.connect()
        except Exception as e:
            return await ctx.send(f"Failed to connect: {e}")
    # extract audio
    try:
        ydl_opts = {"format":"bestaudio","noplaylist":"True"}
        with ytdl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info["url"]
        # play via FFmpegPCMAudio
        source = discord.FFmpegPCMAudio(audio_url, options="-vn")
        if voice.is_playing():
            voice.stop()
        voice.play(source)
        await ctx.send(f"▶ Now playing: {info.get('title')}")
    except Exception as e:
        await ctx.send(f"Failed to play: {e}")

# -----------------------------
# ZONE 13: Setup command (post a persistent setup button)
# -----------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    # Post a persistent 'Open Dashboard' message (global)
    emb = discord.Embed(title="Server Setup", description="Click the button to open the Dashboard (Admin only).", color=THEME_COLOR)
    view = MainSetupPersistent()
    # add persistent view to bot (ensures callback after restarts)
    bot.add_view(view)
    await ctx.send(embed=emb, view=view)

# -----------------------------
# ZONE 14: error handling & run
# -----------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(description="❌ You don't have permission to use this command.", color=discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(description="❌ Missing argument. Check command usage.", color=discord.Color.red()))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=discord.Embed(description="❌ Invalid argument type.", color=discord.Color.red()))
    else:
        print("Unhandled command error:", error)
        try:
            await ctx.send(embed=discord.Embed(description="❌ An unexpected error occurred. Check console.", color=discord.Color.red()))
        except:
            pass

if __name__ == "__main__":
    # ensure settings for guilds bot is already in
    for g in bot.guilds:
        ensure_guild(g.id)
    save_json(DATA_FILE, settings)
    bot.run(TOKEN)
