from __future__ import annotations

import math

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.db import Database
from app.i18n import all_texts, t
from app.keyboards import (
    clan_card_keyboard,
    clan_invite_keyboard,
    clan_join_confirm_keyboard,
    clan_menu_keyboard,
)
from app.routers.common import lang_for_callback, lang_for_message
from app.services.clans import (
    ClanAlreadyIn,
    ClanExists,
    ClanFull,
    ClanInviteInvalid,
    ClanNameError,
    ClanNotIn,
    ClanPermission,
    ClanService,
)
from app.services.economy import InsufficientFunds

router = Router(name="clans")


def card_text(lang: str, row, config: Config) -> str:
    deputy = f"<code>{row['deputy_id']}</code>" if row["deputy_id"] else "—"
    return t(
        lang,
        "clan_card",
        name=row["name"],
        owner=row["owner_id"],
        deputy=deputy,
        treasury=int(row["treasury"]),
        members=int(row["members"]),
        limit=config.clan_member_limit,
    )


@router.message(Command("clans"))
@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("clans")))
async def clans_menu(message: Message, db: Database):
    lang = lang_for_message(message, db)
    await message.answer(t(lang, "clan_menu"), reply_markup=clan_menu_keyboard(lang))


@router.message(Command("clan_create"))
async def clan_create(message: Message, db: Database, clans: ClanService, config: Config):
    lang = lang_for_message(message, db)
    name = (message.text or "").partition(" ")[2].strip()
    if not name:
        await message.answer("/clan_create Name"); return
    try:
        clan = clans.create(message.from_user.id, name, f"msg:{message.chat.id}:{message.message_id}:clancreate")
    except ClanNameError:
        await message.answer(t(lang, "clan_name_bad")); return
    except ClanExists:
        await message.answer(t(lang, "clan_exists")); return
    except ClanAlreadyIn:
        await message.answer(t(lang, "clan_already")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    await message.answer(t(lang, "clan_created", name=clan["name"], cost=config.clan_create_cost))


@router.message(Command("clan_invite"))
async def clan_invite(message: Message, db: Database, clans: ClanService, bot: Bot):
    lang = lang_for_message(message, db)
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Reply: /clan_invite"); return
    u = message.reply_to_message.from_user
    db.ensure_user(u.id, u.username, u.first_name)
    try:
        invite, clan = clans.invite(message.from_user.id, u.id)
    except ClanPermission:
        await message.answer(t(lang, "clan_permission")); return
    except ClanAlreadyIn:
        await message.answer(t(lang, "clan_already")); return
    except ClanFull:
        await message.answer(t(lang, "clan_full")); return
    await message.answer(t(lang, "clan_invite_sent"))
    try:
        user_lang = db.get_user_language(u.id)
        await bot.send_message(
            u.id,
            t(user_lang, "clan_invite_received", name=clan["name"]),
            reply_markup=clan_invite_keyboard(int(invite["invite_id"])),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("clan:invite:accept:"))
async def invite_accept(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    invite_id = int(call.data.rsplit(":", 1)[1])
    try:
        clan = clans.accept_invite(invite_id, call.from_user.id)
    except ClanInviteInvalid:
        await call.answer(t(lang, "clan_invite_invalid"), show_alert=True); return
    except ClanAlreadyIn:
        await call.answer(t(lang, "clan_already"), show_alert=True); return
    except ClanFull:
        await call.answer(t(lang, "clan_full"), show_alert=True); return
    await call.message.edit_text(t(lang, "clan_joined", name=clan["name"]))
    await call.answer()


@router.callback_query(F.data.startswith("clan:invite:decline:"))
async def invite_decline(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    invite_id = int(call.data.rsplit(":", 1)[1])
    try:
        clans.decline_invite(invite_id, call.from_user.id)
    except ClanInviteInvalid:
        await call.answer(t(lang, "clan_invite_invalid"), show_alert=True); return
    await call.message.edit_text(t(lang, "clan_invite_declined"))
    await call.answer()


@router.callback_query(F.data == "clan:invites")
async def my_invites(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    rows = clans.pending_invites(call.from_user.id)
    if not rows:
        await call.message.answer(t(lang, "clan_no_invites"))
        await call.answer(); return
    for row in rows:
        await call.message.answer(
            t(lang, "clan_invite_received", name=row["name"]),
            reply_markup=clan_invite_keyboard(int(row["invite_id"])),
        )
    await call.answer()


@router.callback_query(F.data == "clan:mine")
async def my_clan(call: CallbackQuery, db: Database, clans: ClanService, config: Config):
    lang = lang_for_callback(call, db)
    clan = clans.user_clan(call.from_user.id)
    if not clan:
        await call.answer(t(lang, "clan_none"), show_alert=True); return
    card = clans.card(int(clan["clan_id"]))
    await call.message.answer(card_text(lang, card, config), reply_markup=clan_card_keyboard(int(card["clan_id"]), lang, can_join=False))
    await call.answer()


@router.callback_query(F.data.startswith("clan:list:"))
async def clan_list(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    page = max(0, int(call.data.rsplit(":", 1)[1]))
    rows, total = clans.list_clans(page)
    kb = []
    for row in rows:
        kb.append([InlineKeyboardButton(text=f"🏰 {row['name']} · {row['members']}", callback_data=f"clan:card:{row['clan_id']}")])
    pages = max(1, math.ceil(total / 8))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"clan:list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"clan:list:{page+1}"))
    kb.append(nav)
    text = t(lang, "clan_list_title") if rows else t(lang, "clan_no_search")
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data.startswith("clan:card:"))
async def clan_card(call: CallbackQuery, db: Database, clans: ClanService, config: Config):
    lang = lang_for_callback(call, db)
    clan_id = int(call.data.rsplit(":", 1)[1])
    row = clans.card(clan_id)
    if not row:
        await call.answer(t(lang, "clan_not_found"), show_alert=True); return
    can_join = clans.user_clan(call.from_user.id) is None
    await call.message.edit_text(card_text(lang, row, config), reply_markup=clan_card_keyboard(clan_id, lang, can_join=can_join))
    await call.answer()


@router.callback_query(F.data.startswith("clan:joinask:"))
async def clan_join_ask(call: CallbackQuery, db: Database):
    clan_id = int(call.data.rsplit(":", 1)[1])
    lang = lang_for_callback(call, db)
    await call.message.edit_reply_markup(reply_markup=clan_join_confirm_keyboard(clan_id, lang))
    await call.answer(t(lang, "clan_confirm_join"))


@router.callback_query(F.data.startswith("clan:join:"))
async def clan_join(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    clan_id = int(call.data.rsplit(":", 1)[1])
    try:
        clan = clans.join_open(clan_id, call.from_user.id)
    except ClanAlreadyIn:
        await call.answer(t(lang, "clan_already"), show_alert=True); return
    except (ClanFull, ClanInviteInvalid):
        await call.answer(t(lang, "clan_unavailable"), show_alert=True); return
    await call.message.edit_text(t(lang, "clan_joined", name=clan["name"]))
    await call.answer()


@router.callback_query(F.data == "clan:top")
async def clan_top(call: CallbackQuery, db: Database, clans: ClanService):
    lang = lang_for_callback(call, db)
    rows = clans.top()
    lines = [t(lang, "clan_top_title")]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {row['name']} — {int(row['treasury']):,} GENTRA · {row['members']} {t(lang, 'clan_members_word')}")
    await call.message.edit_text("\n".join(lines))
    await call.answer()


@router.message(Command("clan_search"))
async def clan_search(message: Message, db: Database, clans: ClanService):
    query = (message.text or "").partition(" ")[2].strip()
    if not query:
        await message.answer("/clan_search name"); return
    rows = clans.search(query)
    if not rows:
        await message.answer(t(lang_for_message(message, db), "clan_no_search")); return
    lang = lang_for_message(message, db)
    kb = [[InlineKeyboardButton(text=f"🏰 {r['name']}", callback_data=f"clan:card:{r['clan_id']}")] for r in rows]
    await message.answer(t(lang, "clan_search_results"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.message(Command("clan_leave"))
async def clan_leave(message: Message, db: Database, clans: ClanService):
    lang = lang_for_message(message, db)
    try:
        clans.leave(message.from_user.id)
    except ClanNotIn:
        await message.answer(t(lang, "clan_none")); return
    await message.answer(t(lang, "clan_left"))


@router.message(Command("clan_deputy"))
async def clan_deputy(message: Message, db: Database, clans: ClanService):
    lang = lang_for_message(message, db)
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Reply: /clan_deputy"); return
    u = message.reply_to_message.from_user
    db.ensure_user(u.id, u.username, u.first_name)
    try:
        clans.set_deputy(message.from_user.id, u.id)
    except ClanPermission:
        await message.answer(t(lang, "clan_permission")); return
    await message.answer(t(lang, "clan_deputy_set"))


@router.message(Command("clan_kick"))
async def clan_kick(message: Message, db: Database, clans: ClanService):
    lang = lang_for_message(message, db)
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Reply: /clan_kick"); return
    try:
        clans.kick(message.from_user.id, message.reply_to_message.from_user.id)
    except ClanPermission:
        await message.answer(t(lang, "clan_permission")); return
    await message.answer(t(lang, "clan_member_removed"))


@router.message(Command("clan_treasury"))
async def clan_treasury(message: Message, db: Database, clans: ClanService):
    lang = lang_for_message(message, db)
    parts = (message.text or "").split()
    try:
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await message.answer(t(lang, "invalid_amount")); return
    try:
        clans.deposit(message.from_user.id, amount, f"msg:{message.chat.id}:{message.message_id}:clantreasury")
    except ClanNotIn:
        await message.answer(t(lang, "clan_none")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    await message.answer(t(lang, "clan_treasury_added", amount=amount))
