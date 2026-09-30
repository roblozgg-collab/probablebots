from app.services.roulette import BetSpec, evaluate_payout, parse_bet_target


def test_standard_payouts(env):
    cfg, db, economy = env
    assert evaluate_payout(100, "number", "17", 17, cfg) == 3600
    assert evaluate_payout(100, "number", "17", 18, cfg) == 0
    assert evaluate_payout(100, "color", "red", 1, cfg) == 200
    assert evaluate_payout(100, "color", "red", 0, cfg) == 0
    assert evaluate_payout(100, "parity", "even", 2, cfg) == 200
    assert evaluate_payout(100, "parity", "even", 0, cfg) == 0


def test_parser_supports_range_and_aliases(env):
    assert parse_bet_target("красное").value == "red"
    assert parse_bet_target("black").value == "black"
    assert parse_bet_target("0").value == "0"
    spec = parse_bet_target("1-12")
    assert spec.bet_type == "range" and spec.value == "1-12"
