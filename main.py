import logging
import os
import uuid
import time
import requests
from flask import Flask, request as flask_request, jsonify
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "").split(",")))
ROBLOX_SECRET = os.environ.get("ROBLOX_SECRET", "supersecret")

command_queue = []
result_store = {}

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return 'OK', 200

@flask_app.route('/poll', methods=['POST'])
def poll():
    data = flask_request.json
    if not data or data.get('secret') != ROBLOX_SECRET:
        return jsonify({'error': 'forbidden'}), 403
    
    pending = [c for c in command_queue if not c.get('taken')]
    for c in pending:
        c['taken'] = True
    return jsonify({'commands': pending})

@flask_app.route('/result', methods=['POST'])
def result():
    data = flask_request.json
    if not data or data.get('secret') != ROBLOX_SECRET:
        return jsonify({'error': 'forbidden'}), 403
    cmd_id = data.get('id')
    if cmd_id:
        result_store[cmd_id] = data
    return jsonify({'ok': True})

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def send_command(action: str, params: dict, timeout: int = 12):
    cmd_id = str(uuid.uuid4())
    cmd = {'id': cmd_id, 'action': action, 'taken': False, **params}
    command_queue.append(cmd)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        if cmd_id in result_store:
            res = result_store.pop(cmd_id)
            command_queue[:] = [c for c in command_queue if c['id'] != cmd_id]
            return res
    command_queue[:] = [c for c in command_queue if c['id'] != cmd_id]
    return {'success': False, 'error': 'Timeout. Игра не ответила.'}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_player_keyboard(username: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить статистику", callback_data=f"refresh:{username}")],
        [
            InlineKeyboardButton("💰 Поставить монеты", callback_data=f"setcoins:{username}"),
            InlineKeyboardButton("💀 Поставить смерти", callback_data=f"setdeaths:{username}"),
        ],
        [InlineKeyboardButton("🎁 Выдать предмет", callback_data=f"giveitem:{username}")],
        [
            InlineKeyboardButton("👢 Кикнуть", callback_data=f"kick:{username}"),
            InlineKeyboardButton("🔨 Забанить", callback_data=f"ban:{username}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def format_player_message(data: dict) -> str:
    private = "Да" if data.get("isPrivate") else "Нет"
    return (
        f"👤 <b>Дисплейнейм:</b> {data['displayName']}\n"
        f"🔑 <b>Юзернейм:</b> {data['username']}\n"
        f"💰 <b>Монет:</b> {data['coins']}\n"
        f"💀 <b>Смертей:</b> {data['deaths']}\n"
        f"🔒 <b>На приватке:</b> {private}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "/find — найти игрока\n"
        "/permban ник — перманентный бан\n"
        "/unban ник — разбан\n"
        "/globalmessage — глобальное сообщение"
    )

WAIT_PLAYER = 0

async def find_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return ConversationHandler.END
    await update.message.reply_text("🔍 Введи ник игрока:")
    return WAIT_PLAYER


async def find_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    context.user_data["target_username"] = username
    msg = await update.message.reply_text("⏳ Ищу игрока...")
    
    result = await context.application.loop.run_in_executor(
        None, lambda: send_command("getPlayer", {"username": username})
    )

    if not result.get("success"):
        await msg.edit_text(
            f"❌ Игрок <b>{username}</b> не найден.\n<i>{result.get('error','')}</i>",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    text = format_player_message(result["data"])
    keyboard = build_player_keyboard(username)
    await msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    return ConversationHandler.END


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return

    data = query.data
    action, username = data.split(":", 1)
    context.user_data["target_username"] = username

    if action == "refresh":
        await query.edit_message_text("⏳ Обновляю...", parse_mode="HTML")
        result = await context.application.loop.run_in_executor(
            None, lambda: send_command("getPlayer", {"username": username})
        )
        if not result.get("success"):
            await query.edit_message_text(
                f"❌ Не удалось обновить.\n<i>{result.get('error','')}</i>", parse_mode="HTML"
            )
            return
        text = format_player_message(result["data"])
        keyboard = build_player_keyboard(username)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif action == "setcoins":
        await query.message.reply_text(f"💰 Введи количество монет для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["awaiting"] = "coins"

    elif action == "setdeaths":
        await query.message.reply_text(f"💀 Введи количество смертей для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["awaiting"] = "deaths"

    elif action == "giveitem":
        await query.message.reply_text(f"🎁 Введи название предмета для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["awaiting"] = "item_name"

    elif action == "kick":
        await query.message.reply_text(
            f"👢 Введи причину кика для <b>{username}</b>:\n"
            "<i>Один символ = кик без причины</i>",
            parse_mode="HTML"
        )
        context.user_data["awaiting"] = "kick_reason"

    elif action == "ban":
        await query.message.reply_text(
            f"🔨 Введи причину бана для <b>{username}</b>:\n"
            "<i>Один символ = бан без причины</i>",
            parse_mode="HTML"
        )
        context.user_data["awaiting"] = "ban_reason"


async def text_awaiting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    text = update.message.text.strip()
    username = context.user_data.get("target_username", "")

    async def run_cmd(action, params):
        return await context.application.loop.run_in_executor(
            None, lambda: send_command(action, params)
        )

    if awaiting == "coins":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Введи целое число.")
            return
        msg = await update.message.reply_text("⏳ Применяю...")
        result = await run_cmd("setCoins", {"username": username, "amount": int(text)})
        if result.get("success"):
            await msg.edit_text(f"✅ Монеты <b>{username}</b>: {text}", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "deaths":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Введи целое число.")
            return
        msg = await update.message.reply_text("⏳ Применяю...")
        result = await run_cmd("setDeaths", {"username": username, "amount": int(text)})
        if result.get("success"):
            await msg.edit_text(f"✅ Смерти <b>{username}</b>: {text}", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "item_name":
        context.user_data["item_name"] = text
        context.user_data["awaiting"] = "item_amount"
        await update.message.reply_text(
            f"🎁 Предмет: <b>{text}</b>\nКоличество? (0 — отмена, макс. 100):",
            parse_mode="HTML"
        )

    elif awaiting == "item_amount":
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.")
            return
        amount = int(text)
        if amount == 0:
            await update.message.reply_text("🚫 Отменено.")
            context.user_data.pop("awaiting")
            context.user_data.pop("item_name", None)
            return
        if amount > 100:
            await update.message.reply_text("❌ Максимум 100.")
            return
        item_name = context.user_data.get("item_name", "")
        msg = await update.message.reply_text("⏳ Выдаю...")
        result = await run_cmd("giveItem", {"username": username, "itemName": item_name, "amount": amount})
        if result.get("success"):
            await msg.edit_text(f"✅ Выдано <b>{amount}x {item_name}</b> → <b>{username}</b>", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")
        context.user_data.pop("item_name", None)

    elif awaiting == "kick_reason":
        reason = None if len(text) == 1 else text
        msg = await update.message.reply_text("⏳ Кикаю...")
        result = await run_cmd("kickPlayer", {"username": username, "reason": reason})
        if result.get("success"):
            r = f"\n📝 {reason}" if reason else ""
            await msg.edit_text(f"✅ <b>{username}</b> кикнут.{r}", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "ban_reason":
        reason = None if len(text) == 1 else text
        msg = await update.message.reply_text("⏳ Баню...")
        result = await run_cmd("banPlayer", {"username": username, "reason": reason})
        if result.get("success"):
            r = f"\n📝 {reason}" if reason else ""
            await msg.edit_text(f"✅ <b>{username}</b> забанен.{r}", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "global_message":
        if text.lower() == "отмена":
            await update.message.reply_text("🚫 Отменено.")
            context.user_data.pop("awaiting")
            return
        msg = await update.message.reply_text("⏳ Отправляю...")
        result = await run_cmd("globalMessage", {"message": text})
        if result.get("success"):
            await msg.edit_text(f"📢 Отправлено:\n<i>{text}</i>", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "permban_nick":
        msg = await update.message.reply_text("⏳ Баню...")
        result = await run_cmd("permBan", {"username": text})
        if result.get("success"):
            await msg.edit_text(f"🔨 <b>{text}</b> перманентно забанен.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")

    elif awaiting == "unban_nick":
        msg = await update.message.reply_text("⏳ Разбаниваю...")
        result = await run_cmd("unban", {"username": text})
        if result.get("success"):
            await msg.edit_text(f"✅ <b>{text}</b> разбанен.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
        context.user_data.pop("awaiting")


async def permban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    if context.args:
        username = context.args[0]
        msg = await update.message.reply_text("⏳ Баню...")
        result = await context.application.loop.run_in_executor(
            None, lambda: send_command("permBan", {"username": username})
        )
        if result.get("success"):
            await msg.edit_text(f"🔨 <b>{username}</b> перманентно забанен.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
    else:
        await update.message.reply_text("🔨 Введи ник для перм-бана:")
        context.user_data["awaiting"] = "permban_nick"


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    if context.args:
        username = context.args[0]
        msg = await update.message.reply_text("⏳ Разбаниваю...")
        result = await context.application.loop.run_in_executor(
            None, lambda: send_command("unban", {"username": username})
        )
        if result.get("success"):
            await msg.edit_text(f"✅ <b>{username}</b> разбанен.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")
    else:
        await update.message.reply_text("🔓 Введи ник для разбана:")
        context.user_data["awaiting"] = "unban_nick"


async def globalmessage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await update.message.reply_text('📢 Введи текст сообщения (или "Отмена"):')
    context.user_data["awaiting"] = "global_message"


def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("find", find_start)],
        states={WAIT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, find_player)]},
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("permban", permban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("globalmessage", globalmessage_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_awaiting_handler))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
