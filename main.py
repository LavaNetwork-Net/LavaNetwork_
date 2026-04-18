import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect, url_for
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta

# --- DB SETUP ---
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
                "help": {"enabled": "True", "aliases": "help", "text": "Help Text"}
            }
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    # Link Filter Logik
    if conf['modules']['link_filter']['enabled'] == "True" and "http" in message.content:
        # Check Whitelist
        if not conf['modules']['link_filter']['chans'] or str(message.channel.id) in conf['modules']['link_filter']['chans']:
            user_roles = [str(r.id) for r in message.author.roles]
            if not any(rid in conf['modules']['link_filter']['roles'] for rid in user_roles):
                await message.delete()
    await bot.process_commands(message)

# --- WEB GUI ---
app = Flask(__name__)
app.secret_key = "lava_ultimate_v5"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Lava Network</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3e3e; --border: #1a1a1a; --text: #ececec; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        
        .sidebar { width: 220px; background: var(--side); border-right: 1px solid var(--border); padding: 30px 15px; flex-shrink: 0; }
        .nav-btn { width: 100%; padding: 12px; background: none; border: none; color: #555; text-align: left; font-size: 16px; cursor: pointer; border-radius: 8px; margin-bottom: 5px; transition: 0.2s; }
        .nav-btn:hover, .nav-btn.active { background: #151515; color: var(--accent); }

        .content { flex: 1; padding: 40px; overflow-y: auto; display: none; }
        .content.active { display: block; }

        .module-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; margin-bottom: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }

        /* Compact List Fix */
        .item-row { display: flex; align-items: center; gap: 10px; padding: 5px 0; font-size: 14px; border-bottom: 1px solid #161616; }
        .item-row input { width: 16px; height: 16px; margin: 0; cursor: pointer; }

        input[type="text"], select, textarea { width: 100%; padding: 12px; background: #080808; border: 1px solid #222; color: white; border-radius: 6px; margin-top: 10px; }
        .btn-save { background: var(--accent); color: white; border: none; padding: 12px 25px; border-radius: 6px; cursor: pointer; font-weight: bold; float: right; margin-top: 10px; }
        
        .login-screen { width: 100%; display: flex; justify-content: center; align-items: center; height: 100vh; }
    </style>
    <script>
        function showPage(pageId, btn) {
            document.querySelectorAll('.content').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(pageId).classList.add('active');
            btn.classList.add('active');
        }
    </script>
</head>
<body>
    {% if not session.user %}
    <div class="login-screen">
        <div class="module-card" style="width: 300px; text-align: center;">
            <h2 style="color:var(--accent)">LAVA LOGIN</h2>
            <form method="POST"><input type="text" name="user" placeholder="User" required><input type="password" name="pw" placeholder="Key" required><button class="btn-save" style="float:none; width:100%">BOOT</button></form>
        </div>
    </div>
    {% else %}
    <div class="sidebar">
        <h2 style="color:var(--accent); margin-bottom: 40px;">LAVA CLIENT 🌋</h2>
        <button class="nav-btn active" onclick="showPage('dash', this)"><i class="fas fa-home"></i> Dashboard</button>
        <button class="nav-btn" onclick="showPage('sett', this)"><i class="fas fa-cog"></i> Settings</button>
        <a href="/logout" class="nav-btn" style="text-decoration:none; margin-top: 50px; display:block;"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>

    <div class="main-wrapper" style="flex:1;">
        <form method="POST">
            <input type="hidden" name="save_all" value="true">
            
            <div id="dash" class="content active">
                <div class="header"><h1>Dashboard</h1><span style="color:#444">User: {{ session.user }}</span></div>
                <div class="module-card">
                    <h3>Bot Status & Prefix</h3>
                    Prefix: <select name="prefix"><option value="!" {% if config.prefix == '!' %}selected{% endif %}>!</option><option value="." {% if config.prefix == '.' %}selected{% endif %}>.</option></select>
                    Status: <input type="text" name="status" value="{{ config.status }}">
                </div>
                <div class="module-card">
                    <h3>Help Module</h3>
                    Aliases: <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                    Text: <textarea name="h_text">{{ config.modules.help.text }}</textarea>
                </div>
            </div>

            <div id="sett" class="content">
                <div class="header"><h1>Settings</h1></div>
                <div class="module-card">
                    <h3>Link Filter (Channels)</h3>
                    <p style="font-size:12px; color:#555;">Klicke Kanäle an, in denen Links verboten sind:</p>
                    <div style="max-height: 200px; overflow-y: auto;">
                        {% for c in discord.channels %}
                        <div class="item-row">
                            <input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}>
                            <span>{{ c.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <div class="module-card">
                    <h3>Moderation (Roles)</h3>
                    <p style="font-size:12px; color:#555;">Diese Rollen dürfen Mod-Befehle nutzen:</p>
                    <div style="max-height: 200px; overflow-y: auto;">
                        {% for r in discord.roles %}
                        <div class="item-row">
                            <input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>
                            <span>{{ r.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <div style="position: fixed; bottom: 30px; right: 30px;">
                <button type="submit" class="btn-save" style="font-size:18px; padding: 15px 40px;">SAVE SYSTEM</button>
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
    discord_data = {
        "channels": [{"id": c.id, "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": r.id, "name": r.name} for r in guild.roles if not r.managed and r.name != "@everyone"] if guild else []
    }

    if request.method == "POST":
        if "user" in request.form:
            if request.form.get("pw") == "10":
                session['user'] = request.form.get("user").upper()
                return redirect(url_for('index'))
        
        if request.form.get("save_all"):
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

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
