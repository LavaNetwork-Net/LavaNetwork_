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

# Funktion zum Laden der Config
def get_config():
    conf = config_col.find_one({"id": "bot_config"})
    if not conf:
        # Standardwerte falls DB leer
        default = {
            "id": "bot_config",
            "welcome_msg": "Willkommen auf dem Server!",
            "info_prefix": "!",
            "info_content": "Ich bin der LavaNetwork Bot."
        }
        config_col.insert_one(default)
        return default
    return conf

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Eingeloggt als {bot.user}')

@bot.event
async def on_member_join(member):
    conf = get_config()
    if member.guild.system_channel:
        await member.guild.system_channel.send(f"{member.mention}, {conf['welcome_msg']}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    conf = get_config()
    info_trigger = f"{conf['info_prefix']}info"
    if message.content.lower() == info_trigger.lower():
        await message.channel.send(conf['info_content'])
    await bot.process_commands(message)

# --- WEB SERVER ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>LavaBot Admin Panel</title>
    <style>
        body { background: #2c2f33; color: white; font-family: 'Segoe UI', Arial; text-align: center; padding: 50px; }
        .box { background: #23272a; padding: 30px; display: inline-block; border-radius: 15px; border: 1px solid #7289da; }
        input, textarea { background: #40444b; color: white; border: 1px solid #202225; padding: 10px; margin: 10px; border-radius: 5px; width: 90%; }
        button { background: #7289da; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; }
        button:hover { background: #5b6eae; }
    </style>
</head>
<body>
    <h1>LavaBot Control Panel</h1>
    <div class="box">
        {% if not authorized %}
            <form method="POST">
                <p>Admin Key erforderlich:</p>
                <input type="password" name="key">
                <button type="submit">Login</button>
            </form>
        {% else %}
            <p style="color: #43b581;">✓ Datenbank-Verbindung aktiv</p>
            <form method="POST">
                <input type="hidden" name="key" value="10">
                <h3>Willkommens-Nachricht</h3>
                <textarea name="welcome_msg">{{ config.welcome_msg }}</textarea>
                
                <h3>Info-Befehl</h3>
                Prefix (z.B. ! oder ?):<br>
                <input type="text" name="info_prefix" value="{{ config.info_prefix }}">
                Inhalt des Info-Befehls:<br>
                <textarea name="info_content">{{ config.info_content }}</textarea>
                
                <br><button type="submit" name="update" value="true">SPEICHERN & SYNCHRONISIEREN</button>
            </form>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    authorized = False
    if request.method == "POST":
        if request.form.get("key") == "10":
            authorized = True
            if request.form.get("update"):
                new_conf = {
                    "welcome_msg": request.form.get("welcome_msg"),
                    "info_prefix": request.form.get("info_prefix"),
                    "info_content": request.form.get("info_content")
                }
                config_col.update_one({"id": "bot_config"}, {"$set": new_conf})
    
    return render_template_string(HTML_TEMPLATE, authorized=authorized, config=get_config())

def run(): app.run(host="0.0.0.0", port=10000)
threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
