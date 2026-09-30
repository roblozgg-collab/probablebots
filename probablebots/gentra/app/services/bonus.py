from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import Database
from app.services.economy import DuplicateEvent, EconomyService


class BonusError(Exception):
    pass


class BonusCooldown(BonusError):
    pass


class BonusService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    def _is_vip(self, row) -> bool:
        if not row or not row["vip_until"]:
            return False
        try:
            return datetime.fromisoformat(row["vip_until"]) > datetime.now(timezone.utc)
        except ValueError:
            return False

    def _period_hours(self, user_row) -> int:
        return self.config.vip_bonus_period_hours if self._is_vip(user_row) else self.config.bonus_period_hours

    def can_claim(self, user_id: int) -> bool:
        now = datetime.now(timezone.utc)
        with self.db.connect() as con:
            user = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            last = con.execute(
                "SELECT claimed_at FROM bonus_claims WHERE user_id=? ORDER BY claim_id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not last:
            return True
        return datetime.fromisoformat(last["claimed_at"]) + timedelta(hours=self._period_hours(user)) <= now

    def claim(self, user_id: int, event_key: str) -> int:
        now = datetime.now(timezone.utc)
        try:
            with self.db.transaction() as con:
                user = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
                last = con.execute(
                    "SELECT claimed_at FROM bonus_claims WHERE user_id=? ORDER BY claim_id DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
                if last and datetime.fromisoformat(last["claimed_at"]) + timedelta(hours=self._period_hours(user)) > now:
                    raise BonusCooldown()
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:credit",
                    user_id=user_id,
                    kind="bonus",
                    gentra_delta=self.config.bonus_amount,
                    meta={},
                )
                con.execute(
                    "INSERT INTO bonus_claims(user_id,amount,event_key,claimed_at) VALUES(?,?,?,?)",
                    (user_id, self.config.bonus_amount, event_key, now.isoformat(timespec="seconds")),
                )
                return self.config.bonus_amount
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise
