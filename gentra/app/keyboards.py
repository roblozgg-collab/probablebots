from __future__ import annotations

import json

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.i18n import STAT_NAMES, t


def main_menu(lang: str, admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t(lang, "profile")), KeyboardButton(text=t(lang, "hogwarts"))],
        [KeyboardButton(text=t(lang, "commands")), KeyboardButton(text=t(lang, "donate"))],
        [KeyboardButton(text=t(lang, "tournaments")), KeyboardButton(text=t(lang, "chats"))],
        [KeyboardButton(text=t(lang, "clans")), KeyboardButton(text=t(lang, "games"))],
        [KeyboardButton(text=t(lang, "bonus")), KeyboardButton(text=t(lang, "policy"))],
        [KeyboardButton(text=t(lang, "language"))],
    ]
    if admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang:uk")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])


def stats_keyboard(lang: str, user_row, cost_fn) -> InlineKeyboardMarkup:
    rows = []
    for stat, label in STAT_NAMES[lang if lang in STAT_NAMES else "ru"].items():
        level = int(user_row[stat])
        cost = cost_fn(level)
        rows.append([InlineKeyboardButton(text=f"{label}: {level} → +1 ({cost} 🪙)", callback_data=f"stat:{stat}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def duel_keyboard(duel_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ 
        InlineKeyboardButton(text=t(lang, "duel_accept"), callback_data=f"duel:accept:{duel_id}"),
        InlineKeyboardButton(text=t(lang, "duel_decline"), callback_data=f"duel:decline:{duel_id}"),
    ]])


def mines_keyboard(game_row, lang: str = "ru", reveal_all: bool = False) -> InlineKeyboardMarkup:
    revealed = set(json.loads(game_row["revealed_json"]))
    mines = set(json.loads(game_row["mines_json"]))
    rows, cols = int(game_row["rows"]), int(game_row["cols"])
    kb = []
    for r in range(rows):
        line = []
        for c in range(cols):
            idx = r * cols + c
            if idx in revealed:
                text = "✅"
            elif reveal_all and idx in mines:
                text = "💣"
            elif reveal_all:
                text = "▫️"
            else:
                text = "⬜"
            line.append(InlineKeyboardButton(text=text, callback_data=f"mine:{game_row['game_id']}:{idx}"))
        kb.append(line)
    if game_row["status"] == "active":
        kb.append([InlineKeyboardButton(text=t(lang, "cashout"), callback_data=f"minecash:{game_row['game_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def joker_keyboard(game_row) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"🂠 {i+1}", callback_data=f"joker:{game_row['game_id']}:{i}") for i in range(int(game_row["slots"]))]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def blackjack_keyboard(game_id: str, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "blackjack_hit_button"), callback_data=f"blackjack:hit:{game_id}"),
        InlineKeyboardButton(text=t(lang, "blackjack_stand_button"), callback_data=f"blackjack:stand:{game_id}"),
    ]])


def clan_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "clan_my_button"), callback_data="clan:mine")],
        [InlineKeyboardButton(text=t(lang, "clan_invites_button"), callback_data="clan:invites")],
        [InlineKeyboardButton(text=t(lang, "clan_list_button"), callback_data="clan:list:0")],
        [InlineKeyboardButton(text=t(lang, "clan_top_button"), callback_data="clan:top")],
    ])


def clan_invite_keyboard(invite_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ 
        InlineKeyboardButton(text="✅", callback_data=f"clan:invite:accept:{invite_id}"),
        InlineKeyboardButton(text="❌", callback_data=f"clan:invite:decline:{invite_id}"),
    ]])


def clan_card_keyboard(clan_id: int, lang: str = "ru", can_join: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if can_join:
        rows.append([InlineKeyboardButton(text=t(lang, "clan_join_button"), callback_data=f"clan:joinask:{clan_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="clan:list:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_join_confirm_keyboard(clan_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ 
        InlineKeyboardButton(text=t(lang, "clan_confirm_button"), callback_data=f"clan:join:{clan_id}"),
        InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"clan:card:{clan_id}"),
    ]])


def tournament_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "tour_players"), callback_data="tour:players:current")],
        [InlineKeyboardButton(text=t(lang, "tour_chats"), callback_data="tour:chats:current")],
        [InlineKeyboardButton(text=t(lang, "tour_previous"), callback_data="tour:players:previous")],
    ])


def donate_keyboard(products: dict[str, tuple[int, int]]) -> InlineKeyboardMarkup:
    rows = []
    for code, (stars, gentra) in products.items():
        if code == "vip":
            label = f"⭐ VIP — {stars} Stars"
        else:
            label = f"{stars} ⭐ → {gentra:,} GENTRA"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"buy:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
