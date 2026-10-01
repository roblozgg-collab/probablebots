from __future__ import annotations

import math
import sqlite3
import uuid

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InvalidAmount


class DiceGameNotFound(Exception):
    pass


class DiceGameFinished(Exception):
    pass


class DiceService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    def start(self, user_id: int, chat_id: int, bet: int, choice: str, event_key: str):
        if bet < self.config.dice_min_bet or choice not in {"high", "low"}:
            raise InvalidAmount()
        game_id = uuid.uuid4().hex[:16]
        try:
            with self.db.transaction() as con:
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=user_id,
                    kind="dice_bet",
                    gentra_delta=-bet,
                    meta={"game_id": game_id, "choice": choice},
                )
                con.execute(
                    """INSERT INTO dice_games(game_id,start_event_key,user_id,chat_id,bet,choice,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?)""",
                    (game_id, event_key, user_id, chat_id, bet, choice, utc_now(), utc_now()),
                )
            return self.get(game_id)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def get(self, game_id: str):
        with self.db.connect() as con:
            return con.execute("SELECT * FROM dice_games WHERE game_id=?", (game_id,)).fetchone()

    def settle(self, game_id: str, result: int):
        if not 1 <= int(result) <= 6:
            raise ValueError("invalid dice result")
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM dice_games WHERE game_id=?", (game_id,)).fetchone()
            if not row:
                raise DiceGameNotFound()
            if row["status"] != "active":
                raise DiceGameFinished()
            choice = row["choice"]
            win = int(result) >= 4 if choice == "high" else int(result) <= 3
            payout = int(math.floor(int(row["bet"]) * self.config.dice_payout_multiplier)) if win else 0
            if payout:
                self.economy._insert_operation(
                    con,
                    event_key=f"dice:{game_id}:payout",
                    user_id=int(row["user_id"]),
                    kind="dice_payout",
                    gentra_delta=payout,
                    meta={"game_id": game_id, "result": int(result), "choice": choice},
                )
            con.execute(
                "UPDATE dice_games SET status=?,result=?,payout=?,updated_at=? WHERE game_id=? AND status='active'",
                ("won" if win else "lost", int(result), payout, utc_now(), game_id),
            )
            return win, payout

    def refund_pending(self) -> int:
        refunded = 0
        with self.db.transaction() as con:
            rows = con.execute("SELECT * FROM dice_games WHERE status='active'").fetchall()
            for row in rows:
                self.economy._insert_operation(
                    con,
                    event_key=f"dice:{row['game_id']}:recovery_refund",
                    user_id=int(row["user_id"]),
                    kind="dice_refund",
                    gentra_delta=int(row["bet"]),
                    meta={"game_id": row["game_id"], "reason": "restart"},
                )
                con.execute(
                    "UPDATE dice_games SET status='cancelled',updated_at=? WHERE game_id=?",
                    (utc_now(), row["game_id"]),
                )
                refunded += 1
        return refunded

    def cancel(self, game_id: str):
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM dice_games WHERE game_id=?", (game_id,)).fetchone()
            if not row or row["status"] != "active":
                return False
            self.economy._insert_operation(
                con,
                event_key=f"dice:{game_id}:refund",
                user_id=int(row["user_id"]),
                kind="dice_refund",
                gentra_delta=int(row["bet"]),
                meta={"game_id": game_id},
            )
            con.execute("UPDATE dice_games SET status='cancelled',updated_at=? WHERE game_id=?", (utc_now(), game_id))
            return True
