#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging, random, string, sqlite3, re, time, requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, MessageHandler, filters

# ===== CONFIG =====
BOT_TOKEN = "8794163870:AAHjjR_n3vgrufm3uKO87zFH7yL3RJtDB4g"
ADMIN_ID = 7121570824
SMM_API_URL = "https://aapkaprovider.com/api/v2"
SMM_API_KEY = "3febaf1ad5ec695420b14e9dcaae23ab"
SMM_SERVICE_ID = 12755
VIEWS_PER_CREDIT = 500
FORCE_JOIN_CHATS = [-1004264165330, -1003967851938]
INVITE_LINKS = {-1004264165330: "https://t.me/+jA6VJIxg76NlYTA9", -1003967851938: "https://t.me/+C6Vq50Mp7r4xNDll"}
DB_NAME = "referral.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== DATABASE =====
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn, conn.cursor()

def init_db():
    conn, c = get_db()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, referral_code TEXT UNIQUE, referred_by INTEGER, credits INTEGER DEFAULT 0, total_refers INTEGER DEFAULT 0, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS redeem_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, link TEXT, views_sent INTEGER DEFAULT 500, order_id TEXT, status TEXT DEFAULT "pending", created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); conn.close()
    logger.info("✅ DB initialized.")

def add_user(uid, uname, code, ref=None):
    conn, c = get_db()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, referral_code, referred_by) VALUES (?,?,?,?)", (uid, uname, code, ref))
    conn.commit(); conn.close()

def get_user(uid):
    conn, c = get_db()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    u = c.fetchone(); conn.close(); return u

def update_credits(uid, amt):
    conn, c = get_db()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id=?", (amt, uid))
    conn.commit(); conn.close()

def set_credits(uid, amt):
    conn, c = get_db()
    c.execute("UPDATE users SET credits = ? WHERE user_id=?", (amt, uid))
    conn.commit(); conn.close()

def get_user_by_code(code):
    conn, c = get_db()
    c.execute("SELECT user_id FROM users WHERE referral_code=?", (code,))
    r = c.fetchone(); conn.close(); return r[0] if r else None

def add_referral(ref, referred):
    conn, c = get_db()
    c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?,?)", (ref, referred))
    conn.commit(); conn.close()

def log_redeem(uid, link, oid=None, status="pending"):
    conn, c = get_db()
    c.execute("INSERT INTO redeem_history (user_id, link, order_id, status) VALUES (?,?,?,?)", (uid, link, oid, status))
    conn.commit(); conn.close()

def update_redeem_status(oid, status):
    conn, c = get_db()
    c.execute("UPDATE redeem_history SET status=? WHERE order_id=?", (status, oid))
    conn.commit(); conn.close()

def get_top_referrers(limit=10):
    conn, c = get_db()
    c.execute("SELECT user_id, username, total_refers FROM users ORDER BY total_refers DESC LIMIT ?", (limit,))
    r = c.fetchall(); conn.close(); return r

def get_stats():
    conn, c = get_db()
    c.execute("SELECT COUNT(*) FROM users"); tu = c.fetchone()[0]
    c.execute("SELECT SUM(credits) FROM users"); tc = c.fetchone()[0] or 0
    c.execute("SELECT SUM(total_refers) FROM users"); tr = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM redeem_history"); tred = c.fetchone()[0]
    conn.close(); return tu, tc, tr, tred

def get_all_users(offset=0, limit=10):
    conn, c = get_db()
    c.execute("SELECT user_id, username, credits, total_refers FROM users ORDER BY user_id LIMIT ? OFFSET ?", (limit, offset))
    r = c.fetchall(); conn.close(); return r

def count_users():
    conn, c = get_db(); c.execute("SELECT COUNT(*) FROM users"); r = c.fetchone()[0]; conn.close(); return r

def get_recent_orders(limit=10):
    conn, c = get_db()
    c.execute("SELECT id, user_id, link, status, created_at FROM redeem_history ORDER BY id DESC LIMIT ?", (limit,))
    r = c.fetchall(); conn.close(); return r

# ===== HELPERS =====
def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def validate_instagram_link(link):
    return any(re.match(p, link.strip()) for p in [r"(https?://)?(www\.)?instagram\.com/(reel|p|tv)/[A-Za-z0-9_-]+/?", r"(https?://)?(www\.)?instagram\.com/stories/[^/]+/\d+/?"])

# ===== FORCE JOIN =====
async def check_force_join(update, context):
    uid = update.effective_user.id
    if uid == ADMIN_ID: return True
    if not FORCE_JOIN_CHATS: return True
    not_joined = []
    for cid in FORCE_JOIN_CHATS:
        try:
            m = await context.bot.get_chat_member(cid, uid)
            if m.status in ['left','kicked']: not_joined.append(cid)
        except: not_joined.append(cid)
    if not_joined:
        kb = []
        for cid in not_joined:
            if cid in INVITE_LINKS:
                link = INVITE_LINKS[cid]
                try: chat = await context.bot.get_chat(cid); title = chat.title or cid
                except: title = f"Chat {cid}"
                kb.append([InlineKeyboardButton(f"📢 Join {title}", url=link)])
        kb.append([InlineKeyboardButton("🔄 I've joined, check again", callback_data="check_join")])
        await context.bot.send_message(update.effective_chat.id,
            "⚠️ **You must join the following chats:**\n" + "\n".join([f"• {cid}" for cid in not_joined]) +
            "\n\nAfter joining, click the button below.",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return False
    return True

# ===== SMM API =====
def place_smm_order(link, qty=VIEWS_PER_CREDIT):
    try:
        payload = {"key": SMM_API_KEY, "action":"add", "service":SMM_SERVICE_ID, "link":link, "quantity":qty}
        r = requests.post(SMM_API_URL, data=payload, timeout=30); r.raise_for_status()
        j = r.json()
        if "order" in j: return True, str(j["order"]), "Ok"
        elif j.get("status")=="success" and "order_id" in j: return True, str(j["order_id"]), "Ok"
        else: return False, None, j.get("error","Unknown")
    except Exception as e: return False, None, str(e)

def check_order_status(oid):
    try:
        r = requests.post(SMM_API_URL, data={"key":SMM_API_KEY,"action":"status","order":oid}, timeout=30)
        r.raise_for_status(); return r.json()
    except: return None

# ===== USER COMMANDS =====
async def start(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    u = update.effective_user; uid=u.id; uname=u.username or u.first_name
    exist = get_user(uid)
    ref_code = None; ref_id = None
    if context.args:
        ref_code = context.args[0].upper(); ref_id = get_user_by_code(ref_code)
    if not exist:
        if ref_id and ref_id != uid:
            update_credits(ref_id, 1); add_referral(ref_id, uid)
            conn, c = get_db(); c.execute("UPDATE users SET total_refers = total_refers + 1 WHERE user_id=?", (ref_id,)); conn.commit(); conn.close()
            await update.message.reply_text("✅ Referral Success! Your referrer got 1 Credit.", parse_mode="Markdown")
        new_code = generate_code(); add_user(uid, uname, new_code, ref_id); update_credits(uid, 1)
        welcome = f"👋 Welcome {uname}!\n🎁 Bonus: +1 Credit for joining!\n🔹 Your Referral Code: `{new_code}`\n🔹 Share to get 1 credit per referral!\n🔹 1 Credit = {VIEWS_PER_CREDIT} Views\n\nCommands:\n/refer - Get link\n/balance - Check credits\n/redeem <link> - Get {VIEWS_PER_CREDIT} views\n/leaderboard - Top referrers\n/orderstatus - Last order\n/checkjoin - Force check\n\nAdmin: /admin_panel"
        await update.message.reply_text(welcome, parse_mode="Markdown")
    else:
        code=exist[2]; credits=exist[4]; refs=exist[5]
        await update.message.reply_text(f"👋 Welcome back {uname}!\n🔹 Code: `{code}`\n🔹 Referrals: {refs}\n🔹 Credits: {credits}\n\nSend /redeem <link> to get {VIEWS_PER_CREDIT} views.", parse_mode="Markdown")

async def check_join_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        if not await check_force_join(update, context): return
        await update.message.reply_text("✅ Already joined all required chats!")
    else: await update.message.reply_text("✅ Admin exempt.")

async def refer(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    uid=update.effective_user.id; u=get_user(uid)
    if not u: await update.message.reply_text("❌ Please /start first."); return
    code=u[2]; bot_uname=context.bot.username
    await update.message.reply_text(f"📤 Your Referral Link:\n`https://t.me/{bot_uname}?start={code}`\n\n🎁 Reward: 1 referral = 1 Credit = {VIEWS_PER_CREDIT} Views", parse_mode="Markdown")

async def balance(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    uid=update.effective_user.id; u=get_user(uid)
    if not u: await update.message.reply_text("❌ Please /start first."); return
    credits=u[4]; refs=u[5]
    await update.message.reply_text(f"💰 Your Balance\nCredits: {credits}\nReferrals: {refs}\nViews Available: {credits*VIEWS_PER_CREDIT}\n\n1 Credit = {VIEWS_PER_CREDIT} Views", parse_mode="Markdown")

async def redeem(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    uid=update.effective_user.id; u=get_user(uid)
    if not u: await update.message.reply_text("❌ Please /start first."); return
    if not context.args:
        await update.message.reply_text(f"❌ Usage: /redeem <link>\nExample: /redeem https://www.instagram.com/reel/ABC123/", parse_mode="Markdown")
        return
    link = context.args[0].strip()
    if not validate_instagram_link(link):
        await update.message.reply_text("❌ Invalid Instagram link.", parse_mode="Markdown")
        return
    credits = u[4]
    if credits <= 0:
        await update.message.reply_text(f"❌ Insufficient credits! Need 1 Credit for {VIEWS_PER_CREDIT} views. Use /refer to earn.", parse_mode="Markdown")
        return
    update_credits(uid, -1)
    success, oid, msg = place_smm_order(link, VIEWS_PER_CREDIT)
    if success:
        log_redeem(uid, link, oid, "processing")
        await update.message.reply_text(f"✅ Success! {VIEWS_PER_CREDIT} views being sent to:\n`{link}`\nOrder ID: `{oid}`\nRemaining Credits: {credits-1}\nDelivery 5-30 min.", parse_mode="Markdown")
        await context.bot.send_message(ADMIN_ID, f"📊 New Order\nUser: @{u[1] or uid}\nLink: {link}\nOrder: {oid}\nRemaining: {credits-1}")
    else:
        update_credits(uid, 1)
        await update.message.reply_text(f"❌ Failed: {msg}\nCredit refunded.", parse_mode="Markdown")

async def leaderboard(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    top = get_top_referrers(10)
    if not top or all(x[2]==0 for x in top):
        await update.message.reply_text("No referrals yet. Be first! 🏆")
        return
    msg = "🏆 Top 10 Referrers\n\n"
    for i, (uid, uname, cnt) in enumerate(top, 1):
        if cnt==0: continue
        medal = ["🥇","🥈","🥉"][i-1] if i<=3 else f"{i}."
        msg += f"{medal} @{uname or uid} – {cnt} referrals\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def order_status(update, context):
    if update.effective_user.id != ADMIN_ID and not await check_force_join(update, context): return
    uid=update.effective_user.id
    conn, c = get_db()
    c.execute("SELECT order_id, status, link FROM redeem_history WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))
    r = c.fetchone(); conn.close()
    if not r: await update.message.reply_text("No orders."); return
    oid, st, link = r
    data = check_order_status(oid)
    if data: st = data.get('status', st)
    await update.message.reply_text(f"📊 Order Status\nOrder: {oid}\nLink: {link}\nStatus: {st}", parse_mode="Markdown")

async def check_join_callback(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "check_join":
        if await check_force_join(update, context):
            await q.edit_message_text("✅ Joined all chats! You can now use the bot.")
        else: pass

# ===== ADMIN PANEL =====
ADD_CREDITS, AMOUNT, BROADCAST = range(3)

def get_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Credits", callback_data="admin_credits")],
        [InlineKeyboardButton("📊 Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📈 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("🔐 Force Join", callback_data="admin_forcejoin")],
    ])

async def admin_panel_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text("🛠 Admin Panel", reply_markup=get_admin_menu(), parse_mode="Markdown")

async def admin_callback(update, context):
    q = update.callback_query; await q.answer()
    data = q.data
    if update.effective_user.id != ADMIN_ID:
        await q.edit_message_text("⛔ Unauthorized.")
        return
    if data == "admin_panel":
        await q.edit_message_text("🛠 Admin Panel", reply_markup=get_admin_menu(), parse_mode="Markdown")
    elif data == "admin_users":
        await show_users(update, context, 0)
    elif data == "admin_credits":
        kb = [[InlineKeyboardButton("➕ Add", callback_data="credits_add")],[InlineKeyboardButton("➖ Deduct", callback_data="credits_deduct")],[InlineKeyboardButton("🔧 Set", callback_data="credits_set")],[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]
        await q.edit_message_text("💰 Credits Management", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data == "admin_orders":
        await show_orders(update, context)
    elif data == "admin_settings":
        kb = [[InlineKeyboardButton("🔑 API Key", callback_data="settings_api_key")],[InlineKeyboardButton("🆔 Service ID", callback_data="settings_service_id")],[InlineKeyboardButton("🌐 API URL", callback_data="settings_api_url")],[InlineKeyboardButton("📊 Views/Credit", callback_data="settings_views")],[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]
        await q.edit_message_text("⚙️ Settings", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data == "admin_broadcast":
        await q.edit_message_text("📢 Send broadcast message (type /cancel to abort)")
        return BROADCAST
    elif data == "admin_stats":
        tu, tc, tr, tred = get_stats()
        await q.edit_message_text(f"📊 Stats\n👥 Users: {tu}\n💰 Credits: {tc}\n🔗 Referrals: {tr}\n📹 Redeems: {tred}", parse_mode="Markdown")
        await q.edit_message_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
    elif data == "admin_forcejoin":
        text = "🔐 Force Join Chats:\n" + ("\n".join([str(c) for c in FORCE_JOIN_CHATS]) if FORCE_JOIN_CHATS else "None")
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]), parse_mode="Markdown")
    elif data.startswith("users_page_"):
        page = int(data.split("_")[2]); await show_users(update, context, page)
    elif data.startswith("user_detail_"):
        uid = int(data.split("_")[2]); await show_user_detail(update, context, uid)
    elif data.startswith("order_detail_"):
        oid = data.split("_")[2]; await show_order_detail(update, context, oid)
    elif data.startswith("refund_order_"):
        oid = data.split("_")[2]; update_redeem_status(oid, "refunded")
        await q.edit_message_text(f"✅ Order {oid} refunded.", parse_mode="Markdown")
        await q.edit_message_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_orders")]]))
    elif data in ("credits_add", "credits_deduct", "credits_set"):
        action = data.split("_")[1]
        context.user_data["credit_action"] = action
        await q.edit_message_text(f"Enter user_id for {action}ing credits (or /cancel)")
        return ADD_CREDITS
    elif data.startswith("settings_"):
        setting = data.split("_")[1]
        context.user_data["admin_setting"] = setting
        await q.edit_message_text(f"Enter new {setting.replace('_',' ').title()}:")
        return BROADCAST
    return ConversationHandler.END

async def show_users(update, context, page=0):
    q = update.callback_query
    per = 5; total = count_users(); offset = page*per
    users = get_all_users(offset, per)
    if not users:
        await q.edit_message_text("No users found.")
        return
    text = "👥 Users List\n\n"
    for uid, uname, cred, refs in users:
        text += f"🆔 `{uid}` – @{uname or uid} – Credits: {cred}\n"
    rows = []
    if page>0: rows.append([InlineKeyboardButton("◀️ Prev", callback_data=f"users_page_{page-1}")])
    if total>offset+per: rows.append([InlineKeyboardButton("Next ▶️", callback_data=f"users_page_{page+1}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
    for uid, uname, cred, refs in users:
        rows.append([InlineKeyboardButton(f"👤 {uname or uid}", callback_data=f"user_detail_{uid}")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def show_user_detail(update, context, uid):
    q = update.callback_query
    u = get_user(uid)
    if not u: await q.edit_message_text("User not found."); return
    uid, uname, code, refby, cred, refs, joined = u
    text = f"👤 User Detail\n🆔 {uid}\n👤 @{uname or uid}\n🔗 Code: {code}\n💳 Credits: {cred}\n🔁 Referrals: {refs}\n📅 Joined: {joined}\n👥 Referred by: {refby or 'None'}"
    kb = [[InlineKeyboardButton("➕ Add", callback_data=f"user_addcredits_{uid}")],[InlineKeyboardButton("➖ Deduct", callback_data=f"user_deductcredits_{uid}")],[InlineKeyboardButton("🔧 Set", callback_data=f"user_setcredits_{uid}")],[InlineKeyboardButton("📋 Orders", callback_data=f"user_orders_{uid}")],[InlineKeyboardButton("🔙 Back", callback_data="admin_users")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_orders(update, context):
    q = update.callback_query
    orders = get_recent_orders(10)
    if not orders: await q.edit_message_text("No orders."); return
    text = "📊 Recent Orders\n\n"
    for oid, uid, link, st, created in orders:
        text += f"🆔 {oid} – User: {uid} – Status: {st}\n"
    kb = [[InlineKeyboardButton(f"📋 Order #{o[0]}", callback_data=f"order_detail_{o[0]}")] for o in orders]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_order_detail(update, context, oid):
    q = update.callback_query
    conn, c = get_db()
    c.execute("SELECT * FROM redeem_history WHERE order_id=?", (oid,))
    o = c.fetchone(); conn.close()
    if not o: await q.edit_message_text("Order not found."); return
    oid_db, uid, link, views, oid2, st, created = o
    text = f"📋 Order #{oid_db}\n🆔 ID: {oid2}\n👤 User: {uid}\n🔗 {link}\n📊 Views: {views}\n📌 Status: {st}\n📅 {created}"
    kb = [[InlineKeyboardButton("🔄 Check", callback_data=f"order_check_{oid2}")],[InlineKeyboardButton("💰 Refund", callback_data=f"refund_order_{oid2}")],[InlineKeyboardButton("🔙 Back", callback_data="admin_orders")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def cancel(update, context):
    await update.message.reply_text("❌ Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_credit_user_id(update, context):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Enter numeric user_id or /cancel")
        return ADD_CREDITS
    uid = int(text)
    if not get_user(uid):
        await update.message.reply_text("❌ User not found. Try again.")
        return ADD_CREDITS
    context.user_data["target_user"] = uid
    action = context.user_data["credit_action"]
    await update.message.reply_text(f"Enter amount to {action} for user {uid} (or /cancel)")
    return AMOUNT

async def admin_credit_amount(update, context):
    text = update.message.text.strip()
    if not text.lstrip('-').isdigit():
        await update.message.reply_text("❌ Enter valid number or /cancel")
        return AMOUNT
    amt = int(text)
    uid = context.user_data["target_user"]
    action = context.user_data["credit_action"]
    if action == "add": update_credits(uid, amt)
    elif action == "deduct": update_credits(uid, -amt)
    elif action == "set": set_credits(uid, amt)
    await update.message.reply_text(f"✅ {action.capitalize()}ed {amt} credits to/from user {uid}.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_broadcast_message(update, context):
    msg = update.message.text
    conn, c = get_db()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall(); conn.close()
    sent = 0
    for (uid,) in users:
        try: await context.bot.send_message(uid, f"📢 Announcement:\n\n{msg}", parse_mode="Markdown"); sent += 1; time.sleep(0.05)
        except: pass
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_settings_input(update, context):
    global SMM_API_KEY, SMM_SERVICE_ID, SMM_API_URL, VIEWS_PER_CREDIT
    setting = context.user_data.get("admin_setting")
    text = update.message.text.strip()
    if setting == "api_key": SMM_API_KEY = text; await update.message.reply_text("✅ API Key updated.")
    elif setting == "service_id":
        if not text.isdigit(): await update.message.reply_text("❌ Must be number."); return BROADCAST
        SMM_SERVICE_ID = int(text); await update.message.reply_text(f"✅ Service ID: {SMM_SERVICE_ID}")
    elif setting == "api_url": SMM_API_URL = text; await update.message.reply_text(f"✅ API URL: {SMM_API_URL}")
    elif setting == "views":
        if not text.isdigit(): await update.message.reply_text("❌ Must be number."); return BROADCAST
        VIEWS_PER_CREDIT = int(text); await update.message.reply_text(f"✅ Views per Credit: {VIEWS_PER_CREDIT}")
    context.user_data.clear()
    return ConversationHandler.END

# ===== DIRECT ADMIN COMMANDS =====
async def add_credits_cmd(update, context):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Unauthorized."); return
    try:
        uid = int(context.args[0]); amt = int(context.args[1])
        update_credits(uid, amt); await update.message.reply_text(f"✅ Added {amt} credits to {uid}.")
    except: await update.message.reply_text("Usage: /addcredits <user_id> <amount>")

async def list_users_cmd(update, context):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Unauthorized."); return
    conn, c = get_db(); c.execute("SELECT user_id, username, credits FROM users ORDER BY user_id DESC LIMIT 20")
    users = c.fetchall(); conn.close()
    if not users: await update.message.reply_text("No users."); return
    msg = "👥 Last 20 users:\n"
    for uid, uname, cred in users: msg += f"🆔 {uid} – @{uname or 'N/A'} – Credits: {cred}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def deduct_credits_cmd(update, context):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Unauthorized."); return
    try:
        uid = int(context.args[0]); amt = int(context.args[1])
        update_credits(uid, -amt); await update.message.reply_text(f"✅ Deducted {amt} credits from {uid}.")
    except: await update.message.reply_text("Usage: /deductcredits <user_id> <amount>")

async def set_credits_cmd(update, context):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Unauthorized."); return
    try:
        uid = int(context.args[0]); amt = int(context.args[1])
        set_credits(uid, amt); await update.message.reply_text(f"✅ Set credits to {amt} for {uid}.")
    except: await update.message.reply_text("Usage: /setcredits <user_id> <amount>")

# ===== MAIN =====
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("orderstatus", order_status))
    app.add_handler(CommandHandler("checkjoin", check_join_command))
    app.add_handler(CommandHandler("admin_panel", admin_panel_command))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(CommandHandler("addcredits", add_credits_cmd))
    app.add_handler(CommandHandler("listusers", list_users_cmd))
    app.add_handler(CommandHandler("deductcredits", deduct_credits_cmd))
    app.add_handler(CommandHandler("setcredits", set_credits_cmd))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(admin_callback))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^(credits_add|credits_deduct|credits_set)$")],
        states={ADD_CREDITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_credit_user_id)],
                AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_credit_amount)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv)

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_broadcast$")],
        states={BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_message)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(broadcast_conv)

    settings_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^settings_.*$")],
        states={BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_settings_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(settings_conv)

    print("🤖 Bot running with COMPLETE FIX!")
    print(f"👤 Admin: {ADMIN_ID}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
