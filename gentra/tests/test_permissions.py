import pytest

from app.services.clans import ClanPermission, ClanService


def test_clan_roles_enforced(env):
    cfg, db, economy = env
    clans = ClanService(db, cfg, economy)
    clan = clans.create(1, "Aurors", "create:1")
    clans.join_open(int(clan["clan_id"]), 2)

    assert clans.can_manage(1) is True
    assert clans.can_manage(2) is False

    with pytest.raises(ClanPermission):
        clans.invite(2, 3)

    clans.set_deputy(1, 2)
    assert clans.can_manage(2) is True
    invite, _ = clans.invite(2, 3)
    assert int(invite["invitee_id"]) == 3
