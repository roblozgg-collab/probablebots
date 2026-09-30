from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, TelegramObject

from app.config import Config
from app.db import Database


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user:
            self.db.ensure_user(user.id, user.username, user.first_name)
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat
        if chat and user and chat.type in {"group", "supergroup"}:
            self.db.touch_chat_user(chat.id, user.id, chat.title or "")
        return await handler(event, data)


class BlockedAccessMiddleware(BaseMiddleware):
    def __init__(self, db: Database, config: Config):
        self.db = db
        self.admin_ids = set(config.admin_ids)

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user or user.id in self.admin_ids or not self.db.is_blocked(user.id):
            return await handler(event, data)
        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)
        if isinstance(event, PreCheckoutQuery):
            try:
                await event.answer(ok=False, error_message="Доступ к боту заблокирован.")
            except Exception:
                pass
            return None
        if isinstance(event, CallbackQuery):
            try:
                await event.answer("🚫 Доступ к боту заблокирован.", show_alert=True)
            except Exception:
                pass
            return None
        if isinstance(event, Message) and event.chat.type == "private":
            try:
                await event.answer("🚫 Доступ к боту заблокирован.")
            except Exception:
                pass
        return None


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, min_interval: float = 0.18):
        self.min_interval = min_interval
        self.last: dict[int, float] = defaultdict(float)

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)
        now = time.monotonic()
        limit = 0.08 if isinstance(event, CallbackQuery) else self.min_interval
        if now - self.last[user.id] < limit:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return None
        self.last[user.id] = now
        return await handler(event, data)
