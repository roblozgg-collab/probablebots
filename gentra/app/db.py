from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import Config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'ru',
    gentra INTEGER NOT NULL,
    galleons INTEGER NOT NULL,
    block INTEGER NOT NULL,
    endurance INTEGER NOT NULL,
    health INTEGER NOT NULL,
    intuition INTEGER NOT NULL,
    strength INTEGER NOT NULL,
    speed INTEGER NOT NULL,
    charisma INTEGER NOT NULL,
    clan_id INTEGER,
    vip_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_settings (
    chat_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'ru',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    gentra_delta INTEGER NOT NULL DEFAULT 0,
    galleons_delta INTEGER NOT NULL DEFAULT 0,
    balance_gentra INTEGER NOT NULL,
    balance_galleons INTEGER NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operations_user ON operations(user_id, id DESC);

CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    from_user INTEGER NOT NULL,
    to_user INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roulette_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    result_number INTEGER,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_roulette_rounds_due ON roulette_rounds(status, closes_at);
CREATE INDEX IF NOT EXISTS idx_roulette_rounds_chat ON roulette_rounds(chat_id, id DESC);

CREATE TABLE IF NOT EXISTS roulette_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    bet_type TEXT NOT NULL,
    bet_value TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    settled_at TEXT,
    FOREIGN KEY(round_id) REFERENCES roulette_rounds(id)
);
CREATE INDEX IF NOT EXISTS idx_roulette_bets_round ON roulette_bets(round_id, status);
CREATE INDEX IF NOT EXISTS idx_roulette_bets_user ON roulette_bets(user_id, id DESC);

CREATE TABLE IF NOT EXISTS roulette_last_bets (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    bets_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS mines_games (
    game_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    bet INTEGER NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    mines_count INTEGER NOT NULL,
    mines_json TEXT NOT NULL,
    revealed_json TEXT NOT NULL,
    status TEXT NOT NULL,
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS joker_games (
    game_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    bet INTEGER NOT NULL,
    joker_pos INTEGER NOT NULL,
    slots INTEGER NOT NULL,
    multiplier REAL NOT NULL,
    status TEXT NOT NULL,
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blackjack_games (
    game_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    bet INTEGER NOT NULL,
    player_cards_json TEXT NOT NULL,
    dealer_cards_json TEXT NOT NULL,
    player_value INTEGER NOT NULL,
    dealer_value INTEGER NOT NULL,
    result TEXT NOT NULL,
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blackjack_user ON blackjack_games(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dice_games (
    game_id TEXT PRIMARY KEY,
    start_event_key TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    bet INTEGER NOT NULL,
    choice TEXT NOT NULL,
    status TEXT NOT NULL,
    result INTEGER,
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dice_user ON dice_games(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS duels (
    duel_id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    challenger_id INTEGER NOT NULL,
    opponent_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    winner_id INTEGER,
    challenger_score INTEGER,
    opponent_score INTEGER,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_duels_user1 ON duels(challenger_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_duels_user2 ON duels(opponent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS duel_cooldowns (
    user_id INTEGER PRIMARY KEY,
    last_duel_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clans (
    clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    owner_id INTEGER NOT NULL,
    deputy_id INTEGER,
    treasury INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clan_members (
    clan_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TEXT NOT NULL,
    PRIMARY KEY(clan_id, user_id),
    FOREIGN KEY(clan_id) REFERENCES clans(clan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_clan_members_clan ON clan_members(clan_id);

CREATE TABLE IF NOT EXISTS clan_invites (
    invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    invitee_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(clan_id) REFERENCES clans(clan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_clan_invites_user ON clan_invites(invitee_id, status, invite_id DESC);

CREATE TABLE IF NOT EXISTS tournament_scores (
    day TEXT NOT NULL,
    type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(day, type, subject_id)
);

CREATE TABLE IF NOT EXISTS tournament_finalizations (
    day TEXT NOT NULL,
    type TEXT NOT NULL,
    finalized_at TEXT NOT NULL,
    PRIMARY KEY(day, type)
);

CREATE TABLE IF NOT EXISTS tournament_awards (
    award_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    type TEXT NOT NULL,
    rank INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    reward INTEGER NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_treasury (
    chat_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    reward_amount INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_invite_rewards (
    chat_id INTEGER NOT NULL,
    new_user_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(chat_id, new_user_id)
);

CREATE TABLE IF NOT EXISTS bonus_claims (
    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    claimed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bonus_claims_user ON bonus_claims(user_id, claimed_at DESC);

CREATE TABLE IF NOT EXISTS payments (
    order_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product_code TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount INTEGER NOT NULL,
    payload TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    telegram_charge_id TEXT UNIQUE,
    provider_charge_id TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bot_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_blocks (
    user_id INTEGER PRIMARY KEY,
    blocked_by INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcasts (
    broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


class Database:
    def __init__(self, path: Path | str, config: Optional[Config] = None):
        self.path = str(path)
        self.config = config

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        if not self.config:
            raise RuntimeError("Database requires Config for ensure_user")
        now = utc_now()
        with self.transaction() as con:
            con.execute(
                """
                INSERT INTO users(
                    user_id, username, first_name, language, gentra, galleons,
                    block, endurance, health, intuition, strength, speed, charisma,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'ru', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    username,
                    first_name or "",
                    self.config.start_gentra,
                    self.config.start_galleons,
                    *([self.config.start_stat] * 7),
                    now,
                    now,
                ),
            )

    def touch_chat_user(self, chat_id: int, user_id: int, title: str = "") -> None:
        now = utc_now()
        with self.transaction() as con:
            con.execute(
                "INSERT INTO chat_users(chat_id,user_id,last_seen_at) VALUES(?,?,?) "
                "ON CONFLICT(chat_id,user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                (chat_id, user_id, now),
            )
            con.execute(
                "INSERT INTO group_settings(chat_id,title,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
                (chat_id, title or "", now, now),
            )

    def get_user(self, user_id: int):
        with self.connect() as con:
            return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def get_user_by_username(self, username: str):
        value = username.strip().lstrip("@").casefold()
        if not value:
            return None
        with self.connect() as con:
            return con.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (value,)).fetchone()

    def get_user_language(self, user_id: int) -> str:
        row = self.get_user(user_id)
        return (row["language"] if row else "ru") or "ru"

    def get_group_language(self, chat_id: int) -> str:
        with self.connect() as con:
            row = con.execute("SELECT language FROM group_settings WHERE chat_id=?", (chat_id,)).fetchone()
            return (row["language"] if row else "ru") or "ru"

    def set_user_language(self, user_id: int, lang: str) -> None:
        with self.transaction() as con:
            con.execute("UPDATE users SET language=?, updated_at=? WHERE user_id=?", (lang, utc_now(), user_id))

    def set_group_language(self, chat_id: int, lang: str) -> None:
        now = utc_now()
        with self.transaction() as con:
            con.execute(
                "INSERT INTO group_settings(chat_id,language,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET language=excluded.language, updated_at=excluded.updated_at",
                (chat_id, lang, now, now),
            )

    def mark_event_once(self, event_key: str) -> bool:
        try:
            with self.transaction() as con:
                con.execute("INSERT INTO processed_events(event_key,created_at) VALUES(?,?)", (event_key, utc_now()))
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def dump_meta(data: dict | None) -> str:
        return json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as con:
            row = con.execute("SELECT setting_value FROM bot_settings WHERE setting_key=?", (key,)).fetchone()
            return str(row["setting_value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        now = utc_now()
        with self.transaction() as con:
            con.execute(
                "INSERT INTO bot_settings(setting_key,setting_value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at",
                (key, value, now),
            )

    def is_blocked(self, user_id: int) -> bool:
        with self.connect() as con:
            return con.execute("SELECT 1 FROM bot_blocks WHERE user_id=?", (user_id,)).fetchone() is not None

    def block_user(self, user_id: int, blocked_by: int, reason: str = "") -> None:
        with self.transaction() as con:
            con.execute(
                "INSERT INTO bot_blocks(user_id,blocked_by,reason,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET blocked_by=excluded.blocked_by, reason=excluded.reason, created_at=excluded.created_at",
                (user_id, blocked_by, reason, utc_now()),
            )

    def unblock_user(self, user_id: int) -> None:
        with self.transaction() as con:
            con.execute("DELETE FROM bot_blocks WHERE user_id=?", (user_id,))

    def all_user_ids(self, include_blocked: bool = False) -> list[int]:
        with self.connect() as con:
            if include_blocked:
                rows = con.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()
            else:
                rows = con.execute(
                    "SELECT u.user_id FROM users u LEFT JOIN bot_blocks b ON b.user_id=u.user_id "
                    "WHERE b.user_id IS NULL ORDER BY u.user_id"
                ).fetchall()
            return [int(row["user_id"]) for row in rows]

    def user_count(self) -> int:
        with self.connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def blocked_count(self) -> int:
        with self.connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM bot_blocks").fetchone()[0])

    def set_user_stat(self, user_id: int, stat: str, value: int) -> None:
        allowed = {"block", "endurance", "health", "intuition", "strength", "speed", "charisma"}
        if stat not in allowed:
            raise ValueError("unknown stat")
        if value < 0:
            raise ValueError("negative stat")
        with self.transaction() as con:
            cur = con.execute(f"UPDATE users SET {stat}=?, updated_at=? WHERE user_id=?", (value, utc_now(), user_id))
            if cur.rowcount != 1:
                raise LookupError(user_id)

    def create_broadcast(self, admin_id: int, source_chat_id: int, source_message_id: int, total: int) -> int:
        with self.transaction() as con:
            cur = con.execute(
                "INSERT INTO broadcasts(admin_id,source_chat_id,source_message_id,total,created_at) VALUES(?,?,?,?,?)",
                (admin_id, source_chat_id, source_message_id, total, utc_now()),
            )
            return int(cur.lastrowid)

    def finish_broadcast(self, broadcast_id: int, delivered: int, failed: int) -> None:
        with self.transaction() as con:
            con.execute(
                "UPDATE broadcasts SET delivered=?, failed=?, finished_at=? WHERE broadcast_id=?",
                (delivered, failed, utc_now(), broadcast_id),
            )

