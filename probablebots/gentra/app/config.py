from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv


@dataclass(slots=True)
class Config:
    bot_token: str
    db_path: Path = Path("gentra.sqlite3")
    support_contact: str = "@support"
    news_url: str = "https://t.me/"
    general_chat_url: str = "https://t.me/"
    roulette_chat_url: str = "https://t.me/"
    admin_ids: tuple[int, ...] = ()

    start_gentra: int = 1_000
    start_galleons: int = 2_000
    start_stat: int = 1

    stat_base_cost: int = 10
    stat_growth: float = 1.35

    roulette_round_seconds: int = 45
    roulette_min_bet: int = 1
    roulette_max_bet: int = 1_000_000_000
    roulette_range_house_factor: float = 0.97

    mines_rows: int = 5
    mines_cols: int = 5
    mines_count: int = 5
    mines_house_factor: float = 0.96
    mines_min_bet: int = 1

    joker_slots: int = 3
    joker_payout_multiplier: float = 2.85
    joker_min_bet: int = 1

    duel_reward: int = 250
    duel_cooldown_seconds: int = 300

    clan_create_cost: int = 50_000
    clan_member_limit: int = 50

    treasury_reward_min: int = 1_000
    treasury_reward_max: int = 2_000
    treasury_default_reward: int = 1_000

    bonus_amount: int = 5_000
    bonus_period_hours: int = 24
    vip_bonus_period_hours: int = 20
    vip_days: int = 30

    participant_prizes: tuple[int, ...] = (
        1_000_000,
        500_000,
        300_000,
        200_000,
        100_000,
        75_000,
        50_000,
        30_000,
        20_000,
        10_000,
    )
    chat_prizes: tuple[int, ...] = (250_000, 150_000, 100_000)

    products: Dict[str, tuple[int, int]] = field(
        default_factory=lambda: {
            "g50": (50, 100_000),
            "g100": (100, 204_000),
            "g250": (250, 525_000),
            "g500": (500, 1_150_000),
            "g1000": (1_000, 2_300_000),
            "g2500": (2_500, 6_250_000),
            "vip": (100, 0),
        }
    )


def _parse_admin_ids(value: str) -> tuple[int, ...]:
    result = []
    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if item:
            result.append(int(item))
    return tuple(dict.fromkeys(result))


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and set the token.")

    return Config(
        bot_token=token,
        db_path=Path(os.getenv("DB_PATH", "gentra.sqlite3")),
        support_contact=os.getenv("SUPPORT_CONTACT", "@support"),
        news_url=os.getenv("NEWS_URL", "https://t.me/"),
        general_chat_url=os.getenv("GENERAL_CHAT_URL", "https://t.me/"),
        roulette_chat_url=os.getenv("ROULETTE_CHAT_URL", "https://t.me/"),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        start_gentra=int(os.getenv("START_GENTRA", "1000")),
        start_galleons=int(os.getenv("START_GALLEONS", "2000")),
        start_stat=int(os.getenv("START_STAT", "1")),
        stat_base_cost=int(os.getenv("STAT_BASE_COST", "10")),
        stat_growth=float(os.getenv("STAT_GROWTH", "1.35")),
        roulette_round_seconds=int(os.getenv("ROULETTE_ROUND_SECONDS", "45")),
        roulette_min_bet=int(os.getenv("ROULETTE_MIN_BET", "1")),
        roulette_max_bet=int(os.getenv("ROULETTE_MAX_BET", "1000000000")),
        roulette_range_house_factor=float(os.getenv("ROULETTE_RANGE_HOUSE_FACTOR", "0.97")),
        mines_rows=int(os.getenv("MINES_ROWS", "5")),
        mines_cols=int(os.getenv("MINES_COLS", "5")),
        mines_count=int(os.getenv("MINES_COUNT", "5")),
        mines_house_factor=float(os.getenv("MINES_HOUSE_FACTOR", "0.96")),
        mines_min_bet=int(os.getenv("MINES_MIN_BET", "1")),
        joker_slots=int(os.getenv("JOKER_SLOTS", "3")),
        joker_payout_multiplier=float(os.getenv("JOKER_PAYOUT_MULTIPLIER", "2.85")),
        joker_min_bet=int(os.getenv("JOKER_MIN_BET", "1")),
        duel_reward=int(os.getenv("DUEL_REWARD", "250")),
        duel_cooldown_seconds=int(os.getenv("DUEL_COOLDOWN_SECONDS", "300")),
        clan_create_cost=int(os.getenv("CLAN_CREATE_COST", "50000")),
        clan_member_limit=int(os.getenv("CLAN_MEMBER_LIMIT", "50")),
        treasury_reward_min=int(os.getenv("TREASURY_REWARD_MIN", "1000")),
        treasury_reward_max=int(os.getenv("TREASURY_REWARD_MAX", "2000")),
        treasury_default_reward=int(os.getenv("TREASURY_DEFAULT_REWARD", "1000")),
        bonus_amount=int(os.getenv("BONUS_AMOUNT", "5000")),
        bonus_period_hours=int(os.getenv("BONUS_PERIOD_HOURS", "24")),
        vip_bonus_period_hours=int(os.getenv("VIP_BONUS_PERIOD_HOURS", "20")),
        vip_days=int(os.getenv("VIP_DAYS", "30")),
    )
