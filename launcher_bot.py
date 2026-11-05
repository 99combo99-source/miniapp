"""
Бот-пускач + админка для Mini App «Мины».

Что умеет:
- открывает приложение по кнопке и через меню чата;
- хранит ПОРОГ доступа (минимум и, по желанию, максимум) и подставляет его в приложение;
- порог меняется прямо в Telegram, без правки файлов.

Логика доступа: пропускает, если введённое в приложении число >= минимума
(и <= максимума, если он задан). Меньше минимума или меньше 1 — не пропускает.

Запуск:
1) pip install python-telegram-bot
2) впиши TOKEN ниже
3) python launcher_bot.py
4) напиши боту /admin — первый, кто вызовет, станет администратором.

Команды администратора:
  /admin              — панель и текущие значения
  /setmin ЧИСЛО       — задать минимум (порог), напр. /setmin 343092807
  /setmax ЧИСЛО       — задать максимум (0 = без верхней границы)
  /myid               — узнать свой Telegram ID
"""

import os
import json
import time
import asyncio

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, MenuButtonWebApp,
)
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

# ================= НАСТРОЙКИ =================
# Токен НЕ храним в коде. На VPS он задаётся переменной окружения BOT_TOKEN
# (см. файл сервиса systemd). Для локального запуска на ПК можно временно
# вписать его в кавычки вместо значения по умолчанию.
TOKEN = os.environ.get("BOT_TOKEN", "СЮДА_ТОКЕН_ДЛЯ_ЛОКАЛЬНОГО_ЗАПУСКА")
BASE_URL = "https://mimimi2121.online/"

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "bot_config.json")
USERS_PATH = os.path.join(BASE, "users.json")
DRIP_SEQ_PATH = os.path.join(BASE, "drip_sequence.json")     # сама цепочка постов
DRIP_STATE_PATH = os.path.join(BASE, "drip_state.json")      # у кого что уже отправлено

DEFAULT = {
    "admin_ids": [],
    "code_min": 343092807,   # порог: пропускать всё, что >= этого числа
    "code_max": 0,           # верхняя граница; 0 = без неё
    "fresh_mode": "time",    # "time" — всегда свежая версия (антикэш); "fixed" — по version
    "version": 3,
    "drip_interval_hours": 24,   # раз в сколько часов слать следующий пост цепочки
}


def get_cfg():
    if not os.path.exists(CONFIG_PATH):
        save_cfg(DEFAULT)
        return dict(DEFAULT)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT.items():
        cfg.setdefault(k, v)
    return cfg


def save_cfg(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ================= СПИСОК ПОЛЬЗОВАТЕЛЕЙ (для рассылки) =================
def get_users():
    if not os.path.exists(USERS_PATH):
        return []
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_users(users):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def add_user(uid):
    users = get_users()
    if uid not in users:
        users.append(uid)
        save_users(users)


def remove_user(uid):
    users = get_users()
    if uid in users:
        users.remove(uid)
        save_users(users)


def is_admin(uid):
    return uid in get_cfg().get("admin_ids", [])


# ================= ЗАПЛАНИРОВАННАЯ ЦЕПОЧКА ПОСТОВ (DRIP) =================
def get_drip_sequence():
    """Список постов цепочки: [{chat_id, message_id}, ...] по порядку дня 1, 2, 3..."""
    if not os.path.exists(DRIP_SEQ_PATH):
        return []
    try:
        with open(DRIP_SEQ_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_drip_sequence(seq):
    with open(DRIP_SEQ_PATH, "w", encoding="utf-8") as f:
        json.dump(seq, f, ensure_ascii=False, indent=2)


def get_drip_state():
    """У кого что уже отправлено: {uid: {"joined":ts, "next_idx":0, "last_sent":ts}}"""
    if not os.path.exists(DRIP_STATE_PATH):
        return {}
    try:
        with open(DRIP_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_drip_state(state):
    with open(DRIP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def drip_register_user(uid):
    """Регистрируем пользователя в цепочке при первом /start. Старых не трогаем."""
    state = get_drip_state()
    key = str(uid)
    if key not in state:
        state[key] = {"joined": time.time(), "next_idx": 0, "last_sent": None}
        save_drip_state(state)


def app_url():
    cfg = get_cfg()
    tag = str(int(time.time())) if cfg["fresh_mode"] == "time" else str(cfg["version"])
    url = f"{BASE_URL}?min={cfg['code_min']}&v={tag}"
    if cfg["code_max"] and cfg["code_max"] > 0:
        url += f"&max={cfg['code_max']}"
    return url


# ================= ПОЛЬЗОВАТЕЛЬ =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    drip_register_user(update.effective_user.id)   # включаем в запланированную цепочку постов
    url = app_url()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Открыть «Мины»", web_app=WebAppInfo(url=url))]
    ])
    await update.message.reply_text("Жми кнопку, чтобы открыть приложение 👇", reply_markup=kb)
    try:
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_chat.id,
            menu_button=MenuButtonWebApp(text="Играть", web_app=WebAppInfo(url=url)),
        )
    except Exception:
        pass


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


# ================= АДМИНКА =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = get_cfg()

    # первый вызвавший становится админом
    if not cfg["admin_ids"]:
        cfg["admin_ids"] = [uid]
        save_cfg(cfg)
        await update.message.reply_text("✅ Ты назначен администратором.")

    if not is_admin(uid):
        return

    cfg = get_cfg()
    mx = cfg["code_max"] if cfg["code_max"] else "нет (без верхней границы)"
    text = (
        "⚙️ Панель администратора\n\n"
        f"Минимум (порог): {cfg['code_min']}\n"
        f"Максимум: {mx}\n\n"
        "Пропускаются числа, которые больше или равны минимуму"
        " (и не больше максимума, если он задан).\n\n"
        "Команды:\n"
        "/setmin ЧИСЛО — задать порог\n"
        "/setmax ЧИСЛО — задать максимум (0 = убрать)\n"
        "/setrange МИН МАКС — задать оба сразу, напр. /setrange 343092807 343092999\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить минимум", callback_data="adm:min")],
        [InlineKeyboardButton("✏️ Изменить максимум", callback_data="adm:max")],
        [InlineKeyboardButton("🚫 Убрать максимум", callback_data="adm:clearmax")],
    ])
    await update.message.reply_text(text, reply_markup=kb)


async def on_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    action = q.data.split(":")[1]

    if action == "min":
        context.user_data["await"] = "min"
        await q.message.reply_text("Пришли новый минимум (число). Напр.: 343092807")
    elif action == "max":
        context.user_data["await"] = "max"
        await q.message.reply_text("Пришли новый максимум (число). 0 — убрать верхнюю границу.")
    elif action == "clearmax":
        cfg = get_cfg(); cfg["code_max"] = 0; save_cfg(cfg)
        await q.message.reply_text("✅ Верхняя граница убрана.")


async def set_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        val = int(context.args[0])
        cfg = get_cfg(); cfg["code_min"] = val; save_cfg(cfg)
        await update.message.reply_text(f"✅ Минимум (порог) теперь: {val}\nОткрой приложение заново, чтобы применилось.")
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /setmin 343092807")


async def set_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        val = int(context.args[0])
        cfg = get_cfg(); cfg["code_max"] = max(0, val); save_cfg(cfg)
        txt = "убран" if val <= 0 else str(val)
        await update.message.reply_text(f"✅ Максимум теперь: {txt}\nОткрой приложение заново, чтобы применилось.")
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /setmax 343092999 (или /setmax 0 чтобы убрать)")


async def set_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        lo = int(context.args[0])
        hi = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /setrange 343092807 343092999")
        return
    if lo > hi:
        await update.message.reply_text(
            f"Минимум ({lo}) больше максимума ({hi}) — так никто не пройдёт.\n"
            "Поставь минимум не больше максимума."
        )
        return
    cfg = get_cfg()
    cfg["code_min"] = lo
    cfg["code_max"] = hi
    save_cfg(cfg)
    await update.message.reply_text(
        f"✅ Диапазон доступа: от {lo} до {hi}.\n"
        "Открой приложение заново, чтобы применилось."
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приём значений админки и шагов рассылки."""
    if not is_admin(update.effective_user.id):
        return
    await_key = context.user_data.get("await")
    if not await_key:
        return

    # --- рассылка: приём содержимого ---
    if await_key == "bcast_content":
        await capture_broadcast(update, context)
        return

    # --- рассылка: подтверждение ---
    if await_key == "bcast_confirm":
        if update.message.text.strip().lower() in ("да", "yes", "д", "+"):
            await do_broadcast(update, context)
        else:
            await update.message.reply_text("Не понял. Напиши ДА для отправки или /cancel для отмены.")
        return

    # --- цепочка постов: приём нового поста (текст) ---
    if await_key == "addpost_content":
        await capture_post(update, context)
        return

    # --- цепочка постов: интервал между постами ---
    if await_key == "drip_interval":
        try:
            hours = float(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("Нужно число часов. Например: 24")
            return
        cfg = get_cfg()
        cfg["drip_interval_hours"] = hours
        save_cfg(cfg)
        context.user_data.pop("await", None)
        await update.message.reply_text(f"✅ Интервал между постами цепочки: {hours} ч.")
        return

    # --- админка: числа (min/max) ---
    try:
        val = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Нужно число. Попробуй ещё раз.")
        return
    cfg = get_cfg()
    if await_key == "min":
        cfg["code_min"] = val
        save_cfg(cfg)
        await update.message.reply_text(f"✅ Минимум (порог) теперь: {val}\nОткрой приложение заново, чтобы применилось.")
    elif await_key == "max":
        cfg["code_max"] = max(0, val)
        save_cfg(cfg)
        txt = "убран" if val <= 0 else str(val)
        await update.message.reply_text(f"✅ Максимум теперь: {txt}\nОткрой приложение заново, чтобы применилось.")
    context.user_data.pop("await", None)


# ================= РАССЫЛКА =================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data["await"] = "bcast_content"
    total = len(get_users())
    await update.message.reply_text(
        "📣 Рассылка.\n\n"
        "Пришли сообщение, которое разослать: обычный текст, или фото/видео с подписью.\n"
        f"Сейчас получателей: {total}.\n\n"
        "Отмена в любой момент — /cancel"
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop("await", None)
    context.user_data.pop("bcast", None)
    await update.message.reply_text("Отменено.")


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"👥 Пользователей в базе: {len(get_users())}")


async def capture_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запоминаем присланное сообщение и просим подтверждение."""
    context.user_data["bcast"] = {
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
    }
    context.user_data["await"] = "bcast_confirm"
    total = len(get_users())
    await update.message.reply_text(
        f"👆 Вот это сообщение уйдёт {total} пользователям.\n\n"
        "Отправить? Напиши ДА для подтверждения или /cancel для отмены."
    )


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("bcast")
    if not data:
        await update.message.reply_text("Нечего отправлять. Начни заново: /broadcast")
        context.user_data.pop("await", None)
        return
    users = list(get_users())
    await update.message.reply_text(f"📤 Рассылаю по {len(users)} пользователям…")
    sent = blocked = failed = 0
    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=data["chat_id"],
                message_id=data["message_id"],
            )
            sent += 1
        except Forbidden:
            remove_user(uid)   # заблокировал бота — убираем из базы
            blocked += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)   # мягкая пауза, чтобы не упереться в лимиты
    context.user_data.pop("await", None)
    context.user_data.pop("bcast", None)
    await update.message.reply_text(
        "✅ Готово.\n"
        f"Отправлено: {sent}\n"
        f"Заблокировали бота (удалены из базы): {blocked}\n"
        f"Прочие ошибки: {failed}"
    )


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото/видео от админа во время подготовки рассылки или поста цепочки."""
    if not is_admin(update.effective_user.id):
        return
    aw = context.user_data.get("await")
    if aw == "bcast_content":
        await capture_broadcast(update, context)
    elif aw == "addpost_content":
        await capture_post(update, context)


# ================= ЗАПЛАНИРОВАННАЯ ЦЕПОЧКА ПОСТОВ (DRIP) =================
async def addpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data["await"] = "addpost_content"
    day = len(get_drip_sequence()) + 1
    cfg = get_cfg()
    await update.message.reply_text(
        f"➕ Добавляю пост №{day} в цепочку.\n\n"
        "Пришли сообщение (текст, или фото/видео с подписью) — оно станет "
        f"постом дня {day}: уйдёт новому подписчику через "
        f"{day} × {cfg['drip_interval_hours']} ч после его /start.\n\n"
        "Отмена — /cancel"
    )


async def capture_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seq = get_drip_sequence()
    seq.append({
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
    })
    save_drip_sequence(seq)
    context.user_data.pop("await", None)
    await update.message.reply_text(f"✅ Сохранено как пост №{len(seq)} цепочки.")


async def posts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    seq = get_drip_sequence()
    cfg = get_cfg()
    state = get_drip_state()
    active = sum(1 for s in state.values() if s.get("next_idx", 0) < len(seq))
    await update.message.reply_text(
        f"📚 В цепочке постов: {len(seq)}\n"
        f"⏱ Интервал: {cfg['drip_interval_hours']} ч между постами\n"
        f"👥 Ещё получают цепочку: {active} чел.\n\n"
        "Добавить пост — /addpost\n"
        "Удалить последний — /delpost\n"
        "Изменить интервал — /dripinterval ЧАСЫ (например /dripinterval 24)"
    )


async def delpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    seq = get_drip_sequence()
    if not seq:
        await update.message.reply_text("Цепочка пуста, удалять нечего.")
        return
    seq.pop()  # убираем последний добавленный пост
    save_drip_sequence(seq)
    await update.message.reply_text(f"🗑 Последний пост удалён. Осталось в цепочке: {len(seq)}")


async def dripinterval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if context.args:
        try:
            hours = float(context.args[0])
        except ValueError:
            await update.message.reply_text("Формат: /dripinterval 24")
            return
        cfg = get_cfg()
        cfg["drip_interval_hours"] = hours
        save_cfg(cfg)
        await update.message.reply_text(f"✅ Интервал между постами цепочки: {hours} ч.")
    else:
        context.user_data["await"] = "drip_interval"
        await update.message.reply_text("Через сколько часов слать следующий пост? Пришли число, например 24.")


async def drip_tick(context: ContextTypes.DEFAULT_TYPE):
    """Фоновая проверка: кому пора получить следующий пост цепочки. Запускается по расписанию."""
    seq = get_drip_sequence()
    if not seq:
        return
    state = get_drip_state()
    cfg = get_cfg()
    interval = cfg.get("drip_interval_hours", 24) * 3600
    now = time.time()
    changed = False
    for key, s in list(state.items()):
        idx = s.get("next_idx", 0)
        if idx >= len(seq):
            continue  # цепочка для этого человека уже закончилась
        anchor = s.get("last_sent") or s.get("joined", now)
        if now - anchor < interval:
            continue  # ещё не время для следующего поста
        uid = int(key)
        post = seq[idx]
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=post["chat_id"],
                message_id=post["message_id"],
            )
            s["next_idx"] = idx + 1
            s["last_sent"] = now
            changed = True
        except Forbidden:
            remove_user(uid)          # заблокировал бота — убираем и из общей базы
            s["next_idx"] = len(seq)  # и останавливаем для него цепочку
            changed = True
        except TelegramError:
            pass  # временная ошибка — попробуем на следующей проверке
        await asyncio.sleep(0.05)
    if changed:
        save_drip_state(state)


def main():
    get_cfg()  # создаём файл настроек при первом запуске
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("setmin", set_min))
    app.add_handler(CommandHandler("setmax", set_max))
    app.add_handler(CommandHandler("setrange", set_range))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("addpost", addpost_cmd))
    app.add_handler(CommandHandler("posts", posts_cmd))
    app.add_handler(CommandHandler("delpost", delpost_cmd))
    app.add_handler(CommandHandler("dripinterval", dripinterval_cmd))
    app.add_handler(CallbackQueryHandler(on_admin_button, pattern="^adm:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # проверяем цепочку постов раз в 30 минут — кому пора получить следующий
    app.job_queue.run_repeating(drip_tick, interval=1800, first=15)
    print("✅ Бот запущен! Ctrl+C — остановить.")
    app.run_polling()


if __name__ == "__main__":
    main()
