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
            "guild_id": str(guild_id), "prefix": "!", "status": "Lava Network",
            "modules": {
                "welcome": {"enabled": "True", "msg": "Welcome to the server!"},
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "True", "roles": []},
                "help": {"enabled": "True", "aliases": "help", "text": "Lava Network Support"}
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
    
    hp = conf['modules']['help']
    aliases = [a.strip().lower() for a in hp.get("aliases", "help").split(",")]
    if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
        await message.channel.send(hp.get("text"))
        return
    await bot.process_commands(message)

# Font Translator
def format_font(text, font_type):
    text = text.lower().replace(" ", "-")
    if font_type == "gothic":
        return text.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷"))
    elif font_type == "fancy":
        return text.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"))
    elif font_type == "smallcaps":
        return text.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ"))
    return text

async def create_discord_channel(guild_id, name):
    guild = bot.get_guild(int(guild_id))
    if guild: await guild.create_text_channel(name)

# --- WEB UI ---
app = Flask(__name__)
app.secret_key = "lava_network_v3_final"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LAVA NETWORK</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3333; --border: #1a1a1a; --text: #eee; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 260px; background: var(--side); border-right: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; }
        .sidebar h2 { color: var(--accent); font-size: 22px; margin-bottom: 30px; text-align: center; font-weight: 900; }
        .nav-group { margin-bottom: 20px; }
        .nav-label { font-size: 11px; color: #555; text-transform: uppercase; margin-bottom: 8px; display: block; font-weight: bold; }
        .nav-btn { width: 100%; padding: 12px; background: none; border: none; color: #888; text-align: left; cursor: pointer; border-radius: 6px; font-size: 14px; margin-bottom: 4px; display: flex; align-items: center; transition: 0.2s; }
        .nav-btn i { margin-right: 12px; width: 16px; text-align: center; }
        .nav-btn:hover, .nav-btn.active { background: #151515; color: var(--accent); }
        .content-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; }
        .top-bar { padding: 20px 40px; background: var(--side); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .main-content { flex: 1; padding: 40px; overflow-y: auto; }
        .page { display: none; }
        .page.active { display: block; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; margin-bottom: 20px; }
        input, textarea, select { width: 100%; padding: 12px; background: #000; border: 1px solid #222; color: white; border-radius: 6px; margin-top: 8px; margin-bottom: 15px; box-sizing: border-box; }
        .item-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid #1a1a1a; }
        .item-row input[type="checkbox"] { margin: 0; width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }
        .btn-primary { background: var(--accent); color: white; border: none; padding: 14px 30px; border-radius: 8px; cursor: pointer; font-weight: bold; transition: 0.2s; text-decoration: none; display: inline-block; text-align: center; }
        .btn-primary:hover { opacity: 0.8; transform: translateY(-2px); }
        .guild-card { background: var(--card); border: 1px solid var(--border); padding: 25px; border-radius: 10px; text-align: center; cursor: pointer; transition: 0.2s; }
        .guild-card:hover { border-color: var(--accent); transform: translateY(-5px); }
        .code-block { background: #000; padding: 15px; border-radius: 8px; border: 1px solid #222; color: #00ff00; font-family: monospace; font-size: 14px; margin-bottom: 10px; }
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
    <div style="margin: auto; width: 350px; background: var(--card); padding: 40px; border-radius: 15px; border: 1px solid var(--border);">
        <h1 style="text-align:center; color:var(--accent); font-weight:900;">LAVA NETWORK</h1>
        <form method="POST">
            <input type="text" name="user" placeholder="Username" required>
            <input type="password" name="pw" placeholder="Access Key" required>
            <button class="btn-primary" style="width:100%; margin-top:10px;">LOGIN</button>
        </form>
    </div>
    {% elif not session.guild_id %}
    <div class="main-content" style="text-align:center;">
        <h1 style="color:var(--accent)">SELECT A SERVER</h1>
        <a href="https://discord.com/oauth2/authorize?client_id=1495049063253413979&permissions=8&integration_type=0&scope=bot" target="_blank" class="btn-primary" style="margin-bottom: 30px;">
            <i class="fas fa-plus"></i> Invite Lava Network to a new Server
        </a>
        <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:20px;">
            {% for g in guilds %}
            <div class="guild-card" onclick="location.href='/select/{{ g.id }}'">
                <i class="fas fa-server" style="font-size:35px; color:var(--accent)"></i>
                <div style="margin-top:15px; font-weight:bold;">{{ g.name }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% else %}
    <div class="sidebar">
        <h2>LAVA NETWORK</h2>
        <div class="nav-group">
            <span class="nav-label">Core</span>
            <button class="nav-btn active" onclick="showPage('dash', this)"><i class="fas fa-home"></i> Dashboard</button>
            <button class="nav-btn" onclick="showPage('sett', this)"><i class="fas fa-cog"></i> Global Settings</button>
        </div>
        <div class="nav-group">
            <span class="nav-label">Features</span>
            <button class="nav-btn" onclick="showPage('channel_creator', this)"><i class="fas fa-folder-plus"></i> Create Channels</button>
            <button class="nav-btn" onclick="showPage('welcome', this)"><i class="fas fa-door-open"></i> Welcome Msg</button>
            <button class="nav-btn" onclick="showPage('help_page', this)"><i class="fas fa-question-circle"></i> Help Command</button>
        </div>
        <div class="nav-group">
            <span class="nav-label">Security</span>
            <button class="nav-btn" onclick="showPage('roles_page', this)"><i class="fas fa-user-shield"></i> Mod Roles</button>
            <button class="nav-btn" onclick="showPage('link_filter', this)"><i class="fas fa-link"></i> Link Filter</button>
            <button class="nav-btn" onclick="showPage('mod_page', this)"><i class="fas fa-hammer"></i> Kick / Ban / Timeout</button>
        </div>
        <div style="margin-top:auto;">
            <button class="nav-btn" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i> Switch Server</button>
            <button class="nav-btn" onclick="location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Logout</button>
        </div>
    </div>
    <div class="content-wrapper">
        <div class="top-bar">
            <div style="font-weight:bold;">SERVER: {{ guild_name }}</div>
            <div>Admin: {{ session.user }}</div>
        </div>
        <div class="main-content">
            <div id="dash" class="page active">
                <h1>Dashboard</h1>
                <div class="card">
                    <h3 style="color:var(--accent);">Information:</h3>
                    <p style="color: #00ff00; font-weight:bold;">Welcome to the Lava Network Dashboard. Manage your bot easily!</p>
                    <p>Developer: <span style="color:var(--accent); font-weight:bold;">Byt3Crxsh</span></p>
                </div>
            </div>
            <div id="channel_creator" class="page">
                <h1>Channel Creator</h1>
                <div class="card">
                    <form method="POST">
                        <input type="hidden" name="action" value="create_channel">
                        <input type="text" name="c_name" placeholder="Channel Name" required>
                        <select name="c_font">
                            <option value="normal">Normal</option>
                            <option value="gothic">Gothic (𝔤𝔬𝔱𝔥𝔦𝔠)</option>
                            <option value="fancy">Fancy (𝓯𝓪𝓷𝓬𝔂)</option>
                            <option value="smallcaps">Small Caps (ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ)</option>
                        </select>
                        <button type="submit" class="btn-primary">Create Channel</button>
                    </form>
                </div>
            </div>
            <form method="POST">
                <input type="hidden" name="action" value="save_settings">
                <div id="sett" class="page">
                    <h1>Global Settings</h1>
                    <div class="card">
                        Prefix: <input type="text" name="prefix" value="{{ config.prefix }}">
                        Status: <input type="text" name="status" value="{{ config.status }}">
                    </div>
                </div>
                <div id="welcome" class="page">
                    <h1>Welcome Message</h1>
                    <div class="card">
                        <textarea name="w_msg" rows="4">{{ config.modules.welcome.msg }}</textarea>
                    </div>
                </div>
                <div id="help_page" class="page">
                    <h1>Help Command</h1>
                    <div class="card">
                        Aliases: <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                        Text: <textarea name="h_text" rows="4">{{ config.modules.help.text }}</textarea>
                    </div>
                </div>
                <div id="roles_page" class="page">
                    <h1>Mod Roles</h1>
                    <div class="card">
                        {% for r in roles %}<div class="item-row"><input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}><span>{{ r.name }}</span></div>{% endfor %}
                    </div>
                </div>
                <div id="link_filter" class="page">
                    <h1>Link Filter</h1>
                    <div class="card">
                        {% for c in channels %}<div class="item-row"><input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}><span># {{ c.name }}</span></div>{% endfor %}
                    </div>
                </div>
                <div id="mod_page" class="page">
                    <h1>Moderation</h1>
                    <div class="card">
                        <select name="mod_enabled"><option value="True" {% if config.modules.mod.enabled == "True" %}selected{% endif %}>🟢 ENABLED</option><option value="False" {% if config.modules.mod.enabled == "False" %}selected{% endif %}>🔴 DISABLED</option></select>
                        <div class="code-block">{{ config.prefix }}ban @User [Reason]</div>
                        <div class="code-block">{{ config.prefix }}kick @User [Reason]</div>
                    </div>
                </div>
                <div style="position:fixed; bottom:30px; right:40px;"><button type="submit" class="btn-primary">SAVE ALL</button></div>
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
        action = request.form.get("action")
        if action == "create_channel" and 'guild_id' in session:
            final_name = format_font(request.form.get("c_name"), request.form.get("c_font"))
            asyncio.run_coroutine_threadsafe(create_discord_channel(session['guild_id'], final_name), bot.loop)
            return redirect(url_for('index'))
        elif action == "save_settings" and 'guild_id' in session:
            updates = {"prefix": request.form.get("prefix"), "status": request.form.get("status"), "modules.welcome.msg": request.form.get("w_msg"), "modules.help.aliases": request.form.get("h_aliases"), "modules.help.text": request.form.get("h_text"), "modules.mod.roles": request.form.getlist("mod_roles"), "modules.link_filter.chans": request.form.getlist("lf_chans"), "modules.mod.enabled": request.form.get("mod_enabled")}
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
