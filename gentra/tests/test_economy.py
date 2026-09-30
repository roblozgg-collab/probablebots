import pytest

from app.services.economy import DuplicateEvent, InsufficientFunds, SelfTransfer


def test_transfer_is_atomic_and_idempotent(env):
    cfg, db, economy = env
    economy.transfer(1, 2, 250, "transfer:1")
    assert economy.balance(1).gentra == 750
    assert economy.balance(2).gentra == 1250

    with pytest.raises(DuplicateEvent):
        economy.transfer(1, 2, 250, "transfer:1")

    assert economy.balance(1).gentra == 750
    assert economy.balance(2).gentra == 1250


def test_transfer_guards(env):
    cfg, db, economy = env
    with pytest.raises(SelfTransfer):
        economy.transfer(1, 1, 10, "self")
    with pytest.raises(InsufficientFunds):
        economy.transfer(1, 2, 10_000, "too-much")
    assert economy.balance(1).gentra == 1000
