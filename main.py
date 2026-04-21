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
    default_modules = {
        "link_filter": {"enabled": "False", "chans": [], "roles": []},
        "mod": {"enabled": "False", "roles": []},
        "help": {"enabled": "False", "aliases": "help", "text": "Lava Network Support"},
        "info": {"enabled": "False", "aliases": "info", "text": "Information Module"},
        "dms": {
            "welcome_enabled": "False", "welcome_msg": "Welcome to {server}!",
            "kick_enabled": "False", "kick_msg": "Your Account Got Kicked From {server}",
            "ban_enabled": "False", "ban_msg": "You were permanently banned from {server}",
            "timeout_enabled": "False", "timeout_msg": "You have been timed out in {server}"
        }
    }
    if not conf:
        conf = {"guild_id": str(guild_id), "prefix": "!", "status": "Lava Network", "modules": default_modules}
        config_col.insert_one(conf)
    else:
        updated = False
        if "modules" not in conf:
            conf["modules"] = default_modules
            updated = True
        else:
            for mod_name, mod_data in default_modules.items():
                if mod_name not in conf["modules"]:
                    conf["modules"][mod_name] = mod_data
                    updated = True
        if updated:
            config_col.replace_one({"guild_id": str(guild_id)}, conf)
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

# --- DM HELPER ---
async def send_user_dm(member, msg_template, guild_name):
    try:
        content = msg_template.replace("{server}", guild_name)
        await member.send(content)
    except:
        pass

# --- BOT EVENTS ---
@bot.event
async def on_member_join(member):
    conf = get_guild_config(member.guild.id)
    dm_conf = conf['modules']['dms']
    if dm_conf.get("welcome_enabled") == "True":
        await send_user_dm(member, dm_conf["welcome_msg"], member.guild.name)

@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild: return
    conf = get_guild_config(message.guild.id)
    prefix = conf.get("prefix", "!")
    lf = conf['modules'].get('link_filter', {})
    if lf.get('enabled') == "True" and str(message.channel.id) in lf.get('chans', []):
        user_roles = [str(r.id) for r in message.author.roles]
        has_bypass = any(rid in lf.get('roles', []) for rid in user_roles) or message.author.guild_permissions.administrator
        if not has_bypass and re.search(r'http[s]?://', message.content.lower()):
            await message.delete()
            await message.channel.send(f"**{message.author.mention}**, links are prohibited.", delete_after=5)
            return
    for mod in ['help', 'info']:
        m_data = conf['modules'][mod]
        if m_data['enabled'] == "True":
            aliases = [a.strip().lower() for a in m_data.get("aliases", mod).split(",")]
            if any(message.content.lower() == f"{prefix}{a}" for a in aliases):
                await message.channel.send(m_data.get("text"))
                return
    await bot.process_commands(message)

# --- MODERATION COMMANDS ---
@bot.command()
async def kick(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        if any(str(r.id) in conf['modules']['mod']['roles'] for r in ctx.author.roles) or ctx.author.guild_permissions.administrator:
            dm_conf = conf['modules']['dms']
            if dm_conf.get("kick_enabled") == "True":
                await send_user_dm(member, dm_conf["kick_msg"], ctx.guild.name)
            await member.kick(reason=reason)
            await ctx.send(f"**{member}** was kicked.")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        if any(str(r.id) in conf['modules']['mod']['roles'] for r in ctx.author.roles) or ctx.author.guild_permissions.administrator:
            dm_conf = conf['modules']['dms']
            if dm_conf.get("ban_enabled") == "True":
                await send_user_dm(member, dm_conf["ban_msg"], ctx.guild.name)
            await member.ban(reason=reason)
            await ctx.send(f"**{member}** was banned.")

@bot.command()
async def timeout(ctx, member: discord.Member, minutes: int, *, reason=None):
    conf = get_guild_config(ctx.guild.id)
    if conf['modules']['mod']['enabled'] == "True":
        if any(str(r.id) in conf['modules']['mod']['roles'] for r in ctx.author.roles) or ctx.author.guild_permissions.administrator:
            dm_conf = conf['modules']['dms']
            if dm_conf.get("timeout_enabled") == "True":
                await send_user_dm(member, dm_conf["timeout_msg"], ctx.guild.name)
            await member.timeout(timedelta(minutes=minutes), reason=reason)
            await ctx.send(f"**{member}** timed out for {minutes}m.")

# --- WEB UI (FLASK) ---
app = Flask(__name__)
app.secret_key = "lava_ultimate_mega_key"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Lava Network &mdash; Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:       #0a0a0b;
      --surface:  #111114;
      --card:     #16161a;
      --border:   #1f1f26;
      --border2:  #2a2a35;
      --accent:   #e03535;
      --accent-d: #b82b2b;
      --accent-g: rgba(224,53,53,0.12);
      --text:     #f0f0f4;
      --muted:    #7a7a8c;
      --muted2:   #4a4a5a;
      --success:  #22c55e;
      --warn:     #f59e0b;
      --radius:   10px;
      --radius-lg:16px;
    }

    html, body { height: 100%; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      font-size: 14px;
      line-height: 1.6;
    }

    /* ---- SCROLLBAR ---- */
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 99px; }

    /* ============================
       LOGIN PAGE
    ============================ */
    .login-wrap {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: radial-gradient(ellipse 80% 60% at 50% 0%, rgba(224,53,53,0.07) 0%, transparent 70%);
    }
    .login-card {
      width: 380px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 48px 40px 40px;
      box-shadow: 0 32px 64px rgba(0,0,0,0.6);
    }
    .login-logo {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      margin-bottom: 8px;
    }
    .login-logo-icon {
      width: 40px; height: 40px;
      background: var(--accent);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
      box-shadow: 0 0 24px rgba(224,53,53,0.35);
    }
    .login-logo span {
      font-size: 22px; font-weight: 800;
      letter-spacing: 3px;
      color: var(--text);
    }
    .login-sub {
      text-align: center;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 36px;
    }
    .form-field { margin-bottom: 16px; }
    .form-field label {
      display: block;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .form-field input, .form-field textarea, .form-field select {
      width: 100%;
      background: #0d0d10;
      border: 1px solid var(--border2);
      color: var(--text);
      border-radius: var(--radius);
      padding: 11px 14px;
      font-size: 14px;
      font-family: inherit;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
      resize: vertical;
    }
    .form-field input:focus, .form-field textarea:focus, .form-field select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(224,53,53,0.12);
    }
    .form-field textarea { min-height: 90px; }
    .form-field select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%237a7a8c' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; cursor: pointer; }
    .btn-primary {
      width: 100%; padding: 12px;
      background: var(--accent);
      color: #fff;
      border: none; border-radius: var(--radius);
      font-size: 14px; font-weight: 700;
      letter-spacing: 0.5px;
      cursor: pointer;
      transition: background 0.2s, box-shadow 0.2s, transform 0.1s;
      box-shadow: 0 4px 20px rgba(224,53,53,0.3);
    }
    .btn-primary:hover { background: var(--accent-d); box-shadow: 0 6px 24px rgba(224,53,53,0.4); }
    .btn-primary:active { transform: scale(0.98); }

    /* ============================
       SERVER SELECT
    ============================ */
    .select-wrap {
      min-height: 100vh;
      padding: 60px 40px;
      background: radial-gradient(ellipse 60% 40% at 50% 0%, rgba(224,53,53,0.06) 0%, transparent 70%);
    }
    .select-header {
      text-align: center;
      margin-bottom: 48px;
    }
    .select-header h1 {
      font-size: 28px; font-weight: 800;
      letter-spacing: 1px;
    }
    .select-header h1 span { color: var(--accent); }
    .select-header p { color: var(--muted); margin-top: 8px; }
    .servers-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 16px;
      max-width: 1000px;
      margin: 0 auto;
    }
    .server-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 28px 24px;
      cursor: pointer;
      text-decoration: none;
      display: flex; align-items: center; gap: 16px;
      transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s;
    }
    .server-card:hover {
      border-color: var(--accent);
      transform: translateY(-2px);
      box-shadow: 0 12px 32px rgba(0,0,0,0.4);
    }
    .server-avatar {
      width: 48px; height: 48px;
      background: linear-gradient(135deg, var(--accent) 0%, #7a1010 100%);
      border-radius: 14px;
      display: flex; align-items: center; justify-content: center;
      font-size: 20px; font-weight: 800; color: #fff;
      flex-shrink: 0;
    }
    .server-info strong { display: block; font-weight: 600; color: var(--text); font-size: 15px; }
    .server-info span { color: var(--muted); font-size: 12px; }

    /* ============================
       MAIN LAYOUT
    ============================ */
    .layout { display: flex; height: 100vh; overflow: hidden; }

    /* ---- SIDEBAR ---- */
    .sidebar {
      width: 240px;
      flex-shrink: 0;
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex; flex-direction: column;
      overflow-y: auto;
    }
    .sidebar-brand {
      padding: 24px 20px 20px;
      display: flex; align-items: center; gap: 10px;
      border-bottom: 1px solid var(--border);
    }
    .brand-icon {
      width: 32px; height: 32px;
      background: var(--accent);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 14px;
      box-shadow: 0 0 16px rgba(224,53,53,0.3);
      flex-shrink: 0;
    }
    .brand-text { font-size: 14px; font-weight: 800; letter-spacing: 2px; color: var(--text); }
    .brand-sub { font-size: 10px; color: var(--muted); font-weight: 400; letter-spacing: 0; display: block; margin-top: 1px; }

    .sidebar-section { padding: 20px 12px 8px; }
    .section-label {
      font-size: 10px; font-weight: 700;
      letter-spacing: 1.2px; text-transform: uppercase;
      color: var(--muted2);
      padding: 0 8px; margin-bottom: 4px;
    }
    .nav-item {
      display: flex; align-items: center; gap: 10px;
      padding: 9px 10px;
      border-radius: 8px;
      color: var(--muted);
      font-size: 13px; font-weight: 500;
      cursor: pointer;
      border: none; background: none; width: 100%; text-align: left;
      transition: background 0.15s, color 0.15s;
      text-decoration: none;
    }
    .nav-item i { width: 16px; text-align: center; font-size: 13px; flex-shrink: 0; }
    .nav-item:hover { background: rgba(255,255,255,0.04); color: var(--text); }
    .nav-item.active { background: var(--accent-g); color: var(--accent); font-weight: 600; }
    .nav-item.active i { color: var(--accent); }

    .sidebar-footer {
      margin-top: auto;
      padding: 12px;
      border-top: 1px solid var(--border);
    }

    /* ---- TOPBAR ---- */
    .topbar {
      height: 60px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 32px;
      flex-shrink: 0;
    }
    .topbar-left { display: flex; align-items: center; gap: 8px; }
    .topbar-guild {
      display: flex; align-items: center; gap: 10px;
    }
    .topbar-avatar {
      width: 28px; height: 28px;
      background: var(--accent);
      border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      font-size: 11px; font-weight: 800; color: #fff;
    }
    .topbar-name { font-size: 14px; font-weight: 600; }
    .topbar-right { display: flex; align-items: center; gap: 8px; }
    .topbar-btn {
      display: flex; align-items: center; gap: 7px;
      padding: 6px 12px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--muted);
      font-size: 12px; font-weight: 500;
      cursor: pointer;
      text-decoration: none;
      transition: border-color 0.15s, color 0.15s;
    }
    .topbar-btn:hover { border-color: var(--border2); color: var(--text); }
    .topbar-btn.danger:hover { border-color: var(--accent); color: var(--accent); }

    /* ---- CONTENT ---- */
    .content-wrap {
      flex: 1;
      display: flex; flex-direction: column;
      overflow: hidden;
    }
    .content-body {
      flex: 1;
      overflow-y: auto;
      padding: 32px;
    }

    .page { display: none; }
    .page.active { display: block; }

    /* ---- PAGE HEADER ---- */
    .page-header { margin-bottom: 28px; }
    .page-header h1 { font-size: 22px; font-weight: 700; }
    .page-header p { color: var(--muted); font-size: 13px; margin-top: 4px; }

    /* ---- CARDS ---- */
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 24px;
      margin-bottom: 20px;
    }
    .card-title {
      font-size: 13px; font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 16px;
      display: flex; align-items: center; gap: 8px;
    }
    .card-title i { color: var(--accent); font-size: 12px; }

    /* ---- STAT CARDS ---- */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px 22px;
      display: flex; align-items: center; gap: 16px;
    }
    .stat-icon {
      width: 42px; height: 42px;
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 17px; flex-shrink: 0;
    }
    .stat-icon.red { background: rgba(224,53,53,0.12); color: var(--accent); }
    .stat-icon.green { background: rgba(34,197,94,0.12); color: var(--success); }
    .stat-icon.amber { background: rgba(245,158,11,0.12); color: var(--warn); }
    .stat-icon.blue { background: rgba(59,130,246,0.12); color: #3b82f6; }
    .stat-label { font-size: 11px; color: var(--muted); margin-bottom: 2px; }
    .stat-value { font-size: 22px; font-weight: 700; }

    /* ---- MODULE STATUS BADGES ---- */
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 3px 10px;
      border-radius: 99px;
      font-size: 11px; font-weight: 600;
    }
    .badge.on { background: rgba(34,197,94,0.12); color: var(--success); }
    .badge.off { background: rgba(255,255,255,0.05); color: var(--muted); }
    .badge::before { content: ''; display: block; width: 5px; height: 5px; border-radius: 50%; background: currentColor; }

    /* ---- MODULE GRID ---- */
    .module-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 14px;
    }
    .module-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px;
      display: flex; flex-direction: column; gap: 12px;
    }
    .module-card-head {
      display: flex; align-items: center; justify-content: space-between;
    }
    .module-icon-wrap {
      display: flex; align-items: center; gap: 10px;
    }
    .module-icon {
      width: 36px; height: 36px;
      border-radius: 9px;
      display: flex; align-items: center; justify-content: center;
      font-size: 14px;
      background: var(--accent-g); color: var(--accent);
    }
    .module-name { font-size: 14px; font-weight: 600; }
    .module-desc { font-size: 12px; color: var(--muted); }

    /* ---- TOGGLE SWITCH ---- */
    .toggle-wrap {
      display: flex; align-items: center; gap: 10px;
    }
    .toggle-wrap label { font-size: 13px; color: var(--muted); cursor: pointer; }
    .toggle {
      position: relative; display: inline-block;
      width: 40px; height: 22px;
    }
    .toggle input { opacity: 0; width: 0; height: 0; }
    .toggle-slider {
      position: absolute; inset: 0;
      background: var(--border2);
      border-radius: 22px;
      cursor: pointer;
      transition: background 0.2s;
    }
    .toggle-slider::after {
      content: '';
      position: absolute;
      left: 3px; top: 3px;
      width: 16px; height: 16px;
      background: #fff;
      border-radius: 50%;
      transition: transform 0.2s;
    }
    .toggle input:checked + .toggle-slider { background: var(--accent); }
    .toggle input:checked + .toggle-slider::after { transform: translateX(18px); }
    .toggle input:focus-visible + .toggle-slider { box-shadow: 0 0 0 3px var(--accent-g); }

    /* ---- CHECKBOX LIST ---- */
    .check-list {
      max-height: 200px; overflow-y: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: #0d0d10;
    }
    .check-item {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      transition: background 0.1s;
      cursor: pointer;
    }
    .check-item:last-child { border-bottom: none; }
    .check-item:hover { background: rgba(255,255,255,0.02); }
    .check-item input[type="checkbox"] {
      width: 16px; height: 16px;
      accent-color: var(--accent);
      cursor: pointer; flex-shrink: 0;
    }
    .check-item span { font-size: 13px; color: var(--text); }
    .check-item .item-icon { font-size: 11px; color: var(--muted); margin-right: 2px; }

    /* ---- FORM SECTION ---- */
    .form-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 640px) { .form-row { grid-template-columns: 1fr; } }

    .section-divider {
      border: none;
      border-top: 1px solid var(--border);
      margin: 24px 0;
    }

    .dm-block {
      padding: 20px;
      background: #0d0d10;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 14px;
    }
    .dm-block-head {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 14px;
    }
    .dm-block-title {
      display: flex; align-items: center; gap: 8px;
      font-size: 13px; font-weight: 600;
    }
    .dm-block-title i { color: var(--accent); font-size: 13px; }

    /* ---- SAVE BAR ---- */
    .save-bar {
      position: sticky; bottom: 0;
      background: var(--surface);
      border-top: 1px solid var(--border);
      padding: 14px 32px;
      display: flex; align-items: center; justify-content: space-between;
      z-index: 10;
    }
    .save-bar p { font-size: 12px; color: var(--muted); }
    .btn-save {
      display: flex; align-items: center; gap: 8px;
      padding: 10px 28px;
      background: var(--accent);
      color: #fff;
      border: none; border-radius: var(--radius);
      font-size: 14px; font-weight: 700;
      cursor: pointer;
      transition: background 0.2s, box-shadow 0.2s, transform 0.1s;
      box-shadow: 0 4px 20px rgba(224,53,53,0.25);
    }
    .btn-save:hover { background: var(--accent-d); box-shadow: 0 6px 24px rgba(224,53,53,0.35); }
    .btn-save:active { transform: scale(0.98); }

    /* ---- TOAST ---- */
    #toast {
      position: fixed; bottom: 80px; right: 32px;
      background: #1a1a20;
      border: 1px solid var(--border2);
      border-left: 3px solid var(--success);
      border-radius: var(--radius);
      padding: 12px 18px;
      color: var(--text); font-size: 13px;
      display: flex; align-items: center; gap: 10px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      transform: translateX(120px);
      opacity: 0;
      transition: transform 0.3s cubic-bezier(.22,1,.36,1), opacity 0.3s;
      z-index: 999;
      pointer-events: none;
    }
    #toast.show { transform: translateX(0); opacity: 1; }
    #toast i { color: var(--success); }

    /* ---- CREATE CHANNEL BUTTON ---- */
    .btn-secondary {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 10px 20px;
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--text);
      border-radius: var(--radius);
      font-size: 13px; font-weight: 600;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s;
    }
    .btn-secondary:hover { background: #1e1e24; border-color: var(--accent); color: var(--accent); }

    /* ---- FONT PREVIEW ---- */
    .font-preview {
      background: #0d0d10;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px 14px;
      font-size: 15px;
      color: var(--muted);
      margin-top: 4px;
      min-height: 42px;
    }

    /* ---- EMPTY STATE ---- */
    .empty-state {
      text-align: center;
      padding: 40px 20px;
      color: var(--muted);
    }
    .empty-state i { font-size: 28px; margin-bottom: 10px; display: block; }
    .empty-state p { font-size: 13px; }
  </style>
</head>
<body>

{% if not session.user %}
<!-- ======================== LOGIN ======================== -->
<div class="login-wrap">
  <div class="login-card">
    <div class="login-logo">
      <div class="login-logo-icon"><i class="fas fa-fire" style="color:#fff"></i></div>
      <span>LAVA</span>
    </div>
    <p class="login-sub">Control Panel &mdash; Authorized Access Only</p>
    <form method="POST">
      <div class="form-field">
        <label>Admin Name</label>
        <input type="text" name="user" placeholder="Enter your name" required autocomplete="username">
      </div>
      <div class="form-field">
        <label>Access Key</label>
        <input type="password" name="pw" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;" required autocomplete="current-password">
      </div>
      <div style="margin-top:24px">
        <button type="submit" class="btn-primary"><i class="fas fa-sign-in-alt" style="margin-right:8px"></i>Sign In</button>
      </div>
    </form>
  </div>
</div>

{% elif not session.guild_id %}
<!-- ======================== SERVER SELECT ======================== -->
<div class="select-wrap">
  <div class="select-header">
    <h1>Choose a <span>Server</span></h1>
    <p>Select the server you want to manage</p>
  </div>
  {% if guilds %}
  <div class="servers-grid">
    {% for g in guilds %}
    <a href="/select/{{ g.id }}" class="server-card">
      <div class="server-avatar">{{ g.name[0].upper() }}</div>
      <div class="server-info">
        <strong>{{ g.name }}</strong>
        <span>Click to manage</span>
      </div>
    </a>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty-state">
    <i class="fas fa-server"></i>
    <p>No servers found. Make sure the bot is in at least one server.</p>
  </div>
  {% endif %}
  <div style="text-align:center; margin-top:40px;">
    <a href="/logout" class="topbar-btn danger"><i class="fas fa-sign-out-alt"></i> Logout</a>
  </div>
</div>

{% else %}
<!-- ======================== DASHBOARD ======================== -->
<div class="layout">

  <!-- SIDEBAR -->
  <nav class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-icon"><i class="fas fa-fire" style="color:#fff; font-size:13px"></i></div>
      <div>
        <div class="brand-text">LAVA</div>
        <span class="brand-sub">Network Panel</span>
      </div>
    </div>

    <div class="sidebar-section">
      <div class="section-label">Core</div>
      <button class="nav-item active" onclick="showPage('dash',this)">
        <i class="fas fa-home"></i> Overview
      </button>
      <button class="nav-item" onclick="showPage('sett',this)">
        <i class="fas fa-sliders-h"></i> Settings
      </button>
    </div>

    <div class="sidebar-section">
      <div class="section-label">Modules</div>
      <button class="nav-item" onclick="showPage('links',this)">
        <i class="fas fa-shield-alt"></i> Link Filter
      </button>
      <button class="nav-item" onclick="showPage('mod',this)">
        <i class="fas fa-gavel"></i> Moderation
      </button>
      <button class="nav-item" onclick="showPage('dms',this)">
        <i class="fas fa-envelope"></i> DM System
      </button>
      <button class="nav-item" onclick="showPage('help',this)">
        <i class="fas fa-question-circle"></i> Help Command
      </button>
      <button class="nav-item" onclick="showPage('info',this)">
        <i class="fas fa-info-circle"></i> Info Command
      </button>
    </div>

    <div class="sidebar-section">
      <div class="section-label">Tools</div>
      <button class="nav-item" onclick="showPage('creator',this)">
        <i class="fas fa-plus-circle"></i> Channel Creator
      </button>
    </div>

    <div class="sidebar-footer">
      <a href="/change_server" class="nav-item"><i class="fas fa-exchange-alt"></i> Switch Server</a>
      <a href="/logout" class="nav-item" style="color: var(--accent)"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </nav>

  <!-- CONTENT -->
  <div class="content-wrap">
    <!-- TOPBAR -->
    <div class="topbar">
      <div class="topbar-left">
        <div class="topbar-guild">
          <div class="topbar-avatar">{{ guild_name[0].upper() if guild_name else 'S' }}</div>
          <div class="topbar-name">{{ guild_name }}</div>
        </div>
      </div>
      <div class="topbar-right">
        <a href="/change_server" class="topbar-btn"><i class="fas fa-exchange-alt"></i> Switch</a>
        <a href="/logout" class="topbar-btn danger"><i class="fas fa-sign-out-alt"></i> Logout</a>
      </div>
    </div>

    <form method="POST" id="mainForm">
      <input type="hidden" name="action" value="save">

      <div class="content-body">

        <!-- ===== OVERVIEW ===== -->
        <div id="dash" class="page active">
          <div class="page-header">
            <h1>Overview</h1>
            <p>Server configuration at a glance</p>
          </div>

          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-icon red"><i class="fas fa-shield-alt"></i></div>
              <div>
                <div class="stat-label">Link Filter</div>
                <span class="badge {% if config.modules.link_filter.enabled == 'True' %}on{% else %}off{% endif %}">
                  {% if config.modules.link_filter.enabled == 'True' %}Active{% else %}Inactive{% endif %}
                </span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-icon amber"><i class="fas fa-gavel"></i></div>
              <div>
                <div class="stat-label">Moderation</div>
                <span class="badge {% if config.modules.mod.enabled == 'True' %}on{% else %}off{% endif %}">
                  {% if config.modules.mod.enabled == 'True' %}Active{% else %}Inactive{% endif %}
                </span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-icon green"><i class="fas fa-envelope"></i></div>
              <div>
                <div class="stat-label">Welcome DM</div>
                <span class="badge {% if config.modules.dms.welcome_enabled == 'True' %}on{% else %}off{% endif %}">
                  {% if config.modules.dms.welcome_enabled == 'True' %}Active{% else %}Inactive{% endif %}
                </span>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-icon blue"><i class="fas fa-terminal"></i></div>
              <div>
                <div class="stat-label">Prefix</div>
                <div class="stat-value" style="font-size:18px; font-family: monospace;">{{ config.prefix }}</div>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-title"><i class="fas fa-cubes"></i> Module Status</div>
            <div class="module-grid">
              <div class="module-card">
                <div class="module-card-head">
                  <div class="module-icon-wrap">
                    <div class="module-icon"><i class="fas fa-shield-alt"></i></div>
                    <div>
                      <div class="module-name">Link Filter</div>
                      <div class="module-desc">Block links in channels</div>
                    </div>
                  </div>
                  <span class="badge {% if config.modules.link_filter.enabled == 'True' %}on{% else %}off{% endif %}">
                    {% if config.modules.link_filter.enabled == 'True' %}On{% else %}Off{% endif %}
                  </span>
                </div>
              </div>
              <div class="module-card">
                <div class="module-card-head">
                  <div class="module-icon-wrap">
                    <div class="module-icon"><i class="fas fa-gavel"></i></div>
                    <div>
                      <div class="module-name">Moderation</div>
                      <div class="module-desc">Kick, ban &amp; timeout</div>
                    </div>
                  </div>
                  <span class="badge {% if config.modules.mod.enabled == 'True' %}on{% else %}off{% endif %}">
                    {% if config.modules.mod.enabled == 'True' %}On{% else %}Off{% endif %}
                  </span>
                </div>
              </div>
              <div class="module-card">
                <div class="module-card-head">
                  <div class="module-icon-wrap">
                    <div class="module-icon"><i class="fas fa-question-circle"></i></div>
                    <div>
                      <div class="module-name">Help Command</div>
                      <div class="module-desc">Custom help response</div>
                    </div>
                  </div>
                  <span class="badge {% if config.modules.help.enabled == 'True' %}on{% else %}off{% endif %}">
                    {% if config.modules.help.enabled == 'True' %}On{% else %}Off{% endif %}
                  </span>
                </div>
              </div>
              <div class="module-card">
                <div class="module-card-head">
                  <div class="module-icon-wrap">
                    <div class="module-icon"><i class="fas fa-info-circle"></i></div>
                    <div>
                      <div class="module-name">Info Command</div>
                      <div class="module-desc">Custom info response</div>
                    </div>
                  </div>
                  <span class="badge {% if config.modules.info.enabled == 'True' %}on{% else %}off{% endif %}">
                    {% if config.modules.info.enabled == 'True' %}On{% else %}Off{% endif %}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== SETTINGS ===== -->
        <div id="sett" class="page">
          <div class="page-header">
            <h1>Global Settings</h1>
            <p>Bot prefix and status configuration</p>
          </div>
          <div class="card">
            <div class="form-row">
              <div class="form-field">
                <label>Command Prefix</label>
                <input type="text" name="prefix" value="{{ config.prefix }}" maxlength="5" placeholder="!">
              </div>
              <div class="form-field">
                <label>Bot Status</label>
                <input type="text" name="status" value="{{ config.status }}" placeholder="Lava Network">
              </div>
            </div>
          </div>
        </div>

        <!-- ===== LINK FILTER ===== -->
        <div id="links" class="page">
          <div class="page-header">
            <h1>Link Filter</h1>
            <p>Block links in specified channels</p>
          </div>
          <div class="card">
            <div class="card-title"><i class="fas fa-power-off"></i> Status</div>
            <div class="toggle-wrap" style="margin-bottom:4px">
              <label class="toggle">
                <input type="checkbox" id="lf_toggle" onchange="syncToggle(this,'lf_enabled')" {% if config.modules.link_filter.enabled == 'True' %}checked{% endif %}>
                <span class="toggle-slider"></span>
              </label>
              <input type="hidden" name="lf_enabled" id="lf_enabled" value="{{ config.modules.link_filter.enabled }}">
              <label for="lf_toggle" style="font-size:14px; color:var(--text); font-weight:500;">Enable Link Filter</label>
            </div>
          </div>

          <div class="form-row">
            <div class="card" style="margin-bottom:0">
              <div class="card-title"><i class="fas fa-hashtag"></i> Protected Channels</div>
              <div class="check-list">
                {% for c in channels %}
                <label class="check-item">
                  <input type="checkbox" name="lf_chans" value="{{ c.id }}" {% if c.id|string in config.modules.link_filter.chans %}checked{% endif %}>
                  <span><i class="fas fa-hashtag item-icon"></i> {{ c.name }}</span>
                </label>
                {% else %}
                <div class="empty-state"><i class="fas fa-hashtag"></i><p>No channels found</p></div>
                {% endfor %}
              </div>
            </div>
            <div class="card" style="margin-bottom:0">
              <div class="card-title"><i class="fas fa-user-shield"></i> Bypass Roles</div>
              <div class="check-list">
                {% for r in roles %}
                <label class="check-item">
                  <input type="checkbox" name="lf_roles" value="{{ r.id }}" {% if r.id|string in config.modules.link_filter.roles %}checked{% endif %}>
                  <span>{{ r.name }}</span>
                </label>
                {% else %}
                <div class="empty-state"><i class="fas fa-users"></i><p>No roles found</p></div>
                {% endfor %}
              </div>
            </div>
          </div>
        </div>

        <!-- ===== MODERATION ===== -->
        <div id="mod" class="page">
          <div class="page-header">
            <h1>Moderation</h1>
            <p>Kick, ban, and timeout commands</p>
          </div>
          <div class="card">
            <div class="card-title"><i class="fas fa-power-off"></i> Status</div>
            <div class="toggle-wrap">
              <label class="toggle">
                <input type="checkbox" id="m_toggle" onchange="syncToggle(this,'m_enabled')" {% if config.modules.mod.enabled == 'True' %}checked{% endif %}>
                <span class="toggle-slider"></span>
              </label>
              <input type="hidden" name="m_enabled" id="m_enabled" value="{{ config.modules.mod.enabled }}">
              <label for="m_toggle" style="font-size:14px; color:var(--text); font-weight:500;">Enable Moderation</label>
            </div>
          </div>
          <div class="card">
            <div class="card-title"><i class="fas fa-users-cog"></i> Staff Roles</div>
            <div class="check-list">
              {% for r in roles %}
              <label class="check-item">
                <input type="checkbox" name="mod_roles" value="{{ r.id }}" {% if r.id|string in config.modules.mod.roles %}checked{% endif %}>
                <span>{{ r.name }}</span>
              </label>
              {% else %}
              <div class="empty-state"><i class="fas fa-users"></i><p>No roles found</p></div>
              {% endfor %}
            </div>
          </div>
        </div>

        <!-- ===== DM SYSTEM ===== -->
        <div id="dms" class="page">
          <div class="page-header">
            <h1>DM System</h1>
            <p>Automated DM notifications for server events. Use <code style="background:var(--card);padding:2px 6px;border-radius:4px;">{server}</code> as a placeholder.</p>
          </div>

          <div class="dm-block">
            <div class="dm-block-head">
              <div class="dm-block-title"><i class="fas fa-hand-wave"></i> Welcome Message</div>
              <div class="toggle-wrap">
                <label class="toggle">
                  <input type="checkbox" id="dw_toggle" onchange="syncToggle(this,'dm_w_enabled')" {% if config.modules.dms.welcome_enabled == 'True' %}checked{% endif %}>
                  <span class="toggle-slider"></span>
                </label>
                <input type="hidden" name="dm_w_enabled" id="dm_w_enabled" value="{{ config.modules.dms.welcome_enabled }}">
              </div>
            </div>
            <div class="form-field" style="margin-bottom:0">
              <label>Message Content</label>
              <textarea name="dm_w_msg">{{ config.modules.dms.welcome_msg }}</textarea>
            </div>
          </div>

          <div class="dm-block">
            <div class="dm-block-head">
              <div class="dm-block-title"><i class="fas fa-boot"></i> Kick Notification</div>
              <div class="toggle-wrap">
                <label class="toggle">
                  <input type="checkbox" id="dk_toggle" onchange="syncToggle(this,'dm_k_enabled')" {% if config.modules.dms.kick_enabled == 'True' %}checked{% endif %}>
                  <span class="toggle-slider"></span>
                </label>
                <input type="hidden" name="dm_k_enabled" id="dm_k_enabled" value="{{ config.modules.dms.kick_enabled }}">
              </div>
            </div>
            <div class="form-field" style="margin-bottom:0">
              <label>Message Content</label>
              <textarea name="dm_k_msg">{{ config.modules.dms.kick_msg }}</textarea>
            </div>
          </div>

          <div class="dm-block">
            <div class="dm-block-head">
              <div class="dm-block-title"><i class="fas fa-ban"></i> Ban Notification</div>
              <div class="toggle-wrap">
                <label class="toggle">
                  <input type="checkbox" id="db_toggle" onchange="syncToggle(this,'dm_b_enabled')" {% if config.modules.dms.ban_enabled == 'True' %}checked{% endif %}>
                  <span class="toggle-slider"></span>
                </label>
                <input type="hidden" name="dm_b_enabled" id="dm_b_enabled" value="{{ config.modules.dms.ban_enabled }}">
              </div>
            </div>
            <div class="form-field" style="margin-bottom:0">
              <label>Message Content</label>
              <textarea name="dm_b_msg">{{ config.modules.dms.ban_msg }}</textarea>
            </div>
          </div>
        </div>

        <!-- ===== HELP ===== -->
        <div id="help" class="page">
          <div class="page-header">
            <h1>Help Command</h1>
            <p>Configure the custom help response message</p>
          </div>
          <div class="card">
            <div class="toggle-wrap" style="margin-bottom:20px">
              <label class="toggle">
                <input type="checkbox" id="h_toggle" onchange="syncToggle(this,'h_enabled')" {% if config.modules.help.enabled == 'True' %}checked{% endif %}>
                <span class="toggle-slider"></span>
              </label>
              <input type="hidden" name="h_enabled" id="h_enabled" value="{{ config.modules.help.enabled }}">
              <label for="h_toggle" style="font-size:14px; color:var(--text); font-weight:500;">Enable Help Command</label>
            </div>
            <div class="form-field">
              <label>Command Aliases <span style="color:var(--muted);font-size:11px">(comma-separated)</span></label>
              <input type="text" name="h_aliases" value="{{ config.modules.help.aliases }}" placeholder="help, h">
            </div>
            <div class="form-field" style="margin-bottom:0">
              <label>Response Text</label>
              <textarea name="h_text">{{ config.modules.help.text }}</textarea>
            </div>
          </div>
        </div>

        <!-- ===== INFO ===== -->
        <div id="info" class="page">
          <div class="page-header">
            <h1>Info Command</h1>
            <p>Configure the custom info response message</p>
          </div>
          <div class="card">
            <div class="toggle-wrap" style="margin-bottom:20px">
              <label class="toggle">
                <input type="checkbox" id="i_toggle" onchange="syncToggle(this,'i_enabled')" {% if config.modules.info.enabled == 'True' %}checked{% endif %}>
                <span class="toggle-slider"></span>
              </label>
              <input type="hidden" name="i_enabled" id="i_enabled" value="{{ config.modules.info.enabled }}">
              <label for="i_toggle" style="font-size:14px; color:var(--text); font-weight:500;">Enable Info Command</label>
            </div>
            <div class="form-field">
              <label>Command Aliases <span style="color:var(--muted);font-size:11px">(comma-separated)</span></label>
              <input type="text" name="i_aliases" value="{{ config.modules.info.aliases }}" placeholder="info, i">
            </div>
            <div class="form-field" style="margin-bottom:0">
              <label>Response Text</label>
              <textarea name="i_text">{{ config.modules.info.text }}</textarea>
            </div>
          </div>
        </div>

        <!-- ===== CHANNEL CREATOR ===== -->
        <div id="creator" class="page">
          <div class="page-header">
            <h1>Channel Creator</h1>
            <p>Create text channels with stylized fonts</p>
          </div>
          <div class="card">
            <div class="form-row">
              <div class="form-field">
                <label>Channel Name</label>
                <input type="text" name="c_name" id="c_name_input" placeholder="general" oninput="updatePreview()">
              </div>
              <div class="form-field">
                <label>Category ID <span style="color:var(--muted);font-size:11px">(optional)</span></label>
                <input type="text" name="c_cat" placeholder="1234567890">
              </div>
            </div>
            <div class="form-field">
              <label>Font Style</label>
              <select name="c_font" id="c_font_select" onchange="updatePreview()">
                <option value="normal">Normal</option>
                <option value="gothic">Gothic (𝔤𝔬𝔱𝔥𝔦𝔠)</option>
                <option value="fancy">Fancy (𝓯𝓪𝓷𝓬𝔂)</option>
                <option value="smallcaps">Small Caps (ꜱᴍᴀʟʟ)</option>
              </select>
            </div>
            <div class="form-field">
              <label>Preview</label>
              <div class="font-preview" id="font_preview"># channel-name</div>
            </div>
            <button type="submit" name="action" value="create_chan" class="btn-secondary">
              <i class="fas fa-plus"></i> Create Channel
            </button>
          </div>
        </div>

      </div><!-- end content-body -->

      <div class="save-bar">
        <p>Changes apply immediately after saving</p>
        <button type="submit" class="btn-save"><i class="fas fa-save"></i> Save Configuration</button>
      </div>

    </form>
  </div><!-- end content-wrap -->
</div><!-- end layout -->

<div id="toast"><i class="fas fa-check-circle"></i> Configuration saved successfully</div>

{% endif %}

<script>
  // Page navigation
  function showPage(id, btn) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    if (btn) btn.classList.add('active');
  }

  // Toggle switch syncs to hidden input
  function syncToggle(checkbox, hiddenId) {
    document.getElementById(hiddenId).value = checkbox.checked ? 'True' : 'False';
  }

  // Font preview
  const FONTS = {
    normal: s => s,
    gothic: s => s.split('').map(c => {
      const idx = 'abcdefghijklmnopqrstuvwxyz'.indexOf(c);
      return idx >= 0 ? '𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷'[idx] : c;
    }).join(''),
    fancy: s => s.split('').map(c => {
      const idx = 'abcdefghijklmnopqrstuvwxyz'.indexOf(c);
      return idx >= 0 ? '𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃'[idx] : c;
    }).join(''),
    smallcaps: s => s.split('').map(c => {
      const idx = 'abcdefghijklmnopqrstuvwxyz'.indexOf(c);
      return idx >= 0 ? 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ'[idx] : c;
    }).join('')
  };

  function updatePreview() {
    const raw = (document.getElementById('c_name_input').value || 'channel-name').toLowerCase().replace(/ /g, '-');
    const font = document.getElementById('c_font_select').value;
    const transformed = FONTS[font] ? FONTS[font](raw) : raw;
    document.getElementById('font_preview').textContent = '# ' + transformed;
  }

  // Toast on save
  {% if request.method == 'POST' and session.guild_id %}
  window.addEventListener('DOMContentLoaded', () => {
    const t = document.getElementById('toast');
    if (t) {
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3000);
    }
  });
  {% endif %}
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
            return redirect("/")

        action = request.form.get("action")
        if action == "create_chan" and 'guild_id' in session:
            name = format_font(request.form.get("c_name", ""), request.form.get("c_font", "normal"))
            cat_id = request.form.get("c_cat", "")
            async def run_c():
                g = bot.get_guild(int(session['guild_id']))
                cat = g.get_channel(int(cat_id)) if cat_id and cat_id.isdigit() else None
                await g.create_text_channel(name, category=cat)
            asyncio.run_coroutine_threadsafe(run_c(), bot.loop)
            return redirect("/")

        if action == "save" and 'guild_id' in session:
            updates = {
                "prefix": request.form.get("prefix"),
                "status": request.form.get("status"),
                "modules.mod.enabled": request.form.get("m_enabled"),
                "modules.mod.roles": request.form.getlist("mod_roles"),
                "modules.link_filter.enabled": request.form.get("lf_enabled"),
                "modules.link_filter.chans": request.form.getlist("lf_chans"),
                "modules.link_filter.roles": request.form.getlist("lf_roles"),
                "modules.help.enabled": request.form.get("h_enabled"),
                "modules.help.aliases": request.form.get("h_aliases"),
                "modules.help.text": request.form.get("h_text"),
                "modules.info.enabled": request.form.get("i_enabled"),
                "modules.info.aliases": request.form.get("i_aliases"),
                "modules.info.text": request.form.get("i_text"),
                "modules.dms.welcome_enabled": request.form.get("dm_w_enabled"),
                "modules.dms.welcome_msg": request.form.get("dm_w_msg"),
                "modules.dms.kick_enabled": request.form.get("dm_k_enabled"),
                "modules.dms.kick_msg": request.form.get("dm_k_msg"),
                "modules.dms.ban_enabled": request.form.get("dm_b_enabled"),
                "modules.dms.ban_msg": request.form.get("dm_b_msg"),
            }
            config_col.update_one({"guild_id": session['guild_id']}, {"$set": updates})
            return redirect("/")

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
    return redirect("/")

@app.route("/change_server")
def change_server():
    session.pop('guild_id', None)
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

def run():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run).start()
bot.run(os.environ.get('DISCORD_TOKEN'))
