import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta, datetime
import re

# --- DATABASE SETUP ---
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['lavabot_db']
config_col = db['guild_configs']
warns_col = db['warnings']
cases_col = db['mod_cases']

def get_guild_config(guild_id):
    conf = config_col.find_one({"guild_id": str(guild_id)})
    default_modules = {
        "link_filter": {"enabled": "False", "chans": [], "roles": []},
        "mod": {"enabled": "False", "roles": []},
        "help": {"enabled": "False", "aliases": "help", "text": "Lava Network Support"},
        "info": {"enabled": "False", "aliases": "info", "text": "Information Module"},
        "dms": {
            "welcome_enabled": "False", "welcome_msg": "Welcome to {server}!",
            "kick_enabled": "False", "kick_msg": "Your Account Got Kicked From {server}",
            "ban_enabled": "False", "ban_msg": "You were permanently banned from {server}",
            "timeout_enabled": "False", "timeout_msg": "You have been timed out in {server}",
            "warn_enabled": "False", "warn_msg": "You received a warning in {server}: {reason}",
            "unban_enabled": "False", "unban_msg": "You have been unbanned from {server}",
            "mute_enabled": "False", "mute_msg": "You have been muted in {server}"
        },
        "welcome_channel": {
            "enabled": "False", "channel_id": "", "message": "Welcome {user} to {server}!",
            "embed": "False", "embed_color": "#ff3333", "embed_title": "Welcome!",
            "show_member_count": "True"
        },
        "leave_channel": {
            "enabled": "False", "channel_id": "", "message": "{user} has left {server}."
        },
        "logging": {
            "enabled": "False", "channel_id": "",
            "log_deletes": "True", "log_edits": "True",
            "log_joins": "True", "log_leaves": "True",
            "log_bans": "True", "log_roles": "True",
            "log_mods": "True"
        },
        "auto_mod": {
            "enabled": "False",
            "blacklist": [],
            "blacklist_action": "delete",
            "warn_on_blacklist": "False",
            "caps_filter": "False",
            "caps_threshold": "70",
            "spam_filter": "False",
            "spam_count": "5",
            "spam_seconds": "5"
        },
        "auto_role": {
            "enabled": "False",
            "role_id": ""
        },
        "reaction_roles": [],
        "warn_system": {
            "enabled": "False",
            "warn_threshold_kick": "0",
            "warn_threshold_ban": "0"
        },
        "giveaway": {
            "enabled": "False"
        },
        "slowmode": {
            "enabled": "False"
        },
        "tickets": {
            "enabled": "False",
            "category_id": "",
            "support_role_id": "",
            "open_message": "Your ticket has been created! Support will be with you shortly.",
            "channel_id": "",
            "button_label": "Open Ticket",
            "button_color": "blurple",
            "transcript_enabled": "False"
        },
        "status": {
            "type": "playing",
            "text": "Lava Network"
        }
    }

    if not conf:
        conf = {
            "guild_id": str(guild_id),
            "prefix": "!",
            "bot_name": "LAVA",
            "accent_color": "#ff3333",
            "modules": default_modules
        }
        config_col.insert_one(conf)
    else:
        updated = False
        if "modules" not in conf:
            conf["modules"] = default_modules
            updated = True
        else:
            for mod_name, mod_data in default_modules.items():
                if mod_name not in conf["modules"]:
                    conf["modules"][mod_name] = mod_data
                    updated = True
                elif isinstance(mod_data, dict):
                    for key, val in mod_data.items():
                        if key not in conf["modules"][mod_name]:
                            conf["modules"][mod_name][key] = val
                            updated = True
        if "bot_name" not in conf:
            conf["bot_name"] = "LAVA"
            updated = True
        if "accent_color" not in conf:
            conf["accent_color"] = "#ff3333"
            updated = True
        if updated:
            config_col.replace_one({"guild_id": str(guild_id)}, conf)
    return conf

# --- BOT SETUP ---
intents = discord.Intents.all()

async def get_prefix(bot, message):
    if not message.guild: return "!"
    conf = get_guild_config(message.guild.id)
    return conf.get("prefix", "!")

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# --- SPAM TRACKING ---
spam_tracker = {}

# --- HELPERS ---
def format_font(text, font_type):
    text = text.lower().replace(" ", "-")
    fonts = {
        "gothic": "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷",
        "fancy": "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃",
        "smallcaps": "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ"
    }
    return text.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", fonts[font_type])) if font_type in fonts else text

async def send_user_dm(member, msg_template, guild_name, extra={}):
    try:
        content = msg_template.replace("{server}", guild_name)
        for k, v in extra.items():
            content = content.replace(f"{{{k}}}", str(v))
        await member.send(content)
    except:
        pass

async def log_action(guild, conf, description, color=0xff3333, fields=None):
    log_conf = conf['modules'].get('logging', {})
    if log_conf.get('enabled') != "True" or not log_conf.get('channel_id'):
        return
    channel = guild.get_channel(int(log_conf['channel_id']))
    if not channel: return
    embed = discord.Embed(description=description, color=color, timestamp=datetime.utcnow())
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    await channel.send(embed=embed)

async def add_mod_case(guild_id, action, mod, target, reason):
    case_num = cases_col.count_documents({"guild_id": str(guild_id)}) + 1
    cases_col.insert_one({
        "guild_id": str(guild_id),
        "case": case_num,
        "action": action,
        "mod": str(mod),
        "target": str(target),
        "reason": reason or "No reason",
        "timestamp": datetime.utcnow().isoformat()
    })
    return case_num

def has_mod_perms(ctx, conf):
    return any(str(r.id) in conf['modules']['mod']['roles'] for r in ctx.author.roles) or ctx.author.guild_permissions.administrator

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user}")
    for guild in bot.guilds:
        conf = get_guild_config(guild.id)
        status_conf = conf['modules'].get('status', {})
        status_text = status_conf.get('text', 'Lava Network')
        status_type = status_conf.get('type', 'playing')
        activity_map = {
            'playing': discord.Game(name=status_text),
            'watching': discord.Activity(type=discord.ActivityType.watching, name=status_text),
            'listening': discord.Activity(type=discord.ActivityType.listening, name=status_text),
            'competing': discord.Activity(type=discord.ActivityType.competing, name=status_text)
        }
        await bot.change_presence(activity=activity_map.get(status_type, discord.Game(name=status_text)))
        break

@bot.event
async def on_member_join(member):
    conf = get_guild_config(member.guild.id)
    # DM Welcome
    dm_conf = conf['modules']['dms']
    if dm_conf.get("welcome_enabled") == "True":
        await send_user_dm(member, dm_conf["welcome_msg"], member.guild.name, {"user": member.name})
    # Channel Welcome
    wc = conf['modules'].get('welcome_channel', {})
    if wc.get('enabled') == "True" and wc.get('channel_id'):
        channel = member.guild.get_channel(int(wc['channel_id']))
        if channel:
            msg = wc.get('message', 'Welcome {user}!').replace("{user}", member.mention).replace("{server}", member.guild.name)
            if wc.get('show_member_count') == "True":
                msg += f"\nWe now have **{member.guild.member_count}** members!"
            if wc.get('embed') == "True":
                color_hex = wc.get('embed_color', '#ff3333').lstrip('#')
                color_int = int(color_hex, 16)
                embed = discord.Embed(title=wc.get('embed_title', 'Welcome!'), description=msg, color=color_int)
                embed.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=embed)
            else:
                await channel.send(msg)
    # Auto Role
    ar = conf['modules'].get('auto_role', {})
    if ar.get('enabled') == "True" and ar.get('role_id'):
        role = member.guild.get_role(int(ar['role_id']))
        if role:
            try: await member.add_roles(role)
            except: pass
    # Log
    if conf['modules'].get('logging', {}).get('log_joins') == "True":
        await log_action(member.guild, conf, f"✅ **{member}** joined the server.", 0x00ff88)

@bot.event
async def on_member_remove(member):
    conf = get_guild_config(member.guild.id)
    # Channel Leave
    lc = conf['modules'].get('leave_channel', {})
    if lc.get('enabled') == "True" and lc.get('channel_id'):
        channel = member.guild.get_channel(int(lc['channel_id']))
        if channel:
            msg = lc.get('message', '{user} left.').replace("{user}", str(member)).replace("{server}", member.guild.name)
            await channel.send(msg)
    # Log
    if conf['modules'].get('logging', {}).get('log_leaves') == "True":
        await log_action(member.guild, conf, f"❌ **{member}** left the server.", 0xff6600)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    conf = get_guild_config(message.guild.id)
    if conf['modules'].get('logging', {}).get('log_deletes') == "True":
        await log_action(message.guild, conf,
            f"🗑️ Message by **{message.author}** deleted in {message.channel.mention}",
            0xffcc00, [("Content", message.content[:1024] or "(empty)", False)])

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content: return
    conf = get_guild_config(before.guild.id)
    if conf['modules'].get('logging', {}).get('log_edits') == "True":
        await log_action(before.guild, conf,
            f"✏️ Message by **{before.author}** edited in {before.channel.mention}",
            0x3399ff, [("Before", before.content[:512] or "(empty)", False), ("After", after.content[:512] or "(empty)", False)])

@bot.event
async def on_member_update(before, after):
    if before.roles == after.roles: return
    conf = get_guild_config(before.guild.id)
    if conf['modules'].get('logging', {}).get('log_roles') == "True":
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added:
            await log_action(before.guild, conf, f"🎭 **{before}** gained role: **{added[0].name}**", 0x00ccff)
        if removed:
            await log_action(before.guild, conf, f"🎭 **{before}** lost role: **{removed[0].name}**", 0xff6666)

@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild: return
    conf = get_guild_config(message.guild.id)
    prefix = conf.get("prefix", "!")

    # Link Filter
    lf = conf['modules'].get('link_filter', {})
    if lf.get('enabled') == "True" and str(message.channel.id) in lf.get('chans', []):
        user_roles = [str(r.id) for r in message.author.roles]
        has_bypass = any(rid in lf.get('roles', []) for rid in user_roles) or message.author.guild_permissions.administrator
        if not has_bypass and re.search(r'http[s]?://', message.content.lower()):
            await message.delete()
            await message.channel.send(f"**{message.author.mention}**, links are not allowed here.", delete_after=5)
            return

    # Auto-Mod
    am = conf['modules'].get('auto_mod', {})
    if am.get('enabled') == "True" and not message.author.guild_permissions.administrator:
        content_lower = message.content.lower()
        # Blacklist check
        for word in am.get('blacklist', []):
            if word.lower() in content_lower:
                action = am.get('blacklist_action', 'delete')
                await message.delete()
                if action == 'warn' or am.get('warn_on_blacklist') == "True":
                    await _add_warn(message.guild, message.author, bot.user, "Auto-Mod: Blacklisted word", conf)
                await message.channel.send(f"{message.author.mention} your message was removed (blacklisted content).", delete_after=5)
                return
        # Caps filter
        if am.get('caps_filter') == "True" and len(message.content) > 10:
            caps = sum(1 for c in message.content if c.isupper())
            threshold = int(am.get('caps_threshold', 70))
            if caps / len(message.content) * 100 >= threshold:
                await message.delete()
                await message.channel.send(f"{message.author.mention} please reduce caps lock.", delete_after=5)
                return
        # Spam filter
        if am.get('spam_filter') == "True":
            key = f"{message.guild.id}:{message.author.id}"
            now = datetime.utcnow().timestamp()
            spam_count = int(am.get('spam_count', 5))
            spam_seconds = int(am.get('spam_seconds', 5))
            if key not in spam_tracker:
                spam_tracker[key] = []
            spam_tracker[key] = [t for t in spam_tracker[key] if now - t < spam_seconds]
            spam_tracker[key].append(now)
            if len(spam_tracker[key]) >= spam_count:
                await message.delete()
                await message.channel.send(f"{message.author.mention} you are sending messages too fast!", delete_after=5)
                spam_tracker[key] = []
                return

    # Help & Info
    for mod in ['help', 'info']:
        m_data = conf['modules'][mod]
        if m_data['enabled'] == "True":
            aliases = [a.strip().lower() for a in m_data.get("aliases", mod).split(",")]
            if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
                await message.channel.send(m_data.get("text"))
                return

    await bot.process_commands(message)

# --- WARN HELPER ---
async def _add_warn(guild, member, mod, reason, conf):
    warns_col.insert_one({
        "guild_id": str(guild.id),
        "user_id": str(member.id),
        "user_name": str(member),
        "mod": str(mod),
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    })
    warn_conf = conf['modules'].get('warn_system', {})
    total = warns_col.count_documents({"guild_id": str(guild.id), "user_id": str(member.id)})
    dm_conf = conf['modules']['dms']
    if dm_conf.get("warn_enabled") == "True":
        await send_user_dm(member, dm_conf["warn_msg"], guild.name, {"reason": reason})
    kick_thresh = int(warn_conf.get('warn_threshold_kick', 0))
    ban_thresh = int(warn_conf.get('warn_threshold_ban', 0))
    if ban_thresh > 0 and total >= ban_thresh:
        dm_conf2 = conf['modules']['dms']
        if dm_conf2.get("ban_enabled") == "True":
            await send_user_dm(member, dm_conf2["ban_msg"], guild.name)
        await member.ban(reason=f"Auto-ban: {total} warnings")
    elif kick_thresh > 0 and total >= kick_thresh:
        dm_conf2 = conf['modules']['dms']
        if dm_conf2.get("kick_enabled") == "True":
            await send_user_dm(member, dm_conf2["kick_msg"], guild.name)
        await member.kick(reason=f"Auto-kick: {total} warnings")
    return total

# --- MOD COMMANDS ---
@bot.command()
async def warn(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True": return
    if not has_mod_perms(ctx, conf): return
    total = await _add_warn(ctx.guild, member, ctx.author, reason or "No reason", conf)
    case = await add_mod_case(ctx.guild.id, "WARN", ctx.author, member, reason)
    await ctx.send(f"⚠️ **{member}** warned. Reason: {reason or 'No reason'} | Total warnings: **{total}** | Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"⚠️ **{member}** warned by **{ctx.author}**\nReason: {reason}", 0xffcc00)

@bot.command()
async def warns(ctx, member: discord.Member):
    user_warns = list(warns_col.find({"guild_id": str(ctx.guild.id), "user_id": str(member.id)}))
    if not user_warns:
        await ctx.send(f"**{member}** has no warnings.")
        return
    embed = discord.Embed(title=f"Warnings for {member}", color=0xff3333)
    for i, w in enumerate(user_warns[-10:], 1):
        embed.add_field(name=f"#{i} | {w.get('timestamp','')[:10]}", value=f"**Reason:** {w['reason']}\n**By:** {w['mod']}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clearwarns(ctx, member: discord.Member):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    warns_col.delete_many({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
    await ctx.send(f"✅ Cleared all warnings for **{member}**.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True": return
    if not has_mod_perms(ctx, conf): return
    dm_conf = conf['modules']['dms']
    if dm_conf.get("kick_enabled") == "True":
        await send_user_dm(member, dm_conf["kick_msg"], ctx.guild.name)
    await member.kick(reason=reason)
    case = await add_mod_case(ctx.guild.id, "KICK", ctx.author, member, reason)
    await ctx.send(f"👢 **{member}** was kicked. | Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"👢 **{member}** kicked by **{ctx.author}**\nReason: {reason}", 0xff6600)

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True": return
    if not has_mod_perms(ctx, conf): return
    dm_conf = conf['modules']['dms']
    if dm_conf.get("ban_enabled") == "True":
        await send_user_dm(member, dm_conf["ban_msg"], ctx.guild.name)
    await member.ban(reason=reason)
    case = await add_mod_case(ctx.guild.id, "BAN", ctx.author, member, reason)
    await ctx.send(f"🔨 **{member}** was banned. | Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"🔨 **{member}** banned by **{ctx.author}**\nReason: {reason}", 0xff0000)

@bot.command()
async def unban(ctx, user_id: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)
        dm_conf = conf['modules']['dms']
        if dm_conf.get("unban_enabled") == "True":
            await send_user_dm(user, dm_conf["unban_msg"], ctx.guild.name)
        await ctx.send(f"✅ **{user}** was unbanned.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True": return
    if not has_mod_perms(ctx, conf): return
    dm_conf = conf['modules']['dms']
    if dm_conf.get("timeout_enabled") == "True":
        await send_user_dm(member, dm_conf["timeout_msg"], ctx.guild.name)
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    case = await add_mod_case(ctx.guild.id, f"TIMEOUT {minutes}m", ctx.author, member, reason)
    await ctx.send(f"⏰ **{member}** timed out for {minutes}m. | Case #{case}")

@bot.command()
async def mute(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        muted_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            try: await channel.set_permissions(muted_role, send_messages=False, speak=False)
            except: pass
    await member.add_roles(muted_role, reason=reason)
    dm_conf = conf['modules']['dms']
    if dm_conf.get("mute_enabled") == "True":
        await send_user_dm(member, dm_conf["mute_msg"], ctx.guild.name)
    await ctx.send(f"🔇 **{member}** has been muted.")

@bot.command()
async def unmute(ctx, member: discord.Member):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if muted_role and muted_role in member.roles:
        await member.remove_roles(muted_role)
        await ctx.send(f"🔊 **{member}** has been unmuted.")

@bot.command()
async def slowmode(ctx, channel: discord.TextChannel = None, seconds: int = 0):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    target = channel or ctx.channel
    await target.edit(slowmode_delay=seconds)
    await ctx.send(f"🐌 Slowmode set to **{seconds}s** in {target.mention}.")

@bot.command()
async def purge(ctx, amount: int):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Deleted **{len(deleted)-1}** messages.", delete_after=3)

@bot.command()
async def cases(ctx):
    all_cases = list(cases_col.find({"guild_id": str(ctx.guild.id)}).sort("case", -1).limit(10))
    if not all_cases:
        await ctx.send("No cases found.")
        return
    embed = discord.Embed(title="Recent Mod Cases", color=0xff3333)
    for c in all_cases:
        embed.add_field(name=f"#{c['case']} | {c['action']}", value=f"**Target:** {c['target']}\n**Mod:** {c['mod']}\n**Reason:** {c['reason']}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def giveaway(ctx, duration: str, *, prize: str):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['giveaway']['enabled'] != "True": return
    if not has_mod_perms(ctx, conf): return
    unit = duration[-1].lower()
    try: amount = int(duration[:-1])
    except: await ctx.send("Invalid duration. Example: `!giveaway 1h Nitro`"); return
    seconds = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}.get(unit, 0) * amount
    if not seconds: await ctx.send("Use s/m/h/d (e.g. `30m`)."); return
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**Prize:** {prize}\n**Duration:** {duration}\n\nReact with 🎉 to enter!", color=0xffd700)
    embed.set_footer(text=f"Hosted by {ctx.author}")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")
    await asyncio.sleep(seconds)
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("No valid entries for the giveaway.")
    else:
        import random
        winner = random.choice(users)
        await ctx.send(f"🎉 Congratulations {winner.mention}! You won **{prize}**!")

# --- TICKET SYSTEM ---
class TicketButton(discord.ui.View):
    def __init__(self, conf):
        super().__init__(timeout=None)
        self.conf = conf

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.blurple, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = get_guild_config(interaction.guild.id)
        tc = conf['modules']['tickets']
        category = interaction.guild.get_channel(int(tc['category_id'])) if tc.get('category_id') else None
        support_role = interaction.guild.get_role(int(tc['support_role_id'])) if tc.get('support_role_id') else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ticket_ch = await interaction.guild.create_text_channel(
            f"ticket-{interaction.user.name}", category=category, overwrites=overwrites
        )
        msg = tc.get('open_message', 'Your ticket has been created!').replace("{user}", interaction.user.mention)
        close_view = CloseTicketView()
        await ticket_ch.send(f"{interaction.user.mention} {support_role.mention if support_role else ''}\n{msg}", view=close_view)
        await interaction.response.send_message(f"✅ Ticket created: {ticket_ch.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

@bot.command()
async def setticket(ctx):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['tickets']['enabled'] != "True": return
    if not ctx.author.guild_permissions.administrator: return
    tc = conf['modules']['tickets']
    label = tc.get('button_label', 'Open Ticket')
    embed = discord.Embed(title="🎫 Support Tickets", description="Click the button below to open a support ticket.", color=0xff3333)
    view = TicketButton(conf)
    await ctx.send(embed=embed, view=view)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "lava_ultra_secure_key_2024"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ bot_name }} | Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');
        :root {
            --bg: #060608; --side: #0c0c10; --card: #111116; --border: #1c1c24;
            --accent: {{ accent_color }}; --text: #e8e8f0; --muted: #55556a;
            --accent-glow: {{ accent_color }}44;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: var(--bg); color: var(--text); font-family: 'Rajdhani', sans-serif; display: flex; height: 100vh; overflow: hidden; }

        /* SIDEBAR */
        .sidebar { width: 240px; background: var(--side); border-right: 1px solid var(--border); display: flex; flex-direction: column; padding: 0; flex-shrink: 0; }
        .sidebar-logo { padding: 28px 20px 20px; border-bottom: 1px solid var(--border); }
        .sidebar-logo h2 { color: var(--accent); font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 22px; letter-spacing: 3px; text-transform: uppercase; }
        .sidebar-logo .guild { color: var(--muted); font-size: 12px; font-family: 'JetBrains Mono', monospace; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .nav-section { padding: 16px 12px 4px; }
        .nav-label { font-size: 10px; color: var(--muted); letter-spacing: 2px; text-transform: uppercase; padding: 0 8px; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace; display: block; }
        .nav-btn { width: 100%; padding: 10px 12px; background: none; border: none; color: #888; text-align: left; cursor: pointer; border-radius: 6px; font-size: 14px; font-family: 'Rajdhani', sans-serif; font-weight: 600; display: flex; align-items: center; gap: 10px; transition: 0.15s; letter-spacing: 0.5px; }
        .nav-btn i { width: 16px; text-align: center; font-size: 13px; }
        .nav-btn:hover { background: #141418; color: var(--text); }
        .nav-btn.active { background: var(--accent-glow); color: var(--accent); border-left: 2px solid var(--accent); }
        .sidebar-bottom { margin-top: auto; padding: 12px; border-top: 1px solid var(--border); }

        /* MAIN */
        .main { flex: 1; overflow-y: auto; padding: 36px 40px; }
        .page { display: none; }
        .page.active { display: block; animation: fadeIn 0.2s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .page-title { font-size: 28px; font-weight: 700; letter-spacing: 1px; margin-bottom: 24px; color: var(--text); }
        .page-title span { color: var(--accent); }

        /* CARDS */
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 22px; margin-bottom: 20px; }
        .card-title { font-size: 13px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); margin-bottom: 16px; font-family: 'JetBrains Mono', monospace; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

        /* FORM ELEMENTS */
        label { font-size: 13px; color: var(--muted); display: block; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace; }
        input[type="text"], input[type="password"], input[type="color"], input[type="number"], textarea, select {
            width: 100%; padding: 10px 14px; background: #08080c; border: 1px solid var(--border);
            color: var(--text); border-radius: 6px; font-family: 'Rajdhani', sans-serif; font-size: 14px;
            margin-bottom: 14px; transition: border 0.2s; outline: none;
        }
        input:focus, textarea:focus, select:focus { border-color: var(--accent); }
        textarea { min-height: 80px; resize: vertical; }
        input[type="color"] { height: 42px; padding: 4px 8px; cursor: pointer; }

        .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border); }
        .toggle-row:last-child { border-bottom: none; }
        .toggle-label { font-size: 14px; font-weight: 600; }
        .toggle-sub { font-size: 12px; color: var(--muted); margin-top: 2px; font-family: 'JetBrains Mono', monospace; }

        /* TOGGLE SWITCH */
        .switch { position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; inset: 0; background: #222; border-radius: 24px; transition: 0.3s; }
        .slider:before { content: ""; position: absolute; height: 18px; width: 18px; left: 3px; bottom: 3px; background: #555; border-radius: 50%; transition: 0.3s; }
        input:checked + .slider { background: var(--accent); }
        input:checked + .slider:before { background: white; transform: translateX(20px); }

        /* CHECKBOXES */
        .scroll-box { max-height: 200px; overflow-y: auto; background: #080810; border-radius: 6px; padding: 8px; border: 1px solid var(--border); margin-bottom: 14px; }
        .item-row { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 4px; font-size: 14px; }
        .item-row:hover { background: #0f0f16; }
        .item-row input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent); margin-bottom: 0; }

        /* TAGS / BLACKLIST */
        .tag-input-row { display: flex; gap: 8px; margin-bottom: 10px; }
        .tag-input-row input { margin-bottom: 0; flex: 1; }
        .tag-btn { padding: 10px 16px; background: var(--accent); color: white; border: none; border-radius: 6px; cursor: pointer; font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 14px; white-space: nowrap; }
        .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
        .tag { background: #1a1a22; border: 1px solid var(--border); padding: 4px 10px; border-radius: 4px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
        .tag-x { cursor: pointer; color: var(--muted); font-size: 12px; }
        .tag-x:hover { color: var(--accent); }

        /* STATS CARDS */
        .stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; display: flex; align-items: center; gap: 16px; }
        .stat-icon { width: 44px; height: 44px; border-radius: 8px; background: var(--accent-glow); display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 18px; flex-shrink: 0; }
        .stat-val { font-size: 26px; font-weight: 700; font-family: 'JetBrains Mono', monospace; color: var(--accent); }
        .stat-lbl { font-size: 12px; color: var(--muted); margin-top: 2px; }

        /* CASES TABLE */
        .table { width: 100%; border-collapse: collapse; }
        .table th { text-align: left; padding: 10px 14px; background: #0a0a10; color: var(--muted); font-size: 11px; letter-spacing: 1px; text-transform: uppercase; font-family: 'JetBrains Mono', monospace; border-bottom: 1px solid var(--border); }
        .table td { padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border); }
        .table tr:last-child td { border-bottom: none; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
        .badge-warn { background: #332200; color: #ffaa00; }
        .badge-kick { background: #2a1500; color: #ff6600; }
        .badge-ban { background: #220000; color: #ff3333; }
        .badge-other { background: #001a22; color: #00aaff; }

        /* SAVE BUTTON */
        .btn-save { position: fixed; bottom: 28px; right: 36px; background: var(--accent); color: white; border: none; padding: 14px 36px; border-radius: 8px; font-weight: 700; font-size: 16px; letter-spacing: 1px; cursor: pointer; font-family: 'Rajdhani', sans-serif; box-shadow: 0 4px 20px var(--accent-glow); transition: 0.2s; z-index: 100; }
        .btn-save:hover { transform: translateY(-2px); box-shadow: 0 8px 30px var(--accent-glow); }

        /* LOGIN */
        .login-wrap { margin: auto; width: 340px; background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 40px; text-align: center; }
        .login-wrap h1 { color: var(--accent); font-size: 28px; letter-spacing: 4px; margin-bottom: 28px; }
        .login-btn { width: 100%; padding: 12px; background: var(--accent); color: white; border: none; border-radius: 6px; font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 16px; cursor: pointer; letter-spacing: 1px; }

        /* SERVER SELECT */
        .server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-top: 32px; }
        .server-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 22px; cursor: pointer; transition: 0.2s; text-align: center; font-weight: 600; font-size: 16px; }
        .server-card:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-2px); }

        /* DIVIDER */
        .divider { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
        .form-group { margin-bottom: 16px; }

        /* SCROLLBAR */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    </style>
</head>
<body>

{% if not session.user %}
<div class="login-wrap">
    <h1>{{ bot_name }}</h1>
    <form method="POST">
        <label>Admin Name</label>
        <input type="text" name="user" placeholder="Username" required>
        <label>Password</label>
        <input type="password" name="pw" placeholder="••••••••" required>
        {% if login_error %}<p style="color:var(--accent);margin-bottom:12px;font-size:13px;">❌ Wrong password.</p>{% endif %}
        <button type="submit" class="login-btn">LOGIN</button>
    </form>
</div>

{% elif not session.guild_id %}
<div class="main" style="overflow-y:auto;">
    <h1 class="page-title">Select <span>Server</span></h1>
    <p style="color:var(--muted); font-size:14px;">Choose which server to manage.</p>
    <div class="server-grid">
        {% for g in guilds %}
        <div class="server-card" onclick="location.href='/select/{{ g.id }}'">
            <i class="fas fa-server" style="color:var(--accent);margin-bottom:8px;font-size:20px;display:block;"></i>
            {{ g.name }}
        </div>
        {% endfor %}
    </div>
</div>

{% else %}
<!-- SIDEBAR -->
<div class="sidebar">
    <div class="sidebar-logo">
        <h2>{{ bot_name }}</h2>
        <div class="guild">{{ guild_name }}</div>
    </div>

    <div style="overflow-y:auto; flex:1;">
        <div class="nav-section">
            <span class="nav-label">Core</span>
            <button class="nav-btn active" onclick="showPage('dash',this)"><i class="fas fa-home"></i> Dashboard</button>
            <button class="nav-btn" onclick="showPage('appearance',this)"><i class="fas fa-palette"></i> Appearance</button>
            <button class="nav-btn" onclick="showPage('sett',this)"><i class="fas fa-cog"></i> Settings</button>
        </div>
        <div class="nav-section">
            <span class="nav-label">Modules</span>
            <button class="nav-btn" onclick="showPage('welcome',this)"><i class="fas fa-door-open"></i> Welcome/Leave</button>
            <button class="nav-btn" onclick="showPage('links',this)"><i class="fas fa-link"></i> Link Filter</button>
            <button class="nav-btn" onclick="showPage('automod',this)"><i class="fas fa-robot"></i> Auto-Mod</button>
            <button class="nav-btn" onclick="showPage('mod',this)"><i class="fas fa-hammer"></i> Moderation</button>
            <button class="nav-btn" onclick="showPage('warnsys',this)"><i class="fas fa-exclamation-triangle"></i> Warn System</button>
            <button class="nav-btn" onclick="showPage('tickets',this)"><i class="fas fa-ticket-alt"></i> Tickets</button>
            <button class="nav-btn" onclick="showPage('roles',this)"><i class="fas fa-tags"></i> Roles</button>
            <button class="nav-btn" onclick="showPage('logging',this)"><i class="fas fa-list-alt"></i> Logging</button>
        </div>
        <div class="nav-section">
            <span class="nav-label">Content</span>
            <button class="nav-btn" onclick="showPage('dms',this)"><i class="fas fa-envelope"></i> DM Notifications</button>
            <button class="nav-btn" onclick="showPage('help',this)"><i class="fas fa-question"></i> Help</button>
            <button class="nav-btn" onclick="showPage('info',this)"><i class="fas fa-info-circle"></i> Info</button>
            <button class="nav-btn" onclick="showPage('creator',this)"><i class="fas fa-plus"></i> Channel Creator</button>
            <button class="nav-btn" onclick="showPage('giveaway',this)"><i class="fas fa-gift"></i> Giveaway</button>
        </div>
        <div class="nav-section">
            <span class="nav-label">Overview</span>
            <button class="nav-btn" onclick="showPage('cases',this)"><i class="fas fa-gavel"></i> Mod Cases</button>
        </div>
    </div>

    <div class="sidebar-bottom">
        <button class="nav-btn" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i> Switch Server</button>
        <button class="nav-btn" onclick="location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Logout</button>
    </div>
</div>

<!-- MAIN CONTENT -->
<div class="main">
<form method="POST">
<input type="hidden" name="action" value="save">

<!-- DASHBOARD -->
<div id="dash" class="page active">
    <h1 class="page-title">Dashboard <span>/ {{ guild_name }}</span></h1>
    <div class="grid-3" style="margin-bottom:20px;">
        <div class="stat-card">
            <div class="stat-icon"><i class="fas fa-users"></i></div>
            <div><div class="stat-val">{{ member_count }}</div><div class="stat-lbl">MEMBERS</div></div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><i class="fas fa-exclamation-triangle"></i></div>
            <div><div class="stat-val">{{ total_warns }}</div><div class="stat-lbl">WARNINGS</div></div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><i class="fas fa-gavel"></i></div>
            <div><div class="stat-val">{{ total_cases }}</div><div class="stat-lbl">MOD CASES</div></div>
        </div>
    </div>
    <div class="card">
        <div class="card-title">Module Status</div>
        {% set mod_list = [
            ('link_filter','Link Filter','fa-link'),('mod','Moderation','fa-hammer'),
            ('auto_mod','Auto-Mod','fa-robot'),('logging','Logging','fa-list-alt'),
            ('welcome_channel','Welcome Channel','fa-door-open'),('tickets','Tickets','fa-ticket-alt'),
            ('warn_system','Warn System','fa-exclamation-triangle'),('giveaway','Giveaway','fa-gift')
        ] %}
        {% for key, label, icon in mod_list %}
        <div class="toggle-row">
            <div><i class="fas {{ icon }}" style="margin-right:10px;color:var(--accent)"></i><span class="toggle-label">{{ label }}</span></div>
            <span style="font-size:12px; font-family:'JetBrains Mono',monospace; color:{% if config.modules[key].enabled == 'True' %}var(--accent){% else %}var(--muted){% endif %}">
                {% if config.modules[key].enabled == 'True' %}● ACTIVE{% else %}○ INACTIVE{% endif %}
            </span>
        </div>
        {% endfor %}
    </div>
</div>

<!-- APPEARANCE -->
<div id="appearance" class="page">
    <h1 class="page-title">Appearance <span>& Branding</span></h1>
    <div class="card">
        <div class="card-title">Bot Identity</div>
        <div class="form-group"><label>Dashboard Name</label><input type="text" name="bot_name" value="{{ bot_name }}"></div>
        <div class="form-group"><label>Accent Color</label><input type="color" name="accent_color" value="{{ accent_color }}"></div>
    </div>
    <div class="card">
        <div class="card-title">Bot Status</div>
        <div class="form-group">
            <label>Status Type</label>
            <select name="status_type">
                {% for t in ['playing','watching','listening','competing'] %}
                <option value="{{ t }}" {% if config.modules.status.type == t %}selected{% endif %}>{{ t|capitalize }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group"><label>Status Text</label><input type="text" name="status_text" value="{{ config.modules.status.text }}"></div>
    </div>
</div>

<!-- SETTINGS -->
<div id="sett" class="page">
    <h1 class="page-title">Global <span>Settings</span></h1>
    <div class="card">
        <div class="card-title">Bot Prefix</div>
        <div class="form-group"><label>Command Prefix</label><input type="text" name="prefix" value="{{ config.prefix }}"></div>
    </div>
</div>

<!-- WELCOME / LEAVE -->
<div id="welcome" class="page">
    <h1 class="page-title">Welcome <span>& Leave</span></h1>
    <div class="card">
        <div class="card-title">Welcome Channel</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Welcome Channel</span></div>
            <label class="switch"><input type="checkbox" name="wc_enabled" value="True" {% if config.modules.welcome_channel.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Channel</label>
            <select name="wc_channel_id">
                <option value="">-- Select Channel --</option>
                {% for c in channels %}<option value="{{ c.id }}" {% if c.id|string == config.modules.welcome_channel.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}
            </select>
        </div>
        <div class="form-group"><label>Message (use {user} and {server})</label><textarea name="wc_message">{{ config.modules.welcome_channel.message }}</textarea></div>
        <div class="toggle-row">
            <div><span class="toggle-label">Use Embed</span></div>
            <label class="switch"><input type="checkbox" name="wc_embed" value="True" {% if config.modules.welcome_channel.embed == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="grid-2">
            <div class="form-group"><label>Embed Title</label><input type="text" name="wc_embed_title" value="{{ config.modules.welcome_channel.embed_title }}"></div>
            <div class="form-group"><label>Embed Color</label><input type="color" name="wc_embed_color" value="{{ config.modules.welcome_channel.embed_color }}"></div>
        </div>
        <div class="toggle-row">
            <div><span class="toggle-label">Show Member Count</span></div>
            <label class="switch"><input type="checkbox" name="wc_member_count" value="True" {% if config.modules.welcome_channel.show_member_count == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
    </div>
    <div class="card">
        <div class="card-title">Leave Channel</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Leave Messages</span></div>
            <label class="switch"><input type="checkbox" name="lc_enabled" value="True" {% if config.modules.leave_channel.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Channel</label>
            <select name="lc_channel_id">
                <option value="">-- Select Channel --</option>
                {% for c in channels %}<option value="{{ c.id }}" {% if c.id|string == config.modules.leave_channel.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}
            </select>
        </div>
        <div class="form-group"><label>Message (use {user} and {server})</label><textarea name="lc_message">{{ config.modules.leave_channel.message }}</textarea></div>
    </div>
</div>

<!-- LINK FILTER -->
<div id="links" class="page">
    <h1 class="page-title">Link <span>Filter</span></h1>
    <div class="card">
        <div class="card-title">Configuration</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Link Filter</span></div>
            <label class="switch"><input type="checkbox" name="lf_enabled" value="True" {% if config.modules.link_filter.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <label>Channels to Protect</label>
        <div class="scroll-box">
            {% for c in channels %}<div class="item-row"><input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}> #{{ c.name }}</div>{% endfor %}
        </div>
        <label>Bypass Roles</label>
        <div class="scroll-box">
            {% for r in roles %}<div class="item-row"><input type="checkbox" name="lf_roles" value="{{ r.id }}" {% if r.id|string in config.modules.link_filter.roles %}checked{% endif %}> {{ r.name }}</div>{% endfor %}
        </div>
    </div>
</div>

<!-- AUTO-MOD -->
<div id="automod" class="page">
    <h1 class="page-title">Auto <span>Moderation</span></h1>
    <div class="card">
        <div class="card-title">General</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Auto-Mod</span></div>
            <label class="switch"><input type="checkbox" name="am_enabled" value="True" {% if config.modules.auto_mod.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
    </div>
    <div class="card">
        <div class="card-title">Word Blacklist</div>
        <div class="tag-input-row">
            <input type="text" id="blacklist_input" placeholder="Add word...">
            <button type="button" class="tag-btn" onclick="addTag()">Add</button>
        </div>
        <div class="tags" id="tags-container">
            {% for word in config.modules.auto_mod.blacklist %}
            <div class="tag">{{ word }}<input type="hidden" name="am_blacklist" value="{{ word }}"><span class="tag-x" onclick="removeTag(this)">✕</span></div>
            {% endfor %}
        </div>
        <div class="form-group">
            <label>Action on Blacklisted Word</label>
            <select name="am_blacklist_action">
                <option value="delete" {% if config.modules.auto_mod.blacklist_action == 'delete' %}selected{% endif %}>Delete Message</option>
                <option value="warn" {% if config.modules.auto_mod.blacklist_action == 'warn' %}selected{% endif %}>Delete + Warn</option>
            </select>
        </div>
    </div>
    <div class="card">
        <div class="card-title">Filters</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Caps Lock Filter</span><div class="toggle-sub">Block messages with too many caps</div></div>
            <label class="switch"><input type="checkbox" name="am_caps_filter" value="True" {% if config.modules.auto_mod.caps_filter == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Caps Threshold (%)</label><input type="number" name="am_caps_threshold" value="{{ config.modules.auto_mod.caps_threshold }}" min="10" max="100"></div>
        <hr class="divider">
        <div class="toggle-row">
            <div><span class="toggle-label">Anti-Spam Filter</span><div class="toggle-sub">Block repeated rapid messages</div></div>
            <label class="switch"><input type="checkbox" name="am_spam_filter" value="True" {% if config.modules.auto_mod.spam_filter == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="grid-2">
            <div class="form-group"><label>Max Messages</label><input type="number" name="am_spam_count" value="{{ config.modules.auto_mod.spam_count }}"></div>
            <div class="form-group"><label>Per X Seconds</label><input type="number" name="am_spam_seconds" value="{{ config.modules.auto_mod.spam_seconds }}"></div>
        </div>
    </div>
</div>

<!-- MODERATION -->
<div id="mod" class="page">
    <h1 class="page-title">Moderation <span>Settings</span></h1>
    <div class="card">
        <div class="card-title">Configuration</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Moderation Commands</span></div>
            <label class="switch"><input type="checkbox" name="m_enabled" value="True" {% if config.modules.mod.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <label>Staff Roles (can use mod commands)</label>
        <div class="scroll-box">
            {% for r in roles %}<div class="item-row"><input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}> {{ r.name }}</div>{% endfor %}
        </div>
    </div>
</div>

<!-- WARN SYSTEM -->
<div id="warnsys" class="page">
    <h1 class="page-title">Warning <span>System</span></h1>
    <div class="card">
        <div class="card-title">Auto-Punishment</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Warn Thresholds</span></div>
            <label class="switch"><input type="checkbox" name="ws_enabled" value="True" {% if config.modules.warn_system.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="grid-2">
            <div class="form-group"><label>Warns Before Kick (0 = off)</label><input type="number" name="ws_kick" value="{{ config.modules.warn_system.warn_threshold_kick }}" min="0"></div>
            <div class="form-group"><label>Warns Before Ban (0 = off)</label><input type="number" name="ws_ban" value="{{ config.modules.warn_system.warn_threshold_ban }}" min="0"></div>
        </div>
    </div>
</div>

<!-- TICKETS -->
<div id="tickets" class="page">
    <h1 class="page-title">Ticket <span>System</span></h1>
    <div class="card">
        <div class="card-title">Configuration</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Ticket System</span></div>
            <label class="switch"><input type="checkbox" name="tc_enabled" value="True" {% if config.modules.tickets.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="grid-2">
            <div class="form-group"><label>Ticket Category</label>
                <select name="tc_category_id">
                    <option value="">-- Select Category --</option>
                    {% for cat in categories %}<option value="{{ cat.id }}" {% if cat.id|string == config.modules.tickets.category_id %}selected{% endif %}>{{ cat.name }}</option>{% endfor %}
                </select>
            </div>
            <div class="form-group"><label>Support Role</label>
                <select name="tc_support_role_id">
                    <option value="">-- Select Role --</option>
                    {% for r in roles %}<option value="{{ r.id }}" {% if r.id|string == config.modules.tickets.support_role_id %}selected{% endif %}>{{ r.name }}</option>{% endfor %}
                </select>
            </div>
        </div>
        <div class="form-group"><label>Button Label</label><input type="text" name="tc_button_label" value="{{ config.modules.tickets.button_label }}"></div>
        <div class="form-group"><label>Welcome Message (use {user})</label><textarea name="tc_open_message">{{ config.modules.tickets.open_message }}</textarea></div>
        <p style="color:var(--muted);font-size:13px;margin-top:-8px;">Use <code>!setticket</code> in your server to deploy the ticket panel.</p>
    </div>
</div>

<!-- ROLES -->
<div id="roles" class="page">
    <h1 class="page-title">Role <span>Management</span></h1>
    <div class="card">
        <div class="card-title">Auto Role on Join</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Auto Role</span></div>
            <label class="switch"><input type="checkbox" name="ar_enabled" value="True" {% if config.modules.auto_role.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Role to Assign</label>
            <select name="ar_role_id">
                <option value="">-- Select Role --</option>
                {% for r in roles %}<option value="{{ r.id }}" {% if r.id|string == config.modules.auto_role.role_id %}selected{% endif %}>{{ r.name }}</option>{% endfor %}
            </select>
        </div>
    </div>
</div>

<!-- LOGGING -->
<div id="logging" class="page">
    <h1 class="page-title">Action <span>Logging</span></h1>
    <div class="card">
        <div class="card-title">Configuration</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Logging</span></div>
            <label class="switch"><input type="checkbox" name="log_enabled" value="True" {% if config.modules.logging.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Log Channel</label>
            <select name="log_channel_id">
                <option value="">-- Select Channel --</option>
                {% for c in channels %}<option value="{{ c.id }}" {% if c.id|string == config.modules.logging.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}
            </select>
        </div>
        <hr class="divider">
        {% set log_opts = [
            ('log_deletes','Log Deleted Messages','fa-trash'),
            ('log_edits','Log Edited Messages','fa-edit'),
            ('log_joins','Log Member Joins','fa-user-plus'),
            ('log_leaves','Log Member Leaves','fa-user-minus'),
            ('log_bans','Log Bans','fa-ban'),
            ('log_roles','Log Role Changes','fa-tags'),
            ('log_mods','Log Mod Actions','fa-hammer')
        ] %}
        {% for key, label, icon in log_opts %}
        <div class="toggle-row">
            <div><i class="fas {{ icon }}" style="margin-right:10px;color:var(--muted)"></i><span class="toggle-label">{{ label }}</span></div>
            <label class="switch"><input type="checkbox" name="{{ key }}" value="True" {% if config.modules.logging[key] == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        {% endfor %}
    </div>
</div>

<!-- DM NOTIFICATIONS -->
<div id="dms" class="page">
    <h1 class="page-title">DM <span>Notifications</span></h1>
    <p style="color:var(--muted);font-size:13px;margin-bottom:20px;">Use <code>{server}</code> and <code>{reason}</code> as placeholders.</p>
    {% set dm_fields = [
        ('dm_w','welcome','Welcome DM'),('dm_k','kick','Kick DM'),
        ('dm_b','ban','Ban DM'),('dm_t','timeout','Timeout DM'),
        ('dm_warn','warn','Warn DM'),('dm_ub','unban','Unban DM'),
        ('dm_m','mute','Mute DM')
    ] %}
    {% set dm_keys = {
        'dm_w':'welcome','dm_k':'kick','dm_b':'ban','dm_t':'timeout',
        'dm_warn':'warn','dm_ub':'unban','dm_m':'mute'
    } %}
    {% for prefix_key, dm_key, label in dm_fields %}
    <div class="card">
        <div class="card-title">{{ label }}</div>
        <div class="toggle-row">
            <div><span class="toggle-label">Enable {{ label }}</span></div>
            <label class="switch"><input type="checkbox" name="{{ prefix_key }}_enabled" value="True" {% if config.modules.dms[dm_key+'_enabled'] == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Message</label><textarea name="{{ prefix_key }}_msg">{{ config.modules.dms[dm_key+'_msg'] }}</textarea></div>
    </div>
    {% endfor %}
</div>

<!-- HELP -->
<div id="help" class="page">
    <h1 class="page-title">Help <span>Module</span></h1>
    <div class="card">
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Help Module</span></div>
            <label class="switch"><input type="checkbox" name="h_enabled" value="True" {% if config.modules.help.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Command Aliases (comma-separated)</label><input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}"></div>
        <div class="form-group"><label>Response Text</label><textarea name="h_text">{{ config.modules.help.text }}</textarea></div>
    </div>
</div>

<!-- INFO -->
<div id="info" class="page">
    <h1 class="page-title">Info <span>Module</span></h1>
    <div class="card">
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Info Module</span></div>
            <label class="switch"><input type="checkbox" name="i_enabled" value="True" {% if config.modules.info.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <div class="form-group"><label>Command Aliases (comma-separated)</label><input type="text" name="i_aliases" value="{{ config.modules.info.aliases }}"></div>
        <div class="form-group"><label>Response Text</label><textarea name="i_text">{{ config.modules.info.text }}</textarea></div>
    </div>
</div>

<!-- CHANNEL CREATOR -->
<div id="creator" class="page">
    <h1 class="page-title">Channel <span>Creator</span></h1>
    <div class="card">
        <div class="form-group"><label>Channel Name</label><input type="text" name="c_name" placeholder="my-channel"></div>
        <div class="form-group"><label>Category ID (optional)</label><input type="text" name="c_cat" placeholder="000000000000000000"></div>
        <div class="form-group"><label>Font Style</label>
            <select name="c_font">
                <option value="normal">Normal</option>
                <option value="gothic">Gothic 𝔰𝔱𝔶𝔩𝔢</option>
                <option value="fancy">Fancy 𝓼𝓽𝔂𝓵𝓮</option>
                <option value="smallcaps">Small Caps ꜱᴛʏʟᴇ</option>
            </select>
        </div>
        <button type="submit" name="action" value="create_chan" style="background:var(--accent);color:white;border:none;padding:12px 28px;border-radius:6px;font-family:'Rajdhani',sans-serif;font-weight:700;font-size:15px;cursor:pointer;letter-spacing:1px;">Create Channel</button>
    </div>
</div>

<!-- GIVEAWAY -->
<div id="giveaway" class="page">
    <h1 class="page-title">Giveaway <span>System</span></h1>
    <div class="card">
        <div class="toggle-row">
            <div><span class="toggle-label">Enable Giveaway Command</span></div>
            <label class="switch"><input type="checkbox" name="ga_enabled" value="True" {% if config.modules.giveaway.enabled == "True" %}checked{% endif %}><span class="slider"></span></label>
        </div>
        <br>
        <p style="color:var(--muted);font-size:13px;">Use <code>!giveaway 30m Prize Name</code> in your server to start a giveaway.<br>Duration units: <code>s</code> (seconds), <code>m</code> (minutes), <code>h</code> (hours), <code>d</code> (days).</p>
    </div>
</div>

<!-- MOD CASES -->
<div id="cases" class="page">
    <h1 class="page-title">Mod <span>Cases</span></h1>
    <div class="card">
        <div class="card-title">Recent Cases</div>
        {% if mod_cases %}
        <table class="table">
            <thead><tr><th>#</th><th>Action</th><th>Target</th><th>Moderator</th><th>Reason</th><th>Date</th></tr></thead>
            <tbody>
            {% for c in mod_cases %}
            <tr>
                <td style="font-family:'JetBrains Mono',monospace;color:var(--muted)">#{{ c.case }}</td>
                <td><span class="badge {% if c.action == 'BAN' %}badge-ban{% elif c.action == 'KICK' %}badge-kick{% elif c.action == 'WARN' %}badge-warn{% else %}badge-other{% endif %}">{{ c.action }}</span></td>
                <td>{{ c.target }}</td>
                <td>{{ c.mod }}</td>
                <td style="color:var(--muted)">{{ c.reason }}</td>
                <td style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--muted)">{{ c.timestamp[:10] }}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color:var(--muted);text-align:center;padding:20px;">No mod cases yet.</p>
        {% endif %}
    </div>
</div>

<button type="submit" class="btn-save">SAVE</button>
</form>
</div>
{% endif %}

<script>
function showPage(id, btn) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    btn.classList.add('active');
}

function addTag() {
    const input = document.getElementById('blacklist_input');
    const word = input.value.trim();
    if (!word) return;
    const container = document.getElementById('tags-container');
    const tag = document.createElement('div');
    tag.className = 'tag';
    tag.innerHTML = word + '<input type="hidden" name="am_blacklist" value="' + word + '"><span class="tag-x" onclick="removeTag(this)">✕</span>';
    container.appendChild(tag);
    input.value = '';
}

function removeTag(el) {
    el.parentElement.remove();
}

document.getElementById('blacklist_input')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); addTag(); }
});
</script>
</body>
</html>
"""

# --- FLASK ROUTES ---
@app.route("/", methods=["GET", "POST"])
def index():
    login_error = False
    if request.method == "POST":
        if "pw" in request.form:
            if request.form.get("pw") == os.environ.get("DASHBOARD_PASSWORD", "10"):
                session['user'] = request.form.get("user")
                return redirect("/")
            else:
                login_error = True

        action = request.form.get("action")

        if action == "create_chan" and 'guild_id' in session:
            name = format_font(request.form.get("c_name", "channel"), request.form.get("c_font", "normal"))
            cat_id = request.form.get("c_cat", "")
            async def run_c():
                g = bot.get_guild(int(session['guild_id']))
                cat = g.get_channel(int(cat_id)) if cat_id and cat_id.isdigit() else None
                await g.create_text_channel(name, category=cat)
            asyncio.run_coroutine_threadsafe(run_c(), bot.loop)
            return redirect("/")

        if action == "save" and 'guild_id' in session:
            def cb(v): return "True" if v else "False"
            updates = {
                "prefix": request.form.get("prefix"),
                "bot_name": request.form.get("bot_name"),
                "accent_color": request.form.get("accent_color"),
                "modules.status.type": request.form.get("status_type"),
                "modules.status.text": request.form.get("status_text"),
                # Welcome/Leave
                "modules.welcome_channel.enabled": cb(request.form.get("wc_enabled")),
                "modules.welcome_channel.channel_id": request.form.get("wc_channel_id", ""),
                "modules.welcome_channel.message": request.form.get("wc_message"),
                "modules.welcome_channel.embed": cb(request.form.get("wc_embed")),
                "modules.welcome_channel.embed_title": request.form.get("wc_embed_title"),
                "modules.welcome_channel.embed_color": request.form.get("wc_embed_color"),
                "modules.welcome_channel.show_member_count": cb(request.form.get("wc_member_count")),
                "modules.leave_channel.enabled": cb(request.form.get("lc_enabled")),
                "modules.leave_channel.channel_id": request.form.get("lc_channel_id", ""),
                "modules.leave_channel.message": request.form.get("lc_message"),
                # Link Filter
                "modules.link_filter.enabled": cb(request.form.get("lf_enabled")),
                "modules.link_filter.chans": request.form.getlist("lf_chans"),
                "modules.link_filter.roles": request.form.getlist("lf_roles"),
                # Auto-Mod
                "modules.auto_mod.enabled": cb(request.form.get("am_enabled")),
                "modules.auto_mod.blacklist": request.form.getlist("am_blacklist"),
                "modules.auto_mod.blacklist_action": request.form.get("am_blacklist_action"),
                "modules.auto_mod.caps_filter": cb(request.form.get("am_caps_filter")),
                "modules.auto_mod.caps_threshold": request.form.get("am_caps_threshold"),
                "modules.auto_mod.spam_filter": cb(request.form.get("am_spam_filter")),
                "modules.auto_mod.spam_count": request.form.get("am_spam_count"),
                "modules.auto_mod.spam_seconds": request.form.get("am_spam_seconds"),
                # Mod
                "modules.mod.enabled": cb(request.form.get("m_enabled")),
                "modules.mod.roles": request.form.getlist("mod_roles"),
                # Warn System
                "modules.warn_system.enabled": cb(request.form.get("ws_enabled")),
                "modules.warn_system.warn_threshold_kick": request.form.get("ws_kick"),
                "modules.warn_system.warn_threshold_ban": request.form.get("ws_ban"),
                # Logging
                "modules.logging.enabled": cb(request.form.get("log_enabled")),
                "modules.logging.channel_id": request.form.get("log_channel_id", ""),
                "modules.logging.log_deletes": cb(request.form.get("log_deletes")),
                "modules.logging.log_edits": cb(request.form.get("log_edits")),
                "modules.logging.log_joins": cb(request.form.get("log_joins")),
                "modules.logging.log_leaves": cb(request.form.get("log_leaves")),
                "modules.logging.log_bans": cb(request.form.get("log_bans")),
                "modules.logging.log_roles": cb(request.form.get("log_roles")),
                "modules.logging.log_mods": cb(request.form.get("log_mods")),
                # Tickets
                "modules.tickets.enabled": cb(request.form.get("tc_enabled")),
                "modules.tickets.category_id": request.form.get("tc_category_id", ""),
                "modules.tickets.support_role_id": request.form.get("tc_support_role_id", ""),
                "modules.tickets.button_label": request.form.get("tc_button_label"),
                "modules.tickets.open_message": request.form.get("tc_open_message"),
                # Auto Role
                "modules.auto_role.enabled": cb(request.form.get("ar_enabled")),
                "modules.auto_role.role_id": request.form.get("ar_role_id", ""),
                # DMs
                "modules.dms.welcome_enabled": cb(request.form.get("dm_w_enabled")),
                "modules.dms.welcome_msg": request.form.get("dm_w_msg"),
                "modules.dms.kick_enabled": cb(request.form.get("dm_k_enabled")),
                "modules.dms.kick_msg": request.form.get("dm_k_msg"),
                "modules.dms.ban_enabled": cb(request.form.get("dm_b_enabled")),
                "modules.dms.ban_msg": request.form.get("dm_b_msg"),
                "modules.dms.timeout_enabled": cb(request.form.get("dm_t_enabled")),
                "modules.dms.timeout_msg": request.form.get("dm_t_msg"),
                "modules.dms.warn_enabled": cb(request.form.get("dm_warn_enabled")),
                "modules.dms.warn_msg": request.form.get("dm_warn_msg"),
                "modules.dms.unban_enabled": cb(request.form.get("dm_ub_enabled")),
                "modules.dms.unban_msg": request.form.get("dm_ub_msg"),
                "modules.dms.mute_enabled": cb(request.form.get("dm_m_enabled")),
                "modules.dms.mute_msg": request.form.get("dm_m_msg"),
                # Help/Info
                "modules.help.enabled": cb(request.form.get("h_enabled")),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.info.enabled": cb(request.form.get("i_enabled")),
                "modules.info.aliases": request.form.get("i_aliases"),
                "modules.info.text": request.form.get("i_text"),
                # Giveaway
                "modules.giveaway.enabled": cb(request.form.get("ga_enabled")),
            }
            config_col.update_one({"guild_id": session['guild_id']}, {"$set": updates})

            # Update bot status live
            status_text = request.form.get("status_text", "Lava Network")
            status_type = request.form.get("status_type", "playing")
            async def update_status():
                activity_map = {
                    'playing': discord.Game(name=status_text),
                    'watching': discord.Activity(type=discord.ActivityType.watching, name=status_text),
                    'listening': discord.Activity(type=discord.ActivityType.listening, name=status_text),
                    'competing': discord.Activity(type=discord.ActivityType.competing, name=status_text)
                }
                await bot.change_presence(activity=activity_map.get(status_type, discord.Game(name=status_text)))
            asyncio.run_coroutine_threadsafe(update_status(), bot.loop)
            return redirect("/")

    guilds = [{"name": g.name, "id": str(g.id)} for g in bot.guilds]
    conf, roles, channels, categories, guild_name = None, [], [], [], ""
    member_count = total_warns = total_cases = 0
    mod_cases = []
    bot_name = "LAVA"
    accent_color = "#ff3333"

    if 'guild_id' in session:
        conf = get_guild_config(session['guild_id'])
        bot_name = conf.get('bot_name', 'LAVA')
        accent_color = conf.get('accent_color', '#ff3333')
        g = bot.get_guild(int(session['guild_id']))
        if g:
            guild_name = g.name
            member_count = g.member_count
            roles = [{"id": r.id, "name": r.name} for r in g.roles if not r.managed and r.name != "@everyone"]
            channels = [{"id": c.id, "name": c.name} for c in g.text_channels]
            categories = [{"id": c.id, "name": c.name} for c in g.categories]
        total_warns = warns_col.count_documents({"guild_id": session['guild_id']})
        total_cases = cases_col.count_documents({"guild_id": session['guild_id']})
        mod_cases = list(cases_col.find({"guild_id": session['guild_id']}).sort("case", -1).limit(25))

    return render_template_string(
        HTML_TEMPLATE,
        config=conf, guilds=guilds, roles=roles, channels=channels,
        categories=categories, guild_name=guild_name, bot_name=bot_name,
        accent_color=accent_color, member_count=member_count,
        total_warns=total_warns, total_cases=total_cases, mod_cases=mod_cases,
        login_error=login_error
    )

@app.route("/select/<guild_id>")
def select_guild(guild_id):
    session['guild_id'] = guild_id
    return redirect("/")

@app.route("/change_server")
def change_server():
    session.pop('guild_id', None)
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

def run():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
