import pytest

from app.services.blackjack import BlackjackService
from app.services.dice import DiceGameFinished, DiceService


def test_blackjack_regular_win(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["7♦", "10♥", "9♣", "Q♠"]
    result = game.play(1, 100, 100, "bj:1")
    assert result["result"] == "win"
    assert result["player_value"] == 19
    assert result["dealer_value"] == 17
    assert result["payout"] == 150
    assert economy.balance(1).gentra == 1050


def test_blackjack_natural(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["8♦", "9♥", "K♣", "A♠"]
    result = game.play(1, 100, 100, "bj:2")
    assert result["result"] == "blackjack"
    assert result["payout"] == 200
    assert economy.balance(1).gentra == 1100


def test_dice_high_settles_once(env):
    cfg, db, economy = env
    game = DiceService(db, cfg, economy)
    row = game.start(1, 100, 100, "high", "dice:1")
    assert economy.balance(1).gentra == 900
    win, payout = game.settle(row["game_id"], 6)
    assert win is True
    assert payout == 200
    assert economy.balance(1).gentra == 1100
    with pytest.raises(DiceGameFinished):
        game.settle(row["game_id"], 6)
    assert economy.balance(1).gentra == 1100


def test_dice_cancel_refunds(env):
    cfg, db, economy = env
    game = DiceService(db, cfg, economy)
    row = game.start(1, 100, 100, "low", "dice:2")
    assert game.cancel(row["game_id"]) is True
    assert economy.balance(1).gentra == 1000


def test_username_lookup(env):
    cfg, db, economy = env
    row = db.get_user_by_username("@U2")
    assert row is not None
    assert int(row["user_id"]) == 2


def test_dice_restart_refunds_pending(env):
    cfg, db, economy = env
    game = DiceService(db, cfg, economy)
    game.start(1, 100, 100, "high", "dice:restart")
    assert economy.balance(1).gentra == 900
    assert game.refund_pending() == 1
    assert economy.balance(1).gentra == 1000
    assert game.refund_pending() == 0
