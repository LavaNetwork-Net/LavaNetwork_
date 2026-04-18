import discord
from discord.ext import commands
from flask import Flask, request, render_template_string
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
            "id": "bot_config",
            "prefix": "!",
            "status_text": "LavaClient v4.0",
            # Module Switches
            "mod_enabled": "True",
            "help_enabled": "True",
            # Command Settings
            "help_aliases": "help,list,commands,hilfe",
            "help_text": "Hier sind alle Befehle: !info, !hallo, !ban, !kick",
            "info_text": "LavaClient Premium System",
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT LOGIC ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Dynamischer Help-Befehl (reagiert auf konfigurierte Aliase)
@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    prefix = conf.get("prefix", "!")
    content = message.content.lower()

    # Prüfung für Help-Aliase
    if conf.get("help_enabled") == "True":
        aliases = [a.strip() for a in conf.get("help_aliases", "help").split(",")]
        for alias in aliases:
            if content == f"{prefix}{alias.lower()}":
                await message.channel.send(f"**{conf.get('help_text')}**")
                return

    await bot.process_commands(message)

# --- MODERATION COMMANDS ---
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    if get_config().get("mod_enabled") == "True":
        await member.kick(reason=reason)
        await ctx.send(f"✅ {member.display_name} wurde gekickt. Grund: {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    if get_config().get("mod_enabled") == "True":
        await member.ban(reason=reason)
        await ctx.send(f"🚫 {member.display_name} wurde gebannt. Grund: {reason}")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    if get_config().get("mod_enabled") == "True":
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.send(f"⏳ {member.display_name} ist im Timeout für {minutes} Minuten. Grund: {reason}")

# --- WEB UI (ELITE DESIGN) ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LavaClient Elite Panel</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #0a0b0d; --side: #111216; --card: #181a20; --accent: #ff4d4d; --text: #ffffff; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; }
        .sidebar { width: 260px; background: var(--side); padding: 30px 15px; border-right: 1px solid #222; }
        .nav-item { padding: 12px 15px; border-radius: 10px; cursor: pointer; color: #888; display: flex; align-items: center; gap: 12px; margin-bottom: 5px; transition: 0.2s; text-decoration: none; }
        .nav-item:hover, .nav-item.active { background: #1f2128; color: var(--accent); }
        
        .main { flex: 1; padding: 40px; overflow-y: auto; background: radial-gradient(circle at top right, #15161c, #0a0b0d); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 25px; }
        .glass-card { background: var(--card); border: 1px solid #282a32; border-radius: 15px; padding: 25px; }
        .glass-card h3 { margin: 0 0 20px 0; color: var(--accent); border-bottom: 1px solid #222; padding-bottom: 10px; }

        input, textarea { width: 100%; padding: 12px; background: #0a0b0d; border: 1px solid #333; color: white; border-radius: 8px; margin: 10px 0; box-sizing: border-box; }
        .switch-box { display: flex; justify-content: space-between; align-items: center; background: #111216; padding: 10px 15px; border-radius: 8px; margin-bottom: 15px; }
        .btn-save { position: fixed; bottom: 30px; right: 30px; background: var(--accent); color: white; border: none; padding: 15px 35px; border-radius: 50px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 15px rgba(255, 77, 77, 0.3); }

        /* Toggle */
        .switch { position: relative; display: inline-block; width: 45px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #333; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: var(--accent); }
        input:checked + .slider:before { transform: translateX(21px); }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--accent); margin-bottom:40px;"><i class="fas fa-fire"></i> LavaClient</h2>
        <a href="#" class="nav-item active"><i class="fas fa-hammer"></i> Moderation</a>
        <a href="#" class="nav-item"><i class="fas fa-book"></i> Commands</a>
        <a href="#" class="nav-item"><i class="fas fa-cog"></i> Core Settings</a>
    </div>

    <div class="main">
        <h1>Hey Joshua! 👋</h1>
        <form method="POST">
            <input type="hidden" name="key" value="10">
            <input type="hidden" name="save" value="true">
            
            <div class="grid">
                <div class="glass-card">
                    <h3><i class="fas fa-gavel"></i> Mod System</h3>
                    <div class="switch-box">
                        <span>Ban/Kick/Timeout Aktiv</span>
                        <label class="switch">
                            <input type="checkbox" name="mod_enabled" value="True" {% if config.mod_enabled == 'True' %}checked{% endif %}>
                            <span class="slider"></span>
                        </label>
                    </div>
                    <p style="font-size: 12px; color: #666;">Befehle: <code>!kick @user</code>, <code>!ban @user</code>, <code>!timeout @user 10</code></p>
                </div>

                <div class="glass-card">
                    <h3><i class="fas fa-terminal"></i> Help Command</h3>
                    <div class="switch-box">
                        <span>Modul Aktiv</span>
                        <label class="switch">
                            <input type="checkbox" name="help_enabled" value="True" {% if config.help_enabled == 'True' %}checked{% endif %}>
                            <span class="slider"></span>
                        </label>
                    </div>
                    Aliase (mit Komma trennen):
                    <input type="text" name="help_aliases" value="{{ config.help_aliases }}" placeholder="help, list, info...">
                    Antwort-Text:
                    <textarea name="help_text" rows="3">{{ config.help_text }}</textarea>
                </div>

                <div class="glass-card">
                    <h3><i class="fas fa-sliders"></i> Global Settings</h3>
                    Prefix:
                    <input type="text" name="prefix" value="{{ config.prefix }}">
                    Bot Status:
                    <input type="text" name="status_text" value="{{ config.status_text }}">
                </div>
            </div>
            <button type="submit" class="btn-save">ÄNDERUNGEN SPEICHERN</button>
        </form>
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    auth = False
    conf = get_config()
    if request.method == "POST":
        if request.form.get("key") == "10":
            auth = True
            if request.form.get("save"):
                # Checkboxen Handling
                new_data = {
                    "mod_enabled": "False",
                    "help_enabled": "False",
                    "help_aliases": request.form.get("help_aliases"),
                    "help_text": request.form.get("help_text"),
                    "prefix": request.form.get("prefix"),
                    "status_text": request.form.get("status_text")
                }
                for key in request.form:
                    if key in new_data: new_data[key] = request.form[key]
                
                config_col.update_one({"id": "bot_config"}, {"$set": new_data})
                asyncio.run_coroutine_threadsafe(bot.change_presence(activity=discord.Game(name=new_data['status_text'])), bot.loop)
                conf = get_config()
    return render_template_string(HTML_TEMPLATE, auth=auth, config=conf)

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
