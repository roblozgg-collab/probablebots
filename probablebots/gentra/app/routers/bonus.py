from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db import Database
from app.i18n import all_texts, t
from app.routers.common import lang_for_message
from app.services.bonus import BonusCooldown, BonusService
from app.services.economy import DuplicateEvent

router = Router(name="bonus")


async def claim_bonus(message: Message, db: Database, bonus: BonusService) -> None:
    lang = lang_for_message(message, db)
    if message.chat.type != "private":
        await message.answer(t(lang, "private_only"))
        return
    try:
        amount = bonus.claim(
            message.from_user.id,
            f"msg:{message.chat.id}:{message.message_id}:bonus",
        )
    except BonusCooldown:
        await message.answer(t(lang, "bonus_wait"))
        return
    except DuplicateEvent:
        return
    await message.answer(t(lang, "bonus_claimed", amount=amount))


@router.message(Command("bonus"))
@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("bonus")))
async def bonus_start(message: Message, db: Database, bonus: BonusService):
    await claim_bonus(message, db, bonus)
