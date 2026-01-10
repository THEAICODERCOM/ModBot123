import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import os
import re
import datetime
import random
from typing import Optional

# Configuration
TOKEN_FILE = 'token.txt'
TRUST_FILE_NAME = 'trust_scores.json'

def get_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    return None

TOKEN = get_token()

def find_trust_file():
    """Deep searches for trust_scores.json in common user directories."""
    # List of directories to search in
    base_search = [
        os.getcwd(),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~")
    ]
    
    # First, check immediate paths for speed
    for base in base_search:
        full_path = os.path.join(base, TRUST_FILE_NAME)
        if os.path.exists(full_path):
            return full_path
            
    # If not found, do a shallow walk (1 level deep) in Desktop and Documents
    deep_search = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents")
    ]
    for base in deep_search:
        if os.path.exists(base):
            for item in os.listdir(base):
                item_path = os.path.join(base, item)
                if os.path.isdir(item_path):
                    target = os.path.join(item_path, TRUST_FILE_NAME)
                    if os.path.exists(target):
                        return target
                        
    return os.path.join(os.getcwd(), TRUST_FILE_NAME)

TRUST_FILE = find_trust_file()

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.trust_data = {}
        self.antiraid = False # Anti-raid join gate toggle

    async def setup_hook(self):
        self.load_trust_data()
        # Sync slash commands
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_member_join(self, member: discord.Member):
        if self.antiraid:
            try:
                await member.send("🛡️ The server is currently in **Anti-Raid Mode**. New joins are temporarily restricted. Please try again later.")
                await member.kick(reason="Anti-Raid Mode Active")
            except:
                await member.kick(reason="Anti-Raid Mode Active")

    def load_trust_data(self):
        if os.path.exists(TRUST_FILE):
            with open(TRUST_FILE, 'r') as f:
                self.trust_data = json.load(f)
        else:
            self.trust_data = {}

    def save_trust_data(self):
        with open(TRUST_FILE, 'w') as f:
            json.dump(self.trust_data, f, indent=4)

    def get_trust(self, user_id: str):
        return self.trust_data.get(user_id, 100)

    async def update_trust(self, member: discord.Member, amount: int, reason: str, interaction: discord.Interaction):
        user_id = str(member.id)
        current_score = self.get_trust(user_id)
        new_score = max(0, min(100, current_score + amount))
        self.trust_data[user_id] = new_score
        self.save_trust_data()

        if new_score <= 0:
            try:
                # Try to DM before banning
                try:
                    await member.send(f"⚠️ You have been automatically banned from **{interaction.guild.name}** because your trust score reached 0.\n**Last Action:** {reason}")
                except:
                    pass
                await member.ban(reason=f"Trust score reached 0. Last action: {reason}")
                await interaction.channel.send(f"🚨 {member.mention} has been automatically banned for reaching 0 trust score.")
            except discord.Forbidden:
                await interaction.channel.send(f"⚠️ Failed to auto-ban {member.mention} (missing permissions).")
        
        return new_score

    async def get_invite(self, guild):
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                return await channel.create_invite(max_age=3600, max_uses=1)
        return None

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')

# --- Moderation Slash Commands ---

@bot.tree.command(name="purge", description="Deletes a specified number of messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

@bot.tree.command(name="kick", description="Kicks a member and reduces trust score")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "No reason provided"):
    await interaction.response.defer()
    try:
        await member.send(f"👢 You have been kicked from **{interaction.guild.name}**.\n**Reason:** {reason}")
    except:
        pass
    await member.kick(reason=reason)
    new_score = await bot.update_trust(member, -30, f"Kicked: {reason}", interaction)
    await interaction.followup.send(f"Kicked {member.mention}. Trust score reduced by 30 (Now: {new_score}). Reason: {reason}")

@bot.tree.command(name="ban", description="Bans a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "No reason provided"):
    await interaction.response.defer()
    try:
        await member.send(f"🔨 You have been permanently banned from **{interaction.guild.name}**.\n**Reason:** {reason}")
    except:
        pass
    await member.ban(reason=reason)
    await bot.update_trust(member, -100, f"Manual Ban: {reason}", interaction)
    await interaction.followup.send(f"Banned {member.mention}. Reason: {reason}")

@bot.tree.command(name="timeout", description="Times out a member and reduces trust score")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: Optional[str] = "No reason provided"):
    await interaction.response.defer()
    duration = datetime.timedelta(minutes=minutes)
    try:
        await member.send(f"⏳ You have been timed out in **{interaction.guild.name}** for {minutes} minutes.\n**Reason:** {reason}")
    except:
        pass
    await member.timeout(duration, reason=reason)
    # Deduct 5 trust per 10 minutes, max 50
    deduction = min(50, (minutes // 10) * 5 + 5)
    new_score = await bot.update_trust(member, -deduction, f"Timeout ({minutes}m): {reason}", interaction)
    await interaction.followup.send(f"Timed out {member.mention} for {minutes} minutes. Trust reduced by {deduction} (Now: {new_score}). Reason: {reason}")

@bot.tree.command(name="warn", description="Warns a member and reduces trust score")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer()
    try:
        await member.send(f"⚠️ You have been warned in **{interaction.guild.name}**.\n**Reason:** {reason}")
    except:
        pass
    new_score = await bot.update_trust(member, -10, f"Warned: {reason}", interaction)
    await interaction.followup.send(f"⚠️ {member.mention} has been warned. Trust reduced by 10 (Now: {new_score}). Reason: {reason}")

@bot.tree.command(name="lock", description="Locks the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.followup.send("🔒 Channel locked.")

@bot.tree.command(name="unlock", description="Unlocks the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.followup.send("🔓 Channel unlocked.")

@bot.tree.command(name="softban", description="Bans and immediately unbans to clear messages")
@app_commands.checks.has_permissions(ban_members=True)
async def softban(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "Softban"):
    await interaction.response.defer()
    invite = await bot.get_invite(interaction.guild)
    invite_msg = f"\n**Join back here:** {invite.url}" if invite else ""
    try:
        await member.send(f"💨 You have been softbanned from **{interaction.guild.name}** to clear your message history.\n**Reason:** {reason}{invite_msg}")
    except:
        pass
    await member.ban(reason=reason, delete_message_days=7)
    await interaction.guild.unban(member)
    new_score = await bot.update_trust(member, -50, f"Softban: {reason}", interaction)
    await interaction.followup.send(f"💨 Softbanned {member.mention}. Messages cleared, trust reduced by 50 (Now: {new_score}).")

@bot.tree.command(name="unban", description="Unbans a user by their ID")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer()
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.followup.send(f"✅ Unbanned {user.name} ({user_id}).")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unban: {e}")

@bot.tree.command(name="cleartrust", description="Moderator only: Reset a user's trust score to 100")
@app_commands.checks.has_permissions(manage_guild=True)
async def clear_trust(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer()
    bot.trust_data[str(member.id)] = 100
    bot.save_trust_data()
    await interaction.followup.send(f"♻️ Reset {member.mention}'s trust score to **100**.")

@bot.tree.command(name="massban", description="Bans multiple users by IDs or mentions")
@app_commands.checks.has_permissions(ban_members=True)
async def massban(interaction: discord.Interaction, user_ids: str, reason: Optional[str] = "Mass ban"):
    await interaction.response.defer()
    # Split by space, comma, or mention format
    ids = re.findall(r'\d+', user_ids)
    banned = []
    failed = []
    
    for uid in ids:
        try:
            user = await bot.fetch_user(int(uid))
            await interaction.guild.ban(user, reason=reason)
            banned.append(user.name)
        except:
            failed.append(uid)
            
    await interaction.followup.send(f"✅ Banned: {', '.join(banned) if banned else 'None'}\n❌ Failed IDs: {', '.join(failed) if failed else 'None'}")

@bot.tree.command(name="vmute", description="Mutes a member in voice channels")
@app_commands.checks.has_permissions(mute_members=True)
async def vmute(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "Voice mute"):
    await interaction.response.defer()
    if member.voice:
        await member.edit(mute=True, reason=reason)
        await interaction.followup.send(f"🔇 Voice muted {member.mention}.")
    else:
        await interaction.followup.send(f"❌ {member.mention} is not in a voice channel.")

@bot.tree.command(name="vunmute", description="Unmutes a member in voice channels")
@app_commands.checks.has_permissions(mute_members=True)
async def vunmute(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer()
    if member.voice:
        await member.edit(mute=False)
        await interaction.followup.send(f"🔊 Voice unmuted {member.mention}.")
    else:
        await interaction.followup.send(f"❌ {member.mention} is not in a voice channel.")

@bot.tree.command(name="nickname", description="Changes a user's nickname")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nickname(interaction: discord.Interaction, member: discord.Member, nick: Optional[str] = None):
    await interaction.response.defer()
    try:
        await member.edit(nick=nick)
        await interaction.followup.send(f"✅ Changed {member.mention}'s nickname to `{nick if nick else 'Default'}`.")
    except:
        await interaction.followup.send(f"❌ Failed to change nickname for {member.mention} (missing permissions).")

@bot.tree.command(name="roleadd", description="Adds a role to a member")
@app_commands.checks.has_permissions(manage_roles=True)
async def roleadd(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await interaction.response.defer()
    try:
        await member.add_roles(role)
        await interaction.followup.send(f"✅ Added role {role.name} to {member.mention}.")
    except:
        await interaction.followup.send(f"❌ Failed to add role (check hierarchy/permissions).")

@bot.tree.command(name="roleremove", description="Removes a role from a member")
@app_commands.checks.has_permissions(manage_roles=True)
async def roleremove(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await interaction.response.defer()
    try:
        await member.remove_roles(role)
        await interaction.followup.send(f"✅ Removed role {role.name} from {member.mention}.")
    except:
        await interaction.followup.send(f"❌ Failed to remove role (check hierarchy/permissions).")

@bot.tree.command(name="slowmode", description="Sets the slowmode for the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    await interaction.response.defer()
    await interaction.channel.edit(slowmode_delay=seconds)
    await interaction.followup.send(f"⏲️ Slowmode set to {seconds} seconds.")

@bot.tree.command(name="serverinfo", description="Shows detailed information about the server")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"Server Info: {guild.name}", color=discord.Color.blue())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Created At", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Shows the bot's latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@bot.tree.command(name="poll", description="Creates a simple yes/no poll")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.purple())
    embed.set_footer(text=f"Asked by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await message.add_reaction("✅")
    await message.add_reaction("❌")

@bot.tree.command(name="8ball", description="Ask the magic 8-ball a question")
async def eightball(interaction: discord.Interaction, question: str):
    responses = [
        "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes definitely.",
        "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
        "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
        "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
        "Don't count on it.", "My reply is no.", "My sources say no.",
        "Outlook not so good.", "Very doubtful."
    ]
    await interaction.response.send_message(f"**Question:** {question}\n**🎱 Answer:** {random.choice(responses)}")

@bot.tree.command(name="hug", description="Sends a hug to a member")
async def hug(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message(f"🤗 {interaction.user.mention} gives {member.mention} a big warm hug!")

@bot.tree.command(name="antiraid", description="Toggles anti-raid mode (auto-kicks new joins)")
@app_commands.checks.has_permissions(manage_guild=True)
async def antiraid_toggle(interaction: discord.Interaction, enabled: bool):
    bot.antiraid = enabled
    status = "ENABLED 🛡️" if enabled else "DISABLED 🔓"
    await interaction.response.send_message(f"Anti-Raid Mode is now **{status}**.")

@bot.tree.command(name="lockdown", description="Locks all text channels in the server")
@app_commands.checks.has_permissions(manage_guild=True)
async def lockdown(interaction: discord.Interaction):
    await interaction.response.defer()
    locked_channels = []
    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages != False:
            overwrite.send_messages = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Server Lockdown")
            locked_channels.append(channel.name)
    
    await interaction.followup.send(f"🚨 **Server Lockdown Active**. Locked {len(locked_channels)} channels.")

@bot.tree.command(name="unlockdown", description="Unlocks all text channels in the server")
@app_commands.checks.has_permissions(manage_guild=True)
async def unlockdown(interaction: discord.Interaction):
    await interaction.response.defer()
    unlocked_channels = []
    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages == False:
            overwrite.send_messages = None # Reset to default/neutral
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Server Lockdown Lifted")
            unlocked_channels.append(channel.name)
    
    await interaction.followup.send(f"🔓 **Server Lockdown Lifted**. Unlocked {len(unlocked_channels)} channels.")

@bot.tree.command(name="cleanuser", description="Purges all messages from a specific user across all channels")
@app_commands.checks.has_permissions(manage_messages=True)
async def cleanuser(interaction: discord.Interaction, member: discord.Member, limit: Optional[int] = 100):
    await interaction.response.defer()
    total_deleted = 0
    
    for channel in interaction.guild.text_channels:
        try:
            deleted = await channel.purge(limit=limit, check=lambda m: m.author == member)
            total_deleted += len(deleted)
        except:
            continue
            
    await interaction.followup.send(f"🧹 Cleaned up **{total_deleted}** messages from {member.mention} across the server.")

@bot.tree.command(name="banrole", description="Bans everyone who has a specific role")
@app_commands.checks.has_permissions(ban_members=True)
async def banrole(interaction: discord.Interaction, role: discord.Role, reason: Optional[str] = "Mass role ban"):
    await interaction.response.defer()
    
    count = 0
    failed = 0
    
    # We need to fetch members if they aren't cached
    async for member in interaction.guild.fetch_members(limit=None):
        if role in member.roles:
            try:
                if member.top_role < interaction.guild.me.top_role:
                    await member.ban(reason=reason)
                    count += 1
                else:
                    failed += 1
            except:
                failed += 1
                
    await interaction.followup.send(f"🔨 Banned **{count}** members with the role `{role.name}`. (Failed: {failed})")

@bot.tree.command(name="nuke", description="Deletes and recreates a channel to clear all messages")
@app_commands.checks.has_permissions(administrator=True)
async def nuke(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel_info = {
        "name": interaction.channel.name,
        "category": interaction.channel.category,
        "position": interaction.channel.position,
        "overwrites": interaction.channel.overwrites,
        "topic": interaction.channel.topic
    }
    new_channel = await interaction.guild.create_text_channel(
        name=channel_info["name"],
        category=channel_info["category"],
        overwrites=channel_info["overwrites"],
        position=channel_info["position"],
        topic=channel_info["topic"]
    )
    await interaction.channel.delete()
    await new_channel.send("☢️ Channel Nuked!")

# --- Fun Slash Commands ---

@bot.tree.command(name="avatar", description="Shows a user's avatar")
async def avatar(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"{target.display_name}'s Avatar", color=discord.Color.blue())
    embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="Shows information about a user")
async def userinfo(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    roles = [role.mention for role in target.roles[1:]] # Skip @everyone
    
    embed = discord.Embed(title="User Info", color=target.color)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Name", value=target.name, inline=True)
    embed.add_field(name="ID", value=target.id, inline=True)
    embed.add_field(name="Trust Score", value=f"{bot.get_trust(str(target.id))}/100", inline=True)
    embed.add_field(name="Joined Discord", value=discord.utils.format_dt(target.created_at), inline=False)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(target.joined_at) if target.joined_at else "Unknown", inline=False)
    embed.add_field(name="Roles", value=" ".join(roles) if roles else "None", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roll", description="Rolls a dice")
@app_commands.describe(sides="Number of sides (default 6)")
async def roll(interaction: discord.Interaction, sides: int = 6):
    result = random.randint(1, sides)
    await interaction.response.send_message(f"🎲 Rolled a {result} (1-{sides})")

@bot.tree.command(name="coinflip", description="Flips a coin")
async def coinflip(interaction: discord.Interaction):
    result = random.choice(["Heads", "Tails"])
    await interaction.response.send_message(f"🪙 It's **{result}**!")

@bot.tree.command(name="slap", description="Slaps someone!")
async def slap(interaction: discord.Interaction, member: discord.Member):
    if member == interaction.user:
        await interaction.response.send_message(f"Why would you slap yourself, {interaction.user.mention}? 🤨")
    else:
        await interaction.response.send_message(f"{interaction.user.mention} slapped {member.mention}! Ouch. ✋")

@bot.tree.command(name="help", description="Shows a list of available commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Bot Commands Help", color=discord.Color.gold())
    embed.description = "Here is a list of all available slash commands categorized by their usage."

    mod_cmds = (
        "**/purge <amount>** - Delete multiple messages\n"
        "**/kick <@user> [reason]** - Kick member (-30 trust)\n"
        "**/ban <@user> [reason]** - Ban member (-100 trust)\n"
        "**/banrole <@role>** - Ban everyone with a role\n"
        "**/massban <ids/mentions>** - Ban multiple users\n"
        "**/unban <user_id>** - Unban a user\n"
        "**/timeout <@user> <mins> [reason]** - Mute member\n"
        "**/warn <@user> <reason>** - Warn member (-10 trust)\n"
        "**/softban <@user> [reason]** - Ban/Unban (-50 trust)\n"
        "**/vmute / /vunmute** - Voice mute/unmute\n"
        "**/nickname <@user> [nick]** - Change nickname\n"
        "**/roleadd / /roleremove** - Manage user roles\n"
        "**/lock / /unlock** - Lock/Unlock channel\n"
        "**/lockdown / /unlockdown** - Server-wide lockdown\n"
        "**/antiraid <on/off>** - Auto-kick new joins\n"
        "**/cleanuser <@user>** - Purge user from all channels\n"
        "**/slowmode <secs>** - Set channel slowmode\n"
        "**/nuke** - Recreate channel"
    )
    embed.add_field(name="🛡️ Moderation", value=mod_cmds, inline=False)
    
    trust_cmds = (
        "**/trust [@user]** - Check trust score\n"
        "**/settrust <@user> <score>** - Set trust score (Admin)\n"
        "**/cleartrust <@user>** - Reset trust to 100 (Admin)"
    )
    embed.add_field(name="⚖️ Trust System", value=trust_cmds, inline=False)
    
    util_cmds = (
        "**/serverinfo** - Detailed server statistics\n"
        "**/userinfo [@user]** - Detailed user data\n"
        "**/ping** - Check bot latency\n"
        "**/poll <question>** - Create a simple poll\n"
        "**/avatar [@user]** - View user avatar"
    )
    embed.add_field(name="🛠️ Utility", value=util_cmds, inline=False)

    fun_cmds = (
        "**/roll [sides]** - Roll a dice\n"
        "**/coinflip** - Flip a coin\n"
        "**/slap <@user>** - Slap a user\n"
        "**/hug <@user>** - Hug a user\n"
        "**/8ball <question>** - Ask the magic 8-ball"
    )
    embed.add_field(name="🎉 Fun", value=fun_cmds, inline=False)
    
    embed.set_footer(text="Tip: All commands are slash commands!")
    await interaction.response.send_message(embed=embed)

# --- Trust System Commands ---

@bot.tree.command(name="trust", description="Check a user's trust score")
async def trust_check(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    score = bot.get_trust(str(target.id))
    
    color = discord.Color.green() if score > 70 else discord.Color.orange() if score > 30 else discord.Color.red()
    
    embed = discord.Embed(title=f"Trust Score: {target.display_name}", description=f"Current Score: **{score}/100**", color=color)
    embed.set_thumbnail(url=target.display_avatar.url)
    
    status = "Trusted" if score > 70 else "Warning" if score > 30 else "Critical"
    embed.add_field(name="Status", value=status)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="settrust", description="Moderator only: Set a user's trust score")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_trust(interaction: discord.Interaction, member: discord.Member, score: int):
    if score < 0 or score > 100:
        await interaction.response.send_message("Score must be between 0 and 100.", ephemeral=True)
        return
        
    old_score = bot.get_trust(str(member.id))
    bot.trust_data[str(member.id)] = score
    bot.save_trust_data()
    
    await interaction.response.send_message(f"Updated {member.mention}'s trust score from {old_score} to **{score}**.")
    
    if score <= 0:
        await member.ban(reason="Trust score set to 0 by admin.")
        await interaction.channel.send(f"🚨 {member.mention} has been automatically banned (Score set to 0).")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
    else:
        print(f"Slash Error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)

bot.run(TOKEN)
