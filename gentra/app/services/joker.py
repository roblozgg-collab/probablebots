from __future__ import annotations

import math
import secrets
import sqlite3
import uuid

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InvalidAmount
from app.services.mines import GameFinished, GameNotFound, GameNotYours


class JokerService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy
        self.rng = secrets.SystemRandom()

    def start(self, user_id: int, chat_id: int, bet: int, event_key: str):
        if bet < self.config.joker_min_bet:
            raise InvalidAmount()
        if self.config.joker_slots < 2:
            raise ValueError("JOKER_SLOTS must be >= 2")
        game_id = uuid.uuid4().hex[:16]
        joker_pos = self.rng.randrange(self.config.joker_slots)
        try:
            with self.db.transaction() as con:
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=user_id,
                    kind="joker_bet",
                    gentra_delta=-bet,
                    meta={"game_id": game_id},
                )
                con.execute(
                    """INSERT INTO joker_games(game_id,user_id,chat_id,bet,joker_pos,slots,multiplier,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,'active',?,?)""",
                    (game_id, user_id, chat_id, bet, joker_pos, self.config.joker_slots, self.config.joker_payout_multiplier, utc_now(), utc_now()),
                )
            return self.get(game_id)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def get(self, game_id: str):
        with self.db.connect() as con:
            return con.execute("SELECT * FROM joker_games WHERE game_id=?", (game_id,)).fetchone()

    def choose(self, game_id: str, user_id: int, pos: int, event_key: str) -> tuple[bool, int, int]:
        try:
            with self.db.transaction() as con:
                row = con.execute("SELECT * FROM joker_games WHERE game_id=?", (game_id,)).fetchone()
                if not row:
                    raise GameNotFound()
                if int(row["user_id"]) != user_id:
                    raise GameNotYours()
                if row["status"] != "active":
                    raise GameFinished()
                if not 0 <= pos < int(row["slots"]):
                    raise ValueError("card out of range")
                win = pos == int(row["joker_pos"])
                payout = int(math.floor(int(row["bet"]) * float(row["multiplier"]))) if win else 0
                if win:
                    self.economy._insert_operation(
                        con,
                        event_key=f"{event_key}:payout",
                        user_id=user_id,
                        kind="joker_payout",
                        gentra_delta=payout,
                        meta={"game_id": game_id},
                    )
                con.execute(
                    "UPDATE joker_games SET status=?,payout=?,updated_at=? WHERE game_id=? AND status='active'",
                    ("won" if win else "lost", payout, utc_now(), game_id),
                )
                return win, payout, int(row["joker_pos"])
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise
