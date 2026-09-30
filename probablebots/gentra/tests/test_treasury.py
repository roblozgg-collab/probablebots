import pytest

from app.services.treasury import TreasuryInsufficient, TreasuryService


def test_invite_reward_once_and_balance(env):
    cfg, db, economy = env
    treasury = TreasuryService(db, cfg, economy)
    chat_id = -100123

    db.touch_chat_user(chat_id, 1, "Test")
    treasury.deposit(chat_id, 1, 1000, "seed-deposit")

    assert economy.balance(1).gentra == 0
    assert treasury.reward_inviter_once(chat_id, 2, 1) == 1000
    assert treasury.reward_inviter_once(chat_id, 2, 1) == 0
    assert economy.balance(1).gentra == cfg.start_gentra
    assert int(treasury.get(chat_id)["balance"]) == 0

    with pytest.raises(TreasuryInsufficient):
        treasury.reward_inviter_once(chat_id, 3, 1)
