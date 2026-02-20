import logging
import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "").split(",")))
ROBLOX_API_URL = os.environ.get("ROBLOX_API_URL")
ROBLOX_SECRET = os.environ.get("ROBLOX_SECRET")

(
    WAIT_PLAYER,
    WAIT_COINS,
    WAIT_DEATHS,
    WAIT_ITEM_NAME,
    WAIT_ITEM_AMOUNT,
    WAIT_KICK_REASON,
    WAIT_BAN_REASON,
    WAIT_PERMBAN_NICK,
    WAIT_UNBAN_NICK,
    WAIT_GLOBAL_MESSAGE,
) = range(10)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def roblox_request(action: str, data: dict):
    try:
        resp = requests.post(
            ROBLOX_API_URL,
            json={"action": action, "secret": ROBLOX_SECRET, **data},
            timeout=15
        )
        return resp.json()
    except Exception as e:
        logger.error(f"Roblox request error: {e}")
        return {"success": False, "error": str(e)}


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
        "👋 Привет! Используй команды:\n"
        "/find — найти игрока\n"
        "/permban ник — перманентный бан\n"
        "/unban ник — разбан\n"
        "/globalmessage — глобальное сообщение"
    )


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
    result = roblox_request("getPlayer", {"username": username})

    if not result.get("success"):
        await msg.edit_text(f"❌ Игрок <b>{username}</b> не найден или не в игре.", parse_mode="HTML")
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
    context.user_data["edit_message"] = query.message

    if action == "refresh":
        result = roblox_request("getPlayer", {"username": username})
        if not result.get("success"):
            await query.edit_message_text(f"❌ Игрок <b>{username}</b> не найден.", parse_mode="HTML")
            return
        text = format_player_message(result["data"])
        keyboard = build_player_keyboard(username)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif action == "setcoins":
        await query.message.reply_text(f"💰 Введи количество монет для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["conv_action"] = "setcoins"
        context.user_data["awaiting"] = "coins"

    elif action == "setdeaths":
        await query.message.reply_text(f"💀 Введи количество смертей для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["conv_action"] = "setdeaths"
        context.user_data["awaiting"] = "deaths"

    elif action == "giveitem":
        await query.message.reply_text(f"🎁 Введи название предмета для <b>{username}</b>:", parse_mode="HTML")
        context.user_data["conv_action"] = "giveitem_name"
        context.user_data["awaiting"] = "item_name"

    elif action == "kick":
        await query.message.reply_text(
            f"👢 Введи причину кика для <b>{username}</b>:\n"
            "<i>(один символ/цифра/эмодзи = кик без причины)</i>",
            parse_mode="HTML"
        )
        context.user_data["conv_action"] = "kick"
        context.user_data["awaiting"] = "kick_reason"

    elif action == "ban":
        await query.message.reply_text(
            f"🔨 Введи причину бана для <b>{username}</b>:\n"
            "<i>(один символ/цифра/эмодзи = бан без причины)</i>",
            parse_mode="HTML"
        )
        context.user_data["conv_action"] = "ban"
        context.user_data["awaiting"] = "ban_reason"


async def text_awaiting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    text = update.message.text.strip()
    username = context.user_data.get("target_username")

    if awaiting == "coins":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Введи число.")
            return
        result = roblox_request("setCoins", {"username": username, "amount": int(text)})
        if result.get("success"):
            await update.message.reply_text(f"✅ Монеты игрока <b>{username}</b> установлены: {text}", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "deaths":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Введи число.")
            return
        result = roblox_request("setDeaths", {"username": username, "amount": int(text)})
        if result.get("success"):
            await update.message.reply_text(f"✅ Смерти игрока <b>{username}</b> установлены: {text}", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "item_name":
        context.user_data["item_name"] = text
        context.user_data["awaiting"] = "item_amount"
        await update.message.reply_text(
            f"🎁 Предмет: <b>{text}</b>\nВведи количество (0 — отмена, макс. 100):",
            parse_mode="HTML"
        )

    elif awaiting == "item_amount":
        if not text.isdigit():
            await update.message.reply_text("❌ Введи число.")
            return
        amount = int(text)
        if amount == 0:
            await update.message.reply_text("🚫 Отменено.")
            context.user_data.pop("awaiting", None)
            context.user_data.pop("item_name", None)
            return
        if amount > 100:
            await update.message.reply_text("❌ Максимум 100 предметов.")
            return
        item_name = context.user_data.get("item_name")
        result = roblox_request("giveItem", {"username": username, "itemName": item_name, "amount": amount})
        if result.get("success"):
            await update.message.reply_text(
                f"✅ Выдано <b>{amount}x {item_name}</b> игроку <b>{username}</b>.", parse_mode="HTML"
            )
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)
        context.user_data.pop("item_name", None)

    elif awaiting == "kick_reason":
        import unicodedata
        reason = None if len(text) == 1 else text
        result = roblox_request("kickPlayer", {"username": username, "reason": reason})
        if result.get("success"):
            msg = f"✅ Игрок <b>{username}</b> кикнут."
            if reason:
                msg += f"\n📝 Причина: {reason}"
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "ban_reason":
        reason = None if len(text) == 1 else text
        result = roblox_request("banPlayer", {"username": username, "reason": reason})
        if result.get("success"):
            msg = f"✅ Игрок <b>{username}</b> забанен."
            if reason:
                msg += f"\n📝 Причина: {reason}"
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "global_message":
        if text.lower() == "отмена":
            await update.message.reply_text("🚫 Отменено.")
            context.user_data.pop("awaiting", None)
            return
        result = roblox_request("globalMessage", {"message": text})
        if result.get("success"):
            await update.message.reply_text(f"📢 Глобальное сообщение отправлено:\n<i>{text}</i>", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "permban_nick":
        result = roblox_request("permBan", {"username": text})
        if result.get("success"):
            await update.message.reply_text(f"🔨 Игрок <b>{text}</b> перманентно забанен.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)

    elif awaiting == "unban_nick":
        result = roblox_request("unban", {"username": text})
        if result.get("success"):
            await update.message.reply_text(f"✅ Игрок <b>{text}</b> разбанен.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
        context.user_data.pop("awaiting", None)


async def permban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    args = context.args
    if args:
        username = args[0]
        result = roblox_request("permBan", {"username": username})
        if result.get("success"):
            await update.message.reply_text(f"🔨 Игрок <b>{username}</b> перманентно забанен.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
    else:
        await update.message.reply_text("🔨 Введи ник для бана:")
        context.user_data["awaiting"] = "permban_nick"


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    args = context.args
    if args:
        username = args[0]
        result = roblox_request("unban", {"username": username})
        if result.get("success"):
            await update.message.reply_text(f"✅ Игрок <b>{username}</b> разбанен.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.get('error')}")
    else:
        await update.message.reply_text("🔓 Введи ник для разбана:")
        context.user_data["awaiting"] = "unban_nick"


async def globalmessage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await update.message.reply_text('📢 Введи текст глобального сообщения (или "Отмена"):')
    context.user_data["awaiting"] = "global_message"


def main():
    keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("find", find_start)],
        states={
            WAIT_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, find_player)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("permban", permban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("globalmessage", globalmessage_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_awaiting_handler))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
