def is_lang_text(text: str | None) -> bool:
    value = (text or "").strip().lower()
    head = value.split(maxsplit=1)[0] if value else ""
    return head in {"lang", "/lang"} or head.startswith("/lang@")


def is_profile_text(text: str | None) -> bool:
    value = (text or "").strip().lower()
    return value in {"профиль", "profile", "профіль"} or value.startswith(("/профиль", "/профіль"))


def is_history_text(text: str | None) -> bool:
    value = (text or "").strip().lower()
    return value in {"история", "історія", "history"} or value.startswith(("/история", "/історія"))


def is_top_text(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    head = value.split(maxsplit=1)[0]
    return head in {"top", "топ", "/top", "/топ"} or head.startswith("/top@") or head.startswith("/топ@")


def is_duel_text_value(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if value in {"дуэль", "дуель", "duel", "/дуэль", "/дуель"}:
        return True
    return value.startswith(("/дуэль@", "/дуель@"))
