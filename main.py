import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect, url_for
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta

# --- DATABASE SETUP ---
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['lavabot_db']
config_col = db['settings']

def get_config():
    conf = config_col.find_one({"id": "bot_config"})
    if not conf or 'modules' not in conf:
        default = {
            "id": "bot_config",
            "prefix": "!",
            "status": "LavaNetwork Elite",
            "modules": {
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "True", "chans": [], "roles": []},
                "help": {"enabled": "True", "chans": [], "roles": [], "aliases": "help,list", "text": "LavaBot Commands: !ban, !kick, !timeout"}
            }
        }
        config_col.update_one({"id": "bot_config"}, {"$set": default}, upsert=True)
        return default
    return conf

# --- BOT LOGIC ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# 1. LINK FILTER & DYNAMIC HELP
@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    prefix = conf.get("prefix", "!")
    
    # Link Filter
    lf = conf['modules'].get('link_filter', {})
    if lf.get("enabled") == "True" and "http" in message.content:
        if not lf.get("chans") or str(message.channel.id) in lf["chans"]:
            user_roles = [str(r.id) for r in message.author.roles]
            if not any(rid in lf.get("roles", []) for rid in user_roles) and not message.author.guild_permissions.administrator:
                await message.delete()
                return

    # Custom Help Aliases
    hp = conf['modules'].get('help', {})
    if hp.get("enabled") == "True":
        aliases = [a.strip().lower() for a in hp.get("aliases", "help").split(",")]
        content = message.content.lower()
        for a in aliases:
            if content == f"{prefix}{a}":
                await message.channel.send(hp.get("text", "Help active."))
                return

    await bot.process_commands(message)

# 2. MODERATION COMMANDS
@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    conf = get_config()
    mod_roles = conf['modules']['mod'].get('roles', [])
    user_roles = [str(r.id) for r in ctx.author.roles]
    if any(rid in mod_roles for rid in user_roles) or ctx.author.guild_permissions.kick_members:
        await member.kick(reason=reason)
        await ctx.send(f"✅ Kicked {member.name}")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    conf = get_config()
    mod_roles = conf['modules']['mod'].get('roles', [])
    user_roles = [str(r.id) for r in ctx.author.roles]
    if any(rid in mod_roles for rid in user_roles) or ctx.author.guild_permissions.ban_members:
        await member.ban(reason=reason)
        await ctx.send(f"🚫 Banned {member.name}")

@bot.command()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    conf = get_config()
    mod_roles = conf['modules']['mod'].get('roles', [])
    user_roles = [str(r.id) for r in ctx.author.roles]
    if any(rid in mod_roles for rid in user_roles) or ctx.author.guild_permissions.moderate_members:
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.send(f"⏳ Timeout: {member.name} for {minutes}m")

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "lava_elite_v4"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Lava.Net Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #09090b; --side: #0e0e11; --card: #14151a; --accent: #ff4d4d; --border: #27282e; --text: #ececec; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; }
        .sidebar { width: 260px; background: var(--side); border-right: 1px solid var(--border); padding: 30px 20px; flex-shrink: 0; }
        .main { flex: 1; padding: 40px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; border-bottom: 1px solid var(--border); padding-bottom: 15px; }
        .module-card { background: var(--card); border-radius: 12px; padding: 25px; margin-bottom: 25px; border: 1px solid var(--border); }
        .btn-save { background: var(--accent); color: white; border: none; padding: 12px 30px; border-radius: 6px; cursor: pointer; float: right; font-weight: bold; }
        .selector { height: 120px; overflow-y: auto; background: #09090b; border: 1px solid #333; padding: 10px; border-radius: 8px; margin-top: 10px; }
        input, select, textarea { width: 100%; padding: 10px; background: #09090b; border: 1px solid #333; color: white; border-radius: 6px; margin: 8px 0; }
    </style>
</head>
<body>
    {% if not session.user %}
    <div style="margin: 100px auto; width: 300px; text-align: center; background: var(--card); padding: 30px; border-radius: 15px; border: 1px solid var(--accent);">
        <h1 style="color:var(--accent)">LAVA AUTH</h1>
        <form method="POST">
            <input type="text" name="username" placeholder="User" required>
            <input type="password" name="key" placeholder="Key" required>
            <button class="btn-save" style="float:none; width:100%">LOGIN</button>
        </form>
    </div>
    {% else %}
    <div class="sidebar">
        <h2 style="color:var(--accent)">LAVA.NET</h2>
        <a href="#" style="color:white; text-decoration:none; display:block; margin: 20px 0;">Dashboard</a>
        <a href="/logout" style="color:#444; text-decoration:none;">Logout</a>
    </div>
    <div class="main">
        <div class="header">
            <h1>Elite Dashboard</h1>
            <div style="color:var(--accent); font-weight:bold;">USER: {{ session.user }}</div>
        </div>
        <form method="POST">
            <input type="hidden" name="save" value="true">
            <input type="hidden" name="auth_verify" value="10">
            
            <div class="module-card">
                <h3>Global Config</h3>
                Prefix: <select name="prefix">
                    <option value="!" {% if config.prefix == '!' %}selected{% endif %}>!</option>
                    <option value="." {% if config.prefix == '.' %}selected{% endif %}>.</option>
                </select>
                Status: <input type="text" name="status" value="{{ config.status }}">
            </div>

            <div class="module-card">
                <h3>Link Filter</h3>
                Enabled: <select name="lf_enabled"><option value="True" {% if config.modules.link_filter.enabled == 'True' %}selected{% endif %}>ON</option><option value="False" {% if config.modules.link_filter.enabled == 'False' %}selected{% endif %}>OFF</option></select>
                Whitelist Channels:
                <div class="selector">
                    {% for c in discord.channels %}
                    <div><input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}> {{ c.name }}</div>
                    {% endfor %}
                </div>
            </div>

            <div class="module-card">
                <h3>Help Command & Aliases</h3>
                Enabled: <select name="h_enabled"><option value="True" {% if config.modules.help.enabled == 'True' %}selected{% endif %}>ON</option></select>
                Aliases (comma separated): <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                Help Text: <textarea name="h_text">{{ config.modules.help.text }}</textarea>
            </div>

            <div class="module-card">
                <h3>Moderation (Roles)</h3>
                Whitelist Roles for Mod-Commands:
                <div class="selector">
                    {% for r in discord.roles %}
                    <div><input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}> {{ r.name }}</div>
                    {% endfor %}
                </div>
            </div>

            <button type="submit" class="btn-save">SAVE ALL SETTINGS</button>
        </form>
    </div>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    conf = get_config()
    guild = bot.guilds[0] if bot.guilds else None
    discord_data = {
        "channels": [{"id": c.id, "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": r.id, "name": r.name} for r in guild.roles if not r.managed and r.name != "@everyone"] if guild else []
    }

    if request.method == "POST":
        if "username" in request.form:
            if request.form.get("key") == "10":
                session['user'] = request.form.get("username").upper()
                return redirect(url_for('index'))
        
        if request.form.get("save") and request.form.get("auth_verify") == "10":
            updates = {
                "prefix": request.form.get("prefix"),
                "status": request.form.get("status"),
                "modules.link_filter.enabled": request.form.get("lf_enabled"),
                "modules.link_filter.chans": request.form.getlist("lf_chans"),
                "modules.help.enabled": request.form.get("h_enabled"),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.mod.roles": request.form.getlist("mod_roles")
            }
            config_col.update_one({"id": "bot_config"}, {"$set": updates})
            asyncio.run_coroutine_threadsafe(bot.change_presence(activity=discord.Game(name=updates['status'])), bot.loop)
            return redirect(url_for('index'))

    return render_template_string(HTML_TEMPLATE, config=conf, discord=discord_data)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
