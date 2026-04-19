import discord
from discord.ext import commands
from flask import Flask, request, render_template_string, session, redirect, url_for
import threading
import os
from pymongo import MongoClient
import asyncio
from datetime import timedelta
import re

# --- DATABASE SETUP ---
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
                "welcome": {"enabled": "False", "msg": "Welcome to the server!"},
                "link_filter": {"enabled": "False", "chans": [], "roles": []},
                "mod": {"enabled": "False", "roles": []},
                "help": {"enabled": "False", "aliases": "help", "text": "Lava Network Support"},
                "info": {"enabled": "False", "aliases": "info", "text": "Information Module"}
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

# --- FONT TRANSLATOR ---
def format_font(text, font_type):
    text = text.lower().replace(" ", "-")
    fonts = {
        "gothic": "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷",
        "fancy": "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃",
        "smallcaps": "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ"
    }
    return text.translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", fonts[font_type])) if font_type in fonts else text

# --- BOT EVENTS & COMMANDS ---
@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild: return
    conf = get_guild_config(message.guild.id)
    prefix = conf.get("prefix", "!")

    # Link Filter Logic
    lf = conf['modules'].get('link_filter', {})
    if lf.get('enabled') == "True" and str(message.channel.id) in lf.get('chans', []):
        user_roles = [str(r.id) for r in message.author.roles]
        # Bypass if Admin OR has a whitelisted role
        has_bypass = any(rid in lf.get('roles', []) for rid in user_roles) or message.author.guild_permissions.administrator
        
        if not has_bypass and re.search(r'http[s]?://', message.content.lower()):
            await message.delete()
            await message.channel.send(f"**{message.author.mention}**, links are prohibited in this channel.", delete_after=5)
            return

    # Help & Info Logic
    for mod in ['help', 'info']:
        m_data = conf['modules'][mod]
        if m_data['enabled'] == "True":
            aliases = [a.strip().lower() for a in m_data.get("aliases", mod).split(",")]
            if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
                await message.channel.send(m_data.get("text"))
                return

    await bot.process_commands(message)

@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        user_roles = [str(r.id) for r in ctx.author.roles]
        if any(rid in conf['modules']['mod']['roles'] for rid in user_roles) or ctx.author.guild_permissions.administrator:
            await member.kick(reason=reason)
            await ctx.send(f"Successfully kicked **{member}**.")

@bot.command()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        user_roles = [str(r.id) for r in ctx.author.roles]
        if any(rid in conf['modules']['mod']['roles'] for rid in user_roles) or ctx.author.guild_permissions.administrator:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
            await ctx.send(f"Timed out **{member}** for {minutes} minutes.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        user_roles = [str(r.id) for r in ctx.author.roles]
        if any(rid in conf['modules']['mod']['roles'] for rid in user_roles) or ctx.author.guild_permissions.administrator:
            await member.ban(reason=reason)
            await ctx.send(f"Permanently banned **{member}**.")

# --- WEB DASHBOARD ---
app = Flask(__name__)
app.secret_key = "lava_network_ultimate_v5"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LAVA NETWORK | Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #050505; --side: #0a0a0a; --card: #111111; --accent: #ff3333; --border: #1a1a1a; --text: #eee; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 260px; background: var(--side); border-right: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; }
        .sidebar h2 { color: var(--accent); text-align: center; font-weight: 900; letter-spacing: 2px; margin-bottom: 30px; }
        .nav-group { margin-bottom: 20px; }
        .nav-label { font-size: 10px; color: #444; text-transform: uppercase; display: block; margin-bottom: 8px; font-weight: 800; }
        .nav-btn { width: 100%; padding: 12px; background: none; border: none; color: #888; text-align: left; cursor: pointer; border-radius: 6px; font-size: 14px; display: flex; align-items: center; transition: 0.2s; }
        .nav-btn i { margin-right: 12px; width: 18px; text-align: center; }
        .nav-btn:hover, .nav-btn.active { background: #151515; color: var(--accent); }
        .main-content { flex: 1; padding: 40px; overflow-y: auto; }
        .page { display: none; }
        .page.active { display: block; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 25px; margin-bottom: 25px; }
        input, textarea, select { width: 100%; padding: 12px; background: #000; border: 1px solid #222; color: white; border-radius: 6px; margin-top: 8px; margin-bottom: 15px; box-sizing: border-box; }
        .switch-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #222; padding-bottom: 15px; margin-bottom: 15px; }
        .scroll-box { max-height: 180px; overflow-y: auto; background: #080808; border-radius: 6px; padding: 10px; border: 1px solid #1a1a1a; }
        .item-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #111; }
        .item-row input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }
        .btn-save { position: fixed; bottom: 30px; right: 40px; background: var(--accent); color: white; border: none; padding: 15px 40px; border-radius: 8px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 15px rgba(255,51,51,0.3); }
    </style>
</head>
<body>
    {% if not session.user %}
        <div style="margin: auto; width: 320px; background: var(--card); padding: 40px; border-radius: 15px; border: 1px solid var(--border); text-align: center;">
            <h1 style="color:var(--accent); font-weight:900;">LAVA</h1>
            <form method="POST">
                <input type="text" name="user" placeholder="Username" required>
                <input type="password" name="pw" placeholder="Access Key" required>
                <button type="submit" class="btn-save" style="position:static; width:100%;">LOGIN</button>
            </form>
        </div>
    {% elif not session.guild_id %}
        <div class="main-content" style="text-align:center;">
            <h1 style="color:var(--accent)">CHOOSE SERVER</h1>
            <a href="https://discord.com/oauth2/authorize?client_id=1495049063253413979&permissions=8&integration_type=0&scope=bot" target="_blank" style="color:#888; text-decoration:none;">+ Invite Bot</a>
            <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:20px; margin-top:40px;">
                {% for g in guilds %}
                <div class="card" style="cursor:pointer;" onclick="location.href='/select/{{ g.id }}'">{{ g.name }}</div>
                {% endfor %}
            </div>
        </div>
    {% else %}
        <div class="sidebar">
            <h2>LAVA</h2>
            <div class="nav-group">
                <span class="nav-label">Core</span>
                <button class="nav-btn active" onclick="showPage('dash', this)"><i class="fas fa-home"></i> Home</button>
                <button class="nav-btn" onclick="showPage('sett', this)"><i class="fas fa-cog"></i> Settings</button>
            </div>
            <div class="nav-group">
                <span class="nav-label">Modules</span>
                <button class="nav-btn" onclick="showPage('creator', this)"><i class="fas fa-plus-circle"></i> Channels</button>
                <button class="nav-btn" onclick="showPage('links', this)"><i class="fas fa-link"></i> Link Filter</button>
                <button class="nav-btn" onclick="showPage('mod', this)"><i class="fas fa-hammer"></i> Moderation</button>
            </div>
            <div class="nav-group">
                <span class="nav-label">Messages</span>
                <button class="nav-btn" onclick="showPage('welcome', this)"><i class="fas fa-user-plus"></i> Welcome</button>
                <button class="nav-btn" onclick="showPage('help', this)"><i class="fas fa-question"></i> Help</button>
                <button class="nav-btn" onclick="showPage('info', this)"><i class="fas fa-info-circle"></i> Info</button>
            </div>
            <div style="margin-top:auto;">
                <button class="nav-btn" onclick="location.href='/change_server'"><i class="fas fa-exchange-alt"></i> Switch Server</button>
            </div>
        </div>

        <div class="content-wrapper" style="flex:1; overflow-y:auto;">
            <div class="main-content">
                <form method="POST">
                    <input type="hidden" name="action" value="save">
                    
                    <div id="dash" class="page active">
                        <h1>Dashboard</h1>
                        <div class="card"><h3>Lava Network | {{ guild_name }}</h3><p>Status: Online</p></div>
                    </div>

                    <div id="creator" class="page">
                        <h1>Channel Creator</h1>
                        <div class="card">
                            <input type="text" name="c_name" placeholder="Channel Name">
                            <input type="text" name="c_cat" placeholder="Category ID (Optional)">
                            <select name="c_font">
                                <option value="normal">Normal</option>
                                <option value="gothic">Gothic (𝔤𝔬𝔱𝔥𝔦𝔠)</option>
                                <option value="fancy">Fancy (𝓯𝓪𝓷𝓬𝔂)</option>
                                <option value="smallcaps">Small Caps (ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ)</option>
                            </select>
                            <button type="submit" name="action" value="create_chan" class="nav-btn active" style="justify-content:center;">Create Channel</button>
                        </div>
                    </div>

                    <div id="links" class="page">
                        <h1>Link Filter System</h1>
                        <div class="card">
                            <div class="switch-header">
                                <span>System Status</span>
                                <select name="lf_enabled" style="width:140px;">
                                    <option value="True" {% if config.modules.link_filter.enabled == "True" %}selected{% endif %}>Enabled</option>
                                    <option value="False" {% if config.modules.link_filter.enabled == "False" %}selected{% endif %}>Disabled</option>
                                </select>
                            </div>
                            <label>Protect these Channels (Links will be deleted):</label>
                            <div class="scroll-box">
                                {% for c in channels %}
                                <div class="item-row"><input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}><span># {{ c.name }}</span></div>
                                {% endfor %}
                            </div>
                            <br>
                            <label>Whitelist Roles (These roles CAN send links):</label>
                            <p style="font-size:11px; color:#555;">If no roles are selected, everyone is blocked.</p>
                            <div class="scroll-box">
                                {% for r in roles %}
                                <div class="item-row"><input type="checkbox" name="lf_roles" value="{{ r.id }}" {% if r.id|string in config.modules.link_filter.roles %}checked{% endif %}><span>{{ r.name }}</span></div>
                                {% endfor %}
                            </div>
                        </div>
                    </div>

                    <div id="mod" class="page">
                        <h1>Moderation</h1>
                        <div class="card">
                            <div class="switch-header"><span>Enable Commands</span>
                                <select name="m_enabled" style="width:140px;">
                                    <option value="True" {% if config.modules.mod.enabled == "True" %}selected{% endif %}>Enabled</option>
                                    <option value="False" {% if config.modules.mod.enabled == "False" %}selected{% endif %}>Disabled</option>
                                </select>
                            </div>
                            <label>Staff Roles (Authorized to Kick/Ban/Timeout):</label>
                            <div class="scroll-box">
                                {% for r in roles %}
                                <div class="item-row"><input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}><span>{{ r.name }}</span></div>
                                {% endfor %}
                            </div>
                        </div>
                    </div>

                    <div id="welcome" class="page">
                        <h1>Welcome Message</h1>
                        <div class="card">
                            <select name="w_enabled"><option value="True" {% if config.modules.welcome.enabled == "True" %}selected{% endif %}>Enabled</option><option value="False" {% if config.modules.welcome.enabled == "False" %}selected{% endif %}>Disabled</option></select>
                            <textarea name="w_msg">{{ config.modules.welcome.msg }}</textarea>
                        </div>
                    </div>

                    <div id="help" class="page">
                        <h1>Help Module</h1>
                        <div class="card">
                            <select name="h_enabled"><option value="True" {% if config.modules.help.enabled == "True" %}selected{% endif %}>Enabled</option><option value="False" {% if config.modules.help.enabled == "False" %}selected{% endif %}>Disabled</option></select>
                            <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}">
                            <textarea name="h_text">{{ config.modules.help.text }}</textarea>
                        </div>
                    </div>

                    <div id="info" class="page">
                        <h1>Info Module</h1>
                        <div class="card">
                            <select name="i_enabled"><option value="True" {% if config.modules.info.enabled == "True" %}selected{% endif %}>Enabled</option><option value="False" {% if config.modules.info.enabled == "False" %}selected{% endif %}>Disabled</option></select>
                            <input type="text" name="i_aliases" value="{{ config.modules.info.aliases }}">
                            <textarea name="i_text">{{ config.modules.info.text }}</textarea>
                        </div>
                    </div>

                    <div id="sett" class="page">
                        <h1>Global Settings</h1>
                        <div class="card">
                            <label>Prefix:</label><input type="text" name="prefix" value="{{ config.prefix }}">
                            <label>Status:</label><input type="text" name="status" value="{{ config.status }}">
                        </div>
                    </div>

                    <button type="submit" name="action" value="save" class="btn-save">SAVE ALL CHANGES</button>
                </form>
            </div>
        </div>
    {% endif %}

    <script>
        function showPage(id, btn) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            btn.classList.add('active');
        }
    </script>
</body>
</html>
"""

# --- WEB ROUTES ---
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "pw" in request.form and request.form.get("pw") == "10":
            session['user'] = request.form.get("user")
            return redirect(url_for('index'))
        
        action = request.form.get("action")
        if action == "create_chan" and 'guild_id' in session:
            name = format_font(request.form.get("c_name"), request.form.get("c_font"))
            cat_id = request.form.get("c_cat")
            async def run_create():
                g = bot.get_guild(int(session['guild_id']))
                cat = g.get_channel(int(cat_id)) if cat_id and cat_id.isdigit() else None
                await g.create_text_channel(name, category=cat)
            asyncio.run_coroutine_threadsafe(run_create(), bot.loop)
            return redirect(url_for('index'))

        if action == "save" and 'guild_id' in session:
            updates = {
                "prefix": request.form.get("prefix"),
                "status": request.form.get("status"),
                "modules.welcome.enabled": request.form.get("w_enabled"),
                "modules.welcome.msg": request.form.get("w_msg"),
                "modules.help.enabled": request.form.get("h_enabled"),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.info.enabled": request.form.get("i_enabled"),
                "modules.info.aliases": request.form.get("i_aliases"),
                "modules.info.text": request.form.get("i_text"),
                "modules.mod.enabled": request.form.get("m_enabled"),
                "modules.mod.roles": request.form.getlist("mod_roles"),
                "modules.link_filter.enabled": request.form.get("lf_enabled"),
                "modules.link_filter.chans": request.form.getlist("lf_chans"),
                "modules.link_filter.roles": request.form.getlist("lf_roles")
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
