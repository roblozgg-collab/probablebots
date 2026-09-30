from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import EconomyService


class DuelError(Exception):
    pass


class DuelSelf(DuelError):
    pass


class DuelCooldown(DuelError):
    pass


class DuelNotFound(DuelError):
    pass


class DuelWrongUser(DuelError):
    pass


class DuelNotPending(DuelError):
    pass


class DuelService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy
        self.rng = secrets.SystemRandom()

    def _on_cooldown(self, con, user_id: int) -> bool:
        row = con.execute("SELECT last_duel_at FROM duel_cooldowns WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        last = datetime.fromisoformat(row["last_duel_at"])
        return last + timedelta(seconds=self.config.duel_cooldown_seconds) > datetime.now(timezone.utc)

    def challenge(self, chat_id: int, challenger: int, opponent: int):
        if challenger == opponent:
            raise DuelSelf()
        with self.db.transaction() as con:
            if self._on_cooldown(con, challenger) or self._on_cooldown(con, opponent):
                raise DuelCooldown()
            existing = con.execute(
                """SELECT 1 FROM duels WHERE chat_id=? AND status='pending'
                   AND ((challenger_id=? AND opponent_id=?) OR (challenger_id=? AND opponent_id=?)) LIMIT 1""",
                (chat_id, challenger, opponent, opponent, challenger),
            ).fetchone()
            if existing:
                raise DuelCooldown()
            duel_id = uuid.uuid4().hex[:16]
            con.execute(
                "INSERT INTO duels(duel_id,chat_id,challenger_id,opponent_id,status,created_at) VALUES(?,?,?,?, 'pending', ?)",
                (duel_id, chat_id, challenger, opponent, utc_now()),
            )
            return con.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,)).fetchone()

    def random_opponent(self, chat_id: int, challenger: int) -> int | None:
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT user_id FROM chat_users WHERE chat_id=? AND user_id<>? ORDER BY last_seen_at DESC LIMIT 100",
                (chat_id, challenger),
            ).fetchall()
        if not rows:
            return None
        return int(self.rng.choice(rows)["user_id"])

    @staticmethod
    def _power(row) -> int:
        return sum(int(row[x]) for x in ("block", "endurance", "health", "intuition", "strength", "speed", "charisma"))

    def accept(self, duel_id: str, actor_id: int):
        with self.db.transaction() as con:
            duel = con.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,)).fetchone()
            if not duel:
                raise DuelNotFound()
            if int(duel["opponent_id"]) != actor_id:
                raise DuelWrongUser()
            if duel["status"] != "pending":
                raise DuelNotPending()
            if self._on_cooldown(con, int(duel["challenger_id"])) or self._on_cooldown(con, int(duel["opponent_id"])):
                raise DuelCooldown()
            a = con.execute("SELECT * FROM users WHERE user_id=?", (duel["challenger_id"],)).fetchone()
            b = con.execute("SELECT * FROM users WHERE user_id=?", (duel["opponent_id"],)).fetchone()
            pa, pb = self._power(a), self._power(b)
            a_score = pa + self.rng.randrange(pa + 1)
            b_score = pb + self.rng.randrange(pb + 1)
            if a_score == b_score:
                a_score += self.rng.randrange(2)
                if a_score == b_score:
                    b_score += 1
            winner = int(duel["challenger_id"]) if a_score > b_score else int(duel["opponent_id"])
            self.economy._insert_operation(
                con,
                event_key=f"duel:{duel_id}:reward",
                user_id=winner,
                kind="duel_reward",
                gentra_delta=self.config.duel_reward,
                meta={"duel_id": duel_id},
            )
            now = utc_now()
            con.execute(
                "UPDATE duels SET status='resolved',winner_id=?,challenger_score=?,opponent_score=?,resolved_at=? WHERE duel_id=?",
                (winner, a_score, b_score, now, duel_id),
            )
            for uid in (int(duel["challenger_id"]), int(duel["opponent_id"])):
                con.execute(
                    "INSERT INTO duel_cooldowns(user_id,last_duel_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_duel_at=excluded.last_duel_at",
                    (uid, now),
                )
            result = dict(duel)
            result.update({"winner_id": winner, "challenger_score": a_score, "opponent_score": b_score})
            return result

    def decline(self, duel_id: str, actor_id: int) -> None:
        with self.db.transaction() as con:
            duel = con.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,)).fetchone()
            if not duel:
                raise DuelNotFound()
            if int(duel["opponent_id"]) != actor_id:
                raise DuelWrongUser()
            if duel["status"] != "pending":
                raise DuelNotPending()
            con.execute("UPDATE duels SET status='declined',resolved_at=? WHERE duel_id=?", (utc_now(), duel_id))

    def history(self, user_id: int, limit: int = 10):
        with self.db.connect() as con:
            return con.execute(
                """SELECT * FROM duels WHERE challenger_id=? OR opponent_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, user_id, limit),
            ).fetchall()
