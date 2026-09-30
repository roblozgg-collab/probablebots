from __future__ import annotations

import sqlite3

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import EconomyService


class TreasuryError(Exception):
    pass


class TreasuryInsufficient(TreasuryError):
    pass


class TreasuryRewardRange(TreasuryError):
    pass


class TreasuryService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    def ensure(self, chat_id: int):
        with self.db.transaction() as con:
            con.execute(
                "INSERT INTO group_treasury(chat_id,balance,reward_amount,updated_at) VALUES(?,0,?,?) "
                "ON CONFLICT(chat_id) DO NOTHING",
                (chat_id, self.config.treasury_default_reward, utc_now()),
            )
            return con.execute("SELECT * FROM group_treasury WHERE chat_id=?", (chat_id,)).fetchone()

    def get(self, chat_id: int):
        self.ensure(chat_id)
        with self.db.connect() as con:
            return con.execute("SELECT * FROM group_treasury WHERE chat_id=?", (chat_id,)).fetchone()

    def deposit(self, chat_id: int, user_id: int, amount: int, event_key: str):
        if amount <= 0:
            raise ValueError("amount")
        with self.db.transaction() as con:
            con.execute(
                "INSERT INTO group_treasury(chat_id,balance,reward_amount,updated_at) VALUES(?,0,?,?) ON CONFLICT(chat_id) DO NOTHING",
                (chat_id, self.config.treasury_default_reward, utc_now()),
            )
            self.economy._insert_operation(
                con,
                event_key=f"{event_key}:debit",
                user_id=user_id,
                kind="group_treasury_deposit",
                gentra_delta=-amount,
                meta={"chat_id": chat_id},
            )
            con.execute("UPDATE group_treasury SET balance=balance+?,updated_at=? WHERE chat_id=?", (amount, utc_now(), chat_id))
            return con.execute("SELECT * FROM group_treasury WHERE chat_id=?", (chat_id,)).fetchone()

    def set_reward(self, chat_id: int, amount: int):
        if not self.config.treasury_reward_min <= amount <= self.config.treasury_reward_max:
            raise TreasuryRewardRange()
        with self.db.transaction() as con:
            con.execute(
                "INSERT INTO group_treasury(chat_id,balance,reward_amount,updated_at) VALUES(?,0,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET reward_amount=excluded.reward_amount,updated_at=excluded.updated_at",
                (chat_id, amount, utc_now()),
            )

    def reward_inviter_once(self, chat_id: int, new_user_id: int, inviter_id: int) -> int:
        if new_user_id == inviter_id:
            return 0
        event_key = f"groupinvite:{chat_id}:{new_user_id}"
        try:
            with self.db.transaction() as con:
                if con.execute("SELECT 1 FROM group_invite_rewards WHERE chat_id=? AND new_user_id=?", (chat_id, new_user_id)).fetchone():
                    return 0
                tr = con.execute("SELECT * FROM group_treasury WHERE chat_id=?", (chat_id,)).fetchone()
                if not tr:
                    return 0
                amount = int(tr["reward_amount"])
                if int(tr["balance"]) < amount:
                    raise TreasuryInsufficient()
                user = con.execute("SELECT 1 FROM users WHERE user_id=?", (inviter_id,)).fetchone()
                if not user:
                    return 0
                con.execute("UPDATE group_treasury SET balance=balance-?,updated_at=? WHERE chat_id=?", (amount, utc_now(), chat_id))
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:credit",
                    user_id=inviter_id,
                    kind="group_invite_reward",
                    gentra_delta=amount,
                    meta={"chat_id": chat_id, "new_user_id": new_user_id},
                )
                con.execute(
                    "INSERT INTO group_invite_rewards(chat_id,new_user_id,inviter_id,amount,event_key,created_at) VALUES(?,?,?,?,?,?)",
                    (chat_id, new_user_id, inviter_id, amount, event_key, utc_now()),
                )
                return amount
        except sqlite3.IntegrityError:
            return 0
