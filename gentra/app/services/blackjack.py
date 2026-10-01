from __future__ import annotations

import json
import math
import secrets
import sqlite3
import uuid

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InvalidAmount


class BlackjackService:
    def __init__(self, db: Database, config: Config, economy: EconomyService):
        self.db = db
        self.config = config
        self.economy = economy
        self.rng = secrets.SystemRandom()

    @staticmethod
    def hand_value(cards: list[str]) -> int:
        total = 0
        aces = 0
        for card in cards:
            rank = card[:-1]
            if rank == "A":
                total += 11
                aces += 1
            elif rank in {"J", "Q", "K"}:
                total += 10
            else:
                total += int(rank)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def _deck(self) -> list[str]:
        suits = ["♥", "♦", "♣", "♠"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = [rank + suit for suit in suits for rank in ranks]
        self.rng.shuffle(deck)
        return deck

    def play(self, user_id: int, chat_id: int, bet: int, event_key: str) -> dict:
        if bet < self.config.blackjack_min_bet:
            raise InvalidAmount()
        deck = self._deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        player_natural = self.hand_value(player) == 21
        dealer_natural = self.hand_value(dealer) == 21
        while self.hand_value(player) < self.config.blackjack_player_stand:
            player.append(deck.pop())
        while self.hand_value(dealer) < self.config.blackjack_dealer_stand:
            dealer.append(deck.pop())
        player_value = self.hand_value(player)
        dealer_value = self.hand_value(dealer)
        if player_natural and not dealer_natural:
            result = "blackjack"
            payout = int(math.floor(bet * self.config.blackjack_natural_multiplier))
        elif dealer_natural and not player_natural:
            result = "lose"
            payout = 0
        elif player_value > 21:
            result = "lose"
            payout = 0
        elif dealer_value > 21 or player_value > dealer_value:
            result = "win"
            payout = int(math.floor(bet * self.config.blackjack_win_multiplier))
        elif player_value == dealer_value:
            result = "push"
            payout = bet
        else:
            result = "lose"
            payout = 0
        game_id = uuid.uuid4().hex[:16]
        try:
            with self.db.transaction() as con:
                self.economy._insert_operation(
                    con,
                    event_key=f"{event_key}:debit",
                    user_id=user_id,
                    kind="blackjack_bet",
                    gentra_delta=-bet,
                    meta={"game_id": game_id},
                )
                if payout:
                    self.economy._insert_operation(
                        con,
                        event_key=f"{event_key}:payout",
                        user_id=user_id,
                        kind="blackjack_payout",
                        gentra_delta=payout,
                        meta={"game_id": game_id, "result": result},
                    )
                con.execute(
                    """INSERT INTO blackjack_games(game_id,user_id,chat_id,bet,player_cards_json,dealer_cards_json,player_value,dealer_value,result,payout,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        game_id,
                        user_id,
                        chat_id,
                        bet,
                        json.dumps(player, ensure_ascii=False),
                        json.dumps(dealer, ensure_ascii=False),
                        player_value,
                        dealer_value,
                        result,
                        payout,
                        utc_now(),
                    ),
                )
            return {
                "game_id": game_id,
                "bet": bet,
                "player": player,
                "dealer": dealer,
                "player_value": player_value,
                "dealer_value": dealer_value,
                "result": result,
                "payout": payout,
            }
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise
