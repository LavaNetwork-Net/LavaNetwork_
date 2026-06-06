import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta, datetime
import re

# --- DATABASE ---
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['lavabot_db']
config_col = db['guild_configs']
warns_col = db['warnings']
cases_col = db['mod_cases']
counting_col = db['counting']

def get_guild_config(guild_id):
    conf = config_col.find_one({"guild_id": str(guild_id)})
    default_modules = {
        "link_filter": {"enabled": "False", "chans": [], "roles": []},
        "mod": {"enabled": "False", "roles": []},
        "help": {"enabled": "False", "aliases": "help", "text": "Support"},
        "info": {"enabled": "False", "aliases": "info", "text": "Info"},
        "dms": {
            "welcome_enabled": "False", "welcome_msg": "Welcome to {server}!",
            "kick_enabled": "False", "kick_msg": "You were kicked from {server}.",
            "ban_enabled": "False", "ban_msg": "You were banned from {server}.",
            "timeout_enabled": "False", "timeout_msg": "You were timed out in {server}.",
            "warn_enabled": "False", "warn_msg": "You received a warning in {server}: {reason}",
            "unban_enabled": "False", "unban_msg": "You were unbanned from {server}.",
            "mute_enabled": "False", "mute_msg": "You were muted in {server}."
        },
        "welcome_channel": {
            "enabled": "False", "channel_id": "", "message": "Welcome {user} to {server}!",
            "embed": "False", "embed_color": "#ff3333", "embed_title": "Welcome!",
            "show_member_count": "True"
        },
        "leave_channel": {"enabled": "False", "channel_id": "", "message": "{user} left {server}."},
        "logging": {
            "enabled": "False", "channel_id": "",
            "log_deletes": "True", "log_edits": "True",
            "log_joins": "True", "log_leaves": "True",
            "log_bans": "True", "log_roles": "True", "log_mods": "True"
        },
        "auto_mod": {
            "enabled": "False", "blacklist": [], "blacklist_action": "delete",
            "caps_filter": "False", "caps_threshold": "70",
            "spam_filter": "False", "spam_count": "5", "spam_seconds": "5"
        },
        "auto_role": {"enabled": "False", "role_id": ""},
        "warn_system": {"enabled": "False", "warn_threshold_kick": "0", "warn_threshold_ban": "0"},
        "message_emojis": {
            "link_filter": "🚫",
            "auto_mod_blacklist": "⚠️",
            "auto_mod_caps": "⚠️",
            "auto_mod_spam": "⌛",
            "counting_fail": "❌",
            "counting_success": "✅",
            "honeypot": "🚨",
            "mod_action": "🌋",
            "help_info": "ℹ️"
        },
        "giveaway": {"enabled": "False"},
        "tickets": {
            "enabled": "False",
            "support_role_id": "",
            "categories": {
                "support": {"enabled": "True", "label": "Support", "emoji": "🎫", "category_id": "", "description": "General support"},
                "store": {"enabled": "True", "label": "Store", "emoji": "🛒", "category_id": "", "description": "Purchase help"},
                "apply": {"enabled": "True", "label": "Apply", "emoji": "📋", "category_id": "", "description": "Staff applications"},
                "report": {"enabled": "True", "label": "User Report", "emoji": "🚨", "category_id": "", "description": "Report a user"},
                "bug": {"enabled": "True", "label": "Bug Report", "emoji": "🐛", "category_id": "", "description": "Report a bug"},
                "beta": {"enabled": "True", "label": "Beta tester", "emoji": "🌋", "category_id": "", "description": "Apply for Beta Tester"}
            }
        },
        "counting": {"enabled": "False", "channel_id": ""},
        "honeypot": {"enabled": "False", "channel_id": ""},
        "status": {"type": "playing", "text": "Lava Network"}
    }

    if not conf:
        conf = {"guild_id": str(guild_id), "prefix": "!", "bot_name": "LAVA", "accent_color": "#ff3333", "modules": default_modules}
        config_col.insert_one(conf)
    else:
        updated = False
        if "modules" not in conf:
            conf["modules"] = default_modules; updated = True
        else:
            for mod_name, mod_data in default_modules.items():
                if mod_name not in conf["modules"]:
                    conf["modules"][mod_name] = mod_data; updated = True
                elif isinstance(mod_data, dict):
                    for key, val in mod_data.items():
                        if key not in conf["modules"][mod_name]:
                            conf["modules"][mod_name][key] = val; updated = True
        for field in ["bot_name", "accent_color"]:
            if field not in conf:
                conf[field] = "LAVA" if field == "bot_name" else "#ff3333"; updated = True
        if updated:
            config_col.replace_one({"guild_id": str(guild_id)}, conf)
    return conf

# --- BOT SETUP ---
intents = discord.Intents.all()
async def get_prefix(bot, message):
    if not message.guild: return "!"
    return get_guild_config(message.guild.id).get("prefix", "!")

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)
spam_tracker = {}

# --- HELPERS ---
async def send_user_dm(member, msg_template, guild_name, extra={}):
    try:
        content = msg_template.replace("{server}", guild_name)
        for k, v in extra.items(): content = content.replace(f"{{{k}}}", str(v))
        await member.send(content)
    except: pass

async def log_action(guild, conf, description, color=0xff3333, fields=None):
    lc = conf['modules'].get('logging', {})
    if lc.get('enabled') != "True" or not lc.get('channel_id'): return
    ch = guild.get_channel(int(lc['channel_id']))
    if not ch: return
    embed = discord.Embed(description=description, color=color, timestamp=datetime.utcnow())
    if fields:
        for name, value, inline in fields: embed.add_field(name=name, value=value[:1024], inline=inline)
    await ch.send(embed=embed)

async def add_mod_case(guild_id, action, mod, target, reason):
    n = cases_col.count_documents({"guild_id": str(guild_id)}) + 1
    cases_col.insert_one({"guild_id": str(guild_id), "case": n, "action": action, "mod": str(mod), "target": str(target), "reason": reason or "No reason", "timestamp": datetime.utcnow().isoformat()})
    return n

def has_mod_perms(ctx, conf):
    return any(str(r.id) in conf['modules']['mod']['roles'] for r in ctx.author.roles) or ctx.author.guild_permissions.administrator

async def _add_warn(guild, member, mod, reason, conf):
    warns_col.insert_one({"guild_id": str(guild.id), "user_id": str(member.id), "user_name": str(member), "mod": str(mod), "reason": reason, "timestamp": datetime.utcnow().isoformat()})
    total = warns_col.count_documents({"guild_id": str(guild.id), "user_id": str(member.id)})
    dmc = conf['modules']['dms']
    if dmc.get("warn_enabled") == "True": await send_user_dm(member, dmc["warn_msg"], guild.name, {"reason": reason})
    ws = conf['modules'].get('warn_system', {})
    kt = int(ws.get('warn_threshold_kick', 0)); bt = int(ws.get('warn_threshold_ban', 0))
    if bt > 0 and total >= bt:
        if dmc.get("ban_enabled") == "True": await send_user_dm(member, dmc["ban_msg"], guild.name)
        await member.ban(reason=f"Auto-ban: {total} warnings")
    elif kt > 0 and total >= kt:
        if dmc.get("kick_enabled") == "True": await send_user_dm(member, dmc["kick_msg"], guild.name)
        await member.kick(reason=f"Auto-kick: {total} warnings")
    return total

# --- STATUS HELPER ---
async def _set_status(stype, text):
    am = {'playing': discord.Game(name=text), 'watching': discord.Activity(type=discord.ActivityType.watching, name=text), 'listening': discord.Activity(type=discord.ActivityType.listening, name=text), 'competing': discord.Activity(type=discord.ActivityType.competing, name=text)}
    await bot.change_presence(activity=am.get(stype, discord.Game(name=text)))

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f"Ready: {bot.user}")
    for guild in bot.guilds:
        conf = get_guild_config(guild.id)
        sc = conf['modules'].get('status', {})
        await _set_status(sc.get('type', 'playing'), sc.get('text', 'Lava Network'))
        break

@bot.event
async def on_member_join(member):
    conf = get_guild_config(member.guild.id)
    dmc = conf['modules']['dms']
    if dmc.get("welcome_enabled") == "True": await send_user_dm(member, dmc["welcome_msg"], member.guild.name, {"user": member.name})
    wc = conf['modules'].get('welcome_channel', {})
    if wc.get('enabled') == "True" and wc.get('channel_id'):
        ch = member.guild.get_channel(int(wc['channel_id']))
        if ch:
            msg = wc.get('message', 'Welcome {user}!').replace("{user}", member.mention).replace("{server}", member.guild.name)
            if wc.get('show_member_count') == "True": msg += f"\nWe now have **{member.guild.member_count}** members!"
            if wc.get('embed') == "True":
                c = int(wc.get('embed_color', '#ff3333').lstrip('#'), 16)
                e = discord.Embed(title=wc.get('embed_title', 'Welcome!'), description=msg, color=c)
                e.set_thumbnail(url=member.display_avatar.url)
                await ch.send(embed=e)
            else: await ch.send(msg)
    ar = conf['modules'].get('auto_role', {})
    if ar.get('enabled') == "True" and ar.get('role_id'):
        role = member.guild.get_role(int(ar['role_id']))
        if role:
            try: await member.add_roles(role)
            except: pass
    if conf['modules'].get('logging', {}).get('log_joins') == "True":
        await log_action(member.guild, conf, f"✅ **{member}** joined.", 0x00ff88)

@bot.event
async def on_member_remove(member):
    conf = get_guild_config(member.guild.id)
    lc = conf['modules'].get('leave_channel', {})
    if lc.get('enabled') == "True" and lc.get('channel_id'):
        ch = member.guild.get_channel(int(lc['channel_id']))
        if ch:
            msg = lc.get('message', '{user} left.').replace("{user}", str(member)).replace("{server}", member.guild.name)
            await ch.send(msg)
    if conf['modules'].get('logging', {}).get('log_leaves') == "True":
        await log_action(member.guild, conf, f"❌ **{member}** left.", 0xff6600)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    conf = get_guild_config(message.guild.id)
    if conf['modules'].get('logging', {}).get('log_deletes') == "True":
        await log_action(message.guild, conf, f"🗑️ Message by **{message.author}** deleted in {message.channel.mention}", 0xffcc00, [("Content", message.content or "(empty)", False)])

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content: return
    conf = get_guild_config(before.guild.id)
    if conf['modules'].get('logging', {}).get('log_edits') == "True":
        await log_action(before.guild, conf, f"✏️ Message edited by **{before.author}** in {before.channel.mention}", 0x3399ff, [("Before", before.content or "(empty)", False), ("After", after.content or "(empty)", False)])

@bot.event
async def on_member_update(before, after):
    if before.roles == after.roles: return
    conf = get_guild_config(before.guild.id)
    if conf['modules'].get('logging', {}).get('log_roles') == "True":
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added: await log_action(before.guild, conf, f"🎭 **{before}** gained **{added[0].name}**", 0x00ccff)
        if removed: await log_action(before.guild, conf, f"🎭 **{before}** lost **{removed[0].name}**", 0xff6666)

@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild: return
    conf = get_guild_config(message.guild.id)
    prefix = conf.get("prefix", "!")

    # COUNTING
    cm = conf['modules'].get('counting', {})
    if cm.get('enabled') == "True" and cm.get('channel_id') and str(message.channel.id) == cm['channel_id']:
        state = counting_col.find_one({"guild_id": str(message.guild.id)}) or {"count": 0, "last_user": None}
        try: number = int(message.content.strip())
        except:
            await message.add_reaction("❌")
            emoji = conf['modules'].get('message_emojis', {}).get('counting_fail', '❌')
            await message.channel.send(f"{message.author.mention} {emoji} Only numbers! Count resets to **0**.", delete_after=5)
            counting_col.update_one({"guild_id": str(message.guild.id)}, {"$set": {"count": 0, "last_user": None}}, upsert=True)
            return
        expected = state.get('count', 0) + 1
        last_user = state.get('last_user')
        if number != expected or str(message.author.id) == last_user:
            await message.add_reaction("❌")
            reason = "Wrong number!" if number != expected else "You can't count twice in a row!"
            emoji = conf['modules'].get('message_emojis', {}).get('counting_fail', '❌')
            await message.channel.send(f"{message.author.mention} {emoji} {reason} Next: **1**.", delete_after=6)
            counting_col.update_one({"guild_id": str(message.guild.id)}, {"$set": {"count": 0, "last_user": None}}, upsert=True)
        else:
            await message.add_reaction("✅")
            emoji = conf['modules'].get('message_emojis', {}).get('counting_success', '✅')
            await message.channel.send(f"{message.author.mention} {emoji} Nice! Count is now **{number}**.", delete_after=5)
            counting_col.update_one({"guild_id": str(message.guild.id)}, {"$set": {"count": number, "last_user": str(message.author.id)}}, upsert=True)
        return

    # LINK FILTER
    lf = conf['modules'].get('link_filter', {})
    if lf.get('enabled') == "True" and str(message.channel.id) in lf.get('chans', []):
        user_roles = [str(r.id) for r in message.author.roles]
        bypass = any(rid in lf.get('roles', []) for rid in user_roles) or message.author.guild_permissions.administrator
        if not bypass and re.search(r'http[s]?://', message.content.lower()):
            await message.delete()
            emoji = conf['modules'].get('message_emojis', {}).get('link_filter', '🚫')
            await message.channel.send(f"{message.author.mention} {emoji} links not allowed here.", delete_after=5)
            return

    # HONEYPOT
    hp = conf['modules'].get('honeypot', {})
    if hp.get('enabled') == "True" and hp.get('channel_id') and str(message.channel.id) == hp['channel_id']:
        if not message.author.bot and not message.author.guild_permissions.administrator:
            await message.delete()
            try:
                await message.author.send(f"You were soft kicked from {message.guild.name} for typing in a honeypot channel.")
            except: pass
            emoji = conf['modules'].get('message_emojis', {}).get('honeypot', '🚨')
            await message.channel.send(f"{message.author.mention} {emoji} You have been soft kicked for sending a message in this honeypot channel.", delete_after=8)
            await message.author.kick(reason="Honeypot channel violation")
        return

    # AUTO-MOD
    am = conf['modules'].get('auto_mod', {})
    if am.get('enabled') == "True" and not message.author.guild_permissions.administrator:
        cl = message.content.lower()
        for word in am.get('blacklist', []):
            if word.lower() in cl:
                await message.delete()
                if am.get('blacklist_action') == 'warn': await _add_warn(message.guild, message.author, bot.user, "Auto-Mod: Blacklisted word", conf)
                emoji = conf['modules'].get('message_emojis', {}).get('auto_mod_blacklist', '⚠️')
                await message.channel.send(f"{message.author.mention} {emoji} message removed.", delete_after=5)
                return
        if am.get('caps_filter') == "True" and len(message.content) > 10:
            caps = sum(1 for c in message.content if c.isupper())
            if caps / len(message.content) * 100 >= int(am.get('caps_threshold', 70)):
                await message.delete()
                emoji = conf['modules'].get('message_emojis', {}).get('auto_mod_caps', '⚠️')
                await message.channel.send(f"{message.author.mention} {emoji} too many caps.", delete_after=5)
                return
        if am.get('spam_filter') == "True":
            key = f"{message.guild.id}:{message.author.id}"; now = datetime.utcnow().timestamp()
            sc = int(am.get('spam_count', 5)); ss = int(am.get('spam_seconds', 5))
            spam_tracker.setdefault(key, [])
            spam_tracker[key] = [t for t in spam_tracker[key] if now - t < ss]
            spam_tracker[key].append(now)
            if len(spam_tracker[key]) >= sc:
                await message.delete()
                emoji = conf['modules'].get('message_emojis', {}).get('auto_mod_spam', '⌛')
                await message.channel.send(f"{message.author.mention} {emoji} slow down!", delete_after=5)
                spam_tracker[key] = []; return

    # HELP / INFO
    for mod in ['help', 'info']:
        md = conf['modules'][mod]
        if md['enabled'] == "True":
            aliases = [a.strip().lower() for a in md.get("aliases", mod).split(",")]
            if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
                emoji = conf['modules'].get('message_emojis', {}).get('help_info', 'ℹ️')
                await message.channel.send(f"{emoji} {md.get('text')}"); return

    await bot.process_commands(message)

# --- COUNTING COMMAND ---
@bot.command()
async def setcounting(ctx):
    if not ctx.author.guild_permissions.administrator: return
    config_col.update_one({"guild_id": str(ctx.guild.id)}, {"$set": {"modules.counting.enabled": "True", "modules.counting.channel_id": str(ctx.channel.id)}})
    counting_col.update_one({"guild_id": str(ctx.guild.id)}, {"$set": {"count": 0, "last_user": None}}, upsert=True)
    await ctx.send(f"✅ Counting set to {ctx.channel.mention}! Start with **1**.")

@bot.command()
async def honeypot(ctx, arg: str = None):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    if arg and arg.lower() in ["off", "disable", "remove"]:
        hp = conf['modules'].get('honeypot', {})
        if hp.get('enabled') == "True" and hp.get('channel_id') == str(ctx.channel.id):
            config_col.update_one({"guild_id": str(ctx.guild.id)}, {"$set": {"modules.honeypot.enabled": "False", "modules.honeypot.channel_id": ""}})
            await ctx.send("✅ Honeypot disabled for this channel.")
        else:
            await ctx.send("Honeypot is not enabled in this channel.")
        return

    config_col.update_one({"guild_id": str(ctx.guild.id)}, {"$set": {"modules.honeypot.enabled": "True", "modules.honeypot.channel_id": str(ctx.channel.id)}})
    embed = discord.Embed(
        title="HONEYPOT ENABLED",
        description="This channel is now a honeypot. Anyone who sends a message here will be softly kicked. Do not type here unless you want to be removed.",
        color=0x00ffff
    )
    await ctx.send(embed=embed)

# --- MOD COMMANDS ---
@bot.command()
async def warn(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True" or not has_mod_perms(ctx, conf): return
    total = await _add_warn(ctx.guild, member, ctx.author, reason or "No reason", conf)
    case = await add_mod_case(ctx.guild.id, "WARN", ctx.author, member, reason)
    emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** warned · {total} total · Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"{emoji} **{member}** warned by **{ctx.author}**\nReason: {reason}", 0xffcc00)

@bot.command()
async def warns(ctx, member: discord.Member):
    ws = list(warns_col.find({"guild_id": str(ctx.guild.id), "user_id": str(member.id)}))
    if not ws: await ctx.send(f"**{member}** has no warnings."); return
    e = discord.Embed(title=f"Warnings — {member}", color=0xff3333)
    for i, w in enumerate(ws[-10:], 1): e.add_field(name=f"#{i}", value=f"**{w['reason']}** · by {w['mod']}", inline=False)
    await ctx.send(embed=e)

@bot.command()
async def clearwarns(ctx, member: discord.Member):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    warns_col.delete_many({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
    await ctx.send(f"✅ Cleared warnings for **{member}**.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True" or not has_mod_perms(ctx, conf): return
    dmc = conf['modules']['dms']
    if dmc.get("kick_enabled") == "True": await send_user_dm(member, dmc["kick_msg"], ctx.guild.name)
    await member.kick(reason=reason)
    case = await add_mod_case(ctx.guild.id, "KICK", ctx.author, member, reason)
    emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** kicked. Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"{emoji} **{member}** kicked by **{ctx.author}**\nReason: {reason}", 0xff6600)

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True" or not has_mod_perms(ctx, conf): return
    dmc = conf['modules']['dms']
    if dmc.get("ban_enabled") == "True": await send_user_dm(member, dmc["ban_msg"], ctx.guild.name)
    await member.ban(reason=reason)
    case = await add_mod_case(ctx.guild.id, "BAN", ctx.author, member, reason)
    emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** banned. Case #{case}")
    if conf['modules'].get('logging', {}).get('log_mods') == "True":
        await log_action(ctx.guild, conf, f"{emoji} **{member}** banned by **{ctx.author}**\nReason: {reason}", 0xff0000)

@bot.command()
async def unban(ctx, user_id: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)
        dmc = conf['modules']['dms']
        if dmc.get("unban_enabled") == "True": await send_user_dm(user, dmc["unban_msg"], ctx.guild.name)
        emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
        await ctx.send(f"{emoji} **{user}** unbanned.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] != "True" or not has_mod_perms(ctx, conf): return
    dmc = conf['modules']['dms']
    if dmc.get("timeout_enabled") == "True": await send_user_dm(member, dmc["timeout_msg"], ctx.guild.name)
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    case = await add_mod_case(ctx.guild.id, f"TIMEOUT {minutes}m", ctx.author, member, reason)
    emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** timed out {minutes}m. Case #{case}")

@bot.command()
async def mute(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        role = await ctx.guild.create_role(name="Muted")
        for ch in ctx.guild.channels:
            try: await ch.set_permissions(role, send_messages=False, speak=False)
            except: pass
    await member.add_roles(role, reason=reason)
    dmc = conf['modules']['dms']
    if dmc.get("mute_enabled") == "True": await send_user_dm(member, dmc["mute_msg"], ctx.guild.name)
    emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** muted.")

@bot.command()
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role and role in member.roles:
        await member.remove_roles(role)
        emoji = conf['modules'].get('message_emojis', {}).get('mod_action', '🌋')
    await ctx.send(f"{emoji} **{member}** unmuted.")

@bot.command()
async def slowmode(ctx, channel: discord.TextChannel = None, seconds: int = 0):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    target = channel or ctx.channel
    await target.edit(slowmode_delay=seconds)
    await ctx.send(f"🌋 Slowmode set to **{seconds}s** in {target.mention}.")

@bot.command(aliases=["clear"])
async def purge(ctx, amount: int):
    conf = get_guild_config(ctx.guild.id)
    if not has_mod_perms(ctx, conf): return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🌋 Deleted **{len(deleted)-1}** messages.", delete_after=3)

@bot.command()
async def cases(ctx):
    all_cases = list(cases_col.find({"guild_id": str(ctx.guild.id)}).sort("case", -1).limit(10))
    if not all_cases: await ctx.send("No cases."); return
    e = discord.Embed(title="Mod Cases", color=0xff3333)
    for c in all_cases: e.add_field(name=f"#{c['case']} {c['action']}", value=f"**{c['target']}** · {c['reason']}", inline=False)
    await ctx.send(embed=e)

@bot.command()
async def giveaway(ctx, duration: str, *, prize: str):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['giveaway']['enabled'] != "True" or not has_mod_perms(ctx, conf): return
    unit = duration[-1].lower()
    try: amount = int(duration[:-1])
    except: await ctx.send("Example: `!giveaway 1h Nitro`"); return
    seconds = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}.get(unit, 0) * amount
    if not seconds: return
    e = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**Prize:** {prize}\n**Duration:** {duration}\n\nReact with 🎉 to enter!", color=0xffd700)
    e.set_footer(text=f"Hosted by {ctx.author}")
    msg = await ctx.send(embed=e)
    await msg.add_reaction("🌋")
    await asyncio.sleep(seconds)
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🌋")
    users = [u async for u in reaction.users() if not u.bot]
    if not users: await ctx.send("No entries.")
    else:
        import random
        await ctx.send(f"🎉 {random.choice(users).mention} won **{prize}**!")

# --- TICKET SYSTEM ---
class TicketSelect(discord.ui.Select):
    def __init__(self, conf):
        tc = conf['modules']['tickets']
        cats = tc.get('categories', {})
        cat_order = ['support', 'store', 'apply', 'report','bug', 'beta']
        options = []
        for key in cat_order:
            cat_conf = cats.get(key, {})
            if cat_conf.get('enabled', 'True') == "True":
                options.append(discord.SelectOption(
                    label=cat_conf.get('label', key.title()),
                    emoji=cat_conf.get('emoji', '🎫'),
                    value=key,
                    description=cat_conf.get('description', '')
                ))
        super().__init__(placeholder="Select ticket type...", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        conf = get_guild_config(interaction.guild.id)
        tc = conf['modules']['tickets']
        cat_key = self.values[0]
        cat_conf = tc.get('categories', {}).get(cat_key, {})
        cat_id = cat_conf.get('category_id', '')
        support_role_id = tc.get('support_role_id', '')
        category = interaction.guild.get_channel(int(cat_id)) if cat_id and cat_id.isdigit() else None
        support_role = interaction.guild.get_role(int(support_role_id)) if support_role_id and support_role_id.isdigit() else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if support_role: overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        label = cat_conf.get('label', cat_key)
        ch = await interaction.guild.create_text_channel(f"ticket-{label.lower()}-{interaction.user.name}", category=category, overwrites=overwrites)
        close_view = CloseTicketView()
        e = discord.Embed(title=f"{cat_conf.get('emoji','🎫')} {label} Ticket", description=f"{interaction.user.mention} your ticket has been created!\n{support_role.mention if support_role else ''}", color=0xff3333)
        await ch.send(embed=e, view=close_view)
        await interaction.response.send_message(f"✅ Ticket created: {ch.mention}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self, conf):
        super().__init__(timeout=None)
        self.add_item(TicketSelect(conf))

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

@bot.command()
async def setticket(ctx):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['tickets']['enabled'] != "True" or not ctx.author.guild_permissions.administrator: return
    e = discord.Embed(title="🎫 Support Tickets", description="Select a category below to open a ticket.", color=0xff3333)
    await ctx.send(embed=e, view=TicketView(conf))
    await ctx.message.delete()

# ============================================================
# FLASK WEB DASHBOARD
# ============================================================
app = Flask(__name__)
app.secret_key = "lava_ultra_key_v3"

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ bot_name }} Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
:root {
  --bg: #0d0d0f; --surface: #141416; --surface2: #1c1c20; --surface3: #232328;
  --border: #222226; --border2: #2c2c32;
  --accent: {{ accent_color }};
  --accent-dim: {{ accent_color }}18;
  --accent-soft: {{ accent_color }}44;
  --text: #ededf0; --text2: #a0a0b0; --text3: #606070;
  --success: #22c55e; --danger: #ef4444; --warning: #f59e0b; --info: #3b82f6;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body { background: var(--bg); color: var(--text); font-family: 'DM Sans', sans-serif; display: flex; height: 100vh; overflow: hidden; font-size: 14px; }
::-webkit-scrollbar { width: 3px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 99px; }

/* ── SIDEBAR ── */
.sidebar { width: 216px; flex-shrink: 0; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
.sb-head { padding: 18px 14px 14px; border-bottom: 1px solid var(--border); }
.sb-logo { font-size: 14px; font-weight: 600; color: var(--accent); letter-spacing: .04em; }
.sb-guild { font-size: 11px; color: var(--text3); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: 'DM Mono', monospace; }
.sb-nav { flex: 1; overflow-y: auto; padding: 6px 6px; }
.sb-section { margin-bottom: 2px; }
.sb-section-lbl { font-size: 10px; font-weight: 500; color: var(--text3); letter-spacing: .07em; text-transform: uppercase; font-family: 'DM Mono', monospace; padding: 8px 8px 3px; display: block; }
.nb { display: flex; align-items: center; gap: 7px; width: 100%; padding: 7px 9px; border-radius: 6px; border: none; background: none; color: var(--text2); cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 13px; font-weight: 500; text-align: left; transition: all .12s; white-space: nowrap; overflow: hidden; }
.nb i { width: 13px; text-align: center; font-size: 11px; flex-shrink: 0; }
.nb:hover { background: var(--surface2); color: var(--text); }
.nb.active { background: var(--accent-dim); color: var(--accent); }
.sb-foot { padding: 6px; border-top: 1px solid var(--border); }

/* ── MAIN ── */
.main { flex: 1; overflow-y: auto; }
.inner { max-width: 820px; margin: 0 auto; padding: 30px 28px 100px; }

/* ── PAGE ── */
.page { display: none; }
.page.active { display: block; animation: fu .16s ease; }
@keyframes fu { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
.ph { margin-bottom: 22px; }
.pt { font-size: 20px; font-weight: 600; }
.ps { font-size: 12px; color: var(--text3); margin-top: 3px; }

/* ── CARDS ── */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 14px; }
.ch { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ct { font-size: 11px; font-weight: 500; color: var(--text3); text-transform: uppercase; letter-spacing: .07em; font-family: 'DM Mono', monospace; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.g3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 10px; }

/* ── STATS ── */
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 14px 16px; }
.stat-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.stat-lbl { font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: .07em; font-family: 'DM Mono', monospace; }
.stat-ico { width: 26px; height: 26px; background: var(--accent-dim); border-radius: 6px; display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 11px; }
.stat-val { font-size: 26px; font-weight: 600; font-family: 'DM Mono', monospace; }

/* ── MODULE ROWS ── */
.mr { display: flex; align-items: center; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid var(--border); }
.mr:last-child { border: none; padding-bottom: 0; }
.mr-l { display: flex; align-items: center; gap: 9px; }
.mr-ic { width: 28px; height: 28px; background: var(--surface2); border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--text3); }
.mr-name { font-size: 13px; font-weight: 500; }
.badge-on { font-size: 10px; font-family: 'DM Mono', monospace; padding: 2px 7px; border-radius: 4px; background: #16301f; color: var(--success); }
.badge-off { font-size: 10px; font-family: 'DM Mono', monospace; padding: 2px 7px; border-radius: 4px; background: var(--surface2); color: var(--text3); }

/* ── FORM ── */
.f { margin-bottom: 13px; }
.f:last-child { margin-bottom: 0; }
.fl { display: block; font-size: 11px; font-weight: 500; color: var(--text3); margin-bottom: 5px; font-family: 'DM Mono', monospace; }
input[type="text"], input[type="password"], input[type="number"], textarea, select {
  width: 100%; padding: 8px 11px; background: var(--surface2); border: 1px solid var(--border2);
  color: var(--text); border-radius: 7px; font-family: 'DM Sans', sans-serif; font-size: 13px; outline: none; transition: border .13s;
}
input:focus, textarea:focus, select:focus { border-color: var(--accent-soft); }
input[type="color"] { height: 36px; padding: 3px 5px; cursor: pointer; border-radius: 7px; width: 100%; background: var(--surface2); border: 1px solid var(--border2); }
textarea { resize: vertical; min-height: 68px; }

/* ── TOGGLE ── */
.tr { display: flex; align-items: center; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid var(--border); }
.tr:last-child { border: none; }
.ti .tl { font-size: 13px; font-weight: 500; }
.ti .ts { font-size: 11px; color: var(--text3); margin-top: 1px; font-family: 'DM Mono', monospace; }
.sw { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
.sw input { opacity: 0; width: 0; height: 0; }
.sl { position: absolute; inset: 0; background: var(--surface3); border: 1px solid var(--border2); border-radius: 99px; cursor: pointer; transition: .18s; }
.sl::before { content: ""; position: absolute; width: 12px; height: 12px; left: 3px; top: 3px; background: var(--text3); border-radius: 50%; transition: .18s; }
input:checked + .sl { background: var(--accent); border-color: var(--accent); }
input:checked + .sl::before { background: #fff; transform: translateX(16px); }

/* ── SCROLL LIST ── */
.sl-box { max-height: 170px; overflow-y: auto; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; }
.ci { display: flex; align-items: center; gap: 8px; padding: 7px 11px; border-bottom: 1px solid var(--border); font-size: 13px; }
.ci:last-child { border: none; }
.ci:hover { background: #ffffff04; }
input[type="checkbox"] { width: 13px; height: 13px; accent-color: var(--accent); flex-shrink: 0; }

/* ── TAG INPUT ── */
.tag-row { display: flex; gap: 7px; margin-bottom: 7px; }
.tag-row input { flex: 1; }
.btn-add { padding: 8px 14px; background: var(--surface2); border: 1px solid var(--border2); color: var(--text2); border-radius: 7px; cursor: pointer; font-size: 13px; font-family: 'DM Sans', sans-serif; white-space: nowrap; transition: .13s; }
.btn-add:hover { border-color: var(--accent-soft); color: var(--accent); }
.tags { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 11px; min-height: 20px; }
.tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px 2px 9px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 5px; font-size: 12px; font-family: 'DM Mono', monospace; }
.tag-x { cursor: pointer; color: var(--text3); font-size: 10px; padding: 1px 2px; border-radius: 2px; }
.tag-x:hover { color: var(--danger); }

/* ── TABLE ── */
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; padding: 8px 11px; font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: .06em; font-family: 'DM Mono', monospace; border-bottom: 1px solid var(--border); font-weight: 500; }
.tbl td { padding: 9px 11px; border-bottom: 1px solid var(--border); }
.tbl tr:last-child td { border: none; }
.tbl tr:hover td { background: #ffffff03; }
.pill { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-family: 'DM Mono', monospace; font-weight: 600; }
.pw { background: #451a03; color: var(--warning); }
.pk { background: #431407; color: #fb923c; }
.pb { background: #450a0a; color: var(--danger); }
.po { background: #172554; color: #60a5fa; }

/* ── FONT CREATOR ── */
.fgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.fcard { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.flabel { font-size: 10px; color: var(--text3); font-family: 'DM Mono', monospace; margin-bottom: 5px; text-transform: uppercase; letter-spacing: .06em; }
.ftext { font-size: 15px; word-break: break-all; min-height: 22px; }
.cpbtn { display: inline-flex; align-items: center; gap: 4px; margin-top: 8px; padding: 4px 9px; background: var(--surface); border: 1px solid var(--border2); border-radius: 5px; color: var(--text3); font-size: 11px; cursor: pointer; font-family: 'DM Mono', monospace; transition: .13s; }
.cpbtn:hover { color: var(--accent); border-color: var(--accent-soft); }
.cpbtn.ok { color: var(--success); border-color: var(--success); }

/* ── DIVIDER ── */
hr.dv { border: none; border-top: 1px solid var(--border); margin: 14px 0; }

/* ── SAVE BAR ── */
.savebar { position: fixed; bottom: 0; left: 216px; right: 0; padding: 12px 28px; background: var(--surface); border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: flex-end; gap: 12px; z-index: 100; }
.btn-save { padding: 8px 24px; background: var(--accent); color: #fff; border: none; border-radius: 7px; font-family: 'DM Sans', sans-serif; font-weight: 600; font-size: 13px; cursor: pointer; transition: .13s; }
.btn-save:hover { opacity: .85; }
.save-hint { font-size: 11px; color: var(--text3); }

/* ── AUTH ── */
.auth-wrap { margin: auto; width: 340px; }
.auth-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 32px 28px; }
.auth-logo { font-size: 16px; font-weight: 600; color: var(--accent); margin-bottom: 3px; }
.auth-sub { font-size: 12px; color: var(--text3); margin-bottom: 24px; }
.auth-btn { width: 100%; padding: 9px; background: var(--accent); color: #fff; border: none; border-radius: 7px; font-family: 'DM Sans', sans-serif; font-weight: 600; font-size: 13px; cursor: pointer; margin-top: 2px; }
.err { font-size: 12px; color: var(--danger); padding: 7px 11px; background: #450a0a33; border-radius: 6px; margin-bottom: 11px; border: 1px solid #450a0a66; }

/* ── SERVER SELECT ── */
.sgrid { display: grid; grid-template-columns: repeat(auto-fill,minmax(170px,1fr)); gap: 10px; margin-top: 20px; }
.scard { background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 18px; cursor: pointer; text-align: center; font-size: 13px; font-weight: 500; transition: .13s; }
.scard:hover { border-color: var(--accent-soft); color: var(--accent); transform: translateY(-1px); }
.scard i { font-size: 18px; color: var(--text3); display: block; margin-bottom: 7px; }
.scard:hover i { color: var(--accent); }

.code { font-family: 'DM Mono', monospace; background: var(--surface2); padding: 1px 5px; border-radius: 3px; font-size: 12px; color: var(--accent); }
.muted { color: var(--text3); }
</style>
</head>
<body>

{% if not session.user %}
<div class="auth-wrap">
  <div class="auth-card">
    <div class="auth-logo">{{ bot_name }}</div>
    <div class="auth-sub">Admin Dashboard · Sign in to continue</div>
    {% if login_error %}<div class="err">Incorrect password.</div>{% endif %}
    <form method="POST">
      <div class="f"><label class="fl">Username</label><input type="text" name="user" placeholder="admin" required></div>
      <div class="f"><label class="fl">Password</label><input type="password" name="pw" placeholder="••••••••" required></div>
      <button type="submit" class="auth-btn">Sign in</button>
    </form>
  </div>
</div>

{% elif not session.guild_id %}
<div class="main" style="padding:36px;">
  <div style="max-width:760px;margin:0 auto;">
    <div class="ph"><div class="pt">Select a Server</div><div class="ps">Choose which server to manage.</div></div>
    <div class="sgrid">
      {% for g in guilds %}<div class="scard" onclick="location.href='/select/{{ g.id }}'"><i class="fas fa-server"></i>{{ g.name }}</div>{% endfor %}
    </div>
  </div>
</div>

{% else %}
<div class="sidebar">
  <div class="sb-head">
    <div class="sb-logo">{{ bot_name }}</div>
    <div class="sb-guild">{{ guild_name }}</div>
  </div>
  <div class="sb-nav">
    <div class="sb-section">
      <span class="sb-section-lbl">Overview</span>
      <button class="nb active" onclick="sp('dash',this)"><i class="fas fa-home"></i>Dashboard</button>
    </div>
    <div class="sb-section">
      <span class="sb-section-lbl">Config</span>
      <button class="nb" onclick="sp('appearance',this)"><i class="fas fa-palette"></i>Appearance</button>
      <button class="nb" onclick="sp('settings',this)"><i class="fas fa-sliders-h"></i>Settings</button>
    </div>
    <div class="sb-section">
      <span class="sb-section-lbl">Modules</span>
      <button class="nb" onclick="sp('welcome',this)"><i class="fas fa-door-open"></i>Welcome / Leave</button>
      <button class="nb" onclick="sp('automod',this)"><i class="fas fa-shield-alt"></i>Auto-Mod</button>
      <button class="nb" onclick="sp('linkfilter',this)"><i class="fas fa-link"></i>Link Filter</button>
      <button class="nb" onclick="sp('mod',this)"><i class="fas fa-gavel"></i>Moderation</button>
      <button class="nb" onclick="sp('warnsys',this)"><i class="fas fa-exclamation-triangle"></i>Warn System</button>
      <button class="nb" onclick="sp('tickets',this)"><i class="fas fa-ticket-alt"></i>Tickets</button>
      <button class="nb" onclick="sp('counting',this)"><i class="fas fa-sort-numeric-up"></i>Counting</button>
      <button class="nb" onclick="sp('roles',this)"><i class="fas fa-user-tag"></i>Auto Role</button>
      <button class="nb" onclick="sp('logging',this)"><i class="fas fa-list-alt"></i>Logging</button>
      <button class="nb" onclick="sp('giveaway',this)"><i class="fas fa-gift"></i>Giveaway</button>
    </div>
    <div class="sb-section">
      <span class="sb-section-lbl">Content</span>
      <button class="nb" onclick="sp('dms',this)"><i class="fas fa-envelope"></i>DM Notifications</button>
      <button class="nb" onclick="sp('helpinfo',this)"><i class="fas fa-question-circle"></i>Help / Info</button>
      <button class="nb" onclick="sp('emojis',this)"><i class="fas fa-smile"></i>Emojis</button>
      <button class="nb" onclick="sp('fonts',this)"><i class="fas fa-font"></i>Font Creator</button>
    </div>
    <div class="sb-section">
      <span class="sb-section-lbl">Records</span>
      <button class="nb" onclick="sp('cases',this)"><i class="fas fa-folder-open"></i>Mod Cases</button>
    </div>
  </div>
  <div class="sb-foot">
    <button class="nb" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i>Switch Server</button>
    <button class="nb" onclick="location.href='/logout'"><i class="fas fa-sign-out-alt"></i>Logout</button>
  </div>
</div>

<div class="main">
<div class="inner">
<form method="POST">
<input type="hidden" name="action" value="save">

<!-- DASHBOARD -->
<div id="dash" class="page active">
  <div class="ph"><div class="pt">Dashboard</div><div class="ps">{{ guild_name }}</div></div>
  <div class="g3" style="margin-bottom:14px;">
    <div class="stat"><div class="stat-top"><div class="stat-lbl">Members</div><div class="stat-ico"><i class="fas fa-users"></i></div></div><div class="stat-val">{{ member_count }}</div></div>
    <div class="stat"><div class="stat-top"><div class="stat-lbl">Warnings</div><div class="stat-ico"><i class="fas fa-exclamation"></i></div></div><div class="stat-val">{{ total_warns }}</div></div>
    <div class="stat"><div class="stat-top"><div class="stat-lbl">Mod Cases</div><div class="stat-ico"><i class="fas fa-gavel"></i></div></div><div class="stat-val">{{ total_cases }}</div></div>
  </div>
  <div class="card">
    <div class="ct" style="margin-bottom:10px;">Modules</div>
    {% set mods=[('link_filter','Link Filter','fa-link'),('mod','Moderation','fa-gavel'),('auto_mod','Auto-Mod','fa-shield-alt'),('logging','Logging','fa-list-alt'),('welcome_channel','Welcome','fa-door-open'),('tickets','Tickets','fa-ticket-alt'),('counting','Counting','fa-sort-numeric-up'),('giveaway','Giveaway','fa-gift')] %}
    {% for k,lbl,ic in mods %}
    <div class="mr">
      <div class="mr-l"><div class="mr-ic"><i class="fas {{ ic }}"></i></div><div class="mr-name">{{ lbl }}</div></div>
      {% if config.modules[k].enabled=='True' %}<span class="badge-on">● active</span>{% else %}<span class="badge-off">inactive</span>{% endif %}
    </div>
    {% endfor %}
  </div>
</div>

<!-- APPEARANCE -->
<div id="appearance" class="page">
  <div class="ph"><div class="pt">Appearance</div><div class="ps">Dashboard branding and bot status.</div></div>
  <div class="card">
    <div class="ct" style="margin-bottom:12px;">Branding</div>
    <div class="g2">
      <div class="f"><label class="fl">Dashboard Name</label><input type="text" name="bot_name" value="{{ bot_name }}"></div>
      <div class="f"><label class="fl">Accent Color</label><input type="color" name="accent_color" value="{{ accent_color }}"></div>
    </div>
  </div>
  <div class="card">
    <div class="ct" style="margin-bottom:12px;">Bot Status</div>
    <div class="g2">
      <div class="f"><label class="fl">Type</label><select name="status_type">{% for t in ['playing','watching','listening','competing'] %}<option value="{{ t }}" {% if config.modules.status.type==t %}selected{% endif %}>{{ t|capitalize }}</option>{% endfor %}</select></div>
      <div class="f"><label class="fl">Text</label><input type="text" name="status_text" value="{{ config.modules.status.text }}"></div>
    </div>
  </div>
</div>

<!-- SETTINGS -->
<div id="settings" class="page">
  <div class="ph"><div class="pt">Settings</div><div class="ps">Global bot configuration.</div></div>
  <div class="card">
    <div class="ct" style="margin-bottom:12px;">Prefix</div>
    <div class="f"><label class="fl">Command Prefix</label><input type="text" name="prefix" value="{{ config.prefix }}" style="max-width:100px;"></div>
  </div>
</div>

<!-- WELCOME / LEAVE -->
<div id="welcome" class="page">
  <div class="ph"><div class="pt">Welcome & Leave</div><div class="ps">Messages for member joins and leaves.</div></div>
  <div class="card">
    <div class="ch"><div class="ct">Welcome Channel</div><label class="sw"><input type="checkbox" name="wc_enabled" value="True" {% if config.modules.welcome_channel.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="g2">
      <div class="f"><label class="fl">Channel</label><select name="wc_channel_id"><option value="">— Select —</option>{% for c in channels %}<option value="{{ c.id }}" {% if c.id|string==config.modules.welcome_channel.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}</select></div>
      <div class="f"><label class="fl">Embed Color</label><input type="color" name="wc_embed_color" value="{{ config.modules.welcome_channel.embed_color }}"></div>
    </div>
    <div class="f"><label class="fl">Message — use {user} {server}</label><textarea name="wc_message">{{ config.modules.welcome_channel.message }}</textarea></div>
    <div class="f"><label class="fl">Embed Title</label><input type="text" name="wc_embed_title" value="{{ config.modules.welcome_channel.embed_title }}"></div>
    <div class="tr"><div class="ti"><div class="tl">Use Embed</div></div><label class="sw"><input type="checkbox" name="wc_embed" value="True" {% if config.modules.welcome_channel.embed=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="tr"><div class="ti"><div class="tl">Show Member Count</div></div><label class="sw"><input type="checkbox" name="wc_member_count" value="True" {% if config.modules.welcome_channel.show_member_count=="True" %}checked{% endif %}><span class="sl"></span></label></div>
  </div>
  <div class="card">
    <div class="ch"><div class="ct">Leave Channel</div><label class="sw"><input type="checkbox" name="lc_enabled" value="True" {% if config.modules.leave_channel.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="f"><label class="fl">Channel</label><select name="lc_channel_id"><option value="">— Select —</option>{% for c in channels %}<option value="{{ c.id }}" {% if c.id|string==config.modules.leave_channel.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}</select></div>
    <div class="f"><label class="fl">Message — use {user} {server}</label><textarea name="lc_message">{{ config.modules.leave_channel.message }}</textarea></div>
  </div>
</div>

<!-- AUTO-MOD -->
<div id="automod" class="page">
  <div class="ph"><div class="pt">Auto-Moderation</div><div class="ps">Automatically handle rule violations.</div></div>
  <div class="card"><div class="tr"><div class="ti"><div class="tl">Enable Auto-Mod</div><div class="ts">Applies to all filters below</div></div><label class="sw"><input type="checkbox" name="am_enabled" value="True" {% if config.modules.auto_mod.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div></div>
  <div class="card">
    <div class="ct" style="margin-bottom:10px;">Word Blacklist</div>
    <div class="tag-row"><input type="text" id="bl_in" placeholder="Add word..."><button type="button" class="btn-add" onclick="addTag('bl_in','bl_tags','am_blacklist')">Add</button></div>
    <div class="tags" id="bl_tags">{% for w in config.modules.auto_mod.blacklist %}<div class="tag">{{ w }}<input type="hidden" name="am_blacklist" value="{{ w }}"><span class="tag-x" onclick="this.parentElement.remove()">✕</span></div>{% endfor %}</div>
    <div class="f"><label class="fl">Action on Trigger</label><select name="am_blacklist_action"><option value="delete" {% if config.modules.auto_mod.blacklist_action=='delete' %}selected{% endif %}>Delete only</option><option value="warn" {% if config.modules.auto_mod.blacklist_action=='warn' %}selected{% endif %}>Delete + Warn</option></select></div>
  </div>
  <div class="card">
    <div class="ct" style="margin-bottom:10px;">Filters</div>
    <div class="tr"><div class="ti"><div class="tl">Caps Lock Filter</div><div class="ts">Block excessive caps</div></div><label class="sw"><input type="checkbox" name="am_caps_filter" value="True" {% if config.modules.auto_mod.caps_filter=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="f" style="margin-top:11px;"><label class="fl">Caps Threshold (%)</label><input type="number" name="am_caps_threshold" value="{{ config.modules.auto_mod.caps_threshold }}" min="10" max="100" style="max-width:100px;"></div>
    <hr class="dv">
    <div class="tr"><div class="ti"><div class="tl">Anti-Spam Filter</div><div class="ts">Block rapid messages</div></div><label class="sw"><input type="checkbox" name="am_spam_filter" value="True" {% if config.modules.auto_mod.spam_filter=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="g2" style="margin-top:11px;"><div class="f"><label class="fl">Max Messages</label><input type="number" name="am_spam_count" value="{{ config.modules.auto_mod.spam_count }}"></div><div class="f"><label class="fl">Per X Seconds</label><input type="number" name="am_spam_seconds" value="{{ config.modules.auto_mod.spam_seconds }}"></div></div>
  </div>
</div>

<!-- LINK FILTER -->
<div id="linkfilter" class="page">
  <div class="ph"><div class="pt">Link Filter</div><div class="ps">Block links in selected channels.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Link Filter</div></div><label class="sw"><input type="checkbox" name="lf_enabled" value="True" {% if config.modules.link_filter.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Protected Channels</label><div class="sl-box">{% for c in channels %}<div class="ci"><input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}>#{{ c.name }}</div>{% endfor %}</div></div>
    <div class="f"><label class="fl">Bypass Roles</label><div class="sl-box">{% for r in roles %}<div class="ci"><input type="checkbox" name="lf_roles" value="{{ r.id }}" {% if r.id|string in config.modules.link_filter.roles %}checked{% endif %}>{{ r.name }}</div>{% endfor %}</div></div>
  </div>
</div>

<!-- MODERATION -->
<div id="mod" class="page">
  <div class="ph"><div class="pt">Moderation</div><div class="ps">Commands: kick, ban, warn, mute, timeout, purge, clear, slowmode.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Mod Commands</div></div><label class="sw"><input type="checkbox" name="m_enabled" value="True" {% if config.modules.mod.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Staff Roles</label><div class="sl-box">{% for r in roles %}<div class="ci"><input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>{{ r.name }}</div>{% endfor %}</div></div>
  </div>
</div>

<!-- WARN SYSTEM -->
<div id="warnsys" class="page">
  <div class="ph"><div class="pt">Warn System</div><div class="ps">Auto-punish at warning thresholds.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Auto-Punishment</div></div><label class="sw"><input type="checkbox" name="ws_enabled" value="True" {% if config.modules.warn_system.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="g2" style="margin-top:12px;">
      <div class="f"><label class="fl">Warns → Auto Kick (0 = off)</label><input type="number" name="ws_kick" value="{{ config.modules.warn_system.warn_threshold_kick }}" min="0"></div>
      <div class="f"><label class="fl">Warns → Auto Ban (0 = off)</label><input type="number" name="ws_ban" value="{{ config.modules.warn_system.warn_threshold_ban }}" min="0"></div>
    </div>
  </div>
</div>

<!-- EMOJIS -->
<div id="emojis" class="page">
  <div class="ph"><div class="pt">Emojis</div><div class="ps">Choose which emoji the bot sends with each type of message.</div></div>
  <div class="card">
    <div class="ct">Message Emoji Settings</div>
    <div class="g2">
      <div class="f"><label class="fl">Link Filter Emoji</label><input type="text" name="me_link_filter" value="{{ config.modules.message_emojis.link_filter }}"></div>
      <div class="f"><label class="fl">Auto-Mod Blacklist Emoji</label><input type="text" name="me_auto_mod_blacklist" value="{{ config.modules.message_emojis.auto_mod_blacklist }}"></div>
      <div class="f"><label class="fl">Auto-Mod Caps Emoji</label><input type="text" name="me_auto_mod_caps" value="{{ config.modules.message_emojis.auto_mod_caps }}"></div>
      <div class="f"><label class="fl">Auto-Mod Spam Emoji</label><input type="text" name="me_auto_mod_spam" value="{{ config.modules.message_emojis.auto_mod_spam }}"></div>
      <div class="f"><label class="fl">Counting Fail Emoji</label><input type="text" name="me_counting_fail" value="{{ config.modules.message_emojis.counting_fail }}"></div>
      <div class="f"><label class="fl">Counting Success Emoji</label><input type="text" name="me_counting_success" value="{{ config.modules.message_emojis.counting_success }}"></div>
      <div class="f"><label class="fl">Honeypot Emoji</label><input type="text" name="me_honeypot" value="{{ config.modules.message_emojis.honeypot }}"></div>
      <div class="f"><label class="fl">Mod Action Emoji</label><input type="text" name="me_mod_action" value="{{ config.modules.message_emojis.mod_action }}"></div>
      <div class="f"><label class="fl">Help / Info Emoji</label><input type="text" name="me_help_info" value="{{ config.modules.message_emojis.help_info }}"></div>
    </div>
  </div>
</div>

<!-- TICKETS -->
<div id="tickets" class="page">
  <div class="ph"><div class="pt">Tickets</div><div class="ps">Configure categories, then use <span class="code">!setticket</span> to deploy.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Ticket System</div></div><label class="sw"><input type="checkbox" name="tc_enabled" value="True" {% if config.modules.tickets.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Global Support Role</label><select name="tc_support_role_id"><option value="">— Select Role —</option>{% for r in roles %}<option value="{{ r.id }}" {% if r.id|string==config.modules.tickets.support_role_id %}selected{% endif %}>{{ r.name }}</option>{% endfor %}</select></div>
  </div>
  {% if config and config.modules.tickets %}
  {% for key, (def_emoji, def_label) in [('support',('🎫','Support')),('store',('🛒','Store')),('apply',('📋','Apply')),('report',('🚨','User Report')),('bug',('🐛','Bug Report')),('beta',('🌋','Beta Tester'))] %}
  <div class="card">
    <div class="ch" style="margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:8px;"><span style="font-size:16px;">{{ config.modules.tickets.categories.get(key,{}).get('emoji',def_emoji) }}</span><div class="ct" style="margin:0;">{{ def_label }}</div></div>
      <label class="sw"><input type="checkbox" name="tc_{{ key }}_enabled" value="True" {% if config.modules.tickets.categories.get(key,{}).get('enabled','True')=="True" %}checked{% endif %}><span class="sl"></span></label>
    </div>
    <div class="g2">
      <div class="f"><label class="fl">Label</label><input type="text" name="tc_{{ key }}_label" value="{{ config.modules.tickets.categories.get(key,{}).get('label',def_label) }}"></div>
      <div class="f"><label class="fl">Emoji</label><input type="text" name="tc_{{ key }}_emoji" value="{{ config.modules.tickets.categories.get(key,{}).get('emoji',def_emoji) }}"></div>
    </div>
    <div class="f"><label class="fl">Description (shown in dropdown)</label><input type="text" name="tc_{{ key }}_desc" value="{{ config.modules.tickets.categories.get(key,{}).get('description','') }}"></div>
    <div class="f"><label class="fl">Discord Category (where tickets open)</label><select name="tc_{{ key }}_category"><option value="">— No Category —</option>{% for c in categories %}<option value="{{ c.id }}" {% if c.id|string==config.modules.tickets.categories.get(key,{}).get('category_id','') %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></div>
  </div>
  {% endfor %}
  {% endif %}
</div>

<!-- COUNTING -->
<div id="counting" class="page">
  <div class="ph"><div class="pt">Counting</div><div class="ps">Members count up — wrong number or double-post resets to 0.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Counting</div></div><label class="sw"><input type="checkbox" name="count_enabled" value="True" {% if config.modules.counting.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Counting Channel</label><select name="count_channel_id"><option value="">— Select Channel —</option>{% for c in channels %}<option value="{{ c.id }}" {% if c.id|string==config.modules.counting.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}</select></div>
    <p class="muted" style="font-size:12px;">Or use <span class="code">!setcounting</span> directly in the channel.</p>
  </div>
  <div class="card">
    <div class="ct" style="margin-bottom:6px;">Current Count</div>
    <div style="font-size:36px;font-weight:600;font-family:'DM Mono',monospace;color:var(--accent);">{{ current_count }}</div>
    <div class="muted" style="font-size:12px;margin-top:4px;">Next expected: {{ current_count+1 }}</div>
  </div>
</div>

<!-- ROLES -->
<div id="roles" class="page">
  <div class="ph"><div class="pt">Auto Role</div><div class="ps">Assign a role to new members automatically.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Auto Role</div></div><label class="sw"><input type="checkbox" name="ar_enabled" value="True" {% if config.modules.auto_role.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Role to Assign</label><select name="ar_role_id"><option value="">— Select Role —</option>{% for r in roles %}<option value="{{ r.id }}" {% if r.id|string==config.modules.auto_role.role_id %}selected{% endif %}>{{ r.name }}</option>{% endfor %}</select></div>
  </div>
</div>

<!-- LOGGING -->
<div id="logging" class="page">
  <div class="ph"><div class="pt">Logging</div><div class="ps">Log server activity to a channel.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Logging</div></div><label class="sw"><input type="checkbox" name="log_enabled" value="True" {% if config.modules.logging.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <div class="f"><label class="fl">Log Channel</label><select name="log_channel_id"><option value="">— Select —</option>{% for c in channels %}<option value="{{ c.id }}" {% if c.id|string==config.modules.logging.channel_id %}selected{% endif %}>#{{ c.name }}</option>{% endfor %}</select></div>
    <hr class="dv">
    {% for k,lbl in [('log_deletes','Deleted Messages'),('log_edits','Edited Messages'),('log_joins','Member Joins'),('log_leaves','Member Leaves'),('log_bans','Bans'),('log_roles','Role Changes'),('log_mods','Mod Actions')] %}
    <div class="tr"><div class="ti"><div class="tl">{{ lbl }}</div></div><label class="sw"><input type="checkbox" name="{{ k }}" value="True" {% if config.modules.logging[k]=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    {% endfor %}
  </div>
</div>

<!-- GIVEAWAY -->
<div id="giveaway" class="page">
  <div class="ph"><div class="pt">Giveaway</div><div class="ps">Use <span class="code">!giveaway 30m Prize Name</span> to start.</div></div>
  <div class="card">
    <div class="tr"><div class="ti"><div class="tl">Enable Giveaway Command</div></div><label class="sw"><input type="checkbox" name="ga_enabled" value="True" {% if config.modules.giveaway.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <hr class="dv">
    <p class="muted" style="font-size:12px;">Duration units: <span class="code">s</span> <span class="code">m</span> <span class="code">h</span> <span class="code">d</span></p>
  </div>
</div>

<!-- DM NOTIFICATIONS -->
<div id="dms" class="page">
  <div class="ph"><div class="pt">DM Notifications</div><div class="ps">Placeholders: <span class="code">{server}</span> <span class="code">{reason}</span></div></div>
  {% for pfx,key,lbl in [('dm_w','welcome','Welcome'),('dm_k','kick','Kick'),('dm_b','ban','Ban'),('dm_t','timeout','Timeout'),('dm_warn','warn','Warning'),('dm_ub','unban','Unban'),('dm_m','mute','Mute')] %}
  <div class="card">
    <div class="ch" style="margin-bottom:11px;"><div class="ct" style="margin:0;">{{ lbl }} DM</div><label class="sw"><input type="checkbox" name="{{ pfx }}_enabled" value="True" {% if config.modules.dms[key+'_enabled']=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="f"><label class="fl">Message</label><textarea name="{{ pfx }}_msg">{{ config.modules.dms[key+'_msg'] }}</textarea></div>
  </div>
  {% endfor %}
</div>

<!-- HELP / INFO -->
<div id="helpinfo" class="page">
  <div class="ph"><div class="pt">Help & Info</div><div class="ps">Static response commands.</div></div>
  <div class="card">
    <div class="ch" style="margin-bottom:12px;"><div class="ct" style="margin:0;">Help Module</div><label class="sw"><input type="checkbox" name="h_enabled" value="True" {% if config.modules.help.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="f"><label class="fl">Aliases (comma-separated)</label><input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}"></div>
    <div class="f"><label class="fl">Response</label><textarea name="h_text">{{ config.modules.help.text }}</textarea></div>
  </div>
  <div class="card">
    <div class="ch" style="margin-bottom:12px;"><div class="ct" style="margin:0;">Info Module</div><label class="sw"><input type="checkbox" name="i_enabled" value="True" {% if config.modules.info.enabled=="True" %}checked{% endif %}><span class="sl"></span></label></div>
    <div class="f"><label class="fl">Aliases (comma-separated)</label><input type="text" name="i_aliases" value="{{ config.modules.info.aliases }}"></div>
    <div class="f"><label class="fl">Response</label><textarea name="i_text">{{ config.modules.info.text }}</textarea></div>
  </div>
</div>

<!-- FONT CREATOR -->
<div id="fonts" class="page">
  <div class="ph"><div class="pt">Font Creator</div><div class="ps">Type text and copy it in any Unicode style for Discord.</div></div>
  <div class="card">
    <div class="f"><label class="fl">Input Text</label><input type="text" id="fi" placeholder="Type something..." oninput="uf(this.value)" autocomplete="off"></div>
    <div class="fgrid" id="fgrid">
      {% for fid,flbl in [('f_gothic','Gothic'),('f_fancy','Fancy / Cursive'),('f_smallcaps','Small Caps'),('f_bold','Bold Serif'),('f_italic','Italic'),('f_double','Double Struck'),('f_mono','Monospace'),('f_circle','Circled')] %}
      <div class="fcard"><div class="flabel">{{ flbl }}</div><div class="ftext" id="{{ fid }}"></div><button type="button" class="cpbtn" onclick="cf('{{ fid }}',this)"><i class="fas fa-copy"></i> Copy</button></div>
      {% endfor %}
    </div>
  </div>
</div>

<!-- MOD CASES -->
<div id="cases" class="page">
  <div class="ph"><div class="pt">Mod Cases</div><div class="ps">Recent moderation actions.</div></div>
  <div class="card">
    {% if mod_cases %}
    <table class="tbl">
      <thead><tr><th>#</th><th>Action</th><th>Target</th><th>Mod</th><th>Reason</th><th>Date</th></tr></thead>
      <tbody>
      {% for c in mod_cases %}
      <tr>
        <td style="font-family:'DM Mono',monospace;color:var(--text3)">{{ c.case }}</td>
        <td><span class="pill {% if c.action=='BAN' %}pb{% elif c.action=='KICK' %}pk{% elif c.action=='WARN' %}pw{% else %}po{% endif %}">{{ c.action }}</span></td>
        <td>{{ c.target }}</td>
        <td class="muted">{{ c.mod }}</td>
        <td class="muted">{{ c.reason }}</td>
        <td style="font-family:'DM Mono',monospace;font-size:11px;color:var(--text3)">{{ c.timestamp[:10] }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div style="text-align:center;padding:30px;color:var(--text3);">No mod cases yet.</div>
    {% endif %}
  </div>
</div>

<div class="savebar">
  <span class="save-hint">Changes apply instantly.</span>
  <button type="submit" class="btn-save">Save Changes</button>
</div>
</form>
</div>
</div>
{% endif %}

<script>
function sp(id,btn){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nb').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}

function addTag(inp,cont,name){
  const i=document.getElementById(inp),w=i.value.trim();
  if(!w)return;
  const c=document.getElementById(cont),t=document.createElement('div');
  t.className='tag';
  t.innerHTML=`${w}<input type="hidden" name="${name}" value="${w}"><span class="tag-x" onclick="this.parentElement.remove()">✕</span>`;
  c.appendChild(t);i.value='';
}
document.getElementById('bl_in')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addTag('bl_in','bl_tags','am_blacklist');}});

const F={
  gothic:   {f:'abcdefghijklmnopqrstuvwxyz',t:'𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷'},
  fancy:    {f:'abcdefghijklmnopqrstuvwxyz',t:'𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃'},
  smallcaps:{f:'abcdefghijklmnopqrstuvwxyz',t:'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ'},
  bold:     {f:'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',t:'𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗'},
  italic:   {f:'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',t:'𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡'},
  double:   {f:'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',t:'𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡'},
  mono:     {f:'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',t:'𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿'},
  circle:   {f:'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',t:'ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩⒶⒷⒸⒹⒺⒻⒼⒽⒾⒿⓀⓁⓂⓃⓄⓅⓆⓇⓈⓉⓊⓋⓌⓍⓎⓏ①②③④⑤⑥⑦⑧⑨'}
};
function conv(text,fn){
  const {f,t}=F[fn];const fa=[...f];const ta=[...t];
  return[...text].map(c=>{const i=fa.indexOf(c);return i>=0?ta[i]:c;}).join('');
}
function uf(v){
  const map={f_gothic:'gothic',f_fancy:'fancy',f_smallcaps:'smallcaps',f_bold:'bold',f_italic:'italic',f_double:'double',f_mono:'mono',f_circle:'circle'};
  for(const[id,fn]of Object.entries(map)){const el=document.getElementById(id);if(el)el.textContent=conv(v,fn);}
}
async function cf(id,btn){
  const t=document.getElementById(id)?.textContent;if(!t)return;
  await navigator.clipboard.writeText(t);
  btn.classList.add('ok');btn.innerHTML='<i class="fas fa-check"></i> Copied!';
  setTimeout(()=>{btn.classList.remove('ok');btn.innerHTML='<i class="fas fa-copy"></i> Copy';},2000);
}
</script>
</body>
</html>
"""

@app.route("/", methods=["GET","POST"])
def index():
    login_error = False
    if request.method == "POST":
        if "pw" in request.form:
            if request.form.get("pw") == os.environ.get("DASHBOARD_PASSWORD","10"):
                session['user'] = request.form.get("user"); return redirect("/")
            else: login_error = True
        action = request.form.get("action")
        if action == "save" and 'guild_id' in session:
            def cb(v): return "True" if v else "False"
            gid = session['guild_id']
            updates = {
                "prefix": request.form.get("prefix"), "bot_name": request.form.get("bot_name"), "accent_color": request.form.get("accent_color"),
                "modules.status.type": request.form.get("status_type"), "modules.status.text": request.form.get("status_text"),
                "modules.welcome_channel.enabled": cb(request.form.get("wc_enabled")), "modules.welcome_channel.channel_id": request.form.get("wc_channel_id",""),
                "modules.welcome_channel.message": request.form.get("wc_message"), "modules.welcome_channel.embed": cb(request.form.get("wc_embed")),
                "modules.welcome_channel.embed_title": request.form.get("wc_embed_title"), "modules.welcome_channel.embed_color": request.form.get("wc_embed_color"),
                "modules.welcome_channel.show_member_count": cb(request.form.get("wc_member_count")),
                "modules.leave_channel.enabled": cb(request.form.get("lc_enabled")), "modules.leave_channel.channel_id": request.form.get("lc_channel_id",""),
                "modules.leave_channel.message": request.form.get("lc_message"),
                "modules.link_filter.enabled": cb(request.form.get("lf_enabled")), "modules.link_filter.chans": request.form.getlist("lf_chans"), "modules.link_filter.roles": request.form.getlist("lf_roles"),
                "modules.auto_mod.enabled": cb(request.form.get("am_enabled")), "modules.auto_mod.blacklist": request.form.getlist("am_blacklist"),
                "modules.auto_mod.blacklist_action": request.form.get("am_blacklist_action"), "modules.auto_mod.caps_filter": cb(request.form.get("am_caps_filter")),
                "modules.auto_mod.caps_threshold": request.form.get("am_caps_threshold"), "modules.auto_mod.spam_filter": cb(request.form.get("am_spam_filter")),
                "modules.auto_mod.spam_count": request.form.get("am_spam_count"), "modules.auto_mod.spam_seconds": request.form.get("am_spam_seconds"),
                "modules.mod.enabled": cb(request.form.get("m_enabled")), "modules.mod.roles": request.form.getlist("mod_roles"),
                "modules.warn_system.enabled": cb(request.form.get("ws_enabled")), "modules.warn_system.warn_threshold_kick": request.form.get("ws_kick"), "modules.warn_system.warn_threshold_ban": request.form.get("ws_ban"),
                "modules.logging.enabled": cb(request.form.get("log_enabled")), "modules.logging.channel_id": request.form.get("log_channel_id",""),
                "modules.logging.log_deletes": cb(request.form.get("log_deletes")), "modules.logging.log_edits": cb(request.form.get("log_edits")),
                "modules.logging.log_joins": cb(request.form.get("log_joins")), "modules.logging.log_leaves": cb(request.form.get("log_leaves")),
                "modules.logging.log_bans": cb(request.form.get("log_bans")), "modules.logging.log_roles": cb(request.form.get("log_roles")), "modules.logging.log_mods": cb(request.form.get("log_mods")),
                "modules.tickets.enabled": cb(request.form.get("tc_enabled")), "modules.tickets.support_role_id": request.form.get("tc_support_role_id",""),
                "modules.message_emojis.link_filter": request.form.get("me_link_filter","🚫"), "modules.message_emojis.auto_mod_blacklist": request.form.get("me_auto_mod_blacklist","⚠️"),
                "modules.message_emojis.auto_mod_caps": request.form.get("me_auto_mod_caps","⚠️"), "modules.message_emojis.auto_mod_spam": request.form.get("me_auto_mod_spam","⌛"),
                "modules.message_emojis.counting_fail": request.form.get("me_counting_fail","❌"), "modules.message_emojis.counting_success": request.form.get("me_counting_success","✅"),
                "modules.message_emojis.honeypot": request.form.get("me_honeypot","🚨"), "modules.message_emojis.mod_action": request.form.get("me_mod_action","🌋"),
                "modules.message_emojis.help_info": request.form.get("me_help_info","ℹ️"),
                "modules.auto_role.enabled": cb(request.form.get("ar_enabled")), "modules.auto_role.role_id": request.form.get("ar_role_id",""),
                "modules.counting.enabled": cb(request.form.get("count_enabled")), "modules.counting.channel_id": request.form.get("count_channel_id",""),
                "modules.giveaway.enabled": cb(request.form.get("ga_enabled")),
                "modules.dms.welcome_enabled": cb(request.form.get("dm_w_enabled")), "modules.dms.welcome_msg": request.form.get("dm_w_msg"),
                "modules.dms.kick_enabled": cb(request.form.get("dm_k_enabled")), "modules.dms.kick_msg": request.form.get("dm_k_msg"),
                "modules.dms.ban_enabled": cb(request.form.get("dm_b_enabled")), "modules.dms.ban_msg": request.form.get("dm_b_msg"),
                "modules.dms.timeout_enabled": cb(request.form.get("dm_t_enabled")), "modules.dms.timeout_msg": request.form.get("dm_t_msg"),
                "modules.dms.warn_enabled": cb(request.form.get("dm_warn_enabled")), "modules.dms.warn_msg": request.form.get("dm_warn_msg"),
                "modules.dms.unban_enabled": cb(request.form.get("dm_ub_enabled")), "modules.dms.unban_msg": request.form.get("dm_ub_msg"),
                "modules.dms.mute_enabled": cb(request.form.get("dm_m_enabled")), "modules.dms.mute_msg": request.form.get("dm_m_msg"),
                "modules.help.enabled": cb(request.form.get("h_enabled")), "modules.help.aliases": request.form.get("h_aliases"), "modules.help.text": request.form.get("h_text"),
                "modules.info.enabled": cb(request.form.get("i_enabled")), "modules.info.aliases": request.form.get("i_aliases"), "modules.info.text": request.form.get("i_text"),
            }
            for key in ['support','store','apply','report','bug']:
                updates[f"modules.tickets.categories.{key}.enabled"] = cb(request.form.get(f"tc_{key}_enabled"))
                updates[f"modules.tickets.categories.{key}.label"] = request.form.get(f"tc_{key}_label","")
                updates[f"modules.tickets.categories.{key}.emoji"] = request.form.get(f"tc_{key}_emoji","")
                updates[f"modules.tickets.categories.{key}.description"] = request.form.get(f"tc_{key}_desc","")
                updates[f"modules.tickets.categories.{key}.category_id"] = request.form.get(f"tc_{key}_category","")
            config_col.update_one({"guild_id": gid}, {"$set": updates})
            async def us(): await _set_status(request.form.get("status_type","playing"), request.form.get("status_text","Lava Network"))
            asyncio.run_coroutine_threadsafe(us(), bot.loop)
            return redirect("/")

    guilds = [{"name": g.name, "id": str(g.id)} for g in bot.guilds]
    conf = roles = channels = categories = None
    guild_name = ""; member_count = total_warns = total_cases = current_count = 0
    mod_cases = []; bot_name = "LAVA"; accent_color = "#ff3333"

    if 'guild_id' in session:
        conf = get_guild_config(session['guild_id'])
        bot_name = conf.get('bot_name','LAVA'); accent_color = conf.get('accent_color','#ff3333')
        g = bot.get_guild(int(session['guild_id']))
        if g:
            guild_name = g.name; member_count = g.member_count
            roles = [{"id": r.id,"name": r.name} for r in g.roles if not r.managed and r.name!="@everyone"]
            channels = [{"id": c.id,"name": c.name} for c in g.text_channels]
            categories = [{"id": c.id,"name": c.name} for c in g.categories]
        total_warns = warns_col.count_documents({"guild_id": session['guild_id']})
        total_cases = cases_col.count_documents({"guild_id": session['guild_id']})
        mod_cases = list(cases_col.find({"guild_id": session['guild_id']}).sort("case",-1).limit(30))
        cd = counting_col.find_one({"guild_id": session['guild_id']})
        current_count = cd.get('count',0) if cd else 0

    return render_template_string(HTML, config=conf, guilds=guilds, roles=roles or [], channels=channels or [],
        categories=categories or [], guild_name=guild_name, bot_name=bot_name, accent_color=accent_color,
        member_count=member_count, total_warns=total_warns, total_cases=total_cases,
        mod_cases=mod_cases, current_count=current_count, login_error=login_error)

@app.route("/select/<guild_id>")
def select_guild(guild_id): session['guild_id']=guild_id; return redirect("/")

@app.route("/change_server")
def change_server(): session.pop('guild_id',None); return redirect("/")

@app.route("/logout")
def logout(): session.clear(); return redirect("/")

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
