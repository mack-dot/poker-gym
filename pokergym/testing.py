"""Helpers for scripted, fully-controlled hands (tests and specs)."""
from __future__ import annotations

from typing import Callable, Sequence

from .agent import CALL, CHECK, Action, Observation, TableInfo
from .cards import fresh_deck, parse_cards


class ScriptedAgent:
    """Plays a fixed list of actions, then checks/calls. Records observations."""

    def __init__(self, actions: Sequence[Action] = (), on_exhausted: Action | None = None):
        self.script = list(actions)
        self.on_exhausted = on_exhausted
        self.observations: list[Observation] = []

    def reset(self, table: TableInfo) -> None:
        self.i = 0

    def act(self, obs: Observation) -> Action:
        self.observations.append(obs)
        if self.i < len(self.script):
            a = self.script[self.i]
            self.i += 1
            return a
        if self.on_exhausted is not None:
            return self.on_exhausted
        return CHECK if obs.can_check else CALL


class PolicyAgent:
    """Wraps a function ``obs -> Action``; records observations."""

    def __init__(self, fn: Callable[[Observation], Action]):
        self.fn = fn
        self.observations: list[Observation] = []

    def reset(self, table: TableInfo) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        self.observations.append(obs)
        return self.fn(obs)


class CrashingAgent:
    def reset(self, table: TableInfo) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        raise RuntimeError("boom")


def build_deck(hole: dict[int, str], board: str, sb_seat: int, live_seats: Sequence[int], hole_cards: int = 2) -> list[int]:
    """Construct a deck so that ``play_hand`` deals the requested cards.

    Dealing order is round-robin starting from the small blind. Unspecified
    seats receive unused cards. ``board`` lists the five community cards.
    """
    n_live = len(live_seats)
    order = []
    i = live_seats.index(sb_seat)
    for j in range(n_live):
        order.append(live_seats[(i + j) % n_live])
    wanted = {s: parse_cards(h) for s, h in hole.items()}
    board_cards = parse_cards(board)
    used = set(board_cards)
    for cs in wanted.values():
        used.update(cs)
    spare = [c for c in fresh_deck() if c not in used]
    deck: list[int] = []
    for r in range(hole_cards):
        for s in order:
            if s in wanted:
                deck.append(wanted[s][r])
            else:
                deck.append(spare.pop(0))
    deck.extend(board_cards)
    deck.extend(spare)
    assert len(deck) == 52 and len(set(deck)) == 52
    return deck
