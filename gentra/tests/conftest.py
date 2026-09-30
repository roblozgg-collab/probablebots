from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config
from app.db import Database
from app.services.economy import EconomyService


@pytest.fixture
def env(tmp_path):
    cfg = Config(
        bot_token="test-token",
        db_path=tmp_path / "test.sqlite3",
        start_gentra=1_000,
        start_galleons=2_000,
        clan_create_cost=100,
        roulette_round_seconds=45,
    )
    db = Database(cfg.db_path, cfg)
    db.init()
    for uid in (1, 2, 3, 4):
        db.ensure_user(uid, f"u{uid}", f"User {uid}")
    economy = EconomyService(db, cfg)
    return cfg, db, economy
