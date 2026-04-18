import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect, url_for
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta

# --- DATABASE ---
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
            "status": "LavaClient Active",
            "modules": {
                "help": {"enabled": "True", "channels": [], "roles": []},
                "link_filter": {"enabled": "False", "channels": [], "roles": []},
                "mod": {"enabled": "True", "channels": [], "roles": []}
            }
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Helper to check permissions
def has_module_perms(ctx, module_name):
    conf = get_config()
    mod = conf['modules'].get(module_name, {})
    if mod.get("enabled") != "True": return False
    
    # Check Channel
    if mod.get("channels") and str(ctx.channel.id) not in mod["channels"]: return False
    
    # Check Roles (Admins always allowed)
    if ctx.author.guild_permissions.administrator: return True
    if mod.get("roles"):
        user_role_ids = [str(r.id) for r in ctx.author.roles]
        if not any(rid in mod["roles"] for rid in user_role_ids): return False
    
    return True

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    
    # Link Filter Logic
    lf = conf['modules'].get('link_filter', {})
    if lf.get("enabled") == "True" and "http" in message.content:
        # Check if channel is restricted
        if not lf.get("channels") or str(message.channel.id) in lf["channels"]:
            if not message.author.guild_permissions.administrator:
                await message.delete()
                return

    await bot.process_commands(message)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "lava_secret_key"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LavaClient | Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3e3e; --text: #ececec; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; }
        
        .sidebar { width: 240px; background: var(--side); border-right: 1px solid #1a1a1a; padding: 25px; }
        .logo { font-size: 22px; font-weight: 900; color: var(--accent); margin-bottom: 40px; letter-spacing: 1px; }
        
        .main { flex: 1; padding: 40px; overflow-y: auto; }
        .nav-link { display: block; padding: 12px; color: #666; text-decoration: none; border-radius: 8px; margin-bottom: 5px; transition: 0.2s; }
        .nav-link:hover, .nav-link.active { background: #151515; color: white; }

        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 40px; }
        .user-tag { background: #151515; padding: 8px 15px; border-radius: 50px; border: 1px solid #222; font-size: 14px; }

        .module-card { background: var(--card); border-radius: 12px; padding: 25px; margin-bottom: 25px; border: 1px solid #1a1a1a; position: relative; }
        .module-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        label { display: block; font-size: 12px; color: #555; text-transform: uppercase; margin-bottom: 8px; font-weight: bold; }
        
        select, input, textarea { width: 100%; background: #080808; border: 1px solid #222; color: white; padding: 12px; border-radius: 6px; outline: none; }
        select:focus, input:focus { border-color: var(--accent); }

        .btn-save { background: var(--accent); color: white; border: none; padding: 12px 25px; border-radius: 6px; cursor: pointer; font-weight: bold; float: right; }
        
        /* Multi-select box style */
        .select-box { height: 100px; overflow-y: auto; border: 1px solid #222; border-radius: 6px; padding: 5px; }
        .select-box div { font-size: 13px; padding: 5px; display: flex; align-items: center; gap: 8px; }

        .login-box { width: 350px; margin: 150px auto; background: var(--card); padding: 30px; border-radius: 12px; border: 1px solid #222; }
    </style>
</head>
<body>
    {% if not session.user %}
    <div class="login-box">
        <h2 style="color:var(--accent)">System Auth</h2>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required><br>
            <input type="password" name="key" placeholder="Access Key" required><br>
            <button class="btn-save" style="float:none; width:100%">LOGIN</button>
        </form>
    </div>
    {% else %}
    <div class="sidebar">
        <div class="logo">LAVA.NET</div>
        <a href="#" class="nav-link active">Dashboard</a>
        <a href="#" class="nav-link">Security</a>
        <a href="#" class="nav-link">Logs</a>
    </div>

    <div class="main">
        <div class="header">
            <h1>Server Management</h1>
            <div class="user-tag"><i class="fas fa-user"></i> {{ session.user }}</div>
        </div>

        <form method="POST">
            <input type="hidden" name="save_settings" value="true">
            
            <div class="module-card">
                <h3>Global Config</h3>
                <div class="settings-grid">
                    <div>
                        <label>Prefix</label>
                        <select name="prefix">
                            <option value="!" {% if config.prefix == '!' %}selected{% endif %}>! (Exclamation)</option>
                            <option value="." {% if config.prefix == '.' %}selected{% endif %}>. (Dot)</option>
                            <option value="?" {% if config.prefix == '?' %}selected{% endif %}>? (Question)</option>
                            <option value="/" {% if config.prefix == '/' %}selected{% endif %}>/ (Slash)</option>
                        </select>
                    </div>
                    <div>
                        <label>Bot Status</label>
                        <input type="text" name="status" value="{{ config.status }}">
                    </div>
                </div>
            </div>

            <div class="module-card">
                <div class="module-header">
                    <h3>Link Filter</h3>
                    <select name="mod_lf_enabled" style="width: 100px;">
                        <option value="True" {% if config.modules.link_filter.enabled == 'True' %}selected{% endif %}>ON</option>
                        <option value="False" {% if config.modules.link_filter.enabled == 'False' %}selected{% endif %}>OFF</option>
                    </select>
                </div>
                <div class="settings-grid">
                    <div>
                        <label>Allowed Channels</label>
                        <div class="select-box">
                            {% for chan in channels %}
                            <div><input type="checkbox" name="lf_chans" value="{{ chan.id }}" {% if chan.id|string in config.modules.link_filter.channels %}checked{% endif %}> {{ chan.name }}</div>
                            {% endfor %}
                        </div>
                    </div>
                    <div>
                        <label>Allowed Roles (Bypass)</label>
                        <div class="select-box">
                            {% for role in roles %}
                            <div><input type="checkbox" name="lf_roles" value="{{ role.id }}" {% if role.id|string in config.modules.link_filter.roles %}checked{% endif %}> {{ role.name }}</div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
                <button class="btn-save">Update Module</button>
                <div style="clear:both"></div>
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
    # Fetch real data from discord
    guild = bot.guilds[0] if bot.guilds else None
    channels = [{"id": c.id, "name": c.name} for c in guild.text_channels] if guild else []
    roles = [{"id": r.id, "name": r.name} for r in guild.roles if not r.managed] if guild else []

    if request.method == "POST":
        if "username" in request.form:
            if request.form.get("key") == "10":
                session['user'] = request.form.get("username")
                return redirect(url_for('index'))
        
        if request.form.get("save_settings"):
            new_prefix = request.form.get("prefix")
            new_status = request.form.get("status")
            
            # Update DB logic for modules
            lf_chans = request.form.getlist("lf_chans")
            lf_roles = request.form.getlist("lf_roles")
            lf_enabled = request.form.get("mod_lf_enabled")

            update_dict = {
                "prefix": new_prefix,
                "status": new_status,
                "modules.link_filter.enabled": lf_enabled,
                "modules.link_filter.channels": lf_chans,
                "modules.link_filter.roles": lf_roles
            }
            config_col.update_one({"id": "bot_config"}, {"$set": update_dict})
            
            # Apply bot status
            asyncio.run_coroutine_threadsafe(bot.change_presence(activity=discord.Game(name=new_status)), bot.loop)
            bot.command_prefix = new_prefix
            return redirect(url_for('index'))

    return render_template_string(HTML_TEMPLATE, config=conf, channels=channels, roles=roles)

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
