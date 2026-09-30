from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.db import Database
from app.i18n import t
from app.routers.common import is_admin, lang_for_message
from app.services.economy import DuplicateEvent, InsufficientFunds
from app.services.treasury import TreasuryInsufficient, TreasuryRewardRange, TreasuryService

router = Router(name="groups")


def parse_treasury(text: str | None):
    parts = (text or "").strip().lower().split()
    if not parts or parts[0] not in {"казна", "treasury"}:
        return None
    if len(parts) == 1:
        return ("show", None)
    if len(parts) == 2:
        try:
            return ("deposit", int(parts[1]))
        except ValueError:
            return ("bad", None)
    return None


def parse_reward(text: str | None):
    parts = (text or "").strip().lower().split()
    if len(parts) != 2 or parts[0] not in {"награда", "reward"}:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return -1


@router.message(lambda m: parse_treasury(m.text) is not None)
async def treasury_command(message: Message, db: Database, treasury: TreasuryService):
    lang = lang_for_message(message, db)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "private_only")); return
    action, amount = parse_treasury(message.text)
    if action == "show":
        row = treasury.get(message.chat.id)
        await message.answer(t(lang, "treasury_status", balance=int(row["balance"]), reward=int(row["reward_amount"])))
        return
    if action == "bad" or amount is None or amount <= 0:
        await message.answer(t(lang, "invalid_amount")); return
    try:
        row = treasury.deposit(message.chat.id, message.from_user.id, amount, f"msg:{message.chat.id}:{message.message_id}:treasury")
    except InsufficientFunds:
        await message.answer(t(lang, "not_enough")); return
    except DuplicateEvent:
        return
    await message.answer(t(lang, "treasury_added", amount=amount) + "\n" + t(lang, "treasury_status", balance=int(row["balance"]), reward=int(row["reward_amount"])))


@router.message(lambda m: parse_reward(m.text) is not None)
async def reward_command(message: Message, db: Database, treasury: TreasuryService, bot: Bot):
    lang = lang_for_message(message, db)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "private_only")); return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer(t(lang, "admin_only")); return
    amount = parse_reward(message.text)
    try:
        treasury.set_reward(message.chat.id, amount)
    except TreasuryRewardRange:
        await message.answer(t(lang, "treasury_range", min=treasury.config.treasury_reward_min, max=treasury.config.treasury_reward_max))
        return
    await message.answer(t(lang, "treasury_reward_set", amount=amount))


@router.message(F.new_chat_members)
async def new_members(message: Message, db: Database, treasury: TreasuryService):
    lang = lang_for_message(message, db)
    inviter = message.from_user
    if not inviter:
        return
    for member in message.new_chat_members:
        db.ensure_user(member.id, member.username, member.first_name)
        db.touch_chat_user(message.chat.id, member.id, message.chat.title or "")
        if member.id == inviter.id or member.is_bot:
            continue
        try:
            paid = treasury.reward_inviter_once(message.chat.id, member.id, inviter.id)
        except TreasuryInsufficient:
            paid = 0
        if paid:
            await message.answer(t(lang, "treasury_reward_paid", amount=paid))
