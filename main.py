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
config_col = db['guild_configs'] # Jetzt pro Server!

def get_guild_config(guild_id):
    conf = config_col.find_one({"guild_id": str(guild_id)})
    if not conf:
        default = {
            "guild_id": str(guild_id), "prefix": "!", "status": "LavaNetwork",
            "modules": {
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "True", "roles": []},
                "help": {"enabled": "True", "aliases": "help", "text": "Wir sind bald Fertig!"}
            }
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT SETUP ---
intents = discord.Intents.all()
async def get_prefix(bot, message):
    if not message.guild: return "!"
    conf = get_guild_config(message.guild.id)
    return conf.get("prefix", "!")

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild: return
    
    conf = get_guild_config(message.guild.id)
    prefix = conf.get("prefix", "!")
    
    # Link Filter
    if conf['modules']['link_filter']['enabled'] == "True" and "http" in message.content:
        lf = conf['modules']['link_filter']
        if not lf['chans'] or str(message.channel.id) in lf['chans']:
            user_roles = [str(r.id) for r in message.author.roles]
            if not any(rid in lf['roles'] for rid in user_roles) and not message.author.guild_permissions.administrator:
                await message.delete()
                return

    # Help Aliases
    hp = conf['modules']['help']
    aliases = [a.strip().lower() for a in hp.get("aliases", "help").split(",")]
    if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
        await message.channel.send(hp.get("text", "Online!"))
        return

    await bot.process_commands(message)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "lava_multi_v8"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Lava Client</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #060606; --side: #0b0b0b; --card: #121212; --accent: #ff3333; --border: #1e1e1e; --text: #f0f0f0; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; display: flex; height: 100vh; }
        .sidebar { width: 240px; background: var(--side); border-right: 1px solid var(--border); padding: 25px; flex-shrink: 0; }
        .nav-btn { width: 100%; padding: 14px; background: none; border: none; color: #666; text-align: left; cursor: pointer; border-radius: 8px; margin-bottom: 8px; }
        .nav-btn.active { background: #1a1a1a; color: var(--accent); font-weight: bold; }
        .main { flex: 1; padding: 40px; overflow-y: auto; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 20px; transition: 0.3s; }
        .guild-select-card:hover { border-color: var(--accent); cursor: pointer; transform: translateY(-3px); }
        .row { display: flex; align-items: center; gap: 12px; padding: 10px; border-bottom: 1px solid #1a1a1a; }
        input, textarea { width: 100%; padding: 12px; background: #000; border: 1px solid #222; color: white; border-radius: 5px; margin-top: 8px; }
        .btn-save { background: var(--accent); color: white; border: none; padding: 15px 40px; border-radius: 8px; cursor: pointer; font-weight: bold; position: fixed; bottom: 30px; right: 30px; }
    </style>
</head>
<body>
    {% if not session.user %}
    <div style="margin: auto; width: 320px; background: var(--card); padding: 30px; border-radius: 15px; border: 1px solid var(--accent); text-align: center;">
        <h2 style="color:var(--accent)">LAVA ACCESS</h2>
        <form method="POST"><input type="text" name="user" placeholder="Name" required><br><input type="password" name="pw" placeholder="Key" required><br><br><button class="btn-save" style="position:static; width:100%">LOGIN</button></form>
    </div>
    {% elif not session.guild_id %}
    <div class="main" style="text-align: center;">
        <h1 style="color:var(--accent)">Select Server</h1>
        <p>Choose the server you want to configure:</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 20px; margin-top: 30px;">
            {% for g in guilds %}
            <div class="card guild-select-card" onclick="location.href='/select/'+'{{ g.id }}'">
                <div style="font-size: 40px; margin-bottom: 10px;"><i class="fas fa-server"></i></div>
                <div style="font-weight: bold; font-size: 18px;">{{ g.name }}</div>
                <div style="color: #555; font-size: 12px;">ID: {{ g.id }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% else %}
    <div class="sidebar">
        <h2 style="color:var(--accent)">LAVA CLIENT</h2>
        <p style="font-size: 11px; color: #444;">Server: {{ guild_name }}</p>
        <button class="nav-btn active" onclick="location.href='/'">Dashboard</button>
        <button class="nav-btn" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i> Change Server</button>
        <a href="/logout" class="nav-btn" style="text-decoration:none; display:block; margin-top: 50px;">Logout</a>
    </div>
    <div class="main">
        <form method="POST">
            <input type="hidden" name="action" value="save">
            <div class="card">
                <h3>Global ({{ guild_name }})</h3>
                Prefix: <input type="text" name="prefix" value="{{ config.prefix }}">
                Status: <input type="text" name="status" value="{{ config.status }}">
            </div>
            <div class="card">
                <h3>Help Module</h3>
                Aliases: <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                Text: <textarea name="h_text">{{ config.modules.help.text }}</textarea>
            </div>
            <div class="card">
                <h3>Permissions (Roles)</h3>
                <div style="max-height: 200px; overflow-y: auto;">
                    {% for r in roles %}
                    <div class="row">
                        <input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>
                        <span>{{ r.name }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <button type="submit" class="btn-save">SAVE CONFIG</button>
        </form>
    </div>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "pw" in request.form and request.form.get("pw") == "10":
            session['user'] = request.form.get("user")
            return redirect(url_for('index'))
        
        if request.form.get("action") == "save":
            updates = {
                "prefix": request.form.get("prefix"),
                "status": request.form.get("status"),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.mod.roles": request.form.getlist("mod_roles")
            }
            config_col.update_one({"guild_id": session['guild_id']}, {"$set": updates})
            return redirect(url_for('index'))

    guilds = [{"name": g.name, "id": str(g.id)} for g in bot.guilds]
    
    conf = None
    roles = []
    guild_name = ""
    if 'guild_id' in session:
        conf = get_guild_config(session['guild_id'])
        g = bot.get_guild(int(session['guild_id']))
        if g:
            guild_name = g.name
            roles = [{"id": r.id, "name": r.name} for r in g.roles if not r.managed and r.name != "@everyone"]

    return render_template_string(HTML_TEMPLATE, config=conf, guilds=guilds, roles=roles, guild_name=guild_name)

@app.route("/select/<guild_id>")
def select_guild(guild_id):
    session['guild_id'] = guild_id
    return redirect(url_for('index'))

@app.route("/change_server")
def change_server():
    session.pop('guild_id', None)
    return redirect(url_for('index'))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
