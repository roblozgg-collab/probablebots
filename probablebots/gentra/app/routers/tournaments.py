from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db import Database
from app.i18n import all_texts, t
from app.keyboards import tournament_keyboard
from app.routers.common import lang_for_callback, lang_for_message
from app.services.tournaments import KYIV, TournamentService

router = Router(name="tournaments")


@router.message(Command("tournaments"))
@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("tournaments")))
async def tournament_menu(message: Message, db: Database):
    lang = lang_for_message(message, db)
    now = datetime.now(KYIV)
    end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=KYIV)
    left = end - now
    extra = "\n" + t(lang, "tour_end", end=end.strftime("%Y-%m-%d %H:%M"), hours=int(left.total_seconds()//3600), minutes=int((left.total_seconds()%3600)//60))
    await message.answer(t(lang, "tournament_menu") + extra, reply_markup=tournament_keyboard(lang))


def _subject_name(db: Database, tournament_type: str, subject_id: int) -> str:
    with db.connect() as con:
        if tournament_type == "players":
            row = con.execute("SELECT username,first_name FROM users WHERE user_id=?", (subject_id,)).fetchone()
            if row:
                return f"@{row['username']}" if row["username"] else (row["first_name"] or str(subject_id))
        else:
            row = con.execute("SELECT title FROM group_settings WHERE chat_id=?", (subject_id,)).fetchone()
            if row and row["title"]:
                return row["title"]
    return str(subject_id)


@router.callback_query(F.data.startswith("tour:"))
async def tour_table(call: CallbackQuery, db: Database, tournaments: TournamentService):
    lang = lang_for_callback(call, db)
    _, tournament_type, period = call.data.split(":", 2)
    if tournament_type not in {"players", "chats"}:
        await call.answer("Bad tournament", show_alert=True); return
    day = tournaments.current_day() if period == "current" else tournaments.previous_day()
    rows = tournaments.standings(tournament_type, day, 10)
    if not rows:
        await call.message.edit_text(t(lang, "tournament_empty"), reply_markup=tournament_keyboard(lang))
        await call.answer(); return
    title = t(lang, "tour_players") if tournament_type == "players" else t(lang, "tour_chats")
    lines = [f"🏆 <b>{title} · {day}</b>"]
    for i, row in enumerate(rows, 1):
        score = int(row["score"])
        unit = t(lang, "tour_net") if tournament_type == "players" else t(lang, "tour_turnover")
        lines.append(f"{i}. {_subject_name(db, tournament_type, int(row['subject_id']))} — <b>{score:+,}</b> {unit}")
    if period == "current":
        subject = call.from_user.id if tournament_type == "players" else (call.message.chat.id if call.message.chat.type in {"group", "supergroup"} else None)
        if subject is not None:
            own = tournaments.subject_score(tournament_type, subject, day)
            lines.append("\n" + t(lang, "tour_own", score=own))
    await call.message.edit_text("\n".join(lines), reply_markup=tournament_keyboard(lang))
    await call.answer()
