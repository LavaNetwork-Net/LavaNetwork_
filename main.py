import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect, url_for
import threading
import os
from pymongo import MongoClient
import asyncio

# --- DATABASE REPAIR LOGIC ---
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['lavabot_db']
config_col = db['settings']

def get_config():
    conf = config_col.find_one({"id": "bot_config"})
    # If config doesn't exist OR is missing the new modules structure, reset/update it
    if not conf or 'modules' not in conf:
        default = {
            "id": "bot_config",
            "prefix": "!",
            "status": "LavaClient Online",
            "modules": {
                "link_filter": {"enabled": "False", "channels": [], "roles": []},
                "mod": {"enabled": "True", "channels": [], "roles": []},
                "help": {"enabled": "True", "channels": [], "roles": []}
            }
        }
        config_col.update_one({"id": "bot_config"}, {"$set": default}, upsert=True)
        return default
    return conf

# --- BOT SETUP ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    
    # LINK FILTER LOGIC
    lf = conf['modules'].get('link_filter', {})
    if lf.get("enabled") == "True" and "http" in message.content:
        # Check if channel whitelist is empty (means all) or if current channel is in it
        if not lf.get("channels") or str(message.channel.id) in lf["channels"]:
            # Admins and Whitelisted Roles bypass
            is_whitelisted = any(str(r.id) in lf.get("roles", []) for r in message.author.roles)
            if not message.author.guild_permissions.administrator and not is_whitelisted:
                await message.delete()
                return

    await bot.process_commands(message)

# --- WEB PANEL ---
app = Flask(__name__)
app.secret_key = "lava_elite_key_2026"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Lava.Net | Elite Panel</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3e3e; --text: #ececec; --border: #1a1a1a; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        
        .sidebar { width: 240px; background: var(--side); border-right: 1px solid var(--border); padding: 25px; display: flex; flex-direction: column; }
        .logo { font-size: 24px; font-weight: 900; color: var(--accent); margin-bottom: 40px; text-transform: uppercase; }
        
        .nav-link { padding: 12px; color: #666; text-decoration: none; border-radius: 8px; margin-bottom: 8px; transition: 0.2s; display: flex; align-items: center; gap: 12px; }
        .nav-link:hover, .nav-link.active { background: #151515; color: white; }

        .main { flex: 1; padding: 40px; overflow-y: auto; background: linear-gradient(135deg, #050505 0%, #0f0f0f 100%); }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 40px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
        .user-tag { background: #151515; padding: 10px 20px; border-radius: 50px; border: 1px solid #222; font-weight: 600; color: var(--accent); }

        .module-card { background: var(--card); border-radius: 15px; padding: 30px; margin-bottom: 30px; border: 1px solid var(--border); }
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 20px; }
        
        label { display: block; font-size: 11px; color: #444; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; font-weight: 800; }
        select, input { width: 100%; background: #080808; border: 1px solid #222; color: white; padding: 14px; border-radius: 8px; box-sizing: border-box; }
        
        .selector-list { height: 150px; overflow-y: auto; background: #080808; border: 1px solid #222; border-radius: 8px; padding: 10px; }
        .selector-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 13px; color: #ccc; }

        .btn-save { background: var(--accent); color: white; border: none; padding: 14px 30px; border-radius: 8px; cursor: pointer; font-weight: bold; float: right; transition: 0.3s; }
        .btn-save:hover { transform: scale(1.05); box-shadow: 0 0 20px rgba(255, 62, 62, 0.4); }

        .login-screen { width: 100%; height: 100vh; display: flex; align-items: center; justify-content: center; background: #000; }
        .login-card { background: var(--card); padding: 40px; border-radius: 20px; border: 1px solid var(--accent); width: 350px; text-align: center; }
    </style>
</head>
<body>
    {% if not session.user %}
    <div class="login-screen">
        <div class="login-card">
            <h1 style="color:var(--accent)">LAVA AUTH</h1>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required style="margin-bottom:15px">
                <input type="password" name="access_key" placeholder="Access Key" required style="margin-bottom:20px">
                <button class="btn-save" style="float:none; width:100%">BOOT SYSTEM</button>
            </form>
        </div>
    </div>
    {% else %}
    <div class="sidebar">
        <div class="logo">LAVA.NET</div>
        <a href="#" class="nav-link active"><i class="fas fa-home"></i> Dashboard</a>
        <a href="#" class="nav-link"><i class="fas fa-shield-alt"></i> Security</a>
        <a href="#" class="nav-link"><i class="fas fa-list"></i> Audit Logs</a>
        <a href="/logout" class="nav-link" style="margin-top:auto"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>

    <div class="main">
        <div class="header">
            <div><h1 style="margin:0">Elite Management</h1><p style="color:#444; margin:5px 0 0">System Online and Synchronized</p></div>
            <div class="user-tag"><i class="fas fa-user-circle"></i> {{ session.user }}</div>
        </div>

        <form method="POST">
            <input type="hidden" name="save_action" value="true">
            
            <div class="module-card">
                <h2 style="margin-top:0">Core Configuration</h2>
                <div class="settings-grid">
                    <div>
                        <label>Command Prefix</label>
                        <select name="prefix">
                            <option value="!" {% if config.prefix == '!' %}selected{% endif %}>! (Exclamation)</option>
                            <option value="." {% if config.prefix == '.' %}selected{% endif %}>. (Period)</option>
                            <option value="?" {% if config.prefix == '?' %}selected{% endif %}>? (Question)</option>
                            <option value="/" {% if config.prefix == '/' %}selected{% endif %}>/ (Slash)</option>
                        </select>
                    </div>
                    <div>
                        <label>Bot Activity Status</label>
                        <input type="text" name="status" value="{{ config.status }}">
                    </div>
                </div>
            </div>

            <div class="module-card">
                <div style="display:flex; justify-content:space-between; align-items:center">
                    <h2 style="margin:0">Link Filter Module</h2>
                    <select name="lf_enabled" style="width:100px">
                        <option value="True" {% if config.modules.link_filter.enabled == 'True' %}selected{% endif %}>ACTIVE</option>
                        <option value="False" {% if config.modules.link_filter.enabled == 'False' %}selected{% endif %}>DISABLED</option>
                    </select>
                </div>
                
                <div class="settings-grid">
                    <div>
                        <label>Restrict to Channels</label>
                        <div class="selector-list">
                            {% for chan in channels %}
                            <div class="selector-item">
                                <input type="checkbox" name="lf_chans" value="{{ chan.id }}" {% if chan.id|string in config.modules.link_filter.channels %}checked{% endif %}> {{ chan.name }}
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    <div>
                        <label>Whitelist Roles (Bypass)</label>
                        <div class="selector-list">
                            {% for role in roles %}
                            <div class="selector-item">
                                <input type="checkbox" name="lf_roles" value="{{ role.id }}" {% if role.id|string in config.modules.link_filter.roles %}checked{% endif %}> {{ role.name }}
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
                <div style="margin-top:20px; overflow:hidden">
                    <button type="submit" class="btn-save">DEPLOY CHANGES</button>
                </div>
            </div>
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
    channels = [{"id": c.id, "name": c.name} for c in guild.text_channels] if guild else []
    roles = [{"id": r.id, "name": r.name} for r in guild.roles if not r.managed] if guild else []

    if request.method == "POST":
        if "username" in request.form:
            if request.form.get("access_key") == "10":
                session['user'] = request.form.get("username").upper()
                return redirect(url_for('index'))
        
        if request.form.get("save_action"):
            lf_chans = request.form.getlist("lf_chans")
            lf_roles = request.form.getlist("lf_roles")
            
            update_data = {
                "prefix": request.form.get("prefix"),
                "status": request.form.get("status"),
                "modules.link_filter.enabled": request.form.get("lf_enabled"),
                "modules.link_filter.channels": lf_chans,
                "modules.link_filter.roles": lf_roles
            }
            config_col.update_one({"id": "bot_config"}, {"$set": update_data})
            
            # Update Live Bot
            asyncio.run_coroutine_threadsafe(bot.change_presence(activity=discord.Game(name=request.form.get("status"))), bot.loop)
            bot.command_prefix = request.form.get("prefix")
            return redirect(url_for('index'))

    return render_template_string(HTML_TEMPLATE, config=conf, channels=channels, roles=roles)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
