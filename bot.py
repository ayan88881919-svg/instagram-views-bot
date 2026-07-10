#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 Instagram Views Telegram Bot - Complete
- Referral (1 refer = 1 credit = 500 views)
- NEW USER BONUS: +1 Credit on joining channel/group + start
- Auto-order via SMM Panel API
- Admin Panel - ONLY via /admin_panel command (NO BUTTON visible to anyone)
- Force Join (1 private channel + 1 private group) - Admin exempt
- SQLite database
"""

import logging
import random
import string
import sqlite3
import re
import time
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===================== CONFIGURATION =====================
BOT_TOKEN = "8794163870:AAHjjR_n3vgrufm3uKO87zFH7yL3RJtDB4g"
ADMIN_ID = 7121570824  # Replace with your numeric ID (from @userinfobot)

SMM_API_URL = "https://aapkaprovider.com/api/v2"
SMM_API_KEY = "3febaf1ad5ec695420b14e9dcaae23ab"
SMM_SERVICE_ID = 12755

VIEWS_PER_CREDIT = 500

# Force Join – 1 Private Channel + 1 Private Group
# 👇 Get chat IDs using @RawDataBot
FORCE_JOIN_CHATS = [
    -1004264165330,  # Channel ID (replace with actual)
    -1003967851938   # Group ID (replace with actual)
]

# 👇 Invite links for each (generate from Telegram)
INVITE_LINKS = {
    -1004264165330: "https://t.me/+jA6VJIxg76NlYTA9",  # Channel link
    -1003967851938: "https://t.me/+C6Vq50Mp7r4xNDll"   # Group link
}

DB_NAME = "referral.db"
# ========================================================

# ===================== LOGGING =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ===================== DATABASE FUNCTIONS =====================
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    return conn, cursor

def init_db():
    conn, cursor = get_db()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            credits INTEGER DEFAULT 0,
            total_refers INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            views_sent INTEGER DEFAULT 500,
            order_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized.")

def add_user(user_id, username, referral_code, referred_by=None):
    conn, cursor = get_db()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, referral_code, referred_by) VALUES (?, ?, ?, ?)",
        (user_id, username, referral_code, referred_by),
    )
    conn.commit()
    conn.close()

def get_user(user_id):
    conn, cursor = get_db()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_credits(user_id, amount):
    conn, cursor = get_db()
    cursor.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def set_credits(user_id, new_amount):
    conn, cursor = get_db()
    cursor.execute("UPDATE users SET credits = ? WHERE user_id = ?", (new_amount, user_id))
    conn.commit()
    conn.close()

def get_user_by_code(code):
    conn, cursor = get_db()
    cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (code,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def add_referral(referrer_id, referred_id):
    conn, cursor = get_db()
    cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
    conn.commit()
    conn.close()

def log_redeem(user_id, link, order_id=None, status="pending"):
    conn, cursor = get_db()
    cursor.execute(
        "INSERT INTO redeem_history (user_id, link, views_sent, order_id, status) VALUES (?, ?, ?, ?, ?)",
        (user_id, link, VIEWS_PER_CREDIT, order_id, status),
    )
    conn.commit()
    conn.close()

def update_redeem_status(order_id, status):
    conn, cursor = get_db()
    cursor.execute("UPDATE redeem_history SET status = ? WHERE order_id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_top_referrers(limit=10):
    conn, cursor = get_db()
    cursor.execute("""
        SELECT user_id, username, total_refers FROM users ORDER BY total_refers DESC LIMIT ?
    """, (limit,))
    result = cursor.fetchall()
    conn.close()
    return result

def get_stats():
    conn, cursor = get_db()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(credits) FROM users")
    total_credits = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(total_refers) FROM users")
    total_refers = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM redeem_history")
    total_redeems = cursor.fetchone()[0]
    conn.close()
    return total_users, total_credits, total_refers, total_redeems

def get_all_users(offset=0, limit=10):
    conn, cursor = get_db()
    cursor.execute("SELECT user_id, username, credits, total_refers FROM users ORDER BY user_id LIMIT ? OFFSET ?", (limit, offset))
    users = cursor.fetchall()
    conn.close()
    return users

def count_users():
    conn, cursor = get_db()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_recent_orders(limit=10):
    conn, cursor = get_db()
    cursor.execute("SELECT id, user_id, link, status, created_at FROM redeem_history ORDER BY id DESC LIMIT ?", (limit,))
    orders = cursor.fetchall()
    conn.close()
    return orders

# ===================== HELPER FUNCTIONS =====================
def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def validate_instagram_link(link):
    patterns = [
        r"(https?://)?(www\.)?instagram\.com/(reel|p|tv)/[A-Za-z0-9_-]+/?",
        r"(https?://)?(www\.)?instagram\.com/stories/[^/]+/\d+/?",
    ]
    return any(re.match(p, link.strip()) for p in patterns)

# ===================== FORCE JOIN FUNCTIONS =====================
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user joined all required chats. Admin exempt."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id == ADMIN_ID:
        return True

    if not FORCE_JOIN_CHATS:
        return True

    not_joined = []
    for chat_id_check in FORCE_JOIN_CHATS:
        try:
            member = await context.bot.get_chat_member(chat_id_check, user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(chat_id_check)
        except Exception as e:
            logger.error(f"Force join check failed for {chat_id_check}: {e}")
            not_joined.append(chat_id_check)

    if not_joined:
        keyboard = []
        for chat_id_check in not_joined:
            if chat_id_check in INVITE_LINKS:
                invite_link = INVITE_LINKS[chat_id_check]
                try:
                    chat = await context.bot.get_chat(chat_id_check)
                    title = chat.title or chat_id_check
                except:
                    title = f"Chat ID: {chat_id_check}"
                keyboard.append([InlineKeyboardButton(f"📢 Join {title}", url=invite_link)])
            else:
                keyboard.append([InlineKeyboardButton(f"📢 Join Chat ID: {chat_id_check}", callback_data="dummy")])
        keyboard.append([InlineKeyboardButton("🔄 I've joined, check again", callback_data="check_join")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        chat_names = []
        for chat_id_check in not_joined:
            try:
                chat = await context.bot.get_chat(chat_id_check)
                chat_names.append(f"• {chat.title or chat_id_check}")
            except:
                chat_names.append(f"• {chat_id_check}")

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ **You must join the following private chats to use this bot:**\n\n" +
                 "\n".join(chat_names) +
                 "\n\n🔹 Click the buttons below to join.\n🔹 After joining, click **'I've joined, check again'**.",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        return False
    return True

# ===================== SMM API FUNCTIONS =====================
def place_smm_order(link, quantity=VIEWS_PER_CREDIT):
    try:
        payload = {"key": SMM_API_KEY, "action": "add", "service": SMM_SERVICE_ID, "link": link, "quantity": quantity}
        response = requests.post(SMM_API_URL, data=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        if "order" in result:
            return True, str(result["order"]), "Order placed"
        elif result.get("status") == "success" and "order_id" in result:
            return True, str(result["order_id"]), "Order placed"
        else:
            return False, None, result.get("error", "Unknown error")
    except Exception as e:
        return False, None, str(e)

def check_order_status(order_id):
    try:
        payload = {"key": SMM_API_KEY, "action": "status", "order": order_id}
        response = requests.post(SMM_API_URL, data=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except:
        return None

# ===================== TELEGRAM BOT HANDLERS =====================

# ---------- User Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Force join check – admin exempt
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return

    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name

    existing = get_user(user_id)
    ref_code = None
    referrer_id = None
    if context.args:
        ref_code = context.args[0].upper()
        referrer_id = get_user_by_code(ref_code)

    if not existing:
        # 🔥 Referral logic (referrer ko credit)
        if referrer_id and referrer_id != user_id:
            update_credits(referrer_id, 1)
            add_referral(referrer_id, user_id)
            conn, cursor = get_db()
            cursor.execute("UPDATE users SET total_refers = total_refers + 1 WHERE user_id = ?", (referrer_id,))
            conn.commit()
            conn.close()
            await update.message.reply_text(
                "✅ **Referral Success!** 🎉\nYour referrer got **1 Credit**.",
                parse_mode="Markdown",
            )

        new_code = generate_code()
        add_user(user_id, username, new_code, referrer_id)

        # 🎁 BONUS: 1 credit for joining channel/group and starting!
        update_credits(user_id, 1)

        welcome = f"""
👋 **Welcome {username}!**

You've joined the **Refer & Earn** bot.

🎁 **Bonus:** +1 Credit for joining our channel/group!
🔹 Your Referral Code: `{new_code}`
🔹 Share this code – get **1 credit** per referral!
🔹 1 Credit = **{VIEWS_PER_CREDIT} Views** on your Reel

📌 **Commands:**
/refer - Get your referral link
/balance - Check your credits
/redeem <link> - Send your Reel link to get {VIEWS_PER_CREDIT} views
/leaderboard - Top referrers
/orderstatus - Check last order status

🤖 *Admin: Use /admin_panel to open admin panel.*
        """
        await update.message.reply_text(welcome, parse_mode="Markdown")
            
    else:
        code = existing[2]
        credits = existing[4]
        refers = existing[5]
        msg = f"""
👋 **Welcome back, {username}!**

🔹 Your Code: `{code}`
🔹 Total Referrals: {refers}
🔹 Your Credits: {credits}

➡️ Send `/redeem <your_reel_link>` to get **{VIEWS_PER_CREDIT} views**!

📌 **Commands:**
/refer - Get your referral link
/balance - Check your credits
/redeem <link> - Send your Reel link to get views
/leaderboard - Top referrers
/orderstatus - Check last order status

🤖 *Admin: Use /admin_panel to open admin panel.*
        """
        await update.message.reply_text(msg, parse_mode="Markdown")

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Please /start first.")
        return
    code = user[2]
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"📤 **Your Referral Link**\n\n`{link}`\n\n🎁 **Reward:** 1 referral = 1 Credit = {VIEWS_PER_CREDIT} Views\nShare now and start earning! 🚀",
        parse_mode="Markdown",
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Please /start first.")
        return
    credits = user[4]
    refers = user[5]
    await update.message.reply_text(
        f"💰 **Your Balance**\n\nCredits: **{credits}**\nReferrals: **{refers}**\nViews Available: **{credits * VIEWS_PER_CREDIT}**\n\n1 Credit = {VIEWS_PER_CREDIT} Views",
        parse_mode="Markdown",
    )

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ Please /start first.")
        return

    if not context.args:
        await update.message.reply_text(
            f"❌ **Please send your Instagram Reel/Post link!**\n\nUsage: `/redeem <link>`\nExample: `/redeem https://www.instagram.com/reel/ABC123/`",
            parse_mode="Markdown",
        )
        return

    reel_link = context.args[0].strip()
    if not validate_instagram_link(reel_link):
        await update.message.reply_text("❌ **Invalid link!** Please send a valid Instagram Reel/Post link.", parse_mode="Markdown")
        return

    credits = user[4]
    if credits <= 0:
        await update.message.reply_text(
            f"❌ **Insufficient credits!** You need at least **1 Credit** to get {VIEWS_PER_CREDIT} views.\nUse /refer to earn.",
            parse_mode="Markdown",
        )
        return

    update_credits(user_id, -1)

    success, order_id, message = place_smm_order(reel_link, VIEWS_PER_CREDIT)

    if success:
        log_redeem(user_id, reel_link, order_id, "processing")
        await update.message.reply_text(
            f"✅ **Redeemed Successfully!** 🎉\n\n📹 **{VIEWS_PER_CREDIT} views** are being sent to:\n`{reel_link}`\n\n🆔 Order ID: `{order_id}`\n⏳ Delivery may take 5-30 minutes.\n💰 Remaining Credits: **{credits - 1}**\n\n⚠️ *Disclaimer: Automated views may violate Instagram ToS.*",
            parse_mode="Markdown",
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"📊 **New Order Alert**\nUser: @{user[1] or user_id}\nLink: {reel_link}\nViews: {VIEWS_PER_CREDIT}\nOrder ID: {order_id}\nRemaining Credits: {credits - 1}",
        )
    else:
        update_credits(user_id, 1)
        await update.message.reply_text(
            f"❌ **Failed to place order!**\n\nError: {message}\n\nYour 1 credit has been refunded. Please try again later."
        )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return
    top = get_top_referrers(10)
    if not top or all(row[2] == 0 for row in top):
        await update.message.reply_text("No referrals yet. Be the first! 🏆")
        return
    msg = "🏆 **Top 10 Referrers**\n\n"
    for i, (user_id, username, count) in enumerate(top, 1):
        if count == 0:
            continue
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        msg += f"{medal} @{username or user_id} – {count} referrals\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context):
            return
    user_id = update.effective_user.id
    conn, cursor = get_db()
    cursor.execute(
        "SELECT order_id, status, link FROM redeem_history WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    result = cursor.fetchone()
    conn.close()
    if not result:
        await update.message.reply_text("❌ No orders found.")
        return
    order_id, status, link = result
    status_data = check_order_status(order_id)
    if status_data:
        api_status = status_data.get("status", status)
        await update.message.reply_text(
            f"📊 **Order Status**\n\n🆔 Order ID: `{order_id}`\n📹 Link: {link}\n📌 Status: **{api_status}**",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"📊 **Order Status**\n\n🆔 Order ID: `{order_id}`\n📹 Link: {link}\n📌 Status: **{status}**",
            parse_mode="Markdown",
        )

# ---------- Force Join Check Callback ----------
async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "check_join":
        if await check_force_join(update, context):
            await query.edit_message_text("✅ You have joined all required chats! You can now use the bot.")
        else:
            pass

# ===================== ADMIN PANEL =====================
(SELECT_ACTION, AWAIT_USER_ID, AWAIT_AMOUNT, AWAIT_SERVICE_ID, AWAIT_BROADCAST_MSG, AWAIT_CREDIT_USER_ID) = range(6)

# ---------- Admin Menu Markup (reusable) ----------
def get_admin_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users Management", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Credits Management", callback_data="admin_credits")],
        [InlineKeyboardButton("📊 Orders Management", callback_data="admin_orders")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📈 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔐 Force Join Chats", callback_data="admin_forcejoin")],
    ])

# ---------- Admin Panel Command (Only for admin) ----------
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized. You are not the admin.")
        return
    await update.message.reply_text(
        "🛠 **Admin Panel**\nSelect an option:",
        reply_markup=get_admin_menu_markup(),
        parse_mode="Markdown"
    )

# ---------- Admin Callback Router ----------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # 🔒 Security: Only admin can use these callbacks
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Unauthorized. You are not the admin.")
        return

    if data == "admin_panel":
        await query.edit_message_text(
            "🛠 **Admin Panel**\nSelect an option:",
            reply_markup=get_admin_menu_markup(),
            parse_mode="Markdown"
        )
    elif data == "admin_users":
        await show_users(update, context, page=0)
    elif data == "admin_credits":
        keyboard = [
            [InlineKeyboardButton("➕ Add Credits", callback_data="credits_add")],
            [InlineKeyboardButton("➖ Deduct Credits", callback_data="credits_deduct")],
            [InlineKeyboardButton("🔧 Set Credits", callback_data="credits_set")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")],
        ]
        await query.edit_message_text("💰 **Credits Management**\nChoose action:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "admin_orders":
        await show_orders(update, context)
    elif data == "admin_settings":
        keyboard = [
            [InlineKeyboardButton("🔑 Change API Key", callback_data="settings_api_key")],
            [InlineKeyboardButton("🆔 Change Service ID", callback_data="settings_service_id")],
            [InlineKeyboardButton("🌐 Change API URL", callback_data="settings_api_url")],
            [InlineKeyboardButton("📊 Change Views per Credit", callback_data="settings_views")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")],
        ]
        await query.edit_message_text("⚙️ **Settings**\nChoose setting to change:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "admin_broadcast":
        await query.edit_message_text("📢 **Broadcast**\nSend the message you want to broadcast to all users. (Cancel: /cancel)")
        context.user_data["admin_action"] = "broadcast"
        return AWAIT_BROADCAST_MSG
    elif data == "admin_stats":
        total_users, total_credits, total_refers, total_redeems = get_stats()
        await query.edit_message_text(
            f"📊 **Bot Statistics**\n\n👥 Total Users: {total_users}\n💰 Total Credits: {total_credits}\n🔗 Total Referrals: {total_refers}\n📹 Total Redeems: {total_redeems}",
            parse_mode="Markdown",
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "admin_forcejoin":
        text = "🔐 **Force Join Chats**\n\n"
        if FORCE_JOIN_CHATS:
            for chat_id in FORCE_JOIN_CHATS:
                try:
                    chat = await context.bot.get_chat(chat_id)
                    title = chat.title or chat_id
                except:
                    title = f"ID: {chat_id}"
                text += f"• {title}\n"
        else:
            text += "No chats configured."
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("users_page_"):
        page = int(data.split("_")[2])
        await show_users(update, context, page)
    elif data.startswith("user_detail_"):
        user_id = int(data.split("_")[2])
        await show_user_detail(update, context, user_id)
    elif data.startswith("order_detail_"):
        order_id = data.split("_")[2]
        await show_order_detail(update, context, order_id)
    elif data.startswith("refund_order_"):
        order_id = data.split("_")[2]
        update_redeem_status(order_id, "refunded")
        await query.edit_message_text(f"✅ Order `{order_id}` marked as refunded.", parse_mode="Markdown")
        keyboard = [[InlineKeyboardButton("🔙 Back to Orders", callback_data="admin_orders")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "credits_add" or data == "credits_deduct" or data == "credits_set":
        action = data.split("_")[1]
        context.user_data["credit_action"] = action
        await query.edit_message_text(f"Enter the **user_id** for {action}ing credits.\n(use /cancel to abort)")
        return AWAIT_CREDIT_USER_ID
    elif data == "settings_service_id":
        await query.edit_message_text("Enter the new **Service ID** (number):\n(use /cancel to abort)")
        context.user_data["admin_action"] = "settings_service_id"
        return AWAIT_SERVICE_ID
    elif data == "settings_api_key":
        await query.edit_message_text("Enter the new **API Key**:\n(use /cancel to abort)")
        context.user_data["admin_action"] = "settings_api_key"
        return AWAIT_SERVICE_ID
    elif data == "settings_api_url":
        await query.edit_message_text("Enter the new **API URL** (e.g., https://ezkify.com/api/v2):\n(use /cancel to abort)")
        context.user_data["admin_action"] = "settings_api_url"
        return AWAIT_SERVICE_ID
    elif data == "settings_views":
        await query.edit_message_text(f"Enter the new **Views per Credit** (currently {VIEWS_PER_CREDIT}):\n(use /cancel to abort)")
        context.user_data["admin_action"] = "settings_views"
        return AWAIT_SERVICE_ID
    return ConversationHandler.END

# ---------- Admin Sub-functions ----------
async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    query = update.callback_query
    per_page = 5
    total = count_users()
    offset = page * per_page
    users = get_all_users(offset, per_page)
    if not users:
        await query.edit_message_text("No users found.")
        return
    text = "👥 **Users List**\n\n"
    for uid, username, credits, refs in users:
        text += f"🆔 `{uid}` – @{username or uid} – Credits: {credits}\n"
    rows = []
    if page > 0:
        rows.append([InlineKeyboardButton("◀️ Prev", callback_data=f"users_page_{page-1}")])
    if total > offset + per_page:
        rows.append([InlineKeyboardButton("Next ▶️", callback_data=f"users_page_{page+1}")])
    rows.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
    for uid, username, credits, refs in users:
        rows.append([InlineKeyboardButton(f"👤 {username or uid}", callback_data=f"user_detail_{uid}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def show_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    query = update.callback_query
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("User not found.")
        return
    uid, username, code, referred_by, credits, total_refers, joined = user
    text = f"👤 **User Details**\n\n🆔 `{uid}`\n👤 @{username or uid}\n🔗 Ref Code: `{code}`\n💳 Credits: {credits}\n🔁 Referrals: {total_refers}\n📅 Joined: {joined}\n👥 Referred by: {referred_by or 'None'}"
    keyboard = [
        [InlineKeyboardButton("➕ Add Credits", callback_data=f"user_addcredits_{uid}")],
        [InlineKeyboardButton("➖ Deduct Credits", callback_data=f"user_deductcredits_{uid}")],
        [InlineKeyboardButton("🔧 Set Credits", callback_data=f"user_setcredits_{uid}")],
        [InlineKeyboardButton("📋 View Orders", callback_data=f"user_orders_{uid}")],
        [InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    orders = get_recent_orders(10)
    if not orders:
        await query.edit_message_text("No orders found.")
        return
    text = "📊 **Recent Orders**\n\n"
    for oid, uid, link, status, created in orders:
        text += f"🆔 `{oid}` – User: `{uid}` – Status: {status}\n"
    keyboard = []
    for oid, uid, link, status, created in orders:
        keyboard.append([InlineKeyboardButton(f"📋 Order #{oid}", callback_data=f"order_detail_{oid}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id):
    query = update.callback_query
    conn, cursor = get_db()
    cursor.execute("SELECT * FROM redeem_history WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    conn.close()
    if not order:
        await query.edit_message_text("Order not found.")
        return
    oid, uid, link, views, oid2, status, created = order
    text = f"📋 **Order #{oid}**\n\n🆔 Order ID: `{oid2}`\n👤 User: `{uid}`\n🔗 Link: {link}\n📊 Views: {views}\n📌 Status: {status}\n📅 Created: {created}"
    keyboard = [
        [InlineKeyboardButton("🔄 Check Status", callback_data=f"order_check_{oid2}")],
        [InlineKeyboardButton("💰 Refund Order", callback_data=f"refund_order_{oid2}")],
        [InlineKeyboardButton("🔙 Back to Orders", callback_data="admin_orders")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- Conversation Handlers ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Action cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_credit_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text.isdigit():
        await update.message.reply_text("❌ Please enter a valid numeric user_id.")
        return AWAIT_CREDIT_USER_ID
    user_id = int(text)
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("❌ User not found. Try again or /cancel.")
        return AWAIT_CREDIT_USER_ID
    context.user_data["target_user"] = user_id
    action = context.user_data.get("credit_action")
    if action == "add":
        await update.message.reply_text(f"Enter the amount of credits to **add** to user {user_id}:\n(/cancel to abort)")
        return AWAIT_AMOUNT
    elif action == "deduct":
        await update.message.reply_text(f"Enter the amount of credits to **deduct** from user {user_id}:\n(/cancel to abort)")
        return AWAIT_AMOUNT
    elif action == "set":
        await update.message.reply_text(f"Enter the **new total credits** for user {user_id}:\n(/cancel to abort)")
        return AWAIT_AMOUNT

async def admin_credit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text.lstrip('-').isdigit():
        await update.message.reply_text("❌ Please enter a valid number.")
        return AWAIT_AMOUNT
    amount = int(text)
    user_id = context.user_data.get("target_user")
    action = context.user_data.get("credit_action")
    if action == "add":
        update_credits(user_id, amount)
        await update.message.reply_text(f"✅ Added {amount} credits to user {user_id}.")
    elif action == "deduct":
        update_credits(user_id, -amount)
        await update.message.reply_text(f"✅ Deducted {amount} credits from user {user_id}.")
    elif action == "set":
        set_credits(user_id, amount)
        await update.message.reply_text(f"✅ Set credits to {amount} for user {user_id}.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SMM_SERVICE_ID, SMM_API_KEY, SMM_API_URL, VIEWS_PER_CREDIT
    text = update.message.text
    action = context.user_data.get("admin_action")
    if action == "settings_service_id":
        if not text.isdigit():
            await update.message.reply_text("❌ Service ID must be a number.")
            return AWAIT_SERVICE_ID
        SMM_SERVICE_ID = int(text)
        await update.message.reply_text(f"✅ Service ID updated to: {SMM_SERVICE_ID}")
    elif action == "settings_api_key":
        SMM_API_KEY = text
        await update.message.reply_text("✅ API Key updated.")
    elif action == "settings_api_url":
        SMM_API_URL = text
        await update.message.reply_text(f"✅ API URL updated to: {SMM_API_URL}")
    elif action == "settings_views":
        if not text.isdigit():
            await update.message.reply_text("❌ Views per credit must be a number.")
            return AWAIT_SERVICE_ID
        VIEWS_PER_CREDIT = int(text)
        await update.message.reply_text(f"✅ Views per Credit updated to: {VIEWS_PER_CREDIT}")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    conn, cursor = get_db()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, f"📢 **Announcement:**\n\n{msg}", parse_mode="Markdown")
            sent += 1
            time.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")
    context.user_data.clear()
    return ConversationHandler.END

# ===================== MAIN FUNCTION =====================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("orderstatus", order_status))

    # Admin command (NO BUTTON - only via command)
    app.add_handler(CommandHandler("admin_panel", admin_panel_command))
    app.add_handler(CommandHandler("admin", admin_panel_command))  # Alias

    # Callbacks
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(admin_callback))

    # Conversation handlers
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_callback, pattern="^(credits_add|credits_deduct|credits_set)$"),
            CallbackQueryHandler(admin_callback, pattern="^(settings_service_id|settings_api_key|settings_api_url|settings_views)$"),
            CallbackQueryHandler(admin_callback, pattern="^admin_broadcast$"),
        ],
        states={
            AWAIT_CREDIT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_credit_user_id)],
            AWAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_credit_amount)],
            AWAIT_SERVICE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_settings_input)],
            AWAIT_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_message)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    print("🤖 Bot is running with Admin Panel (Command only - NO BUTTON)!")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print(f"🔐 Force Join Chats: {FORCE_JOIN_CHATS}")
    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()