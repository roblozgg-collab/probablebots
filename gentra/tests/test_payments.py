import pytest

from app.services.payments import PaymentDuplicate, PaymentInvalid, PaymentService


def test_stars_order_validates_and_settles_once(env):
    cfg, db, economy = env
    payments = PaymentService(db, cfg, economy)
    order = payments.create_order(1, "g50")

    assert payments.validate_precheckout(1, "XTR", 50, order["payload"])
    assert not payments.validate_precheckout(2, "XTR", 50, order["payload"])
    assert not payments.validate_precheckout(1, "USD", 50, order["payload"])
    assert not payments.validate_precheckout(1, "XTR", 49, order["payload"])

    item = payments.settle(
        user_id=1,
        currency="XTR",
        amount=50,
        payload=order["payload"],
        telegram_charge_id="tg-charge-1",
    )
    assert "100,000" in item
    assert economy.balance(1).gentra == 101_000

    with pytest.raises(PaymentDuplicate):
        payments.settle(
            user_id=1,
            currency="XTR",
            amount=50,
            payload=order["payload"],
            telegram_charge_id="tg-charge-1",
        )
    assert economy.balance(1).gentra == 101_000


def test_payment_rejects_wrong_amount(env):
    cfg, db, economy = env
    payments = PaymentService(db, cfg, economy)
    order = payments.create_order(1, "g100")
    with pytest.raises(PaymentInvalid):
        payments.settle(
            user_id=1,
            currency="XTR",
            amount=99,
            payload=order["payload"],
            telegram_charge_id="wrong",
        )
