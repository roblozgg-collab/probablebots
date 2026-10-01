from __future__ import annotations

import json
import math
import secrets
import sqlite3
import uuid

from app.config import Config
from app.db import Database, utc_now
from app.services.economy import DuplicateEvent, EconomyService, InvalidAmount


class BlackjackError(Exception):
    pass


class BlackjackNotFound(BlackjackError):
    pass


class BlackjackNotYours(BlackjackError):
    pass


class BlackjackFinished(BlackjackError):
    pass


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

    def _load(self, con: sqlite3.Connection, game_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
        game = con.execute("SELECT * FROM blackjack_games WHERE game_id=?", (game_id,)).fetchone()
        state = con.execute("SELECT * FROM blackjack_state WHERE game_id=?", (game_id,)).fetchone()
        if not game or not state:
            raise BlackjackNotFound()
        return game, state

    def _view(self, game: sqlite3.Row, state: sqlite3.Row) -> dict:
        return {
            "game_id": game["game_id"],
            "user_id": int(game["user_id"]),
            "chat_id": int(game["chat_id"]),
            "bet": int(game["bet"]),
            "player": json.loads(game["player_cards_json"]),
            "dealer": json.loads(game["dealer_cards_json"]),
            "player_value": int(game["player_value"]),
            "dealer_value": int(game["dealer_value"]),
            "result": game["result"],
            "payout": int(game["payout"]),
            "status": state["status"],
        }

    def _result(self, player: list[str], dealer: list[str], natural: bool = False) -> tuple[str, int]:
        player_value = self.hand_value(player)
        dealer_value = self.hand_value(dealer)
        bet_result = "lose"
        if player_value > 21:
            bet_result = "lose"
        elif dealer_value > 21 or player_value > dealer_value:
            bet_result = "blackjack" if natural else "win"
        elif player_value == dealer_value:
            bet_result = "push"
        return bet_result, dealer_value

    def _payout_for(self, bet: int, result: str) -> int:
        if result == "blackjack":
            return int(math.floor(bet * self.config.blackjack_natural_multiplier))
        if result == "win":
            return int(math.floor(bet * self.config.blackjack_win_multiplier))
        if result == "push":
            return bet
        return 0

    def _settle(self, con: sqlite3.Connection, game: sqlite3.Row, state: sqlite3.Row, natural: bool = False) -> dict:
        player = json.loads(game["player_cards_json"])
        dealer = json.loads(game["dealer_cards_json"])
        deck = json.loads(state["deck_json"])
        if self.hand_value(player) <= 21 and not natural:
            while self.hand_value(dealer) < self.config.blackjack_dealer_stand and deck:
                dealer.append(deck.pop())
        player_value = self.hand_value(player)
        dealer_value = self.hand_value(dealer)
        player_natural = len(player) == 2 and player_value == 21
        dealer_natural = len(dealer) == 2 and dealer_value == 21
        if player_natural and dealer_natural:
            result = "push"
        elif player_natural and natural:
            result = "blackjack"
        elif dealer_natural:
            result = "lose"
        elif player_value > 21:
            result = "lose"
        elif dealer_value > 21 or player_value > dealer_value:
            result = "win"
        elif player_value == dealer_value:
            result = "push"
        else:
            result = "lose"
        payout = self._payout_for(int(game["bet"]), result)
        if payout:
            self.economy._insert_operation(
                con,
                event_key=f"blackjack:{game['game_id']}:payout",
                user_id=int(game["user_id"]),
                kind="blackjack_payout",
                gentra_delta=payout,
                meta={"game_id": game["game_id"], "result": result},
            )
        con.execute(
            "UPDATE blackjack_games SET player_cards_json=?,dealer_cards_json=?,player_value=?,dealer_value=?,result=?,payout=? WHERE game_id=?",
            (
                json.dumps(player, ensure_ascii=False),
                json.dumps(dealer, ensure_ascii=False),
                player_value,
                dealer_value,
                result,
                payout,
                game["game_id"],
            ),
        )
        con.execute(
            "UPDATE blackjack_state SET deck_json=?,status='settled',updated_at=? WHERE game_id=?",
            (json.dumps(deck, ensure_ascii=False), utc_now(), game["game_id"]),
        )
        updated_game, updated_state = self._load(con, game["game_id"])
        return self._view(updated_game, updated_state)

    def start(self, user_id: int, chat_id: int, bet: int, event_key: str) -> dict:
        if bet < self.config.blackjack_min_bet:
            raise InvalidAmount()
        deck = self._deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        game_id = uuid.uuid4().hex[:16]
        player_value = self.hand_value(player)
        dealer_value = self.hand_value(dealer)
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
                con.execute(
                    "INSERT INTO blackjack_games(game_id,user_id,chat_id,bet,player_cards_json,dealer_cards_json,player_value,dealer_value,result,payout,created_at) VALUES(?,?,?,?,?,?,?,?,?,0,?)",
                    (
                        game_id,
                        user_id,
                        chat_id,
                        bet,
                        json.dumps(player, ensure_ascii=False),
                        json.dumps(dealer, ensure_ascii=False),
                        player_value,
                        dealer_value,
                        "active",
                        utc_now(),
                    ),
                )
                con.execute(
                    "INSERT INTO blackjack_state(game_id,deck_json,status,updated_at) VALUES(?,?,'active',?)",
                    (game_id, json.dumps(deck, ensure_ascii=False), utc_now()),
                )
                game, state = self._load(con, game_id)
                if player_value == 21 or dealer_value == 21:
                    return self._settle(con, game, state, natural=True)
                return self._view(game, state)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def get(self, game_id: str) -> dict:
        with self.db.connect() as con:
            game, state = self._load(con, game_id)
            return self._view(game, state)

    def hit(self, game_id: str, user_id: int, event_key: str) -> dict:
        try:
            with self.db.transaction() as con:
                game, state = self._load(con, game_id)
                if int(game["user_id"]) != user_id:
                    raise BlackjackNotYours()
                if state["status"] != "active" or game["result"] != "active":
                    raise BlackjackFinished()
                con.execute("INSERT INTO processed_events(event_key,created_at) VALUES(?,?)", (event_key, utc_now()))
                player = json.loads(game["player_cards_json"])
                deck = json.loads(state["deck_json"])
                if not deck:
                    raise BlackjackFinished()
                player.append(deck.pop())
                player_value = self.hand_value(player)
                con.execute(
                    "UPDATE blackjack_games SET player_cards_json=?,player_value=? WHERE game_id=?",
                    (json.dumps(player, ensure_ascii=False), player_value, game_id),
                )
                con.execute(
                    "UPDATE blackjack_state SET deck_json=?,updated_at=? WHERE game_id=?",
                    (json.dumps(deck, ensure_ascii=False), utc_now(), game_id),
                )
                game, state = self._load(con, game_id)
                if player_value >= 21:
                    return self._settle(con, game, state)
                return self._view(game, state)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise

    def stand(self, game_id: str, user_id: int, event_key: str) -> dict:
        try:
            with self.db.transaction() as con:
                game, state = self._load(con, game_id)
                if int(game["user_id"]) != user_id:
                    raise BlackjackNotYours()
                if state["status"] != "active" or game["result"] != "active":
                    raise BlackjackFinished()
                con.execute("INSERT INTO processed_events(event_key,created_at) VALUES(?,?)", (event_key, utc_now()))
                return self._settle(con, game, state)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEvent(event_key) from exc
            raise
