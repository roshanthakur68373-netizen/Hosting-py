from flask import Flask
from threading import Thread
# EXU CODER - Simple Render Telegram Hosting Bot
# Single-file version. No .env / no requirements.txt needed.
# Render Build Command:
# pip install pyTelegramBotAPI psutil
# Render Start Command:
# python bot.py

import os
import time
import sqlite3
import threading
import subprocess
import signal
from datetime import datetime, timedelta

import telebot
from telebot import types

# =========================================================
# CONFIG - CHANGE THESE
# =========================================================
TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required. Set it in Render Environment.")
OWNER_ID = 6567632240
ADMIN_ID = OWNER_ID

OWNER_USERNAME = "@Harshit_5stare"

FREE_LIMIT = 10
PREMIUM_LIMIT = 15
ADMIN_LIMIT = 999

# =========================================================
# PATHS
# =========================================================

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
BOT_DIR = os.path.join(DATA_DIR, "bots")
DB_FILE = os.path.join(DATA_DIR, "bot.db")
LOG_DIR = os.path.join(DATA_DIR, "logs")

os.makedirs(BOT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# =========================================================
# BOT
# =========================================================

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

admins = {OWNER_ID, ADMIN_ID}
running = {}
start_time = datetime.now()

# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            user_id INTEGER,
            name TEXT,
            file_type TEXT,
            size INTEGER,
            uploaded TEXT,
            PRIMARY KEY(user_id, name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            expiry TEXT
        )
    """)

    con.commit()
    con.close()

def save_user(message):
    con = db()
    cur = con.cursor()
    now = datetime.now().isoformat()

    cur.execute("""
        INSERT INTO users(user_id, username, first_seen, last_seen)
        VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        last_seen=excluded.last_seen
    """, (
        message.from_user.id,
        message.from_user.username or "Unknown",
        now,
        now
    ))

    con.commit()
    con.close()

def save_file(user_id, name, file_type, size):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO files
        VALUES(?,?,?,?,?)
    """, (
        user_id,
        name,
        file_type,
        size,
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()

def remove_file(user_id, name):
    con = db()
    con.execute(
        "DELETE FROM files WHERE user_id=? AND name=?",
        (user_id, name)
    )
    con.commit()
    con.close()

def get_files(user_id):
    con = db()
    rows = con.execute(
        "SELECT name,file_type,size FROM files WHERE user_id=?",
        (user_id,)
    ).fetchall()
    con.close()
    return rows

def user_count():
    con = db()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return n

def subscription_active(user_id):
    con = db()
    row = con.execute(
        "SELECT expiry FROM subscriptions WHERE user_id=?",
        (user_id,)
    ).fetchone()
    con.close()

    if not row:
        return False

    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except:
        return False

# =========================================================
# HELPERS
# =========================================================

def user_dir(user_id):
    path = os.path.join(BOT_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def limit_for(user_id):
    if user_id == OWNER_ID:
        return 999999
    if user_id in admins:
        return ADMIN_LIMIT
    if subscription_active(user_id):
        return PREMIUM_LIMIT
    return FREE_LIMIT

def safe_name(name):
    name = os.path.basename(name)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    name = "".join(c for c in name if c in allowed)
    return name[:100] or "file"

def size_text(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def uptime():
    return str(datetime.now() - start_time).split(".")[0]

def is_running(user_id, name):
    key = f"{user_id}:{name}"
    p = running.get(key)
    return bool(p and p.poll() is None)

def log_path(user_id, name):
    return os.path.join(LOG_DIR, f"{user_id}_{safe_name(name)}.log")

# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(user_id):
    k = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    k.row("📤 Upload File", "📂 My Files")
    k.row("🟢 Running Bots", "⚡ Bot Speed")
    k.row("📊 Statistics", "📢 Updates Channel")
    k.row("📞 Contact Owner")

    if user_id in admins:
        k.row("👑 Admin Panel", "📢 Broadcast")

    return k

def file_keyboard(user_id, name):
    k = types.InlineKeyboardMarkup(row_width=2)

    if is_running(user_id, name):
        k.add(
            types.InlineKeyboardButton(
                "🛑 Stop",
                callback_data=f"stop:{name}"
            ),
            types.InlineKeyboardButton(
                "📋 Logs",
                callback_data=f"logs:{name}"
            )
        )
        k.add(
            types.InlineKeyboardButton(
                "🔄 Restart",
                callback_data=f"restart:{name}"
            )
        )
    else:
        k.add(
            types.InlineKeyboardButton(
                "▶️ Run",
                callback_data=f"run:{name}"
            ),
            types.InlineKeyboardButton(
                "🗑️ Delete",
                callback_data=f"delete:{name}"
            )
        )
        k.add(
            types.InlineKeyboardButton(
                "📥 Download",
                callback_data=f"download:{name}"
            )
        )

    return k

# =========================================================
# START / HELP
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    save_user(message)

    if message.from_user.id not in admins:
        pass

    bot.send_message(
        message.chat.id,
        f"""
🤖 <b>EXU CODER</b>

👋 Welcome, <b>{message.from_user.first_name}</b>!

📤 Upload your Python/Node file
🚀 Run your own script
🛑 Stop running scripts
📋 View logs
📥 Download files
🗑️ Delete files

📁 Limit: {len(get_files(message.from_user.id))}/{limit_for(message.from_user.id)}
⏱️ Uptime: {uptime()}
""",
        reply_markup=main_keyboard(message.from_user.id)
    )

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.send_message(
        message.chat.id,
        """
📚 <b>COMMANDS</b>

/start - Start bot
/help - Help
/files - My files
/running - Running bots
/stats - Statistics
/speed - Bot speed
/id - Your Telegram ID

📤 You can also send a .py or .js file directly.
"""
    )

@bot.message_handler(commands=["id"])
def id_cmd(message):
    bot.reply_to(
        message,
        f"🆔 <code>{message.from_user.id}</code>"
    )

# =========================================================
# TEXT BUTTONS
# =========================================================

@bot.message_handler(content_types=["text"])
def buttons(message):
    save_user(message)
    text = message.text
    uid = message.from_user.id

    if text == "📤 Upload File":
        bot.send_message(
            message.chat.id,
            "📤 Send a <b>.py</b>, <b>.js</b> or <b>.zip</b> file."
        )

    elif text == "📂 My Files":
        show_files(message)

    elif text == "🟢 Running Bots":
        show_running(message)

    elif text == "⚡ Bot Speed":
        t = time.time()
        bot.send_chat_action(message.chat.id, "typing")
        ms = (time.time() - t) * 1000
        bot.send_message(
            message.chat.id,
            f"⚡ Ping: <code>{ms:.2f} ms</code>"
        )

    elif text == "📊 Statistics":
        bot.send_message(
            message.chat.id,
            f"""
📊 <b>STATISTICS</b>

👥 Users: {user_count()}
🤖 Running bots: {len(running)}
⏱️ Uptime: {uptime()}
"""
        )

    elif text == "📢 Updates Channel":
        bot.send_message(
            message.chat.id,
            f"📢 Updates:\n{UPDATE_CHANNEL}"
        )

    elif text == "📞 Contact Owner":
        bot.send_message(
            message.chat.id,
            f"📞 Owner: {OWNER_USERNAME}"
        )

    elif text == "👑 Admin Panel":
        if uid in admins:
            bot.send_message(
                message.chat.id,
                f"""
👑 <b>ADMIN PANEL</b>

👥 Users: {user_count()}
🤖 Running: {len(running)}
⏱️ Uptime: {uptime()}
"""
            )

    elif text == "📢 Broadcast":
        if uid in admins:
            msg = bot.reply_to(
                message,
                "📢 Send the broadcast message:"
            )
            bot.register_next_step_handler(
                msg,
                broadcast
            )

# =========================================================
# UPLOAD
# =========================================================

@bot.message_handler(content_types=["document"])
def upload(message):
    save_user(message)

    uid = message.from_user.id
    doc = message.document
    name = safe_name(doc.file_name)

    files = get_files(uid)

    if len(files) >= limit_for(uid):
        bot.reply_to(
            message,
            f"❌ File limit reached: {len(files)}/{limit_for(uid)}"
        )
        return

    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if ext not in ["py", "js", "zip", "json", "txt", "yml", "yaml"]:
        bot.reply_to(
            message,
            "❌ Allowed: .py .js .zip .json .txt .yml .yaml"
        )
        return

    msg = bot.reply_to(
        message,
        f"⏳ Downloading <code>{name}</code>..."
    )

    try:
        info = bot.get_file(doc.file_id)
        data = bot.download_file(info.file_path)

        path = os.path.join(user_dir(uid), name)

        with open(path, "wb") as f:
            f.write(data)

        save_file(uid, name, ext, len(data))

        bot.edit_message_text(
            f"""
✅ <b>UPLOAD COMPLETE</b>

📄 File: <code>{name}</code>
📦 Size: {size_text(len(data))}

Use the button below.
""",
            message.chat.id,
            msg.message_id,
            reply_markup=file_keyboard(uid, name)
        )

    except Exception as e:
        bot.edit_message_text(
            f"❌ Upload failed\n<code>{str(e)[:500]}</code>",
            message.chat.id,
            msg.message_id
        )

# =========================================================
# FILE LIST
# =========================================================

def show_files(message):
    uid = message.from_user.id
    rows = get_files(uid)

    if not rows:
        bot.send_message(
            message.chat.id,
            "📂 You have no files."
        )
        return

    for name, ext, size in rows:
        status = "🟢 Running" if is_running(uid, name) else "🔴 Stopped"

        bot.send_message(
            message.chat.id,
            f"""
📄 <b>{name}</b>

📁 Type: {ext.upper()}
📦 Size: {size_text(size)}
📊 Status: {status}
""",
            reply_markup=file_keyboard(uid, name)
        )

# =========================================================
# RUNNING
# =========================================================

def show_running(message):
    uid = message.from_user.id
    found = False

    for key, process in list(running.items()):
        owner, name = key.split(":", 1)

        if int(owner) != uid and uid not in admins:
            continue

        if process.poll() is None:
            found = True
            bot.send_message(
                message.chat.id,
                f"🟢 <b>{name}</b>\nPID: <code>{process.pid}</code>",
                reply_markup=file_keyboard(int(owner), name)
            )

    if not found:
        bot.send_message(
            message.chat.id,
            "🔴 No running bots."
        )

# =========================================================
# RUN SCRIPT
# =========================================================

def run_script(uid, name, chat_id):
    key = f"{uid}:{name}"
    folder = user_dir(uid)
    path = os.path.join(folder, name)

    if not os.path.exists(path):
        bot.send_message(chat_id, "❌ File not found.")
        return

    if is_running(uid, name):
        bot.send_message(chat_id, "⚠️ Already running.")
        return

    ext = name.rsplit(".", 1)[-1].lower()

    if ext not in ["py", "js"]:
        bot.send_message(
            chat_id,
            "❌ Only .py and .js files can be run."
        )
        return

    logfile = log_path(uid, name)

    try:
        log = open(logfile, "a", encoding="utf-8")

        command = (
            ["python", path]
            if ext == "py"
            else ["node", path]
        )

        process = subprocess.Popen(
            command,
            cwd=folder,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL
        )

        running[key] = process

        bot.send_message(
            chat_id,
            f"""
🚀 <b>BOT STARTED</b>

📄 <code>{name}</code>
🆔 PID: <code>{process.pid}</code>
"""
        )

        threading.Thread(
            target=watch_process,
            args=(key, log),
            daemon=True
        ).start()

    except Exception as e:
        bot.send_message(
            chat_id,
            f"❌ Start failed:\n<code>{str(e)[:1000]}</code>"
        )

def watch_process(key, log):
    process = running.get(key)

    if process:
        process.wait()

    try:
        log.close()
    except:
        pass

    running.pop(key, None)

# =========================================================
# STOP
# =========================================================

def stop_script(uid, name):
    key = f"{uid}:{name}"
    process = running.get(key)

    if not process or process.poll() is not None:
        running.pop(key, None)
        return False

    try:
        process.terminate()
        process.wait(timeout=5)
    except:
        try:
            process.kill()
        except:
            pass

    running.pop(key, None)
    return True

# =========================================================
# CALLBACKS
# =========================================================

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    try:
        action, name = call.data.split(":", 1)
        uid = call.from_user.id

        if action == "run":
            bot.answer_callback_query(call.id, "🚀 Starting...")
            threading.Thread(
                target=run_script,
                args=(uid, name, call.message.chat.id),
                daemon=True
            ).start()

        elif action == "stop":
            if stop_script(uid, name):
                bot.answer_callback_query(call.id, "🛑 Stopped")
                bot.send_message(
                    call.message.chat.id,
                    f"🛑 <b>{name}</b> stopped."
                )
            else:
                bot.answer_callback_query(
                    call.id,
                    "❌ Not running."
                )

        elif action == "restart":
            stop_script(uid, name)
            bot.answer_callback_query(call.id, "🔄 Restarting...")
            threading.Thread(
                target=run_script,
                args=(uid, name, call.message.chat.id),
                daemon=True
            ).start()

        elif action == "download":
            path = os.path.join(user_dir(uid), name)

            if not os.path.exists(path):
                bot.answer_callback_query(
                    call.id,
                    "❌ File not found."
                )
                return

            with open(path, "rb") as f:
                bot.send_document(
                    call.message.chat.id,
                    f,
                    caption=f"📄 {name}"
                )

            bot.answer_callback_query(call.id, "📥 Sent")

        elif action == "logs":
            path = log_path(uid, name)

            if not os.path.exists(path):
                bot.answer_callback_query(
                    call.id,
                    "📋 No logs."
                )
                return

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="ignore"
            ) as f:
                text = f.read()[-3500:]

            if not text:
                text = "No output yet."

            bot.send_message(
                call.message.chat.id,
                f"📋 <b>{name}</b>\n\n<pre>{text}</pre>"
            )

            bot.answer_callback_query(call.id)

        elif action == "delete":
            if is_running(uid, name):
                bot.answer_callback_query(
                    call.id,
                    "🛑 Stop it first."
                )
                return

            path = os.path.join(user_dir(uid), name)

            if os.path.exists(path):
                os.remove(path)

            remove_file(uid, name)

            bot.answer_callback_query(
                call.id,
                "🗑️ Deleted"
            )

            bot.edit_message_text(
                f"🗑️ <b>{name}</b> deleted.",
                call.message.chat.id,
                call.message.message_id
            )

    except Exception as e:
        bot.answer_callback_query(
            call.id,
            f"❌ {str(e)[:100]}"
        )

# =========================================================
# BROADCAST
# =========================================================

def broadcast(message):
    if message.from_user.id not in admins:
        return

    text = message.text

    con = db()
    users = con.execute(
        "SELECT user_id FROM users"
    ).fetchall()
    con.close()

    success = 0

    for (uid,) in users:
        try:
            bot.send_message(
                uid,
                f"📢 <b>Broadcast</b>\n\n{text}"
            )
            success += 1
            time.sleep(0.05)
        except:
            pass

    bot.send_message(
        message.chat.id,
        f"✅ Broadcast sent to {success} users."
    )

# =========================================================
# ADMIN COMMANDS
# =========================================================

@bot.message_handler(commands=["stats"])
def stats(message):
    if message.from_user.id not in admins:
        return

    bot.send_message(
        message.chat.id,
        f"""
📊 <b>ADMIN STATS</b>

👥 Users: {user_count()}
🤖 Running: {len(running)}
⏱️ Uptime: {uptime()}
"""
    )

@bot.message_handler(commands=["running"])
def running_cmd(message):
    show_running(message)

@bot.message_handler(commands=["files"])
def files_cmd(message):
    show_files(message)

@bot.message_handler(commands=["speed"])
def speed_cmd(message):
    start = time.time()
    bot.get_me()
    ms = (time.time() - start) * 1000

    bot.send_message(
        message.chat.id,
        f"⚡ Telegram API: <code>{ms:.2f} ms</code>"
    )

# =========================================================
# SHUTDOWN
# =========================================================

def stop_all():
    for key, process in list(running.items()):
        try:
            process.terminate()
        except:
            pass
    running.clear()

# =========================================================
# RENDER + UPTIMEROBOT HEALTH SERVER
# =========================================================

_web_app = Flask(__name__)

@_web_app.get("/")
def _home():
    return "Telegram Hosting Bot is running", 200

@_web_app.get("/health")
def _health():
    return {"status": "ok", "service": "telegram-hosting-bot"}, 200

def _run_web_server():
    port = int(os.environ.get("PORT", "10000"))
    _web_app.run(host="0.0.0.0", port=port, threaded=True)

# =========================================================
# START
# =========================================================

init_db()

print("=" * 45)
print("🤖 EXU CODER")
print("🚀 Render Web Service starting...")
print("❤️ Health: /health")
print("=" * 45)

# Render needs an HTTP server; UptimeRobot can ping /health.
Thread(target=_run_web_server, daemon=True).start()

while True:
    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=30,
            skip_pending=True
        )
    except KeyboardInterrupt:
        stop_all()
        break
    except Exception as e:
        print("Bot error:", e)
        time.sleep(5)
