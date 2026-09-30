from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.db import Database
from app.services.economy import DuplicateEvent, EconomyService, InsufficientFunds

router = Router(name="admin")

STAT_LABELS = {
    "block": "Блок",
    "endurance": "Выносливость",
    "health": "Здоровье",
    "intuition": "Интуиция",
    "strength": "Сила",
    "speed": "Скорость",
    "charisma": "Харизма",
}

LINK_KEYS = {
    "news": ("NEWS_URL", "📰 Новостной канал"),
    "general": ("GENERAL_CHAT_URL", "💬 Общий чат"),
    "roulette": ("ROULETTE_CHAT_URL", "🎰 Чат рулетки"),
}


class AdminStates(StatesGroup):
    broadcast_message = State()
    user_search = State()
    user_value = State()
    stat_value = State()
    info_value = State()
    block_search = State()


def is_owner(user_id: int, config: Config) -> bool:
    return user_id in set(config.admin_ids)


async def reject_message(message: Message, config: Config) -> bool:
    if is_owner(message.from_user.id, config):
        return False
    await message.answer("⛔ Нет доступа.")
    return True


async def reject_call(call: CallbackQuery, config: Config) -> bool:
    if is_owner(call.from_user.id, config):
        return False
    await call.answer("⛔ Нет доступа.", show_alert=True)
    return True


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 РАССЫЛКА", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="👥 ПОЛЬЗОВАТЕЛИ", callback_data="admin:users")],
        [InlineKeyboardButton(text="ℹ️ ИНФОРМАЦИЯ", callback_data="admin:info")],
        [InlineKeyboardButton(text="🚫 ЗАБЛОКИРОВАТЬ", callback_data="admin:block")],
    ])


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]
    ])


def cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:cancel")]
    ])


def user_keyboard(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="💰 GENTRA", callback_data=f"admin:userfield:{user_id}:gentra"),
            InlineKeyboardButton(text="🪙 Галеоны", callback_data=f"admin:userfield:{user_id}:galleons"),
        ],
        [InlineKeyboardButton(text="📊 Характеристики", callback_data=f"admin:stats:{user_id}")],
        [InlineKeyboardButton(text="✅ Разблокировать" if blocked else "🚫 Заблокировать", callback_data=f"admin:toggleblock:{user_id}")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin:user:{user_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:users")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats_keyboard(user_id: int, row) -> InlineKeyboardMarkup:
    rows = []
    for key, label in STAT_LABELS.items():
        rows.append([InlineKeyboardButton(text=f"{label}: {int(row[key])}", callback_data=f"admin:stat:{user_id}:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ К пользователю", callback_data=f"admin:user:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def info_keyboard(db: Database, config: Config) -> InlineKeyboardMarkup:
    rows = []
    defaults = {
        "NEWS_URL": config.news_url,
        "GENERAL_CHAT_URL": config.general_chat_url,
        "ROULETTE_CHAT_URL": config.roulette_chat_url,
    }
    for short, (key, label) in LINK_KEYS.items():
        value = db.get_setting(key, defaults[key])
        mark = "✅" if value else "➖"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"admin:infoedit:{short}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_text(db: Database, user_id: int) -> str:
    row = db.get_user(user_id)
    if not row:
        return "👤 Пользователь не найден."
    name = f"@{row['username']}" if row["username"] else row["first_name"] or "—"
    stats = sum(int(row[key]) for key in STAT_LABELS)
    clan = "Нет"
    if row["clan_id"]:
        with db.connect() as con:
            c = con.execute("SELECT name FROM clans WHERE clan_id=?", (row["clan_id"],)).fetchone()
            if c:
                clan = c["name"]
    status = "🚫 Заблокирован" if db.is_blocked(user_id) else "✅ Активен"
    vip = row["vip_until"] or "Нет"
    return (
        "👤 <b>Пользователь</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: {name}\n"
        f"💰 GENTRA: <b>{int(row['gentra']):,}</b>\n"
        f"🪙 Галеоны: <b>{int(row['galleons']):,}</b>\n"
        f"📊 Характеристики: <b>{stats}</b>\n"
        f"🏰 Клан: <b>{clan}</b>\n"
        f"⭐ VIP: <b>{vip}</b>\n"
        f"Статус: <b>{status}</b>"
    )


async def show_admin(target: Message, db: Database) -> None:
    text = (
        "⚙️ <b>Админ-панель gentra</b>\n\n"
        f"👥 Пользователей: <b>{db.user_count()}</b>\n"
        f"🚫 Заблокировано: <b>{db.blocked_count()}</b>\n\n"
        "Выберите раздел:"
    )
    await target.answer(text, reply_markup=admin_menu())


@router.message(Command("admin"))
@router.message(F.text == "⚙️ Админ-панель")
async def admin_entry(message: Message, db: Database, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    await state.clear()
    await show_admin(message, db)


@router.callback_query(F.data == "admin:home")
async def admin_home(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    text = (
        "⚙️ <b>Админ-панель gentra</b>\n\n"
        f"👥 Пользователей: <b>{db.user_count()}</b>\n"
        f"🚫 Заблокировано: <b>{db.blocked_count()}</b>\n\n"
        "Выберите раздел:"
    )
    await call.message.edit_text(text, reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    await call.message.edit_text("❌ Действие отменено.", reply_markup=back_menu())
    await call.answer()


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(call: CallbackQuery, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.set_state(AdminStates.broadcast_message)
    await call.message.edit_text(
        "📢 <b>РАССЫЛКА</b>\n\nОтправьте следующим сообщением текст, фото, видео, документ или другой контент.\n\nПосле этого бот покажет подтверждение перед отправкой всем пользователям.",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.broadcast_message)
async def broadcast_capture(message: Message, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    await state.update_data(source_chat_id=message.chat.id, source_message_id=message.message_id)
    await message.answer("👁 <b>Предпросмотр рассылки:</b>")
    try:
        await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    except TelegramBadRequest:
        await message.answer("Этот тип сообщения нельзя использовать для рассылки. Отправьте другой материал.")
        return
    await message.answer(
        "Отправить это сообщение всем пользователям?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить всем", callback_data="admin:broadcast:send")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:cancel")],
        ]),
    )


@router.callback_query(F.data == "admin:broadcast:send")
async def broadcast_send(call: CallbackQuery, bot: Bot, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    data = await state.get_data()
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    if not source_chat_id or not source_message_id:
        await call.answer("Материал рассылки не найден.", show_alert=True)
        return
    await state.clear()
    users = db.all_user_ids(include_blocked=False)
    broadcast_id = db.create_broadcast(call.from_user.id, int(source_chat_id), int(source_message_id), len(users))
    await call.message.edit_text(f"📢 Рассылка запущена. Получателей: <b>{len(users)}</b>.")
    delivered = 0
    failed = 0
    for user_id in users:
        try:
            await bot.copy_message(user_id, int(source_chat_id), int(source_message_id))
            delivered += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after))
            try:
                await bot.copy_message(user_id, int(source_chat_id), int(source_message_id))
                delivered += 1
            except Exception:
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.035)
    db.finish_broadcast(broadcast_id, delivered, failed)
    await call.message.answer(
        "✅ <b>Рассылка завершена</b>\n\n"
        f"Доставлено: <b>{delivered}</b>\n"
        f"Не доставлено: <b>{failed}</b>",
        reply_markup=back_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:users")
async def users_start(call: CallbackQuery, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.set_state(AdminStates.user_search)
    await call.message.edit_text(
        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\nОтправьте Telegram ID пользователя.\nПосле поиска можно изменить GENTRA, галеоны, характеристики и доступ к боту.",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.user_search)
async def users_search(message: Message, db: Database, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите числовой Telegram ID.")
        return
    row = db.get_user(user_id)
    if not row:
        await message.answer("❌ Пользователь с таким ID ещё не зарегистрирован в боте.")
        return
    await state.clear()
    await message.answer(user_text(db, user_id), reply_markup=user_keyboard(user_id, db.is_blocked(user_id)))


@router.callback_query(F.data.startswith("admin:user:"))
async def user_open(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    user_id = int(call.data.rsplit(":", 1)[1])
    if not db.get_user(user_id):
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    await call.message.edit_text(user_text(db, user_id), reply_markup=user_keyboard(user_id, db.is_blocked(user_id)))
    await call.answer()


@router.callback_query(F.data.startswith("admin:userfield:"))
async def user_field(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    _, _, user_id_s, field = call.data.split(":", 3)
    user_id = int(user_id_s)
    row = db.get_user(user_id)
    if not row or field not in {"gentra", "galleons"}:
        await call.answer("Некорректные данные.", show_alert=True)
        return
    await state.set_state(AdminStates.user_value)
    await state.update_data(target_user_id=user_id, field=field)
    label = "GENTRA" if field == "gentra" else "галеонов"
    await call.message.edit_text(
        f"✏️ <b>Изменение {label}</b>\n\nПользователь: <code>{user_id}</code>\nТекущее значение: <b>{int(row[field]):,}</b>\n\nОтправьте новое точное значение от 0 и выше.",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.user_value)
async def user_value_save(message: Message, db: Database, economy: EconomyService, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    try:
        value = int((message.text or "").replace(" ", "").strip())
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое число 0 или больше.")
        return
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    field = str(data["field"])
    row = db.get_user(user_id)
    if not row:
        await state.clear()
        await message.answer("Пользователь не найден.", reply_markup=back_menu())
        return
    delta = value - int(row[field])
    kwargs = {"gentra_delta": delta} if field == "gentra" else {"galleons_delta": delta}
    try:
        economy.change(
            user_id,
            kind=f"admin_set_{field}",
            event_key=f"admin:{message.from_user.id}:{message.chat.id}:{message.message_id}:{field}:{user_id}",
            meta={"admin_id": message.from_user.id, "set_to": value},
            **kwargs,
        )
    except (InsufficientFunds, DuplicateEvent):
        await message.answer("Не удалось изменить значение.")
        return
    await state.clear()
    await message.answer("✅ Значение изменено.\n\n" + user_text(db, user_id), reply_markup=user_keyboard(user_id, db.is_blocked(user_id)))


@router.callback_query(F.data.startswith("admin:stats:"))
async def stats_open(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    user_id = int(call.data.rsplit(":", 1)[1])
    row = db.get_user(user_id)
    if not row:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    await call.message.edit_text(
        f"📊 <b>Характеристики</b>\nПользователь: <code>{user_id}</code>\n\nНажмите характеристику для изменения:",
        reply_markup=stats_keyboard(user_id, row),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:stat:"))
async def stat_edit(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    _, _, user_id_s, stat = call.data.split(":", 3)
    user_id = int(user_id_s)
    row = db.get_user(user_id)
    if not row or stat not in STAT_LABELS:
        await call.answer("Некорректные данные.", show_alert=True)
        return
    await state.set_state(AdminStates.stat_value)
    await state.update_data(target_user_id=user_id, stat=stat)
    await call.message.edit_text(
        f"📊 <b>{STAT_LABELS[stat]}</b>\nПользователь: <code>{user_id}</code>\nТекущее значение: <b>{int(row[stat])}</b>\n\nОтправьте новое значение:",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.stat_value)
async def stat_save(message: Message, db: Database, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    try:
        value = int((message.text or "").strip())
        if value < 0 or value > 1_000_000:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое значение от 0 до 1 000 000.")
        return
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    stat = str(data["stat"])
    try:
        db.set_user_stat(user_id, stat, value)
    except (ValueError, LookupError):
        await message.answer("Не удалось изменить характеристику.")
        return
    await state.clear()
    row = db.get_user(user_id)
    await message.answer("✅ Характеристика изменена.", reply_markup=stats_keyboard(user_id, row))


@router.callback_query(F.data == "admin:info")
async def info_open(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    defaults = {
        "NEWS_URL": config.news_url,
        "GENERAL_CHAT_URL": config.general_chat_url,
        "ROULETTE_CHAT_URL": config.roulette_chat_url,
    }
    lines = ["ℹ️ <b>ИНФОРМАЦИЯ</b>", "", "Ссылки, которые показываются в разделе «💬 Чаты»: ", ""]
    for _, (key, label) in LINK_KEYS.items():
        lines.append(f"{label}: {db.get_setting(key, defaults[key])}")
    lines.append("\nНажмите нужный пункт для изменения.")
    await call.message.edit_text("\n".join(lines), reply_markup=info_keyboard(db, config), disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data.startswith("admin:infoedit:"))
async def info_edit(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    short = call.data.rsplit(":", 1)[1]
    if short not in LINK_KEYS:
        await call.answer("Некорректный раздел.", show_alert=True)
        return
    key, label = LINK_KEYS[short]
    await state.set_state(AdminStates.info_value)
    await state.update_data(info_key=key, info_label=label)
    await call.message.edit_text(
        f"🔗 <b>{label}</b>\n\nОтправьте новую ссылку.\nПример: <code>https://t.me/gentra_chat</code>",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.info_value)
async def info_save(message: Message, db: Database, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    value = (message.text or "").strip()
    if not value.startswith(("https://", "http://", "tg://")):
        await message.answer("Отправьте корректную ссылку, начинающуюся с https://, http:// или tg://.")
        return
    data = await state.get_data()
    db.set_setting(str(data["info_key"]), value)
    await state.clear()
    await message.answer(f"✅ {data['info_label']} изменён.\nНовая ссылка: {value}", reply_markup=back_menu(), disable_web_page_preview=True)


@router.callback_query(F.data == "admin:block")
async def block_start(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.set_state(AdminStates.block_search)
    await call.message.edit_text(
        "🚫 <b>ЗАБЛОКИРОВАТЬ</b>\n\nОтправьте Telegram ID пользователя.\n\nБлокировка полностью отключает команды, игры и inline-кнопки пользователя как в личных сообщениях, так и в группах.",
        reply_markup=cancel_menu(),
    )
    await call.answer()


@router.message(AdminStates.block_search)
async def block_search(message: Message, db: Database, config: Config, state: FSMContext):
    if await reject_message(message, config):
        return
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите числовой Telegram ID.")
        return
    if user_id in set(config.admin_ids):
        await message.answer("⛔ Администратора нельзя заблокировать.")
        return
    if not db.get_user(user_id):
        await message.answer("❌ Пользователь с таким ID ещё не зарегистрирован в боте.")
        return
    await state.clear()
    blocked = db.is_blocked(user_id)
    text = user_text(db, user_id)
    if blocked:
        text += "\n\nПользователь уже заблокирован. Можно разблокировать кнопкой ниже."
    else:
        text += "\n\nНажмите кнопку ниже для полной блокировки доступа."
    await message.answer(text, reply_markup=user_keyboard(user_id, blocked))


@router.callback_query(F.data.startswith("admin:toggleblock:"))
async def toggle_block(call: CallbackQuery, db: Database, config: Config, state: FSMContext):
    if await reject_call(call, config):
        return
    await state.clear()
    user_id = int(call.data.rsplit(":", 1)[1])
    if user_id in set(config.admin_ids):
        await call.answer("Администратора нельзя заблокировать.", show_alert=True)
        return
    if not db.get_user(user_id):
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if db.is_blocked(user_id):
        db.unblock_user(user_id)
        notice = "✅ Пользователь разблокирован."
    else:
        db.block_user(user_id, call.from_user.id)
        notice = "🚫 Пользователь заблокирован во всём боте."
    await call.message.edit_text(notice + "\n\n" + user_text(db, user_id), reply_markup=user_keyboard(user_id, db.is_blocked(user_id)))
    await call.answer()
