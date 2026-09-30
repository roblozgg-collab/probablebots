import pytest

from app.services.bonus import BonusCooldown, BonusService
from app.services.economy import DuplicateEvent


def test_bonus_claim_is_direct_and_cooldown_is_enforced(env):
    cfg, db, economy = env
    bonus = BonusService(db, cfg, economy)
    before = economy.balance(1).gentra
    amount = bonus.claim(1, "bonus:first")
    assert amount == cfg.bonus_amount
    assert economy.balance(1).gentra == before + cfg.bonus_amount
    with pytest.raises(BonusCooldown):
        bonus.claim(1, "bonus:second")


def test_bonus_event_is_idempotent(env):
    cfg, db, economy = env
    bonus = BonusService(db, cfg, economy)
    bonus.claim(1, "bonus:same")
    with pytest.raises((BonusCooldown, DuplicateEvent)):
        bonus.claim(1, "bonus:same")
    with db.connect() as con:
        claims = con.execute("SELECT COUNT(*) FROM bonus_claims WHERE user_id=1").fetchone()[0]
    assert claims == 1
