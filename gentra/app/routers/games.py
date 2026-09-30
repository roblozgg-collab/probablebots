from __future__ import annotations

import json
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db import Database
from app.i18n import t
from app.keyboards import duel_keyboard, joker_keyboard, mines_keyboard
from app.routers.common import lang_for_callback, lang_for_message
from app.services.duels import (
    DuelCooldown,
    DuelNotFound,
    DuelNotPending,
    DuelSelf,
    DuelService,
    DuelWrongUser,
)
from app.services.economy import DuplicateEvent, InsufficientFunds, InvalidAmount
from app.services.joker import JokerService
from app.services.mines import GameFinished, GameNotFound, GameNotYours, MinesService, NeedSafeCell
from app.services.roulette import (
    NoBets,
    NoPreviousBets,
    RoundClosed,
    RouletteService,
    color_of,
    parse_bet_target,
)

router = Router(name="games")


def parse_prefixed_amount(text: str | None, prefixes: set[str]):
    parts = (text or "").strip().lower().split()
    if len(parts) != 2 or parts[0] not in prefixes:
        return None
    try:
        amount = int(parts[1].replace("_", ""))
        return amount
    except ValueError:
        return None


def parse_roulette_message(message: Message):
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        amount = int(parts[0].replace("_", ""))
    except ValueError:
        return None
    spec = parse_bet_target(parts[1])
    if not spec:
        return None
    return amount, spec


@router.message(lambda m: parse_prefixed_amount(m.text, {"мины", "міни", "mines"}) is not None)
async def start_mines(message: Message, db: Database, mines: MinesService):
    lang = lang_for_message(message, db)
    bet = parse_prefixed_amount(message.text, {"мины", "міни", "mines"})
    try:
        row = mines.start(message.from_user.id, message.chat.id, bet, f"msg:{message.chat.id}:{message.message_id}:mines")
    except InvalidAmount:
        await message.answer(t(lang, "invalid_amount")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    except DuplicateEvent:
        return
    await message.answer(
        t(lang, "mines_started", bet=int(row["bet"]), safe=0, potential=int(row["bet"])),
        reply_markup=mines_keyboard(row, lang),
    )


@router.callback_query(F.data.startswith("mine:"))
async def mine_cell(call: CallbackQuery, db: Database, mines: MinesService):
    lang = lang_for_callback(call, db)
    _, game_id, idx_s = call.data.split(":", 2)
    try:
        result = mines.open_cell(game_id, call.from_user.id, int(idx_s), f"cb:{call.id}:mine")
    except GameNotYours:
        await call.answer(t(lang, "game_not_yours"), show_alert=True); return
    except (GameNotFound, GameFinished):
        await call.answer(t(lang, "game_finished"), show_alert=True); return
    state, row = result["state"], result["game"]
    if state == "mine":
        await call.message.edit_text(t(lang, "mines_lost", bet=int(row["bet"])), reply_markup=mines_keyboard(row, lang, reveal_all=True))
    elif state == "complete":
        await call.message.edit_text(t(lang, "mines_cashout", payout=int(row["payout"])), reply_markup=mines_keyboard(row, lang, reveal_all=True))
    else:
        safe = len(json.loads(row["revealed_json"]))
        potential = mines.potential(int(row["bet"]), safe, int(row["mines_count"]))
        await call.message.edit_text(
            t(lang, "mines_started", bet=int(row["bet"]), safe=safe, potential=potential),
            reply_markup=mines_keyboard(row, lang),
        )
    await call.answer()


@router.callback_query(F.data.startswith("minecash:"))
async def mine_cashout(call: CallbackQuery, db: Database, mines: MinesService):
    lang = lang_for_callback(call, db)
    game_id = call.data.split(":", 1)[1]
    try:
        payout = mines.cashout(game_id, call.from_user.id, f"cb:{call.id}:cash")
    except GameNotYours:
        await call.answer(t(lang, "game_not_yours"), show_alert=True); return
    except NeedSafeCell:
        await call.answer(t(lang, "mines_need_open"), show_alert=True); return
    except (GameNotFound, GameFinished, DuplicateEvent):
        await call.answer(t(lang, "game_finished"), show_alert=True); return
    row = mines.get(game_id)
    await call.message.edit_text(t(lang, "mines_cashout", payout=payout), reply_markup=mines_keyboard(row, lang, reveal_all=True))
    await call.answer()


@router.message(lambda m: parse_prefixed_amount(m.text, {"джокер", "joker"}) is not None)
async def start_joker(message: Message, db: Database, joker: JokerService):
    lang = lang_for_message(message, db)
    bet = parse_prefixed_amount(message.text, {"джокер", "joker"})
    try:
        row = joker.start(message.from_user.id, message.chat.id, bet, f"msg:{message.chat.id}:{message.message_id}:joker")
    except InvalidAmount:
        await message.answer(t(lang, "invalid_amount")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    except DuplicateEvent:
        return
    await message.answer(
        t(lang, "joker_started", bet=int(row["bet"]), slots=int(row["slots"]), multiplier=float(row["multiplier"])),
        reply_markup=joker_keyboard(row),
    )


@router.callback_query(F.data.startswith("joker:"))
async def joker_choose(call: CallbackQuery, db: Database, joker: JokerService):
    lang = lang_for_callback(call, db)
    _, game_id, pos_s = call.data.split(":", 2)
    try:
        win, payout, joker_pos = joker.choose(game_id, call.from_user.id, int(pos_s), f"cb:{call.id}:joker")
    except GameNotYours:
        await call.answer(t(lang, "game_not_yours"), show_alert=True); return
    except (GameNotFound, GameFinished, DuplicateEvent):
        await call.answer(t(lang, "game_finished"), show_alert=True); return
    row = joker.get(game_id)
    if win:
        text = t(lang, "joker_win", payout=payout)
    else:
        text = t(lang, "joker_lose", bet=int(row["bet"]))
    text += f"\nJoker: 🃏 #{joker_pos + 1}"
    await call.message.edit_text(text)
    await call.answer()


ACTION_ALIASES = {
    "bets": {"ставки", "ставки!", "bets"},
    "cancel": {"отменить", "скасувати", "cancel"},
    "double": {"удвоить", "подвоїти", "double"},
    "repeat": {"повторить", "повторити", "repeat"},
}


def roulette_action(message: Message) -> str | None:
    s = (message.text or "").strip().lower()
    for action, aliases in ACTION_ALIASES.items():
        if s in aliases:
            return action
    return None


def is_roulette_log(message: Message) -> bool:
    return (message.text or "").strip().lower() in {"лог", "log", "/лог"}


@router.message(Command("log"))
@router.message(lambda m: is_roulette_log(m))
async def roulette_log(message: Message, db: Database, roulette: RouletteService):
    lang = lang_for_message(message, db)
    numbers = roulette.recent_results(message.chat.id)
    if not numbers:
        await message.answer(t(lang, "roulette_log_empty"))
        return
    symbols = {"red": "🔴", "black": "⚫", "green": "🟢"}
    rows = "\n".join(f"{number} {symbols[color_of(number)]}" for number in numbers)
    await message.answer(t(lang, "roulette_log", count=len(numbers), rows=rows))


@router.message(lambda m: roulette_action(m) is not None)
async def roulette_actions(message: Message, db: Database, roulette: RouletteService):
    lang = lang_for_message(message, db)
    action = roulette_action(message)
    key = f"msg:{message.chat.id}:{message.message_id}:roulette:{action}"
    try:
        if action == "bets":
            rr, bets = roulette.current_user_bets(message.chat.id, message.from_user.id)
            if not rr or not bets:
                await message.answer(t(lang, "roulette_bets_none")); return
            rows = [f"• {int(b['amount']):,} → {b['bet_value']}" for b in bets]
            total = sum(int(b["amount"]) for b in bets)
            await message.answer(t(lang, "roulette_bets", round_id=rr["id"], rows="\n".join(rows), total=total)); return
        if action == "cancel":
            amount = roulette.cancel(message.chat.id, message.from_user.id, key)
            await message.answer(t(lang, "roulette_cancelled", amount=amount)); return
        if action == "double":
            amount = roulette.double(message.chat.id, message.from_user.id, key)
            await message.answer(t(lang, "roulette_doubled", amount=amount)); return
        if action == "repeat":
            _, amount = roulette.repeat(message.chat.id, message.from_user.id, key)
            await message.answer(t(lang, "roulette_repeated", amount=amount)); return
    except NoBets:
        await message.answer(t(lang, "roulette_bets_none"))
    except NoPreviousBets:
        await message.answer(t(lang, "roulette_no_previous"))
    except RoundClosed:
        await message.answer(t(lang, "roulette_closed"))
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough"))
    except DuplicateEvent:
        return


@router.message(lambda m: parse_roulette_message(m) is not None)
async def roulette_bet(message: Message, db: Database, roulette: RouletteService):
    lang = lang_for_message(message, db)
    amount, spec = parse_roulette_message(message)
    try:
        rr = roulette.place_bet(
            message.chat.id,
            message.from_user.id,
            amount,
            spec,
            f"msg:{message.chat.id}:{message.message_id}:roulette:bet",
        )
    except InvalidAmount:
        await message.answer(t(lang, "invalid_amount")); return
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    except RoundClosed:
        await message.answer(t(lang, "roulette_closed")); return
    except DuplicateEvent:
        return
    closes = datetime.fromisoformat(rr["closes_at"])
    seconds = max(0, int((closes - datetime.now(timezone.utc)).total_seconds()))
    await message.answer(t(lang, "roulette_bet_ok", amount=amount, label=spec.label, round_id=rr["id"], seconds=seconds))


def is_duel_text(message: Message) -> bool:
    s = (message.text or "").strip().lower()
    return s in {"дуэль", "дуель", "duel"}


@router.message(Command("duel"))
@router.message(lambda m: is_duel_text(m))
async def duel_start(message: Message, db: Database, duels: DuelService):
    lang = lang_for_message(message, db)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "private_only")); return
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        db.ensure_user(target_user.id, target_user.username, target_user.first_name)
        opponent = target_user.id
    else:
        opponent = duels.random_opponent(message.chat.id, message.from_user.id)
        if not opponent:
            await message.answer(t(lang, "duel_no_opponent")); return
    try:
        duel = duels.challenge(message.chat.id, message.from_user.id, opponent)
    except DuelSelf:
        await message.answer(t(lang, "duel_self")); return
    except DuelCooldown:
        await message.answer(t(lang, "duel_cooldown")); return
    a = display_user(db, message.from_user.id)
    b = display_user(db, opponent)
    await message.answer(
        t(lang, "duel_incoming", challenger=a, opponent=b, reward=duels.config.duel_reward),
        reply_markup=duel_keyboard(duel["duel_id"], lang),
    )


def display_user(db: Database, user_id: int) -> str:
    row = db.get_user(user_id)
    if not row:
        return f"<code>{user_id}</code>"
    if row["username"]:
        return f"@{row['username']}"
    return row["first_name"] or f"<code>{user_id}</code>"


@router.callback_query(F.data.startswith("duel:accept:"))
async def duel_accept(call: CallbackQuery, db: Database, duels: DuelService):
    lang = lang_for_callback(call, db)
    duel_id = call.data.rsplit(":", 1)[1]
    try:
        result = duels.accept(duel_id, call.from_user.id)
    except DuelWrongUser:
        await call.answer(t(lang, "duel_wrong_user"), show_alert=True); return
    except DuelCooldown:
        await call.answer(t(lang, "duel_cooldown"), show_alert=True); return
    except (DuelNotFound, DuelNotPending):
        await call.answer(t(lang, "game_finished"), show_alert=True); return
    a_id, b_id = int(result["challenger_id"]), int(result["opponent_id"])
    await call.message.edit_text(
        t(
            lang,
            "duel_result",
            a=display_user(db, a_id),
            a_score=result["challenger_score"],
            b=display_user(db, b_id),
            b_score=result["opponent_score"],
            winner=display_user(db, int(result["winner_id"])),
            reward=duels.config.duel_reward,
        )
    )
    await call.answer()


@router.callback_query(F.data.startswith("duel:decline:"))
async def duel_decline(call: CallbackQuery, db: Database, duels: DuelService):
    lang = lang_for_callback(call, db)
    duel_id = call.data.rsplit(":", 1)[1]
    try:
        duels.decline(duel_id, call.from_user.id)
    except DuelWrongUser:
        await call.answer(t(lang, "duel_wrong_user"), show_alert=True); return
    except (DuelNotFound, DuelNotPending):
        await call.answer(t(lang, "game_finished"), show_alert=True); return
    await call.message.edit_text(t(lang, "duel_declined"))
    await call.answer()
