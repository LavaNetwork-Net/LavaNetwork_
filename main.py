import discord
from discord.ext import commands
from flask import Flask, render_template_string
import threading
import os

# --- WEB SERVER TEIL (Für das Dashboard) ---
app = Flask(__name__)

HTML_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
    <title>LavaNetwork Dashboard</title>
    <style>
        body { font-family: sans-serif; background: #2c2f33; color: white; text-align: center; padding-top: 50px; }
        .status { color: #43b581; font-weight: bold; }
    </style>
</head>
<body>
    <h1>LavaNetwork Bot Status</h1>
    <p>Der Bot läuft aktuell auf Render.com</p>
    <p>Status: <span class="status">ONLINE</span></p>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_DASHBOARD)

def run_webserver():
    # Render nutzt oft Port 10000 oder den, den wir vorgeben
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- DISCORD BOT TEIL ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Eingeloggt als {bot.user}')

# --- START ---
if __name__ == "__main__":
    # Webserver in eigenem Thread starten
    t = threading.Thread(target=run_webserver)
    t.start()
    
    # Den Token holt sich der Bot sicher aus den Einstellungen von Render
    token = os.environ.get('DISCORD_TOKEN')
    
    if token:
        bot.run(token)
    else:
        print("FEHLER: Kein DISCORD_TOKEN gefunden! Bitte bei Render in den Environment Variables eintragen.")