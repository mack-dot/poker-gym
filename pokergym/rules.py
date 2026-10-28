"""Game-rule specification.

Everything the organizer has not confirmed is marked ``synthetic`` and lives
here so that it can be replaced in one place when the starter kit arrives.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from .evaluator import Evaluator, STANDARD_STRENGTH


# --------------------------------------------------------------------------
# Confirmed by https://pokerbot.sequoiacap.com/rules.html (see docs/spec).
# --------------------------------------------------------------------------
CONFIRMED_PLAYERS = 8
CONFIRMED_STARTING_STACK = 2000
CONFIRMED_INITIAL_BLINDS = (10, 20)
CONFIRMED_HANDS_PER_LEVEL = 25
CONFIRMED_MAX_HANDS = 200
CONFIRMED_DECISION_DEADLINE_MS = 1.0


@dataclass(frozen=True)
class BlindSchedule:
    """Blind levels. Level index = hands_played // hands_per_level.

    Only the first level (10/20) and the cadence (25 hands) are confirmed.
    The growth of later levels is SYNTHETIC until the organizer's schedule
    is available.
    """

    levels: tuple[tuple[int, int], ...]
    hands_per_level: int = CONFIRMED_HANDS_PER_LEVEL
    ante: tuple[int, ...] = ()  # optional per-level ante; empty = no ante
    label: str = "synthetic"

    def level_index(self, hand_number: int) -> int:
        """``hand_number`` is 0-based."""
        return min(hand_number // self.hands_per_level, len(self.levels) - 1)

    def blinds_for_hand(self, hand_number: int) -> tuple[int, int]:
        return self.levels[self.level_index(hand_number)]

    def ante_for_hand(self, hand_number: int) -> int:
        if not self.ante:
            return 0
        return self.ante[min(self.level_index(hand_number), len(self.ante) - 1)]


# SYNTHETIC: a smooth doubling-ish ladder. 200 hands / 25 = 8 levels needed.
SYNTHETIC_BLIND_SCHEDULE = BlindSchedule(
    levels=((10, 20), (15, 30), (25, 50), (50, 100), (75, 150), (100, 200), (150, 300), (200, 400)),
    hands_per_level=CONFIRMED_HANDS_PER_LEVEL,
    label="synthetic-v1 (first level and cadence confirmed; later levels invented)",
)


@dataclass(frozen=True)
class PayoutSchedule:
    """Points by finishing position (index 0 = 1st place). SYNTHETIC."""

    points: tuple[float, ...]
    label: str = "synthetic"

    def __post_init__(self):
        if len(self.points) != CONFIRMED_PLAYERS:
            raise ValueError("payout schedule must have 8 entries")
        if any(self.points[i] < self.points[i + 1] for i in range(len(self.points) - 1)):
            raise ValueError("payouts must be non-increasing by position")

    def for_position(self, position: int) -> float:
        """``position`` is 1-based."""
        return self.points[position - 1]


SYNTHETIC_PAYOUTS = PayoutSchedule(
    points=(100.0, 60.0, 40.0, 25.0, 15.0, 10.0, 5.0, 0.0),
    label="synthetic-v1 (organizer schedule unknown)",
)


@dataclass(frozen=True)
class BettingRules:
    """Betting-structure rules.

    ``limit``: ``"no_limit"`` (max raise = stack) or ``"pot_limit"`` (max raise
    bounded by the pot). ``raise_cap_per_street``: maximum number of raises
    (including the first bet) per street, or ``None`` for unlimited.
    """

    limit: str = "no_limit"
    raise_cap_per_street: int | None = None
    # Standard rule: an all-in raise smaller than a full raise does not reopen
    # the action for players who already acted since the last full raise.
    short_all_in_reopens: bool = False
    # Standard rule: the full big blind is the bet to match preflop even if
    # the big blind player is all-in for less.
    bb_is_min_bet_even_if_short: bool = True

    def __post_init__(self):
        if self.limit not in ("no_limit", "pot_limit"):
            raise ValueError(f"unknown limit {self.limit!r}")


@dataclass(frozen=True)
class HandRanking:
    """Which canonical category beats which. ``strength`` is a permutation of
    0..8 indexed by canonical category id (see evaluator)."""

    strength: tuple[int, ...] = STANDARD_STRENGTH
    name: str = "standard"

    def evaluator(self) -> Evaluator:
        return Evaluator(self.strength, self.name)


@dataclass(frozen=True)
class GameRules:
    name: str = "nlhe-baseline"
    description: str = "Standard no-limit Texas Hold'em (baseline reference game, NOT the secret variant)."
    players: int = CONFIRMED_PLAYERS
    starting_stack: int = CONFIRMED_STARTING_STACK
    max_hands: int = CONFIRMED_MAX_HANDS
    hole_cards: int = 2
    board_streets: tuple[int, ...] = (3, 1, 1)  # flop, turn, river
    blinds: BlindSchedule = SYNTHETIC_BLIND_SCHEDULE
    payouts: PayoutSchedule = SYNTHETIC_PAYOUTS
    betting: BettingRules = field(default_factory=BettingRules)
    ranking: HandRanking = field(default_factory=HandRanking)
    decision_deadline_ms: float = CONFIRMED_DECISION_DEADLINE_MS
    # "record":  default. Measure every call, count violations, but never let a
    #            wall-clock event change the game, so records replay exactly.
    # "enforce": apply the organizer's check/fold fallback on a timeout. Faithful
    #            to rule 3.7, but NOT reproducible: a GC pause in the measuring
    #            process replaces a decision and perturbs the rest of the table.
    #            Use only for final tournament-faithfulness runs, not for research.
    # "off":     no timing at all (fastest).
    deadline_mode: str = "record"

    def with_(self, **changes) -> "GameRules":
        return replace(self, **changes)

    def synthetic_components(self) -> list[str]:
        out = []
        if "synthetic" in self.blinds.label:
            out.append(f"blinds: {self.blinds.label}")
        if "synthetic" in self.payouts.label:
            out.append(f"payouts: {self.payouts.label}")
        return out


BASELINE_RULES = GameRules()


# --------------------------------------------------------------------------
# Machine-readable form (used by the arena to seal/reveal a variant and to
# ship it to the competitor workspace, and by the gym to pass rules to
# worker processes).
# --------------------------------------------------------------------------
def rules_to_dict(r: GameRules) -> dict:
    return {
        "name": r.name,
        "description": r.description,
        "players": r.players,
        "starting_stack": r.starting_stack,
        "max_hands": r.max_hands,
        "hole_cards": r.hole_cards,
        "board_streets": list(r.board_streets),
        "blinds": {
            "levels": [list(l) for l in r.blinds.levels],
            "hands_per_level": r.blinds.hands_per_level,
            "ante": list(r.blinds.ante),
            "label": r.blinds.label,
        },
        "payouts": {"points": list(r.payouts.points), "label": r.payouts.label},
        "betting": {
            "limit": r.betting.limit,
            "raise_cap_per_street": r.betting.raise_cap_per_street,
            "short_all_in_reopens": r.betting.short_all_in_reopens,
            "bb_is_min_bet_even_if_short": r.betting.bb_is_min_bet_even_if_short,
        },
        "ranking": {"strength": list(r.ranking.strength), "name": r.ranking.name},
        "decision_deadline_ms": r.decision_deadline_ms,
        "deadline_mode": r.deadline_mode,
    }


def rules_from_dict(d: dict) -> GameRules:
    b = d["blinds"]
    return GameRules(
        name=d["name"],
        description=d.get("description", ""),
        players=d["players"],
        starting_stack=d["starting_stack"],
        max_hands=d["max_hands"],
        hole_cards=d["hole_cards"],
        board_streets=tuple(d["board_streets"]),
        blinds=BlindSchedule(
            levels=tuple(tuple(l) for l in b["levels"]), hands_per_level=b["hands_per_level"],
            ante=tuple(b.get("ante", ())), label=b.get("label", "synthetic"),
        ),
        payouts=PayoutSchedule(points=tuple(d["payouts"]["points"]), label=d["payouts"].get("label", "synthetic")),
        betting=BettingRules(**d["betting"]),
        ranking=HandRanking(strength=tuple(d["ranking"]["strength"]), name=d["ranking"]["name"]),
        decision_deadline_ms=d.get("decision_deadline_ms", CONFIRMED_DECISION_DEADLINE_MS),
        deadline_mode=d.get("deadline_mode", "record"),
    )
