import pytest

from app.services.blackjack import BlackjackFinished, BlackjackNotYours, BlackjackService
from app.services.dice import DiceGameFinished, DiceService


def test_blackjack_stand_regular_win(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["7♦", "10♥", "9♣", "Q♠"]
    row = game.start(1, 100, 100, "bj:1")
    assert row["status"] == "active"
    assert row["player_value"] == 19
    assert economy.balance(1).gentra == 900
    result = game.stand(row["game_id"], 1, "bj:1:stand")
    assert result["result"] == "win"
    assert result["player_value"] == 19
    assert result["dealer_value"] == 17
    assert result["payout"] == 150
    assert economy.balance(1).gentra == 1050
    with pytest.raises(BlackjackFinished):
        game.stand(row["game_id"], 1, "bj:1:again")


def test_blackjack_hit_to_twenty_one(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["2♦", "2♣", "5♦", "7♥", "9♣", "6♠", "10♦"]
    row = game.start(1, 100, 100, "bj:hit")
    assert row["player_value"] == 16
    result = game.hit(row["game_id"], 1, "bj:hit:1")
    assert result["status"] == "settled"
    assert result["player_value"] == 21
    assert result["dealer_value"] == 18
    assert result["result"] == "win"
    assert economy.balance(1).gentra == 1050


def test_blackjack_natural(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["8♦", "9♥", "K♣", "A♠"]
    result = game.start(1, 100, 100, "bj:2")
    assert result["status"] == "settled"
    assert result["result"] == "blackjack"
    assert result["payout"] == 200
    assert economy.balance(1).gentra == 1100


def test_blackjack_buttons_are_owner_only(env):
    cfg, db, economy = env
    game = BlackjackService(db, cfg, economy)
    game._deck = lambda: ["2♦", "2♣", "5♦", "7♥", "9♣", "6♠", "10♦"]
    row = game.start(1, 100, 100, "bj:owner")
    with pytest.raises(BlackjackNotYours):
        game.hit(row["game_id"], 2, "bj:foreign")
    assert economy.balance(1).gentra == 900


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
