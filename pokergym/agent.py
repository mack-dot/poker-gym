"""Rehearsal Agent protocol.

This is OUR approximation of the organizer's Python ``Agent`` interface. The
official method names, observation fields and action encoding are unknown.
Keep bots coded against this module; ``adapters.py`` is the seam where the
real starter-kit interface will be bridged in.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable

from .cards import card_str


class ActionType(IntEnum):
    FOLD = 0
    CHECK = 1
    CALL = 2
    RAISE = 3  # ``amount`` is the total bet-to amount for this street

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionType
    amount: int = 0

    # --- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return {"action": self.kind.name.lower(), "amount": int(self.amount)}

    @staticmethod
    def from_dict(d: dict) -> "Action":
        return Action(ActionType[str(d["action"]).upper()], int(d.get("amount", 0)))

    def serialize(self) -> str:
        return f"{self.kind.name.lower()}:{self.amount}" if self.kind == ActionType.RAISE else self.kind.name.lower()

    @staticmethod
    def parse(text: str) -> "Action":
        text = text.strip().lower()
        if ":" in text:
            k, a = text.split(":", 1)
            return Action(ActionType[k.upper()], int(a))
        return Action(ActionType[text.upper()])


FOLD = Action(ActionType.FOLD)
CHECK = Action(ActionType.CHECK)
CALL = Action(ActionType.CALL)


def raise_to(amount: int) -> Action:
    return Action(ActionType.RAISE, int(amount))


class Observation:
    """Snapshot handed to an agent when it must act. Immutable by convention.

    Seats are table-absolute indices 0..n-1. Cards are ints (see cards.py).
    """

    __slots__ = (
        "hand_number", "street", "seat", "button", "small_blind", "big_blind", "ante",
        "hole_cards", "board", "stacks", "bets", "committed", "in_hand", "all_in",
        "pot", "to_call", "can_check", "can_raise", "min_raise_to", "max_raise_to",
        "history", "num_players", "live_players",
    )

    def __init__(self, hand_number, street, seat, button, small_blind, big_blind, ante,
                 hole_cards, board, stacks, bets, committed, in_hand, all_in,
                 pot, to_call, can_check, can_raise, min_raise_to, max_raise_to,
                 history, num_players, live_players):
        self.hand_number = hand_number
        self.street = street
        self.seat = seat
        self.button = button
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.ante = ante
        self.hole_cards = hole_cards
        self.board = board
        self.stacks = stacks
        self.bets = bets
        self.committed = committed
        self.in_hand = in_hand
        self.all_in = all_in
        self.pot = pot
        self.to_call = to_call
        self.can_check = can_check
        self.can_raise = can_raise
        self.min_raise_to = min_raise_to
        self.max_raise_to = max_raise_to
        self.history = history
        self.num_players = num_players
        self.live_players = live_players

    # Convenience ---------------------------------------------------------
    @property
    def legal_actions(self) -> list[Action]:
        out = [FOLD]
        if self.can_check:
            out.append(CHECK)
        else:
            out.append(CALL)
        if self.can_raise:
            out.append(raise_to(self.min_raise_to))
            if self.max_raise_to != self.min_raise_to:
                out.append(raise_to(self.max_raise_to))
        return out

    @property
    def hole_cards_str(self) -> str:
        return " ".join(card_str(c) for c in self.hole_cards)

    @property
    def board_str(self) -> str:
        return " ".join(card_str(c) for c in self.board)

    def is_legal(self, a: Action) -> bool:
        k = a.kind
        if k == ActionType.FOLD:
            return True
        if k == ActionType.CHECK:
            return self.can_check
        if k == ActionType.CALL:
            return not self.can_check
        if k == ActionType.RAISE:
            return self.can_raise and self.min_raise_to <= a.amount <= self.max_raise_to
        return False

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["hole_cards"] = [card_str(c) for c in self.hole_cards]
        d["board"] = [card_str(c) for c in self.board]
        d["history"] = [list(h) for h in self.history]  # (street, seat, kind, amount)
        return d


@dataclass(frozen=True, slots=True)
class TableInfo:
    """Given to an agent when it is seated (bot state resets here)."""

    seat: int
    num_players: int
    starting_stack: int
    rules_name: str
    seed: int  # per-(table, seat) seed for any bot randomness


@runtime_checkable
class Agent(Protocol):
    def reset(self, table: TableInfo) -> None: ...

    def act(self, obs: Observation) -> Action: ...


def fallback_action(obs: Observation) -> Action:
    """Organizer rule 3.7: on error/timeout the bot folds, or checks if it can."""
    return CHECK if obs.can_check else FOLD


class AgentAdapter:
    """Wraps an Agent: validates, times, catches errors, applies the fallback.

    ``deadline_mode``: "enforce" | "record" | "off". Timing uses
    ``time.perf_counter_ns`` around the call; Python cannot interrupt the bot,
    so an overlong call still completes, and its result is replaced by the
    fallback in "enforce" mode.
    """

    __slots__ = ("agent", "deadline_ns", "mode", "n_calls", "n_timeouts", "n_errors",
                 "n_illegal", "latencies_ns", "record_latency", "last_error")

    def __init__(self, agent: Agent, deadline_ms: float = 1.0, mode: str = "enforce",
                 record_latency: bool = False):
        self.agent = agent
        self.deadline_ns = int(deadline_ms * 1_000_000)
        self.mode = mode
        self.record_latency = record_latency
        self.latencies_ns: list[int] = []
        self.n_calls = self.n_timeouts = self.n_errors = self.n_illegal = 0
        self.last_error: str | None = None

    def reset(self, table: TableInfo) -> None:
        try:
            self.agent.reset(table)
        except Exception as e:  # noqa: BLE001 - bot code is untrusted
            self.n_errors += 1
            self.last_error = repr(e)

    def act(self, obs: Observation) -> Action:
        self.n_calls += 1
        if self.mode == "off":
            try:
                a = self.agent.act(obs)
            except Exception as e:  # noqa: BLE001
                self.n_errors += 1
                self.last_error = repr(e)
                return fallback_action(obs)
        else:
            t0 = time.perf_counter_ns()
            try:
                a = self.agent.act(obs)
            except Exception as e:  # noqa: BLE001
                self.n_errors += 1
                self.last_error = repr(e)
                return fallback_action(obs)
            dt = time.perf_counter_ns() - t0
            if self.record_latency:
                self.latencies_ns.append(dt)
            if dt > self.deadline_ns:
                self.n_timeouts += 1
                if self.mode == "enforce":
                    return fallback_action(obs)
        if not isinstance(a, Action) or not obs.is_legal(a):
            self.n_illegal += 1
            return fallback_action(obs)
        return a

    def stats(self) -> dict:
        return {
            "calls": self.n_calls, "timeouts": self.n_timeouts,
            "errors": self.n_errors, "illegal": self.n_illegal,
        }
