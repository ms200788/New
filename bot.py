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


def extract_media(msg):
    """Extracts file_id and type from any incoming message."""
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    elif msg.video:
        return msg.video.file_id, "video"
    elif msg.animation:
        return msg.animation.file_id, "animation"
    elif msg.document:
        return msg.document.file_id, "document"
    return None, None

# ================== DISCOVER PATH ==================

@bot.message_handler(commands=["path"])
def get_message_path(m):
    if not m.reply_to_message:
        return bot.reply_to(m, "❌ Reply to a message forwarded from the target channel.")
    
    # Handle public channel forwards
    chat = m.reply_to_message.forward_from_chat
    msg_id = m.reply_to_message.forward_from_message_id
    
    if chat and msg_id:
        path_str = f"`{chat.id} {msg_id}`"
        link_str = f"https://t.me/c/{str(chat.id).replace('-100', '')}/{msg_id}" if str(chat.id).startswith("-100") else ""
        return bot.reply_to(
            m, 
            f"📍 **Target Found (Public Header Method):**\n\n"
            f"Copy Path: {path_str}\n"
            f"Private Link alternative: `{link_str}`" if link_str else "",
            parse_mode="Markdown"
        )
    
    # Fallback for strict private channel restrictions
    return bot.reply_to(
        m,
        "⚠️ **Telegram hidden metadata warning.**\n"
        "Because this channel is heavily restricted or private, Telegram stripped the target IDs.\n\n"
        "**Manual Solution:** Copy the post link inside your channel and map it directly:\n"
        "• Link: `https://t.me/c/123456789/453` ➔ Path: `-100123456789 453`",
        parse_mode="Markdown"
    )

# ================== REPLACE / EDIT ENGINE ==================

@bot.message_handler(commands=["replace", "editmessage"])
def replace_message(m):
    args = m.text.split()
    cid = None
    msg_id = None

    if len(args) < 2:
        return bot.reply_to(
            m, 
            "Format:\n"
            "`/replace <channel_id> <message_id>`\n"
            "Or use a private path link directly:\n"
            "`/replace https://t.me/c/123456789/453`\n\n"
            "👉 **Make sure you are replying to your NEW message (text, photo, video, or doc).**",
            parse_mode="Markdown"
        )

    # Parse inputs
    if "t.me/c/" in args[1]:
        try:
            parts = args[1].split("t.me/c/")[1].split("/")
            cid = int("-100" + parts[0])
            msg_id = int(parts[1])
        except:
            return bot.reply_to(m, "❌ Invalid private channel link format.")
    else:
        try:
            cid = int(args[1])
            msg_id = int(args[2])
        except:
            return bot.reply_to(m, "❌ Format must be explicitly: `/replace <channel_id> <message_id>`")

    if not m.reply_to_message:
        return bot.reply_to(m, "❌ **Error:** Reply to the message containing the new assets.")

    # Process parameters
    orig_text = m.reply_to_message.text or m.reply_to_message.caption or ""
    converted_text = convert_texttourl(orig_text)
    media_id, media_type = extract_media(m.reply_to_message)

    edit_sessions[m.from_user.id] = {
        "channel_id": cid,
        "message_id": msg_id,
        "text": converted_text,
        "media_id": media_id,
        "media_type": media_type,
        "buttons": [],
        "rows": None,
        "cols": None
    }

    bot.reply_to(
        m, 
        f"🛠️ **Replacement Session Active**\n\n"
        f"Target Location: `{cid}` | Message: `{msg_id}`\n"
        f"Media Swapped: `{media_type if media_type else 'None (Text Only)'}`\n\n"
        f"💡 **Formatting Utilities:**\n"
        f"• Wrap context inside blockquote: `/wrapblockquote`\n"
        f"• Collect buttons: `Label | URL`\n"
        f"• Layout layout grid: `/set rows cols`\n"
        f"• Execute change: `/done`",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["wrapblockquote"])
def wrap_blockquote(m):
    uid = m.from_user.id
    if uid not in edit_sessions:
        return bot.reply_to(m, "❌ No live replacement session active.")
    
    current_text = edit_sessions[uid]["text"]
    if not current_text:
        return bot.reply_to(m, "❌ There is no text or caption payload to enclose.")
    
    edit_sessions[uid]["text"] = f"<blockquote>{current_text}</blockquote>"
    bot.reply_to(m, "📝 Text content wrapped within HTML blockquotes.")

# ================== SHARED CONTEXT HANDLERS ==================

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

# ================== SETBUTTONS SEPARATE FLOW ==================

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

# ================== CORE UTILS ==================

@bot.message_handler(commands=["blockquote"])
def blockquote(m):
    blockquote_sessions[m.from_user.id] = []
    bot.reply_to(m, "Send lines. Use /done when finished.")


@bot.message_handler(func=lambda m: m.from_user.id in blockquote_sessions and not m.text.startswith("/"))
def collect_block(m):
    line = m.text.strip()
    if line:
        blockquote_sessions[m.from_user.id].append(line)
        bot.reply_to(m, "➕ Added")


@bot.message_handler(commands=["texttourl"])
def texttourl(m):
    if not m.reply_to_message or not m.reply_to_message.text:
        return bot.reply_to(m, "Reply to text.")
    text = convert_texttourl(m.reply_to_message.text)
    bot.send_message(m.chat.id, text, disable_web_page_preview=True)


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

# ================== PIPELINE DONE EXECUTOR ==================

@bot.message_handler(commands=["done"])
def done(m):
    uid = m.from_user.id

    # 1. BLOCKQUOTE CONSTRUCT FLOW
    if uid in blockquote_sessions:
        lines = blockquote_sessions.pop(uid)
        msg = "\n".join(f"<blockquote>{convert_texttourl(l)}</blockquote>" for l in lines)
        bot.send_message(m.chat.id, msg, disable_web_page_preview=True)
        return

    # 2. CHANNEL REPLACE / LIVE MESSAGE EDIT CONTEXT
    if uid in edit_sessions:
        s = edit_sessions.pop(uid)
        kb = build_keyboard(s["buttons"], s["rows"], s["cols"])
        
        try:
            # Check if replacing completely with a new media instance or just updating text/captions
            if s["media_id"]:
                # Build replacement InputMedia model dynamically
                if s["media_type"] == "photo":
                    media_obj = types.InputMediaPhoto(s["media_id"], caption=s["text"], parse_mode="HTML")
                elif s["media_type"] == "video":
                    media_obj = types.InputMediaVideo(s["media_id"], caption=s["text"], parse_mode="HTML")
                elif s["media_type"] == "animation":
                    media_obj = types.InputMediaAnimation(s["media_id"], caption=s["text"], parse_mode="HTML")
                else:
                    media_obj = types.InputMediaDocument(s["media_id"], caption=s["text"], parse_mode="HTML")
                
                bot.edit_message_media(chat_id=s["channel_id"], message_id=s["message_id"], media=media_obj, reply_markup=kb)
            else:
                # Text/Caption fallback alterations
                if s["text"]:
                    bot.edit_message_text(chat_id=s["channel_id"], message_id=s["message_id"], text=s["text"], reply_markup=kb, disable_web_page_preview=True)
                else:
                    bot.edit_message_reply_markup(chat_id=s["channel_id"], message_id=s["message_id"], reply_markup=kb)
                    
            bot.reply_to(m, "🚀 Channel content replaced & updated successfully!")
        except Exception as e:
            bot.reply_to(m, f"❌ Engine failure modifying context:\n`{e}`")
        return

    # 3. BASE SETBUTTON TARGET COPY FLOW
    if uid in button_sessions:
        s = button_sessions.pop(uid)
        kb = build_keyboard(s["buttons"], s["rows"], s["cols"])
        copy_any(m.chat.id, s["msg"], kb)

# ================== RUN INFRA ==================

app = Flask(__name__)

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling(skip_pending=True)