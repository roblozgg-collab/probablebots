from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.db import Database
from app.i18n import LANGS, STAT_NAMES, all_texts, t
from app.keyboards import language_keyboard, main_menu, stats_keyboard
from app.services.duels import DuelService
from app.services.economy import (
    DuplicateEvent,
    EconomyService,
    InsufficientFunds,
    InvalidAmount,
    SelfTransfer,
    UserNotFound,
)

router = Router(name="common")


def lang_for_message(message: Message, db: Database) -> str:
    if message.chat.type in {"group", "supergroup"}:
        return db.get_group_language(message.chat.id)
    return db.get_user_language(message.from_user.id)


def lang_for_callback(call: CallbackQuery, db: Database) -> str:
    if call.message and call.message.chat.type in {"group", "supergroup"}:
        return db.get_group_language(call.message.chat.id)
    return db.get_user_language(call.from_user.id)


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in {"administrator", "creator"}


@router.message(CommandStart())
async def start(message: Message, db: Database, config: Config):
    lang = lang_for_message(message, db)
    await message.answer(t(lang, "welcome"), reply_markup=main_menu(lang, message.chat.type == "private" and message.from_user.id in set(config.admin_ids)))


@router.message(Command("help"))
@router.message(Command("commands"))
async def commands(message: Message, db: Database):
    await message.answer(t(lang_for_message(message, db), "commands_text"))


@router.message(Command("rules"))
async def rules(message: Message, db: Database):
    await message.answer(t(lang_for_message(message, db), "rules_text"))


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("commands")))
async def commands_button(message: Message, db: Database):
    await commands(message, db)


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("policy")))
async def policy(message: Message, db: Database):
    await message.answer(t(lang_for_message(message, db), "policy_text"))


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("language")))
async def language_button(message: Message, db: Database):
    await message.answer("🌐 Language / Мова / Язык", reply_markup=language_keyboard())


@router.message(Command("lang"))
async def lang_command(message: Message, db: Database, bot: Bot, config: Config):
    parts = (message.text or "").split()
    if len(parts) != 2 or parts[1].lower() not in LANGS:
        await message.answer("/lang ru | /lang uk | /lang en")
        return
    lang = parts[1].lower()
    if message.chat.type in {"group", "supergroup"}:
        if not await is_admin(bot, message.chat.id, message.from_user.id):
            await message.answer(t(lang_for_message(message, db), "admin_only"))
            return
        db.set_group_language(message.chat.id, lang)
        await message.answer(t(lang, "group_lang_changed"), reply_markup=main_menu(lang))
    else:
        db.set_user_language(message.from_user.id, lang)
        await message.answer(t(lang, "lang_changed"), reply_markup=main_menu(lang, message.from_user.id in set(config.admin_ids)))


@router.callback_query(F.data.startswith("lang:"))
async def lang_callback(call: CallbackQuery, db: Database, bot: Bot, config: Config):
    lang = call.data.split(":", 1)[1]
    if lang not in LANGS:
        await call.answer("Bad language", show_alert=True)
        return
    if call.message and call.message.chat.type in {"group", "supergroup"}:
        if not await is_admin(bot, call.message.chat.id, call.from_user.id):
            await call.answer(t(lang_for_callback(call, db), "admin_only"), show_alert=True)
            return
        db.set_group_language(call.message.chat.id, lang)
        await call.message.answer(t(lang, "group_lang_changed"), reply_markup=main_menu(lang))
    else:
        db.set_user_language(call.from_user.id, lang)
        await call.message.answer(t(lang, "lang_changed"), reply_markup=main_menu(lang, call.from_user.id in set(config.admin_ids)))
    await call.answer()


@router.message(Command("balance"))
@router.message(lambda m: bool(m.text and m.text.strip().lower() in {"б", "баланс", "b", "balance"}))
async def balance(message: Message, db: Database, economy: EconomyService):
    lang = lang_for_message(message, db)
    bal = economy.balance(message.from_user.id)
    await message.answer(t(lang, "balance", gentra=bal.gentra, galleons=bal.galleons))


def _is_profile_trigger(message: Message) -> bool:
    text = (message.text or "").strip()
    return text in all_texts("profile") or text.lower().startswith("/профиль")


@router.message(Command("profile"))
@router.message(_is_profile_trigger)
async def profile(message: Message, db: Database):
    lang = lang_for_message(message, db)
    row = db.get_user(message.from_user.id)
    with db.connect() as con:
        clan = con.execute("SELECT name FROM clans WHERE clan_id=?", (row["clan_id"],)).fetchone() if row["clan_id"] else None
    stats = sum(int(row[x]) for x in STAT_NAMES["en"].keys())
    vip = ""
    if row["vip_until"]:
        try:
            dt = datetime.fromisoformat(row["vip_until"])
            if dt > datetime.now(timezone.utc):
                vip = t(lang, "vip_line", until=dt.strftime("%Y-%m-%d %H:%M UTC"))
        except ValueError:
            pass
    await message.answer(
        t(
            lang,
            "profile_text",
            user_id=row["user_id"],
            gentra=int(row["gentra"]),
            galleons=int(row["galleons"]),
            stats=stats,
            clan=clan["name"] if clan else t(lang, "no_clan"),
            vip=vip,
        )
    )


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("hogwarts")))
async def stats_menu(message: Message, db: Database, economy: EconomyService):
    lang = lang_for_message(message, db)
    row = db.get_user(message.from_user.id)
    lines = []
    for stat, name in STAT_NAMES[lang].items():
        lines.append(f"• {name}: <b>{int(row[stat])}</b>")
    await message.answer(
        t(lang, "stats_title", rows="\n".join(lines)),
        reply_markup=stats_keyboard(lang, row, economy.stat_cost),
    )


@router.callback_query(F.data.startswith("stat:"))
async def stat_upgrade(call: CallbackQuery, db: Database, economy: EconomyService):
    lang = lang_for_callback(call, db)
    stat = call.data.split(":", 1)[1]
    if stat not in STAT_NAMES["en"]:
        await call.answer("Bad stat", show_alert=True)
        return
    try:
        level, cost = economy.upgrade_stat(call.from_user.id, stat, f"cb:{call.id}:stat")
    except InsufficientFunds:
        await call.answer(t(lang, "stat_no_money"), show_alert=True)
        return
    except DuplicateEvent:
        await call.answer()
        return
    row = db.get_user(call.from_user.id)
    lines = [f"• {name}: <b>{int(row[s])}</b>" for s, name in STAT_NAMES[lang].items()]
    await call.message.edit_text(
        t(lang, "stats_title", rows="\n".join(lines)),
        reply_markup=stats_keyboard(lang, row, economy.stat_cost),
    )
    await call.answer(t(lang, "stat_upgraded", name=STAT_NAMES[lang][stat], level=level, cost=cost))


@router.message(Command("history"))
@router.message(lambda m: bool(m.text and m.text.strip().lower().startswith("/история")))
async def history(message: Message, db: Database, economy: EconomyService, duels: DuelService):
    lang = lang_for_message(message, db)
    ops = economy.recent_operations(message.from_user.id, 10)
    duel_rows = duels.history(message.from_user.id, 5)
    if not ops and not duel_rows:
        await message.answer(t(lang, "history_empty"))
        return
    lines = [t(lang, "history_ops")]
    for row in ops:
        dg = int(row["gentra_delta"])
        dga = int(row["galleons_delta"])
        delta = f"G {dg:+,}" if dg else f"🪙 {dga:+,}"
        lines.append(f"• {row['kind']}: {delta}")
    if duel_rows:
        lines.append("\n" + t(lang, "history_duels"))
        for d in duel_rows:
            if d["status"] == "resolved":
                lines.append(f"• {d['challenger_id']} vs {d['opponent_id']} → {d['winner_id']}")
            else:
                lines.append(f"• {d['challenger_id']} vs {d['opponent_id']} → {d['status']}")
    await message.answer("\n".join(lines))


@router.message(Command("top"))
async def top(message: Message, db: Database, economy: EconomyService):
    lang = lang_for_message(message, db)
    parts = (message.text or "").split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 10
    except ValueError:
        limit = 10
    rows = economy.leaderboard(limit)
    lines = [t(lang, "top_title")]
    for i, row in enumerate(rows, start=1):
        name = row["username"] and f"@{row['username']}" or row["first_name"] or str(row["user_id"])
        lines.append(f"{i}. {name} — <b>{int(row['gentra']):,}</b>")
    await message.answer("\n".join(lines))


def parse_transfer(message: Message):
    text = (message.text or "").strip()
    parts = text.split()
    if not parts or parts[0].lower() not in {"п", "p"}:
        return None
    if message.reply_to_message and len(parts) == 2:
        try:
            return int(message.reply_to_message.from_user.id), int(parts[1])
        except (TypeError, ValueError):
            return None
    if len(parts) == 3:
        try:
            return int(parts[1]), int(parts[2])
        except ValueError:
            return None
    return None


@router.message(lambda m: bool(parse_transfer(m)))
async def transfer(message: Message, db: Database, economy: EconomyService):
    lang = lang_for_message(message, db)
    target, amount = parse_transfer(message)
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        db.ensure_user(u.id, u.username, u.first_name)
    try:
        economy.transfer(message.from_user.id, target, amount, f"msg:{message.chat.id}:{message.message_id}:transfer")
    except InvalidAmount:
        await message.answer(t(lang, "invalid_amount")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    except SelfTransfer:
        await message.answer(t(lang, "self_transfer")); return
    except UserNotFound:
        await message.answer(t(lang, "user_missing")); return
    except DuplicateEvent:
        return
    await message.answer(t(lang, "transfer_ok", amount=amount, target=target))


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("games")))
async def games_help(message: Message, db: Database):
    await message.answer(t(lang_for_message(message, db), "games_help"))


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("chats")))
async def chats(message: Message, db: Database, config: Config, bot: Bot):
    lang = lang_for_message(message, db)
    me = await bot.get_me()
    add_group = f"https://t.me/{me.username}?startgroup=true"
    news = db.get_setting("NEWS_URL", config.news_url)
    general = db.get_setting("GENERAL_CHAT_URL", config.general_chat_url)
    roulette = db.get_setting("ROULETTE_CHAT_URL", config.roulette_chat_url)
    await message.answer(t(lang, "chats_text", news=news, general=general, roulette=roulette, add_group=add_group), disable_web_page_preview=True)
