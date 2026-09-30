from __future__ import annotations

import sqlite3

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import EconomyService, InsufficientFunds


class ClanError(Exception):
    pass


class ClanAlreadyIn(ClanError):
    pass


class ClanNotIn(ClanError):
    pass


class ClanNameError(ClanError):
    pass


class ClanExists(ClanError):
    pass


class ClanPermission(ClanError):
    pass


class ClanFull(ClanError):
    pass


class ClanInviteInvalid(ClanError):
    pass


class ClanService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    def user_clan(self, user_id: int):
        with self.db.connect() as con:
            return con.execute(
                """SELECT c.*,cm.role FROM clans c JOIN clan_members cm ON cm.clan_id=c.clan_id WHERE cm.user_id=?""",
                (user_id,),
            ).fetchone()

    def card(self, clan_id: int):
        with self.db.connect() as con:
            row = con.execute(
                """SELECT c.*, (SELECT COUNT(*) FROM clan_members cm WHERE cm.clan_id=c.clan_id) AS members
                   FROM clans c WHERE c.clan_id=?""",
                (clan_id,),
            ).fetchone()
            return row

    def create(self, owner_id: int, name: str, event_key: str):
        name = " ".join(name.split()).strip()
        if not 3 <= len(name) <= 32:
            raise ClanNameError()
        try:
            with self.db.transaction() as con:
                if con.execute("SELECT 1 FROM clan_members WHERE user_id=?", (owner_id,)).fetchone():
                    raise ClanAlreadyIn()
                if con.execute("SELECT 1 FROM clans WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                    raise ClanExists()
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:create",
                    user_id=owner_id,
                    kind="clan_create",
                    gentra_delta=-self.config.clan_create_cost,
                    meta={"name": name},
                )
                cur = con.execute(
                    "INSERT INTO clans(name,owner_id,treasury,created_at) VALUES(?,?,0,?)",
                    (name, owner_id, utc_now()),
                )
                clan_id = int(cur.lastrowid)
                con.execute(
                    "INSERT INTO clan_members(clan_id,user_id,role,joined_at) VALUES(?,?,'owner',?)",
                    (clan_id, owner_id, utc_now()),
                )
                con.execute("UPDATE users SET clan_id=?,updated_at=? WHERE user_id=?", (clan_id, utc_now(), owner_id))
                return self.card_tx(con, clan_id)
        except sqlite3.IntegrityError as exc:
            if "clans.name" in str(exc):
                raise ClanExists() from exc
            raise

    @staticmethod
    def card_tx(con, clan_id: int):
        return con.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM clan_members cm WHERE cm.clan_id=c.clan_id) AS members
               FROM clans c WHERE c.clan_id=?""",
            (clan_id,),
        ).fetchone()

    def _role(self, con, user_id: int):
        return con.execute("SELECT * FROM clan_members WHERE user_id=?", (user_id,)).fetchone()

    def can_manage(self, user_id: int) -> bool:
        with self.db.connect() as con:
            row = self._role(con, user_id)
            return bool(row and row["role"] in {"owner", "deputy"})

    def invite(self, inviter_id: int, invitee_id: int):
        if inviter_id == invitee_id:
            raise ClanPermission()
        with self.db.transaction() as con:
            inviter = self._role(con, inviter_id)
            if not inviter or inviter["role"] not in {"owner", "deputy"}:
                raise ClanPermission()
            if self._role(con, invitee_id):
                raise ClanAlreadyIn()
            count = con.execute("SELECT COUNT(*) AS n FROM clan_members WHERE clan_id=?", (inviter["clan_id"],)).fetchone()["n"]
            if int(count) >= self.config.clan_member_limit:
                raise ClanFull()
            con.execute(
                "UPDATE clan_invites SET status='expired',updated_at=? WHERE invitee_id=? AND status='pending'",
                (utc_now(), invitee_id),
            )
            cur = con.execute(
                "INSERT INTO clan_invites(clan_id,inviter_id,invitee_id,status,created_at,updated_at) VALUES(?,?,?,'pending',?,?)",
                (inviter["clan_id"], inviter_id, invitee_id, utc_now(), utc_now()),
            )
            invite = con.execute("SELECT * FROM clan_invites WHERE invite_id=?", (cur.lastrowid,)).fetchone()
            clan = self.card_tx(con, int(inviter["clan_id"]))
            return invite, clan

    def accept_invite(self, invite_id: int, user_id: int):
        with self.db.transaction() as con:
            inv = con.execute("SELECT * FROM clan_invites WHERE invite_id=?", (invite_id,)).fetchone()
            if not inv or inv["status"] != "pending" or int(inv["invitee_id"]) != user_id:
                raise ClanInviteInvalid()
            if self._role(con, user_id):
                raise ClanAlreadyIn()
            count = con.execute("SELECT COUNT(*) AS n FROM clan_members WHERE clan_id=?", (inv["clan_id"],)).fetchone()["n"]
            if int(count) >= self.config.clan_member_limit:
                raise ClanFull()
            con.execute(
                "INSERT INTO clan_members(clan_id,user_id,role,joined_at) VALUES(?,?,'member',?)",
                (inv["clan_id"], user_id, utc_now()),
            )
            con.execute("UPDATE users SET clan_id=?,updated_at=? WHERE user_id=?", (inv["clan_id"], utc_now(), user_id))
            con.execute("UPDATE clan_invites SET status='accepted',updated_at=? WHERE invite_id=?", (utc_now(), invite_id))
            con.execute("UPDATE clan_invites SET status='expired',updated_at=? WHERE invitee_id=? AND status='pending'", (utc_now(), user_id))
            return self.card_tx(con, int(inv["clan_id"]))

    def decline_invite(self, invite_id: int, user_id: int) -> None:
        with self.db.transaction() as con:
            inv = con.execute("SELECT * FROM clan_invites WHERE invite_id=?", (invite_id,)).fetchone()
            if not inv or inv["status"] != "pending" or int(inv["invitee_id"]) != user_id:
                raise ClanInviteInvalid()
            con.execute("UPDATE clan_invites SET status='declined',updated_at=? WHERE invite_id=?", (utc_now(), invite_id))

    def pending_invites(self, user_id: int, limit: int = 20):
        with self.db.connect() as con:
            return con.execute(
                """SELECT ci.*,c.name FROM clan_invites ci JOIN clans c ON c.clan_id=ci.clan_id
                   WHERE ci.invitee_id=? AND ci.status='pending' ORDER BY ci.invite_id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()


    def join_open(self, clan_id: int, user_id: int):
        with self.db.transaction() as con:
            if self._role(con, user_id):
                raise ClanAlreadyIn()
            clan = con.execute("SELECT * FROM clans WHERE clan_id=?", (clan_id,)).fetchone()
            if not clan:
                raise ClanInviteInvalid()
            count = con.execute("SELECT COUNT(*) AS n FROM clan_members WHERE clan_id=?", (clan_id,)).fetchone()["n"]
            if int(count) >= self.config.clan_member_limit:
                raise ClanFull()
            con.execute("INSERT INTO clan_members(clan_id,user_id,role,joined_at) VALUES(?,?,'member',?)", (clan_id,user_id,utc_now()))
            con.execute("UPDATE users SET clan_id=?,updated_at=? WHERE user_id=?", (clan_id,utc_now(),user_id))
            con.execute("UPDATE clan_invites SET status='expired',updated_at=? WHERE invitee_id=? AND status='pending'", (utc_now(),user_id))
            return self.card_tx(con, clan_id)

    def kick(self, actor_id: int, target_id: int) -> None:
        with self.db.transaction() as con:
            actor = self._role(con, actor_id)
            target = self._role(con, target_id)
            if not actor or actor["role"] not in {"owner","deputy"}:
                raise ClanPermission()
            if not target or int(target["clan_id"]) != int(actor["clan_id"]):
                raise ClanPermission()
            if target["role"] == "owner" or actor_id == target_id:
                raise ClanPermission()
            if actor["role"] == "deputy" and target["role"] == "deputy":
                raise ClanPermission()
            if target["role"] == "deputy":
                con.execute("UPDATE clans SET deputy_id=NULL WHERE clan_id=?", (actor["clan_id"],))
            con.execute("DELETE FROM clan_members WHERE user_id=?", (target_id,))
            con.execute("UPDATE users SET clan_id=NULL,updated_at=? WHERE user_id=?", (utc_now(),target_id))

    def leave(self, user_id: int) -> None:
        with self.db.transaction() as con:
            member = self._role(con, user_id)
            if not member:
                raise ClanNotIn()
            clan_id = int(member["clan_id"])
            clan = con.execute("SELECT * FROM clans WHERE clan_id=?", (clan_id,)).fetchone()
            if member["role"] == "owner":
                deputy = clan["deputy_id"]
                if deputy:
                    con.execute("UPDATE clans SET owner_id=?,deputy_id=NULL WHERE clan_id=?", (deputy, clan_id))
                    con.execute("UPDATE clan_members SET role='owner' WHERE user_id=? AND clan_id=?", (deputy, clan_id))
                else:
                    users = con.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (clan_id,)).fetchall()
                    for u in users:
                        con.execute("UPDATE users SET clan_id=NULL,updated_at=? WHERE user_id=?", (utc_now(), u["user_id"]))
                    con.execute("DELETE FROM clans WHERE clan_id=?", (clan_id,))
                    return
            elif member["role"] == "deputy":
                con.execute("UPDATE clans SET deputy_id=NULL WHERE clan_id=?", (clan_id,))
            con.execute("DELETE FROM clan_members WHERE user_id=?", (user_id,))
            con.execute("UPDATE users SET clan_id=NULL,updated_at=? WHERE user_id=?", (utc_now(), user_id))

    def set_deputy(self, owner_id: int, target_id: int) -> None:
        with self.db.transaction() as con:
            owner = self._role(con, owner_id)
            target = self._role(con, target_id)
            if not owner or owner["role"] != "owner":
                raise ClanPermission()
            if not target or int(target["clan_id"]) != int(owner["clan_id"]) or target_id == owner_id:
                raise ClanPermission()
            con.execute("UPDATE clan_members SET role='member' WHERE clan_id=? AND role='deputy'", (owner["clan_id"],))
            con.execute("UPDATE clan_members SET role='deputy' WHERE user_id=?", (target_id,))
            con.execute("UPDATE clans SET deputy_id=? WHERE clan_id=?", (target_id, owner["clan_id"]))

    def deposit(self, user_id: int, amount: int, event_key: str) -> None:
        if amount <= 0:
            raise ValueError("amount")
        with self.db.transaction() as con:
            member = self._role(con, user_id)
            if not member:
                raise ClanNotIn()
            self.economy._insert_operation(
                con,
                event_key=f"{event_key}:debit",
                user_id=user_id,
                kind="clan_treasury",
                gentra_delta=-amount,
                meta={"clan_id": member["clan_id"]},
            )
            con.execute("UPDATE clans SET treasury=treasury+? WHERE clan_id=?", (amount, member["clan_id"]))

    def list_clans(self, page: int = 0, page_size: int = 8):
        page = max(0, page)
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT c.*,COUNT(cm.user_id) AS members FROM clans c LEFT JOIN clan_members cm ON cm.clan_id=c.clan_id
                   GROUP BY c.clan_id ORDER BY c.clan_id DESC LIMIT ? OFFSET ?""",
                (page_size, page * page_size),
            ).fetchall()
            total = int(con.execute("SELECT COUNT(*) FROM clans").fetchone()[0])
            return rows, total

    def top(self, limit: int = 10):
        with self.db.connect() as con:
            return con.execute(
                """SELECT c.*,COUNT(cm.user_id) AS members FROM clans c LEFT JOIN clan_members cm ON cm.clan_id=c.clan_id
                   GROUP BY c.clan_id ORDER BY c.treasury DESC,members DESC LIMIT ?""",
                (limit,),
            ).fetchall()

    def search(self, query: str, limit: int = 10):
        with self.db.connect() as con:
            return con.execute(
                """SELECT c.*,COUNT(cm.user_id) AS members FROM clans c LEFT JOIN clan_members cm ON cm.clan_id=c.clan_id
                   WHERE c.name LIKE ? GROUP BY c.clan_id ORDER BY c.name LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()
