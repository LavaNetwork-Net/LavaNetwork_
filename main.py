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
    if not conf:
        default = {
            "id": "bot_config", "prefix": "!", "status": "LavaNetwork",
            "modules": {
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "True", "roles": []},
                "help": {"enabled": "True", "aliases": "help,info", "text": "Wir sind bald Fertig!"}
            }
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT SETUP ---
intents = discord.Intents.all()
def get_prefix(bot, message):
    conf = get_config()
    return conf.get("prefix", "!")

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    conf = get_config()
    prefix = conf.get("prefix", "!")
    
    # Link Filter Logik
    lf = conf['modules'].get('link_filter', {})
    if lf.get("enabled") == "True" and "http" in message.content:
        if not lf.get("chans") or str(message.channel.id) in lf["chans"]:
            user_roles = [str(r.id) for r in message.author.roles]
            if not any(rid in lf.get("roles", []) for rid in user_roles) and not message.author.guild_permissions.administrator:
                await message.delete()
                return

    # Dynamic Help Aliases Fix
    hp = conf['modules'].get('help', {})
    if hp.get("enabled") == "True":
        aliases = [a.strip().lower() for a in hp.get("aliases", "help").split(",")]
        content = message.content.lower()
        for a in aliases:
            if content == f"{prefix}{a}":
                await message.channel.send(hp.get("text", "LavaBot Online!"))
                return

    await bot.process_commands(message)

# --- MODERATION COMMANDS ---
def is_mod():
    async def predicate(ctx):
        conf = get_config()
        mod_roles = conf['modules']['mod'].get('roles', [])
        user_roles = [str(r.id) for r in ctx.author.roles]
        return any(rid in mod_roles for rid in user_roles) or ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@bot.command()
@is_mod()
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"✅ {member.name} wurde gekickt.")

@bot.command()
@is_mod()
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"🚫 {member.name} wurde gebannt.")

@bot.command()
@is_mod()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    duration = timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"⏳ {member.name} für {minutes}m im Timeout.")

# --- WEB UI (STRICT SEPARATION) ---
app = Flask(__name__)
app.secret_key = "lava_elite_final_v7"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Lava Client 🌋</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #060606; --side: #0b0b0b; --card: #121212; --accent: #ff3333; --border: #1e1e1e; --text: #f0f0f0; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 240px; background: var(--side); border-right: 1px solid var(--border); padding: 25px; flex-shrink: 0; }
        .nav-btn { width: 100%; padding: 14px; background: none; border: none; color: #666; text-align: left; font-size: 15px; cursor: pointer; border-radius: 8px; margin-bottom: 8px; transition: 0.2s; }
        .nav-btn:hover, .nav-btn.active { background: #1a1a1a; color: var(--accent); font-weight: bold; }
        .main { flex: 1; padding: 40px; overflow-y: auto; }
        .content-section { display: none; }
        .content-section.active { display: block; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 20px; }
        .row { display: flex; align-items: center; gap: 12px; padding: 10px; border-bottom: 1px solid #1a1a1a; }
        input[type="text"], textarea { width: 100%; padding: 12px; background: #000; border: 1px solid #222; color: white; border-radius: 5px; margin-top: 8px; }
        .btn-save { background: var(--accent); color: white; border: none; padding: 16px 45px; border-radius: 8px; cursor: pointer; font-weight: bold; position: fixed; bottom: 30px; right: 30px; box-shadow: 0 4px 15px rgba(255, 51, 51, 0.3); }
    </style>
    <script>
        function tab(id, el) {
            document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            el.classList.add('active');
        }
    </script>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--accent); margin-bottom: 40px;">LAVA CLIENT 🌋</h2>
        <button class="nav-btn active" onclick="tab('dash', this)"><i class="fas fa-th-large"></i> Dashboard</button>
        <button class="nav-btn" onclick="tab('sett', this)"><i class="fas fa-sliders-h"></i> Settings</button>
    </div>

    <div class="main">
        <form method="POST">
            <input type="hidden" name="action" value="save">
            
            <div id="dash" class="content-section active">
                <h1>Dashboard</h1>
                <div class="card">
                    <h3>Global Settings</h3>
                    <label>Bot Prefix:</label>
                    <input type="text" name="prefix" value="{{ config.prefix }}">
                    <br><br>
                    <label>Bot Status:</label>
                    <input type="text" name="status" value="{{ config.status }}">
                </div>
            </div>

            <div id="sett" class="content-section">
                <h1>Settings</h1>
                
                <div class="card">
                    <h3>Help Module Configuration</h3>
                    Aliases (z.B. help, info): <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                    Antwort-Text: <textarea name="h_text" rows="3">{{ config.modules.help.text }}</textarea>
                </div>

                <div class="card">
                    <h3>Link Filter (Channels)</h3>
                    <div style="max-height: 180px; overflow-y: auto; background: #080808; border-radius: 5px;">
                        {% for c in discord.channels %}
                        <div class="row">
                            <input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}>
                            <span>{{ c.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <div class="card">
                    <h3>Moderation Roles (Kick/Ban/Timeout)</h3>
                    <div style="max-height: 180px; overflow-y: auto; background: #080808; border-radius: 5px;">
                        {% for r in discord.roles %}
                        <div class="row">
                            <input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>
                            <span>{{ r.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <button type="submit" class="btn-save">DEPLOY CHANGES</button>
        </form>
    </div>
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

    if request.method == "POST" and request.form.get("action") == "save":
        updates = {
            "prefix": request.form.get("prefix"),
            "status": request.form.get("status"),
            "modules.help.aliases": request.form.get("h_aliases"),
            "modules.help.text": request.form.get("h_text"),
            "modules.link_filter.chans": request.form.getlist("lf_chans"),
            "modules.mod.roles": request.form.getlist("mod_roles")
        }
        config_col.update_one({"id": "bot_config"}, {"$set": updates})
        asyncio.run_coroutine_threadsafe(bot.change_presence(activity=discord.Game(name=updates['status'])), bot.loop)
        return redirect(url_for('index'))

    return render_template_string(HTML_TEMPLATE, config=conf, discord=discord_data)

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
