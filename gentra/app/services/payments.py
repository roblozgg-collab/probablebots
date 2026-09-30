from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import EconomyService


class PaymentError(Exception):
    pass


class PaymentInvalid(PaymentError):
    pass


class PaymentDuplicate(PaymentError):
    pass


class PaymentService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy

    def create_order(self, user_id: int, product_code: str):
        if product_code not in self.config.products:
            raise PaymentInvalid()
        stars, gentra = self.config.products[product_code]
        order_id = secrets.token_hex(12)
        payload_obj = {"v": 1, "o": order_id, "u": user_id, "p": product_code}
        payload = json.dumps(payload_obj, separators=(",", ":"))
        with self.db.transaction() as con:
            con.execute(
                "INSERT INTO payments(order_id,user_id,product_code,currency,amount,payload,status,created_at) VALUES(?,?,?,?,?,?, 'pending', ?)",
                (order_id, user_id, product_code, "XTR", int(stars), payload, utc_now()),
            )
        return {"order_id": order_id, "payload": payload, "stars": int(stars), "gentra": int(gentra), "product_code": product_code}

    def validate_precheckout(self, user_id: int, currency: str, amount: int, payload: str) -> bool:
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM payments WHERE payload=?", (payload,)).fetchone()
        return bool(
            row
            and row["status"] == "pending"
            and int(row["user_id"]) == int(user_id)
            and row["currency"] == "XTR"
            and currency == "XTR"
            and int(row["amount"]) == int(amount)
        )

    def settle(
        self,
        *,
        user_id: int,
        currency: str,
        amount: int,
        payload: str,
        telegram_charge_id: str,
        provider_charge_id: str = "",
    ) -> str:
        try:
            with self.db.transaction() as con:
                row = con.execute("SELECT * FROM payments WHERE payload=?", (payload,)).fetchone()
                if not row:
                    raise PaymentInvalid()
                if row["status"] == "paid":
                    if row["telegram_charge_id"] == telegram_charge_id:
                        raise PaymentDuplicate()
                    raise PaymentInvalid()
                if int(row["user_id"]) != int(user_id) or currency != "XTR" or row["currency"] != "XTR" or int(row["amount"]) != int(amount):
                    raise PaymentInvalid()
                product = row["product_code"]
                if product not in self.config.products:
                    raise PaymentInvalid()
                expected_stars, gentra = self.config.products[product]
                if int(expected_stars) != int(amount):
                    raise PaymentInvalid()
                if product == "vip":
                    user = con.execute("SELECT vip_until FROM users WHERE user_id=?", (user_id,)).fetchone()
                    now = datetime.now(timezone.utc)
                    base = now
                    if user and user["vip_until"]:
                        try:
                            current = datetime.fromisoformat(user["vip_until"])
                            if current > now:
                                base = current
                        except ValueError:
                            pass
                    until = base + timedelta(days=self.config.vip_days)
                    con.execute("UPDATE users SET vip_until=?,updated_at=? WHERE user_id=?", (until.isoformat(timespec="seconds"), utc_now(), user_id))
                    item = f"VIP {self.config.vip_days} days"
                else:
                    self.economy._insert_operation(
                        con,
                        event_key=f"payment:{telegram_charge_id}:credit",
                        user_id=user_id,
                        kind="stars_purchase",
                        gentra_delta=int(gentra),
                        meta={"order_id": row["order_id"], "stars": amount, "product": product},
                    )
                    item = f"{int(gentra):,} GENTRA"
                con.execute(
                    "UPDATE payments SET status='paid',telegram_charge_id=?,provider_charge_id=?,paid_at=? WHERE order_id=? AND status='pending'",
                    (telegram_charge_id, provider_charge_id, utc_now(), row["order_id"]),
                )
                return item
        except sqlite3.IntegrityError as exc:
            if "telegram_charge_id" in str(exc) or "UNIQUE" in str(exc):
                raise PaymentDuplicate() from exc
            raise
