from app.services.economy import EconomyService


def test_admin_settings_and_blocking(env):
    cfg, db, economy = env
    db.set_setting("NEWS_URL", "https://t.me/new_channel")
    assert db.get_setting("NEWS_URL", "x") == "https://t.me/new_channel"
    assert 2 in db.all_user_ids()
    db.block_user(2, 1)
    assert db.is_blocked(2)
    assert 2 not in db.all_user_ids()
    assert 2 in db.all_user_ids(include_blocked=True)
    db.unblock_user(2)
    assert not db.is_blocked(2)


def test_admin_balance_is_journaled(env):
    cfg, db, economy = env
    before = economy.balance(2)
    economy.change(2, gentra_delta=9000, kind="admin_set_gentra", event_key="admin:test:balance", meta={"admin_id": 1})
    after = economy.balance(2)
    assert after.gentra == before.gentra + 9000
    rows = economy.recent_operations(2, 1)
    assert rows[0]["kind"] == "admin_set_gentra"


def test_admin_stats_edit(env):
    cfg, db, economy = env
    db.set_user_stat(3, "strength", 77)
    assert int(db.get_user(3)["strength"]) == 77
