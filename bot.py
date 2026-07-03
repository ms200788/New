import os
import re
import threading
from flask import Flask
import telebot
from telebot import types

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = 10000

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================== STATE ==================
button_sessions = {}
edit_sessions = {}
blockquote_sessions = {}
last_forward_channel = {}

# ================== HELPERS ==================

def build_keyboard(buttons, rows=None, cols=None):
    if not buttons:
        return None
    kb = types.InlineKeyboardMarkup()
    if not rows or not cols:
        for t, u in buttons:
            kb.add(types.InlineKeyboardButton(t, url=u))
        return kb

    i = 0
    for _ in range(rows):
        row = []
        for _ in range(cols):
            if i >= len(buttons):
                break
            t, u = buttons[i]
            row.append(types.InlineKeyboardButton(t, url=u))
            i += 1
        if row:
            kb.row(*row)
    return kb


def convert_texttourl(text):
    if not text:
        return ""
    def repl(m):
        word, url = m.group(1).strip(), m.group(2).strip()
        if not url.startswith("http"):
            url = "https://" + url
        return f'<a href="{url}">{word}</a>'
    return re.sub(r"\{([^|]+)\|\s*([^}]+)\}", repl, text)


def copy_any(chat_id, msg, reply_markup=None):
    return bot.copy_message(
        chat_id=chat_id,
        from_chat_id=msg.chat.id,
        message_id=msg.message_id,
        reply_markup=reply_markup
    )

# ================== SETBUTTON ==================

@bot.message_handler(commands=["setbutton"])
def setbutton(m):
    if not m.reply_to_message:
        return bot.reply_to(m, "Reply to a message.")

    button_sessions[m.from_user.id] = {
        "msg": m.reply_to_message,
        "buttons": [],
        "rows": None,
        "cols": None
    }

    bot.reply_to(m, "Send buttons:\nText | URL\n\n/set rows cols\n/done")


# ================== EDITMESSAGE ==================

@bot.message_handler(commands=["editmessage"])
def editmessage(m):
    if not m.reply_to_message:
        return bot.reply_to(m, "❌ Reply to a message forwarded from your channel.")

    # Extract original message ID from the forward metadata
    msg_id = m.reply_to_message.forward_from_message_id
    if not msg_id:
        return bot.reply_to(m, "❌ This message does not contain channel forward data. Ensure it is directly forwarded from the channel.")

    try:
        cid = int(m.text.split()[1])
    except:
        # Fallback to forward source chat ID if available
        if m.reply_to_message.forward_from_chat:
            cid = m.reply_to_message.forward_from_chat.id
        else:
            return bot.reply_to(m, "Usage: `/editmessage <channel_id>` (e.g., /editmessage -100123456789)")

    # Read original text/caption and convert {text|url} rules automatically
    orig_text = m.reply_to_message.text or m.reply_to_message.caption or ""
    converted_text = convert_texttourl(orig_text)

    edit_sessions[m.from_user.id] = {
        "channel_id": cid,
        "message_id": msg_id,
        "text": converted_text,
        "is_caption": m.reply_to_message.caption is not None,
        "buttons": [],
        "rows": None,
        "cols": None
    }

    bot.reply_to(
        m, 
        f"📝 **Editing Mode Activated**\n"
        f"Channel: `{cid}`\n"
        f"Message ID: `{msg_id}`\n\n"
        f"Send new buttons: `Text | URL`\n"
        f"Use `/set rows cols` to organize layout.\n"
        f"Use `/done` to apply changes permanently."
    )


# ================== SHARED SESSION HANDLERS ==================

@bot.message_handler(commands=["set"])
def set_layout(m):
    uid = m.from_user.id
    session = button_sessions.get(uid) or edit_sessions.get(uid)
    if not session:
        return

    try:
        _, r, c = m.text.split()
        session["rows"] = int(r)
        session["cols"] = int(c)
        bot.reply_to(m, "Layout set.")
    except:
        bot.reply_to(m, "Usage: /set rows cols")


@bot.message_handler(func=lambda m: (m.from_user.id in button_sessions or m.from_user.id in edit_sessions) and "|" in (m.text or ""))
def collect_button(m):
    uid = m.from_user.id
    s = button_sessions.get(uid) or edit_sessions.get(uid)
    try:
        t, u = map(str.strip, m.text.split("|", 1))
        s["buttons"].append((t, u))
        bot.reply_to(m, "➕ Button added")
    except Exception as e:
        bot.reply_to(m, f"Format error: {e}")

# ================== BLOCKQUOTE ==================

@bot.message_handler(commands=["blockquote"])
def blockquote(m):
    blockquote_sessions[m.from_user.id] = []
    bot.reply_to(m, "Send lines. Use /done when finished.")


@bot.message_handler(
    func=lambda m: m.from_user.id in blockquote_sessions and not m.text.startswith("/")
)
def collect_block(m):
    line = m.text.strip()
    if line:
        blockquote_sessions[m.from_user.id].append(line)
        bot.reply_to(m, "➕ Added")

# ================== TEXT TO URL ==================

@bot.message_handler(commands=["texttourl"])
def texttourl(m):
    if not m.reply_to_message or not m.reply_to_message.text:
        return bot.reply_to(m, "Reply to text.")

    text = convert_texttourl(m.reply_to_message.text)
    bot.send_message(m.chat.id, text, disable_web_page_preview=True)

# ================== FORWARD (COPY) ==================

@bot.message_handler(commands=["forward"])
def forward(m):
    if not m.reply_to_message:
        return bot.reply_to(m, "Reply to a message.")

    try:
        cid = int(m.text.split()[1])
    except:
        return bot.reply_to(m, "Usage: /forward <channel_id>")

    copy_any(cid, m.reply_to_message, m.reply_to_message.reply_markup)
    bot.reply_to(m, "📤 Sent")

# ================== DONE (UNIFIED) ==================

@bot.message_handler(commands=["done"])
def done(m):
    uid = m.from_user.id

    # 1. BLOCKQUOTE DONE
    if uid in blockquote_sessions:
        lines = blockquote_sessions.pop(uid)
        msg = "\n".join(
            f"<blockquote>{convert_texttourl(l)}</blockquote>"
            for l in lines
        )
        bot.send_message(m.chat.id, msg, disable_web_page_preview=True)
        return

    # 2. EDITMESSAGE DONE
    if uid in edit_sessions:
        s = edit_sessions.pop(uid)
        kb = build_keyboard(s["buttons"], s["rows"], s["cols"])
        
        try:
            if s["text"]:
                if s["is_caption"]:
                    bot.edit_message_caption(chat_id=s["channel_id"], message_id=s["message_id"], caption=s["text"], reply_markup=kb)
                else:
                    bot.edit_message_text(chat_id=s["channel_id"], message_id=s["message_id"], text=s["text"], reply_markup=kb, disable_web_page_preview=True)
            else:
                # If there's no text/caption (e.g. pure media element), just edit markup
                bot.edit_message_reply_markup(chat_id=s["channel_id"], message_id=s["message_id"], reply_markup=kb)
            
            bot.reply_to(m, "✅ Channel message edited successfully!")
        except Exception as e:
            bot.reply_to(m, f"❌ Failed to edit channel message:\n`{e}`")
        return

    # 3. SETBUTTON DONE
    if uid in button_sessions:
        s = button_sessions.pop(uid)
        kb = build_keyboard(s["buttons"], s["rows"], s["cols"])
        copy_any(m.chat.id, s["msg"], kb)

# ================== FLASK HEALTH ==================

app = Flask(__name__)

@app.route("/health")
def health():
    return "OK"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# ================== RUN ==================

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
