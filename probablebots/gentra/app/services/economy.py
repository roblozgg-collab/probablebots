from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.config import Config
from app.db import Database, utc_now


class EconomyError(Exception):
    pass


class InsufficientFunds(EconomyError):
    pass


class InvalidAmount(EconomyError):
    pass


class DuplicateEvent(EconomyError):
    pass


class UserNotFound(EconomyError):
    pass


class SelfTransfer(EconomyError):
    pass


@dataclass(slots=True)
class Balance:
    gentra: int
    galleons: int


STATS = ("block", "endurance", "health", "intuition", "strength", "speed", "charisma")


class EconomyService:
    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config

    def _insert_operation(
        self,
        con: sqlite3.Connection,
        *,
        event_key: str,
        user_id: int,
        kind: str,
        gentra_delta: int = 0,
        galleons_delta: int = 0,
        meta: dict[str, Any] | None = None,
    ) -> Balance:
        row = con.execute("SELECT gentra,galleons FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            raise UserNotFound(str(user_id))
        new_g = int(row["gentra"]) + int(gentra_delta)
        new_ga = int(row["galleons"]) + int(galleons_delta)
        if new_g < 0 or new_ga < 0:
            raise InsufficientFunds()
        con.execute(
            "UPDATE users SET gentra=?, galleons=?, updated_at=? WHERE user_id=?",
            (new_g, new_ga, utc_now(), user_id),
        )
        con.execute(
            """INSERT INTO operations(event_key,user_id,kind,gentra_delta,galleons_delta,balance_gentra,balance_galleons,meta_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                event_key,
                user_id,
                kind,
                gentra_delta,
                galleons_delta,
                new_g,
                new_ga,
                self.db.dump_meta(meta),
                utc_now(),
            ),
        )
        return Balance(new_g, new_ga)

    def change(
        self,
        user_id: int,
        *,
        gentra_delta: int = 0,
        galleons_delta: int = 0,
        kind: str,
        event_key: str,
        meta: dict[str, Any] | None = None,
    ) -> Balance:
        try:
            with self.db.transaction() as con:
                return self._insert_operation(
                    con,
                    event_key=event_key,
                    user_id=user_id,
                    kind=kind,
                    gentra_delta=gentra_delta,
                    galleons_delta=galleons_delta,
                    meta=meta,
                )
        except sqlite3.IntegrityError as exc:
            if "operations.event_key" in str(exc) or "UNIQUE constraint failed: operations.event_key" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def balance(self, user_id: int) -> Balance:
        row = self.db.get_user(user_id)
        if not row:
            raise UserNotFound(str(user_id))
        return Balance(int(row["gentra"]), int(row["galleons"]))

    def transfer(self, from_user: int, to_user: int, amount: int, event_key: str) -> Balance:
        if amount <= 0:
            raise InvalidAmount()
        if from_user == to_user:
            raise SelfTransfer()
        try:
            with self.db.transaction() as con:
                src = con.execute("SELECT gentra,galleons FROM users WHERE user_id=?", (from_user,)).fetchone()
                dst = con.execute("SELECT gentra,galleons FROM users WHERE user_id=?", (to_user,)).fetchone()
                if not src or not dst:
                    raise UserNotFound(str(to_user if src else from_user))
                if int(src["gentra"]) < amount:
                    raise InsufficientFunds()
                self._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=from_user,
                    kind="transfer_out",
                    gentra_delta=-amount,
                    meta={"to": to_user},
                )
                self._insert_operation(
                    con,
                    event_key=f"{event_key}:credit",
                    user_id=to_user,
                    kind="transfer_in",
                    gentra_delta=amount,
                    meta={"from": from_user},
                )
                con.execute(
                    "INSERT INTO transfers(event_key,from_user,to_user,amount,created_at) VALUES(?,?,?,?,?)",
                    (event_key, from_user, to_user, amount, utc_now()),
                )
                row = con.execute("SELECT gentra,galleons FROM users WHERE user_id=?", (from_user,)).fetchone()
                return Balance(int(row["gentra"]), int(row["galleons"]))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def stat_cost(self, current_level: int) -> int:
        return max(1, math.ceil(self.config.stat_base_cost * (max(1, current_level) ** self.config.stat_growth)))

    def upgrade_stat(self, user_id: int, stat: str, event_key: str) -> tuple[int, int]:
        if stat not in STATS:
            raise ValueError("unknown stat")
        try:
            with self.db.transaction() as con:
                row = con.execute(f"SELECT galleons,{stat},gentra FROM users WHERE user_id=?", (user_id,)).fetchone()
                if not row:
                    raise UserNotFound(str(user_id))
                level = int(row[stat])
                cost = self.stat_cost(level)
                if int(row["galleons"]) < cost:
                    raise InsufficientFunds()
                new_level = level + 1
                new_galleons = int(row["galleons"]) - cost
                con.execute(
                    f"UPDATE users SET {stat}=?, galleons=?, updated_at=? WHERE user_id=?",
                    (new_level, new_galleons, utc_now(), user_id),
                )
                con.execute(
                    """INSERT INTO operations(event_key,user_id,kind,gentra_delta,galleons_delta,balance_gentra,balance_galleons,meta_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        event_key,
                        user_id,
                        "stat_upgrade",
                        0,
                        -cost,
                        int(row["gentra"]),
                        new_galleons,
                        self.db.dump_meta({"stat": stat, "level": new_level}),
                        utc_now(),
                    ),
                )
                return new_level, cost
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def leaderboard(self, limit: int = 10):
        limit = max(1, min(50, int(limit)))
        with self.db.connect() as con:
            return con.execute(
                "SELECT user_id,username,first_name,gentra FROM users ORDER BY gentra DESC,user_id ASC LIMIT ?",
                (limit,),
            ).fetchall()

    def recent_operations(self, user_id: int, limit: int = 15):
        with self.db.connect() as con:
            return con.execute(
                "SELECT * FROM operations WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()
