from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from app.db import Database
from app.i18n import t
from app.services.roulette import RouletteService
from app.services.tournaments import TournamentService

log = logging.getLogger(__name__)


async def settle_due(bot: Bot, db: Database, roulette: RouletteService) -> None:
    rows = await asyncio.to_thread(roulette.due_rounds)
    for row in rows:
        try:
            result = await asyncio.to_thread(roulette.settle_round, int(row["id"]))
        except Exception:
            log.exception("Failed to settle roulette round %s", row["id"])
            continue
        if not result:
            continue
        lang = db.get_group_language(result["chat_id"])
        try:
            await bot.send_message(
                result["chat_id"],
                t(
                    lang,
                    "roulette_result",
                    round_id=result["round_id"],
                    number=result["number"],
                    color=t(lang, f"color_{result["color"]}"),
                    bets=result["bets"],
                    payout=result["payout"],
                ),
            )
        except Exception:
            log.exception("Failed to publish roulette result to chat %s", result["chat_id"])


async def scheduler_loop(bot: Bot, db: Database, roulette: RouletteService, tournaments: TournamentService) -> None:
    await settle_due(bot, db, roulette)
    try:
        await asyncio.to_thread(tournaments.finalize_all_pending)
    except Exception:
        log.exception("Tournament recovery failed")

    last_tournament_check = ""
    while True:
        try:
            await settle_due(bot, db, roulette)
            minute_key = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
            if minute_key != last_tournament_check:
                last_tournament_check = minute_key
                await asyncio.to_thread(tournaments.finalize_all_pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Background scheduler error")
        await asyncio.sleep(1.0)
