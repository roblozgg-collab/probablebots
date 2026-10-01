from app.command_aliases import is_duel_text_value, is_history_text, is_lang_text, is_profile_text, is_top_text


def test_profile_aliases():
    assert is_profile_text("/профиль")
    assert is_profile_text("профиль")
    assert is_profile_text("/профіль")
    assert is_profile_text("profile")


def test_history_aliases():
    assert is_history_text("/история")
    assert is_history_text("история")
    assert is_history_text("/історія")
    assert is_history_text("history")


def test_duel_aliases():
    assert is_duel_text_value("/дуэль")
    assert is_duel_text_value("дуэль")
    assert is_duel_text_value("/дуель")
    assert is_duel_text_value("duel")


def test_top_and_lang_aliases():
    assert is_top_text("/top 50")
    assert is_top_text("top 10")
    assert is_top_text("топ 5")
    assert is_top_text("/топ 3")
    assert is_lang_text("/lang ru")
    assert is_lang_text("lang uk")
