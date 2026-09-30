from app.services.tournaments import TournamentService


def test_tournament_award_once(env):
    cfg, db, economy = env
    service = TournamentService(db, cfg, economy)
    day = "2026-09-28"
    with db.transaction() as con:
        con.execute(
            "INSERT INTO tournament_scores(day,type,subject_id,score,updated_at) VALUES(?,?,?,?,?)",
            (day, "players", 1, 500, "2026-09-28T20:00:00+00:00"),
        )
    before = economy.balance(1).gentra
    first = service.finalize(day, "players")
    after = economy.balance(1).gentra
    second = service.finalize(day, "players")
    assert len(first) == 1
    assert after - before == cfg.participant_prizes[0]
    assert second == []
    assert economy.balance(1).gentra == after
