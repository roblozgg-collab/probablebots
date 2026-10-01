from __future__ import annotations

import html

from app.db import Database


def display_user(db: Database, user_id: int) -> str:
    row = db.get_user(user_id)
    if not row:
        return "игрок"
    username = (row["username"] or "").strip()
    if username:
        return f"@{html.escape(username)}"
    first_name = (row["first_name"] or "").strip()
    return html.escape(first_name) if first_name else "игрок"


def display_row(row) -> str:
    username = (row["username"] or "").strip()
    if username:
        return f"@{html.escape(username)}"
    first_name = (row["first_name"] or "").strip()
    return html.escape(first_name) if first_name else "игрок"
