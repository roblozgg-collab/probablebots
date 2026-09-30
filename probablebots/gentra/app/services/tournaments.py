from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import EconomyService

KYIV = ZoneInfo("Europe/Kyiv")


class TournamentService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    @staticmethod
    def current_day() -> str:
        return datetime.now(KYIV).date().isoformat()

    @staticmethod
    def previous_day() -> str:
        return (datetime.now(KYIV).date() - timedelta(days=1)).isoformat()

    def standings(self, tournament_type: str, day: str | None = None, limit: int = 10):
        day = day or self.current_day()
        with self.db.connect() as con:
            return con.execute(
                "SELECT * FROM tournament_scores WHERE day=? AND type=? ORDER BY score DESC,subject_id ASC LIMIT ?",
                (day, tournament_type, limit),
            ).fetchall()

    def subject_score(self, tournament_type: str, subject_id: int, day: str | None = None) -> int:
        day = day or self.current_day()
        with self.db.connect() as con:
            row = con.execute(
                "SELECT score FROM tournament_scores WHERE day=? AND type=? AND subject_id=?",
                (day, tournament_type, subject_id),
            ).fetchone()
            return int(row["score"]) if row else 0

    def finalize(self, day: str, tournament_type: str) -> list[dict]:
        prizes = self.config.participant_prizes if tournament_type == "players" else self.config.chat_prizes
        results: list[dict] = []
        with self.db.transaction() as con:
            if con.execute("SELECT 1 FROM tournament_finalizations WHERE day=? AND type=?", (day, tournament_type)).fetchone():
                return []
            rows = con.execute(
                "SELECT * FROM tournament_scores WHERE day=? AND type=? ORDER BY score DESC,subject_id ASC LIMIT ?",
                (day, tournament_type, len(prizes)),
            ).fetchall()
            for rank, (row, reward) in enumerate(zip(rows, prizes), start=1):
                subject_id = int(row["subject_id"])
                event_key = f"tournament:{tournament_type}:{day}:{rank}:{subject_id}"
                if tournament_type == "players":
                    self.economy._insert_operation(
                        con,
                        event_key=event_key,
                        user_id=subject_id,
                        kind="tournament_reward",
                        gentra_delta=int(reward),
                        meta={"day": day, "rank": rank, "type": tournament_type},
                    )
                else:
                    con.execute(
                        "INSERT INTO group_treasury(chat_id,balance,reward_amount,updated_at) VALUES(?,0,?,?) ON CONFLICT(chat_id) DO NOTHING",
                        (subject_id, self.config.treasury_default_reward, utc_now()),
                    )
                    con.execute(
                        "UPDATE group_treasury SET balance=balance+?,updated_at=? WHERE chat_id=?",
                        (int(reward), utc_now(), subject_id),
                    )
                con.execute(
                    "INSERT INTO tournament_awards(day,type,rank,subject_id,reward,event_key,created_at) VALUES(?,?,?,?,?,?,?)",
                    (day, tournament_type, rank, subject_id, int(reward), event_key, utc_now()),
                )
                results.append({"rank": rank, "subject_id": subject_id, "reward": int(reward), "score": int(row["score"])})
            con.execute(
                "INSERT INTO tournament_finalizations(day,type,finalized_at) VALUES(?,?,?)",
                (day, tournament_type, utc_now()),
            )
        return results


    def finalize_all_pending(self) -> dict[str, list[dict]]:
        current = self.current_day()
        with self.db.connect() as con:
            days = [r[0] for r in con.execute("SELECT DISTINCT day FROM tournament_scores WHERE day<? ORDER BY day", (current,)).fetchall()]
        out: dict[str, list[dict]] = {}
        for day in days:
            for typ in ("players", "chats"):
                result = self.finalize(day, typ)
                if result:
                    out[f"{day}:{typ}"] = result
        return out

    def finalize_missing_previous(self) -> dict[str, list[dict]]:
        day = self.previous_day()
        return {"players": self.finalize(day, "players"), "chats": self.finalize(day, "chats")}
