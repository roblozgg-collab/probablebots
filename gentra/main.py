from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import load_config
from app.db import Database
from app.middleware import BlockedAccessMiddleware, RateLimitMiddleware, UserContextMiddleware
from app.routers import admin, bonus, clans, common, games, groups, payments, tournaments
from app.scheduler import scheduler_loop
from app.services.bonus import BonusService
from app.services.clans import ClanService
from app.services.duels import DuelService
from app.services.economy import EconomyService
from app.services.joker import JokerService
from app.services.mines import MinesService
from app.services.payments import PaymentService
from app.services.roulette import RouletteService
from app.services.tournaments import TournamentService
from app.services.treasury import TreasuryService


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    config = load_config()
    db = Database(config.db_path, config)
    db.init()

    economy = EconomyService(db, config)
    roulette = RouletteService(db, config, economy)
    mines = MinesService(db, config, economy)
    joker = JokerService(db, config, economy)
    duels = DuelService(db, config, economy)
    clans_service = ClanService(db, config, economy)
    tournaments_service = TournamentService(db, config, economy)
    treasury = TreasuryService(db, config, economy)
    bonus_service = BonusService(db, config, economy)
    payment_service = PaymentService(db, config, economy)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    user_mw = UserContextMiddleware(db)
    blocked_mw = BlockedAccessMiddleware(db, config)
    rate_mw = RateLimitMiddleware()
    dp.message.outer_middleware(user_mw)
    dp.message.outer_middleware(blocked_mw)
    dp.message.outer_middleware(rate_mw)
    dp.callback_query.outer_middleware(user_mw)
    dp.callback_query.outer_middleware(blocked_mw)
    dp.callback_query.outer_middleware(rate_mw)
    dp.pre_checkout_query.outer_middleware(blocked_mw)

    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(clans.router)
    dp.include_router(tournaments.router)
    dp.include_router(groups.router)
    dp.include_router(payments.router)
    dp.include_router(bonus.router)
    dp.include_router(games.router)

    workflow = {
        "db": db,
        "config": config,
        "economy": economy,
        "roulette": roulette,
        "mines": mines,
        "joker": joker,
        "duels": duels,
        "clans": clans_service,
        "tournaments": tournaments_service,
        "treasury": treasury,
        "bonus": bonus_service,
        "payments": payment_service,
    }

    await bot.set_my_commands([
        BotCommand(command="start", description="Open gentra"),
        BotCommand(command="profile", description="Profile"),
        BotCommand(command="balance", description="Balance"),
        BotCommand(command="history", description="History"),
        BotCommand(command="top", description="Balance top"),
        BotCommand(command="duel", description="Duel in group"),
        BotCommand(command="clans", description="Clans"),
        BotCommand(command="tournaments", description="Tournaments"),
        BotCommand(command="lang", description="Language ru/uk/en"),
        BotCommand(command="help", description="Help"),
    ])

    bg = asyncio.create_task(scheduler_loop(bot, db, roulette, tournaments_service))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), **workflow)
    finally:
        bg.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bg
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
