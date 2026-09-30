from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from app.config import Config
from app.db import Database
from app.i18n import all_texts, t
from app.keyboards import donate_keyboard
from app.routers.common import lang_for_callback, lang_for_message
from app.services.payments import PaymentDuplicate, PaymentInvalid, PaymentService

router = Router(name="payments")


@router.message(lambda m: bool(m.text and m.text.strip() in all_texts("donate")))
async def donate(message: Message, db: Database, config: Config):
    lang = lang_for_message(message, db)
    await message.answer(
        t(lang, "donate_text", vip_days=config.vip_days, vip_bonus_hours=config.vip_bonus_period_hours),
        reply_markup=donate_keyboard(config.products),
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy(call: CallbackQuery, db: Database, payments: PaymentService, bot: Bot):
    lang = lang_for_callback(call, db)
    if call.message.chat.type != "private":
        await call.answer(t(lang, "private_only"), show_alert=True); return
    code = call.data.split(":", 1)[1]
    try:
        order = payments.create_order(call.from_user.id, code)
    except PaymentInvalid:
        await call.answer(t(lang, "payment_bad"), show_alert=True); return
    if code == "vip":
        title = "gentra VIP"
        desc = f"VIP for {payments.config.vip_days} days"
    else:
        title = "GENTRA"
        desc = f"{order['gentra']:,} GENTRA"
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=title,
        description=desc,
        payload=order["payload"],
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=order["stars"])],
    )
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, db: Database, payments: PaymentService):
    ok = payments.validate_precheckout(query.from_user.id, query.currency, query.total_amount, query.invoice_payload)
    lang = db.get_user_language(query.from_user.id)
    await query.answer(ok=ok, error_message=None if ok else t(lang, "payment_precheckout_error"))


@router.message(F.successful_payment)
async def successful_payment(message: Message, db: Database, payments: PaymentService):
    lang = lang_for_message(message, db)
    p = message.successful_payment
    try:
        item = payments.settle(
            user_id=message.from_user.id,
            currency=p.currency,
            amount=p.total_amount,
            payload=p.invoice_payload,
            telegram_charge_id=p.telegram_payment_charge_id,
            provider_charge_id=p.provider_payment_charge_id or "",
        )
    except PaymentDuplicate:
        await message.answer(t(lang, "payment_duplicate")); return
    except PaymentInvalid:
        await message.answer(t(lang, "payment_bad")); return
    await message.answer(t(lang, "payment_ok", item=item))


@router.message(Command("support_payments"))
async def payment_support(message: Message, db: Database, config: Config):
    lang = lang_for_message(message, db)
    await message.answer(t(lang, "payment_support", contact=config.support_contact, user_id=message.from_user.id))
