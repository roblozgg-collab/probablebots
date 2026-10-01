from app.services.roulette import BetSpec, RouletteService, color_of, evaluate_payout, parse_bet_target


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


def test_recent_results_are_per_chat_and_newest_first(env):
    cfg, db, economy = env
    roulette = RouletteService(db, cfg, economy)
    for chat_id, number in ((100, 21), (100, 12), (200, 8), (100, 0), (100, 26)):
        row = roulette.get_or_create_round(chat_id)
        roulette.settle_round(int(row["id"]), forced_number=number)
    assert roulette.recent_results(100, 3) == [26, 0, 12]
    assert roulette.recent_results(200, 10) == [8]
    assert color_of(21) == "red"
    assert color_of(26) == "black"
    assert color_of(0) == "green"


def test_force_close_settles_without_waiting(env):
    cfg, db, economy = env
    roulette = RouletteService(db, cfg, economy)
    spec = parse_bet_target("красное")
    row = roulette.place_bet(100, 1, 100, spec, "roulette:go:bet")
    assert economy.balance(1).gentra == 900
    round_id = roulette.force_close(100)
    assert round_id == int(row["id"])
    result = roulette.settle_round(round_id, forced_number=1)
    assert result["number"] == 1
    assert economy.balance(1).gentra == 1100
    assert roulette.settle_round(round_id, forced_number=1) is None
