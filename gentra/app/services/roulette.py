from __future__ import annotations

import json
import math
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InsufficientFunds, InvalidAmount

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


@dataclass(frozen=True, slots=True)
class BetSpec:
    bet_type: str
    value: str
    label: str


class RouletteError(Exception):
    pass


class NoBets(RouletteError):
    pass


class RoundClosed(RouletteError):
    pass


class NoPreviousBets(RouletteError):
    pass


def color_of(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in RED_NUMBERS else "black"


def parse_bet_target(raw: str) -> BetSpec | None:
    s = raw.strip().lower().replace("ё", "е")
    aliases = {
        "красное": ("color", "red", "красное"),
        "красный": ("color", "red", "красное"),
        "червоне": ("color", "red", "червоне"),
        "red": ("color", "red", "red"),
        "черное": ("color", "black", "черное"),
        "черный": ("color", "black", "черное"),
        "чорне": ("color", "black", "чорне"),
        "black": ("color", "black", "black"),
        "odd": ("parity", "odd", "odd"),
        "нечет": ("parity", "odd", "нечётные"),
        "нечетное": ("parity", "odd", "нечётные"),
        "нечетные": ("parity", "odd", "нечётные"),
        "непарне": ("parity", "odd", "непарне"),
        "even": ("parity", "even", "even"),
        "чет": ("parity", "even", "чётные"),
        "четное": ("parity", "even", "чётные"),
        "четные": ("parity", "even", "чётные"),
        "парне": ("parity", "even", "парне"),
    }
    if s in aliases:
        t, v, label = aliases[s]
        return BetSpec(t, v, label)
    if s.isdigit():
        n = int(s)
        if 0 <= n <= 36:
            return BetSpec("number", str(n), str(n))
        return None
    if "-" in s:
        parts = s.split("-", 1)
        if all(x.strip().isdigit() for x in parts):
            a, b = (int(x.strip()) for x in parts)
            if 0 <= a <= b <= 36:
                return BetSpec("range", f"{a}-{b}", f"{a}–{b}")
    return None


def payout_multiplier(spec: BetSpec, config: Config) -> float:
    if spec.bet_type == "number":
        return 36.0
    if spec.bet_type in {"color", "parity"}:
        return 2.0
    if spec.bet_type == "range":
        a, b = (int(x) for x in spec.value.split("-"))
        count = b - a + 1
        return max(1.01, round((37.0 / count) * config.roulette_range_house_factor, 2))
    raise ValueError(spec.bet_type)


def bet_wins(spec: BetSpec, number: int) -> bool:
    if spec.bet_type == "number":
        return number == int(spec.value)
    if spec.bet_type == "color":
        return color_of(number) == spec.value
    if spec.bet_type == "parity":
        if number == 0:
            return False
        return (number % 2 == 1) if spec.value == "odd" else (number % 2 == 0)
    if spec.bet_type == "range":
        a, b = (int(x) for x in spec.value.split("-"))
        return a <= number <= b
    return False


def evaluate_payout(amount: int, bet_type: str, bet_value: str, number: int, config: Config) -> int:
    spec = BetSpec(bet_type, bet_value, bet_value)
    if not bet_wins(spec, number):
        return 0
    return int(math.floor(amount * payout_multiplier(spec, config)))


class RouletteService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy
        self.rng = secrets.SystemRandom()

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def get_or_create_round(self, chat_id: int):
        now = datetime.now(timezone.utc)
        with self.db.transaction() as con:
            row = con.execute(
                "SELECT * FROM roulette_rounds WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if row and self._parse_iso(row["closes_at"]) > now:
                return row
            if row:
                con.execute("UPDATE roulette_rounds SET status='closing' WHERE id=?", (row["id"],))
            closes = now + timedelta(seconds=self.config.roulette_round_seconds)
            cur = con.execute(
                "INSERT INTO roulette_rounds(chat_id,status,opened_at,closes_at) VALUES(?, 'open', ?, ?)",
                (chat_id, now.isoformat(timespec="seconds"), closes.isoformat(timespec="seconds")),
            )
            return con.execute("SELECT * FROM roulette_rounds WHERE id=?", (cur.lastrowid,)).fetchone()

    def _debit_bet(self, con: sqlite3.Connection, user_id: int, amount: int, event_key: str, meta: dict):
        return self.economy._insert_operation(
            con,
            event_key=event_key,
            user_id=user_id,
            kind="roulette_bet",
            gentra_delta=-amount,
            meta=meta,
        )

    def place_bet(self, chat_id: int, user_id: int, amount: int, spec: BetSpec, event_key: str):
        if amount < self.config.roulette_min_bet or amount > self.config.roulette_max_bet:
            raise InvalidAmount()
        round_row = self.get_or_create_round(chat_id)
        now = datetime.now(timezone.utc)
        if self._parse_iso(round_row["closes_at"]) <= now or round_row["status"] != "open":
            raise RoundClosed()
        try:
            with self.db.transaction() as con:
                rr = con.execute("SELECT * FROM roulette_rounds WHERE id=?", (round_row["id"],)).fetchone()
                if not rr or rr["status"] != "open" or self._parse_iso(rr["closes_at"]) <= now:
                    raise RoundClosed()
                self._debit_bet(con, user_id, amount, f"{event_key}:bet", {"round_id": rr["id"], "bet": spec.value})
                con.execute(
                    "INSERT INTO roulette_bets(round_id,user_id,amount,bet_type,bet_value,status,created_at) VALUES(?,?,?,?,?,'active',?)",
                    (rr["id"], user_id, amount, spec.bet_type, spec.value, utc_now()),
                )
                return rr
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def current_user_bets(self, chat_id: int, user_id: int):
        with self.db.connect() as con:
            rr = con.execute(
                "SELECT * FROM roulette_rounds WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 1", (chat_id,)
            ).fetchone()
            if not rr:
                return None, []
            bets = con.execute(
                "SELECT * FROM roulette_bets WHERE round_id=? AND user_id=? AND status='active' ORDER BY id",
                (rr["id"], user_id),
            ).fetchall()
            return rr, bets

    def recent_results(self, chat_id: int, limit: int | None = None) -> list[int]:
        size = self.config.roulette_log_limit if limit is None else max(1, min(50, int(limit)))
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT result_number FROM roulette_rounds WHERE chat_id=? AND status='settled' AND result_number IS NOT NULL ORDER BY id DESC LIMIT ?",
                (chat_id, size),
            ).fetchall()
        return [int(row["result_number"]) for row in rows]

    def cancel(self, chat_id: int, user_id: int, event_key: str) -> int:
        with self.db.transaction() as con:
            rr = con.execute(
                "SELECT * FROM roulette_rounds WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 1", (chat_id,)
            ).fetchone()
            if not rr:
                raise NoBets()
            if self._parse_iso(rr["closes_at"]) <= datetime.now(timezone.utc):
                raise RoundClosed()
            bets = con.execute(
                "SELECT * FROM roulette_bets WHERE round_id=? AND user_id=? AND status='active'", (rr["id"], user_id)
            ).fetchall()
            if not bets:
                raise NoBets()
            total = sum(int(x["amount"]) for x in bets)
            self.economy._insert_operation(
                con,
                event_key=f"{event_key}:refund",
                user_id=user_id,
                kind="roulette_cancel",
                gentra_delta=total,
                meta={"round_id": rr["id"]},
            )
            con.execute(
                "UPDATE roulette_bets SET status='cancelled', settled_at=? WHERE round_id=? AND user_id=? AND status='active'",
                (utc_now(), rr["id"], user_id),
            )
            return total

    def double(self, chat_id: int, user_id: int, event_key: str) -> int:
        with self.db.transaction() as con:
            rr = con.execute(
                "SELECT * FROM roulette_rounds WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 1", (chat_id,)
            ).fetchone()
            if not rr or self._parse_iso(rr["closes_at"]) <= datetime.now(timezone.utc):
                raise RoundClosed()
            bets = con.execute(
                "SELECT * FROM roulette_bets WHERE round_id=? AND user_id=? AND status='active' ORDER BY id",
                (rr["id"], user_id),
            ).fetchall()
            if not bets:
                raise NoBets()
            extra = sum(int(b["amount"]) for b in bets)
            self.economy._insert_operation(
                con,
                event_key=f"{event_key}:debit",
                user_id=user_id,
                kind="roulette_double",
                gentra_delta=-extra,
                meta={"round_id": rr["id"]},
            )
            for b in bets:
                con.execute("UPDATE roulette_bets SET amount=amount*2 WHERE id=?", (b["id"],))
            return extra

    def repeat(self, chat_id: int, user_id: int, event_key: str):
        with self.db.connect() as con:
            last = con.execute(
                "SELECT bets_json FROM roulette_last_bets WHERE chat_id=? AND user_id=?", (chat_id, user_id)
            ).fetchone()
        if not last:
            raise NoPreviousBets()
        entries = json.loads(last["bets_json"])
        if not entries:
            raise NoPreviousBets()
        rr = self.get_or_create_round(chat_id)
        if self._parse_iso(rr["closes_at"]) <= datetime.now(timezone.utc):
            raise RoundClosed()
        total = sum(int(x["amount"]) for x in entries)
        try:
            with self.db.transaction() as con:
                cur = con.execute("SELECT * FROM roulette_rounds WHERE id=?", (rr["id"],)).fetchone()
                if not cur or cur["status"] != "open" or self._parse_iso(cur["closes_at"]) <= datetime.now(timezone.utc):
                    raise RoundClosed()
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=user_id,
                    kind="roulette_repeat",
                    gentra_delta=-total,
                    meta={"round_id": rr["id"]},
                )
                for x in entries:
                    con.execute(
                        "INSERT INTO roulette_bets(round_id,user_id,amount,bet_type,bet_value,status,created_at) VALUES(?,?,?,?,?,'active',?)",
                        (rr["id"], user_id, int(x["amount"]), x["bet_type"], x["bet_value"], utc_now()),
                    )
            return rr, total
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def due_rounds(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as con:
            return con.execute(
                "SELECT * FROM roulette_rounds WHERE status IN ('open','closing') AND closes_at<=? ORDER BY id", (now,)
            ).fetchall()

    def settle_round(self, round_id: int, forced_number: int | None = None) -> dict | None:
        number = self.rng.randrange(37) if forced_number is None else int(forced_number)
        if not 0 <= number <= 36:
            raise ValueError("roulette number out of range")
        with self.db.transaction() as con:
            rr = con.execute("SELECT * FROM roulette_rounds WHERE id=?", (round_id,)).fetchone()
            if not rr or rr["status"] == "settled":
                return None
            kyiv_day = self._parse_iso(rr["closes_at"]).astimezone(ZoneInfo("Europe/Kyiv")).date().isoformat()
            if rr["status"] == "open" and self._parse_iso(rr["closes_at"]) > datetime.now(timezone.utc) and forced_number is None:
                return None
            con.execute("UPDATE roulette_rounds SET status='settling', result_number=? WHERE id=?", (number, round_id))
            bets = con.execute(
                "SELECT * FROM roulette_bets WHERE round_id=? AND status='active' ORDER BY id", (round_id,)
            ).fetchall()
            total_payout = 0
            per_user_previous: dict[int, list[dict]] = {}
            for b in bets:
                payout = evaluate_payout(int(b["amount"]), b["bet_type"], b["bet_value"], number, self.config)
                total_payout += payout
                if payout:
                    self.economy._insert_operation(
                        con,
                        event_key=f"roulette:{round_id}:bet:{b['id']}:payout",
                        user_id=int(b["user_id"]),
                        kind="roulette_payout",
                        gentra_delta=payout,
                        meta={"round_id": round_id, "number": number, "bet_id": b["id"]},
                    )
                con.execute(
                    "UPDATE roulette_bets SET status='settled', payout=?, settled_at=? WHERE id=?",
                    (payout, utc_now(), b["id"]),
                )
                profit = payout - int(b["amount"])
                con.execute(
                    """INSERT INTO tournament_scores(day,type,subject_id,score,updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(day,type,subject_id) DO UPDATE SET score=score+excluded.score,updated_at=excluded.updated_at""",
                    (kyiv_day, "players", int(b["user_id"]), profit, utc_now()),
                )
                con.execute(
                    """INSERT INTO tournament_scores(day,type,subject_id,score,updated_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(day,type,subject_id) DO UPDATE SET score=score+excluded.score,updated_at=excluded.updated_at""",
                    (kyiv_day, "chats", int(rr["chat_id"]), int(b["amount"]), utc_now()),
                )
                per_user_previous.setdefault(int(b["user_id"]), []).append(
                    {"amount": int(b["amount"]), "bet_type": b["bet_type"], "bet_value": b["bet_value"]}
                )
            for uid, prev in per_user_previous.items():
                con.execute(
                    """INSERT INTO roulette_last_bets(chat_id,user_id,bets_json,updated_at) VALUES(?,?,?,?)
                       ON CONFLICT(chat_id,user_id) DO UPDATE SET bets_json=excluded.bets_json,updated_at=excluded.updated_at""",
                    (rr["chat_id"], uid, json.dumps(prev, ensure_ascii=False), utc_now()),
                )
            con.execute(
                "UPDATE roulette_rounds SET status='settled', settled_at=? WHERE id=?",
                (utc_now(), round_id),
            )
            return {
                "round_id": round_id,
                "chat_id": int(rr["chat_id"]),
                "number": number,
                "color": color_of(number),
                "bets": len(bets),
                "payout": total_payout,
            }
