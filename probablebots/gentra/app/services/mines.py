from __future__ import annotations

import json
import math
import secrets
import sqlite3
import uuid

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InvalidAmount


class MinesError(Exception):
    pass


class GameNotFound(MinesError):
    pass


class GameNotYours(MinesError):
    pass


class GameFinished(MinesError):
    pass


class NeedSafeCell(MinesError):
    pass


class MinesService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy
        self.rng = secrets.SystemRandom()

    @property
    def total_cells(self) -> int:
        return self.config.mines_rows * self.config.mines_cols

    def multiplier(self, safe_opened: int, mines_count: int | None = None) -> float:
        mines = mines_count if mines_count is not None else self.config.mines_count
        if safe_opened <= 0:
            return 1.0
        n = self.total_cells
        if safe_opened > n - mines:
            safe_opened = n - mines
        survival = 1.0
        for i in range(safe_opened):
            survival *= (n - mines - i) / (n - i)
        fair = 1.0 / survival
        return max(1.0, round(fair * self.config.mines_house_factor, 2))

    def potential(self, bet: int, safe_opened: int, mines_count: int | None = None) -> int:
        return max(bet, int(math.floor(bet * self.multiplier(safe_opened, mines_count))))

    def start(self, user_id: int, chat_id: int, bet: int, event_key: str):
        if bet < self.config.mines_min_bet:
            raise InvalidAmount()
        if self.config.mines_count <= 0 or self.config.mines_count >= self.total_cells:
            raise ValueError("MINES_COUNT must be between 1 and total_cells-1")
        game_id = uuid.uuid4().hex[:16]
        mines = sorted(self.rng.sample(range(self.total_cells), self.config.mines_count))
        try:
            with self.db.transaction() as con:
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=user_id,
                    kind="mines_bet",
                    gentra_delta=-bet,
                    meta={"game_id": game_id},
                )
                con.execute(
                    """INSERT INTO mines_games(game_id,user_id,chat_id,bet,rows,cols,mines_count,mines_json,revealed_json,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,'active',?,?)""",
                    (
                        game_id, user_id, chat_id, bet,
                        self.config.mines_rows, self.config.mines_cols, self.config.mines_count,
                        json.dumps(mines), "[]", utc_now(), utc_now(),
                    ),
                )
            return self.get(game_id)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def get(self, game_id: str):
        with self.db.connect() as con:
            return con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone()

    def _validate(self, row, user_id: int):
        if not row:
            raise GameNotFound()
        if int(row["user_id"]) != user_id:
            raise GameNotYours()
        if row["status"] != "active":
            raise GameFinished()

    def open_cell(self, game_id: str, user_id: int, index: int, event_key: str):
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone()
            self._validate(row, user_id)
            total = int(row["rows"]) * int(row["cols"])
            if not 0 <= index < total:
                raise ValueError("cell out of range")
            revealed = set(json.loads(row["revealed_json"]))
            if index in revealed:
                return {"state": "same", "game": row, "index": index}
            mines = set(json.loads(row["mines_json"]))
            if index in mines:
                con.execute(
                    "UPDATE mines_games SET status='lost',updated_at=? WHERE game_id=? AND status='active'",
                    (utc_now(), game_id),
                )
                return {"state": "mine", "game": con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone(), "index": index}
            revealed.add(index)
            safe_count = len(revealed)
            payout = self.potential(int(row["bet"]), safe_count, int(row["mines_count"]))
            if safe_count >= total - int(row["mines_count"]):
                self.economy._insert_operation(
                    con,
                    event_key=f"mines:{game_id}:complete",
                    user_id=user_id,
                    kind="mines_payout",
                    gentra_delta=payout,
                    meta={"game_id": game_id, "safe": safe_count},
                )
                con.execute(
                    "UPDATE mines_games SET revealed_json=?,status='won',payout=?,updated_at=? WHERE game_id=?",
                    (json.dumps(sorted(revealed)), payout, utc_now(), game_id),
                )
                return {"state": "complete", "game": con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone(), "index": index}
            con.execute(
                "UPDATE mines_games SET revealed_json=?,updated_at=? WHERE game_id=?",
                (json.dumps(sorted(revealed)), utc_now(), game_id),
            )
            return {"state": "safe", "game": con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone(), "index": index, "potential": payout}

    def cashout(self, game_id: str, user_id: int, event_key: str) -> int:
        try:
            with self.db.transaction() as con:
                row = con.execute("SELECT * FROM mines_games WHERE game_id=?", (game_id,)).fetchone()
                self._validate(row, user_id)
                safe_count = len(json.loads(row["revealed_json"]))
                if safe_count < 1:
                    raise NeedSafeCell()
                payout = self.potential(int(row["bet"]), safe_count, int(row["mines_count"]))
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:payout",
                    user_id=user_id,
                    kind="mines_cashout",
                    gentra_delta=payout,
                    meta={"game_id": game_id, "safe": safe_count},
                )
                con.execute(
                    "UPDATE mines_games SET status='cashed_out',payout=?,updated_at=? WHERE game_id=? AND status='active'",
                    (payout, utc_now(), game_id),
                )
                return payout
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise
