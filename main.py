import discord
from discord.ext import commands
from flask import Flask, request, render_template_string
import threading
import os
from pymongo import MongoClient

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
            "module_info": "True",      # Info-Befehl an/aus
            "module_welcome": "True",   # Willkommens-System an/aus
            "module_antilink": "False", # Anti-Link Schutz an/aus
            "info_text": "LavaNetwork Bot v3 - Premium System",
            "prefix": "!",
            "welcome_msg": "Willkommen auf dem Server!"
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT LOGIC ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command(name="info")
async def info(ctx):
    conf = get_config()
    # PRÜFUNG: Ist das Modul aktiviert?
    if conf.get("module_info") == "True":
        embed = discord.Embed(title="System Info", description=conf['info_text'], color=0xff4d4d)
        await ctx.send(embed=embed)
    else:
        # Wenn aus, reagiert der Bot einfach nicht oder gibt einen Hinweis
        pass

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    conf = get_config()
    # Anti-Link Modul Check
    if conf.get("module_antilink") == "True":
        if "http" in message.content:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, Links sind hier deaktiviert!", delete_after=5)
            return

    await bot.process_commands(message)

# --- WEB PANEL (CONTROL CENTER) ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LavaBot Control Center</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #0f1011; --card: #1a1b1e; --accent: #ff4d4d; --text: #ffffff; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; padding: 40px; }
        .header { text-align: center; margin-bottom: 50px; }
        .header h1 { color: var(--accent); letter-spacing: 3px; font-size: 32px; }
        
        .module-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }
        .module-card { background: var(--card); padding: 25px; border-radius: 15px; border: 1px solid #333; position: relative; }
        
        /* Toggle Switch Style */
        .switch { position: absolute; top: 25px; right: 25px; display: inline-block; width: 50px; height: 26px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #444; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: var(--accent); }
        input:checked + .slider:before { transform: translateX(24px); }

        h3 { margin-top: 0; display: flex; align-items: center; gap: 10px; color: var(--accent); }
        input[type="text"], textarea { width: 100%; padding: 12px; background: #0b0c10; border: 1px solid #444; color: white; border-radius: 8px; margin: 10px 0; box-sizing: border-box; }
        .btn-save { background: var(--accent); color: white; border: none; padding: 15px; border-radius: 8px; width: 100%; font-weight: bold; cursor: pointer; margin-top: 20px; transition: 0.3s; }
        .btn-save:hover { filter: brightness(1.2); }
        
        .status-badge { font-size: 12px; background: #222; padding: 4px 8px; border-radius: 4px; color: #888; }
    </style>
</head>
<body>
    <div class="header">
        <h1>LAVA BOT MODULES <i class="fas fa-microchip"></i></h1>
        <p>Aktiviere oder deaktiviere Funktionen für deinen Server</p>
    </div>

    {% if not auth %}
    <div style="max-width: 400px; margin: 0 auto; background: var(--card); padding: 30px; border-radius: 15px; text-align: center;">
        <form method="POST"><input type="password" name="key" placeholder="Admin Key"><button class="btn-save">LOGIN</button></form>
    </div>
    {% else %}
    <form method="POST">
        <input type="hidden" name="key" value="10">
        <input type="hidden" name="save" value="true">
        
        <div class="module-grid">
            <div class="module-card">
                <h3><i class="fas fa-info-circle"></i> Info-Befehl</h3>
                <label class="switch">
                    <input type="checkbox" name="module_info" value="True" {% if config.module_info == 'True' %}checked{% endif %}>
                    <span class="slider"></span>
                </label>
                <p>Erlaubt Usern den Befehl <code>!info</code> zu nutzen.</p>
                <input type="text" name="info_text" value="{{ config.info_text }}" placeholder="Info Text eingeben...">
            </div>

            <div class="module-card">
                <h3><i class="fas fa-link-slash"></i> Anti-Link Schutz</h3>
                <label class="switch">
                    <input type="checkbox" name="module_antilink" value="True" {% if config.module_antilink == 'True' %}checked{% endif %}>
                    <span class="slider"></span>
                </label>
                <p>Löscht automatisch alle Links von normalen Usern.</p>
                <span class="status-badge">Automatischer Schutz</span>
            </div>

            <div class="module-card">
                <h3><i class="fas fa-door-open"></i> Welcome System</h3>
                <label class="switch">
                    <input type="checkbox" name="module_welcome" value="True" {% if config.module_welcome == 'True' %}checked{% endif %}>
                    <span class="slider"></span>
                </label>
                <p>Sendet eine Nachricht, wenn jemand beitritt.</p>
                <textarea name="welcome_msg">{{ config.welcome_msg }}</textarea>
            </div>
        </div>

        <div style="text-align: center; margin-top: 40px;">
            <button type="submit" class="btn-save" style="max-width: 300px;">ÄNDERUNGEN SPEICHERN</button>
        </div>
    </form>
    {% endif %}
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
                # Wir setzen alle Checkboxen erst auf False (da nicht gesendete Checkboxen im Formular fehlen)
                new_data = {
                    "module_info": "False",
                    "module_welcome": "False",
                    "module_antilink": "False",
                    "info_text": request.form.get("info_text"),
                    "welcome_msg": request.form.get("welcome_msg")
                }
                # Dann überschreiben wir sie mit "True", wenn sie im Formular vorhanden sind
                for key in request.form:
                    if key in new_data:
                        new_data[key] = request.form[key]
                
                config_col.update_one({"id": "bot_config"}, {"$set": new_data})
                conf = get_config()
    return render_template_string(HTML_TEMPLATE, auth=auth, config=conf)

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
