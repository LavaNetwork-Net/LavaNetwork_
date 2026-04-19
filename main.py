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
config_col = db['guild_configs']

def get_guild_config(guild_id):
    conf = config_col.find_one({"guild_id": str(guild_id)})
    if not conf:
        default = {
            "guild_id": str(guild_id), "prefix": "!", "status": "LavaNetwork",
            "modules": {
                "welcome": {"enabled": "True", "msg": "Willkommen auf dem Server!"},
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "True", "roles": []},
                "help": {"enabled": "True", "aliases": "help", "text": "LavaBot Support"}
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
    
    # Mod Check / Help Aliases etc. hier...
    hp = conf['modules']['help']
    aliases = [a.strip().lower() for a in hp.get("aliases", "help").split(",")]
    if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
        await message.channel.send(hp.get("text"))
        return
    await bot.process_commands(message)

# --- WEB UI (SIDEBAR NAVIGATION) ---
app = Flask(__name__)
app.secret_key = "lava_final_delta"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LAVA CLIENT</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3333; --border: #1a1a1a; --text: #eee; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        
        /* Sidebar */
        .sidebar { width: 260px; background: var(--side); border-right: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; }
        .sidebar h2 { color: var(--accent); font-size: 20px; margin-bottom: 30px; text-align: center; }
        .nav-group { margin-bottom: 20px; }
        .nav-label { font-size: 10px; color: #444; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; display: block; }
        .nav-btn { width: 100%; padding: 12px; background: none; border: none; color: #777; text-align: left; cursor: pointer; border-radius: 6px; transition: 0.2s; font-size: 14px; margin-bottom: 4px; }
        .nav-btn i { margin-right: 10px; width: 20px; }
        .nav-btn:hover, .nav-btn.active { background: #151515; color: var(--accent); }

        /* Content Area */
        .content-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; }
        .top-bar { padding: 20px 40px; background: var(--side); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .main-content { flex: 1; padding: 40px; overflow-y: auto; }
        .page { display: none; }
        .page.active { display: block; }

        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; margin-bottom: 20px; }
        .input-group { margin-bottom: 20px; }
        input, textarea, select { width: 100%; padding: 12px; background: #000; border: 1px solid #222; color: white; border-radius: 6px; margin-top: 8px; }
        
        /* List Rows */
        .item-row { display: flex; align-items: center; gap: 12px; padding: 10px; border-bottom: 1px solid #1a1a1a; }
        .btn-save { background: var(--accent); color: white; border: none; padding: 15px 40px; border-radius: 8px; cursor: pointer; font-weight: bold; align-self: flex-end; }
        
        .guild-card { background: var(--card); border: 1px solid var(--border); padding: 20px; border-radius: 10px; text-align: center; cursor: pointer; transition: 0.2s; }
        .guild-card:hover { border-color: var(--accent); transform: translateY(-5px); }
    </style>
    <script>
        function showPage(id, btn) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            btn.classList.add('active');
        }
    </script>
</head>
<body>
    {% if not session.user %}
    <div style="margin: auto; width: 350px; background: var(--card); padding: 40px; border-radius: 15px; border: 1px solid var(--accent);">
        <h1 style="text-align:center; color:var(--accent)">LAVA AUTH</h1>
        <form method="POST">
            <input type="text" name="user" placeholder="Admin Name" required>
            <input type="password" name="pw" placeholder="Access Key" required>
            <button class="btn-save" style="width:100%; margin-top:20px;">UNLOCK SYSTEM</button>
        </form>
    </div>
    {% elif not session.guild_id %}
    <div class="main-content" style="text-align:center;">
        <h1 style="color:var(--accent)">CHOOSE SERVER</h1>
        <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap:20px; margin-top:40px;">
            {% for g in guilds %}
            <div class="guild-card" onclick="location.href='/select/{{ g.id }}'">
                <i class="fas fa-server" style="font-size:30px; color:var(--accent)"></i>
                <div style="margin-top:15px; font-weight:bold;">{{ g.name }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% else %}
    <div class="sidebar">
        <h2>LAVA CLIENT 🌋</h2>
        
        <div class="nav-group">
            <span class="nav-label">General</span>
            <button class="nav-btn active" onclick="showPage('dash', this)"><i class="fas fa-home"></i> Dashboard</button>
            <button class="nav-btn" onclick="showPage('sett', this)"><i class="fas fa-cog"></i> Settings</button>
        </div>

        <div class="nav-group">
            <span class="nav-label">Modules</span>
            <button class="nav-btn" onclick="showPage('welcome', this)"><i class="fas fa-door-open"></i> Welcome Msg</button>
            <button class="nav-btn" onclick="showPage('help_page', this)"><i class="fas fa-question-circle"></i> Help</button>
        </div>

        <div class="nav-group">
            <span class="nav-label">Filters & Security</span>
            <button class="nav-btn" onclick="showPage('roles_page', this)"><i class="fas fa-user-shield"></i> Roles</button>
            <button class="nav-btn" onclick="showPage('chans_page', this)"><i class="fas fa-hashtag"></i> Channels</button>
            <button class="nav-btn" onclick="showPage('mod_page', this)"><i class="fas fa-hammer"></i> Kick / Ban / Time</button>
        </div>

        <div style="margin-top:auto;">
            <button class="nav-btn" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i> Server wechseln</button>
            <button class="nav-btn" onclick="location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Logout</button>
        </div>
    </div>

    <div class="content-wrapper">
        <div class="top-bar">
            <div style="font-weight:bold;">SERVER: <span style="color:var(--accent)">{{ guild_name }}</span></div>
            <div>User: {{ session.user }}</div>
        </div>

        <div class="main-content">
            <form method="POST">
                <input type="hidden" name="action" value="save">
                
                <div id="dash" class="page active">
                    <h1>Dashboard</h1>
                    <div class="card">
                        <h3>Infos :</h3>
                        <p style="color: #00ff00;">This is the Dashboard!. Here you can Design the LavaBot!</p>
                        <p>For Help add me on Discord!</p>
                        <p>Name : <span style="color:var(--accent)">Byt3Crxsh</span></p>
                    </div>
                </div>

                <div id="sett" class="page">
                    <h1>Settings</h1>
                    <div class="card">
                        <h3>Global Config</h3>
                        Prefix: <input type="text" name="prefix" value="{{ config.prefix }}">
                        Status: <input type="text" name="status" value="{{ config.status }}">
                    </div>
                </div>

                <div id="welcome" class="page">
                    <h1>Welcome Message</h1>
                    <div class="card">
                        <h3>Message Content</h3>
                        <textarea name="w_msg" rows="5">{{ config.modules.welcome.msg }}</textarea>
                    </div>
                </div>

                <div id="help_page" class="page">
                    <h1>Help Module</h1>
                    <div class="card">
                        Aliases: <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                        Help Text: <textarea name="h_text">{{ config.modules.help.text }}</textarea>
                    </div>
                </div>

                <div id="roles_page" class="page">
                    <h1>Role Permissions</h1>
                    <div class="card">
                        <h3>Moderator Roles</h3>
                        {% for r in roles %}
                        <div class="item-row">
                            <input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>
                            <span>{{ r.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <div id="chans_page" class="page">
                    <h1>Channel Settings</h1>
                    <div class="card">
                        <h3>Link-Filter Whitelist</h3>
                        {% for c in channels %}
                        <div class="item-row">
                            <input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}>
                            <span>{{ c.name }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <div id="mod_page" class="page">
                    <h1>Moderation Logic</h1>
                    <div class="card">
                        <p>Hier kannst du einstellen, wie Kick/Ban/Timeout reagieren sollen.</p>
                        <select name="mod_enabled">
                            <option value="True" {% if config.modules.mod.enabled == "True" %}selected{% endif %}>Aktiviert</option>
                            <option value="False" {% if config.modules.mod.enabled == "False" %}selected{% endif %}>Deaktiviert</option>
                        </select>
                    </div>
                </div>

                <div style="display:flex; justify-content:flex-end; margin-top:20px;">
                    <button type="submit" class="btn-save">DEPLOY ALL CHANGES</button>
                </div>
            </form>
        </div>
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
                "modules.welcome.msg": request.form.get("w_msg"),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.mod.roles": request.form.getlist("mod_roles"),
                "modules.link_filter.chans": request.form.getlist("lf_chans"),
                "modules.mod.enabled": request.form.get("mod_enabled")
            }
            config_col.update_one({"guild_id": session['guild_id']}, {"$set": updates})
            return redirect(url_for('index'))

    guilds = [{"name": g.name, "id": str(g.id)} for g in bot.guilds]
    conf, roles, channels, guild_name = None, [], [], ""
    
    if 'guild_id' in session:
        conf = get_guild_config(session['guild_id'])
        g = bot.get_guild(int(session['guild_id']))
        if g:
            guild_name = g.name
            roles = [{"id": r.id, "name": r.name} for r in g.roles if not r.managed and r.name != "@everyone"]
            channels = [{"id": c.id, "name": c.name} for c in g.text_channels]

    return render_template_string(HTML_TEMPLATE, config=conf, guilds=guilds, roles=roles, channels=channels, guild_name=guild_name)

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
