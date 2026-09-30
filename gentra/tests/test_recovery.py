from datetime import datetime, timedelta, timezone

from app.services.roulette import RouletteService, parse_bet_target


def test_overdue_round_recovery_settles_only_once(env):
    cfg, db, economy = env
    roulette = RouletteService(db, cfg, economy)
    spec = parse_bet_target("17")
    rr = roulette.place_bet(1001, 1, 10, spec, "bet:recovery")
    with db.transaction() as con:
        con.execute(
            "UPDATE roulette_rounds SET closes_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds"), rr["id"]),
        )

    due = roulette.due_rounds()
    assert [int(r["id"]) for r in due] == [int(rr["id"])]

    result = roulette.settle_round(int(rr["id"]), forced_number=17)
    assert result["payout"] == 360
    assert economy.balance(1).gentra == 1350

    assert roulette.settle_round(int(rr["id"]), forced_number=17) is None
    assert economy.balance(1).gentra == 1350
