"""Eight-player sit-and-go runner with deterministic records and scoring."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .agent import Agent, AgentAdapter, TableInfo
from .engine import HandRecord, play_hand
from .icm import icm_equities
from .rules import GameRules, BASELINE_RULES


@dataclass
class TournamentResult:
    seed: int
    rules_name: str
    hands_played: int
    final_stacks: list[int]
    positions: list[float]  # 1 = winner; ties share a fractional position
    points: list[float]
    icm_applied: bool
    icm_survivors: list[int]
    elimination_order: list[int]  # seats in order of elimination (first out first)
    agent_stats: list[dict]
    hands: list[HandRecord] = field(default_factory=list)
    record_hash: str = ""
    button_start: int = 0

    def to_dict(self, include_hands: bool = True) -> dict:
        d = {
            "seed": self.seed,
            "rules": self.rules_name,
            "button_start": self.button_start,
            "hands_played": self.hands_played,
            "final_stacks": self.final_stacks,
            "positions": self.positions,
            "points": self.points,
            "icm_applied": self.icm_applied,
            "icm_survivors": self.icm_survivors,
            "elimination_order": self.elimination_order,
            "agent_stats": self.agent_stats,
            "record_hash": self.record_hash,
        }
        if include_hands:
            d["hands"] = [h.to_dict() for h in self.hands]
        return d

    def to_json(self, include_hands: bool = True) -> str:
        return json.dumps(self.to_dict(include_hands), separators=(",", ":"))


def _hash_hands(hands: Sequence[HandRecord], final_stacks, points) -> str:
    h = hashlib.sha256()
    for rec in hands:
        h.update(json.dumps(rec.to_dict(), separators=(",", ":")).encode())
    h.update(json.dumps([final_stacks, points]).encode())
    return h.hexdigest()


def assign_finishes(busted: list[int], start_stacks: Sequence[int], next_position: int, payouts) -> list[tuple[int, float, float]]:
    """Rank players who busted in the same hand.

    A smaller stack at the start of the hand finishes in a worse position;
    equal stacks tie and share the points (and the position) of the slots
    they span. Returns ``[(seat, position, points), ...]``.
    """
    out = []
    busted = sorted(busted, key=lambda s: start_stacks[s])
    i = 0
    while i < len(busted):
        j = i
        while j + 1 < len(busted) and start_stacks[busted[j + 1]] == start_stacks[busted[i]]:
            j += 1
        group = busted[i: j + 1]
        pos_span = list(range(next_position - len(group) + 1, next_position + 1))
        avg_pts = sum(payouts.for_position(p) for p in pos_span) / len(group)
        avg_pos = sum(pos_span) / len(group)
        for s in group:
            out.append((s, avg_pos, avg_pts))
        next_position -= len(group)
        i = j + 1
    return out


def run_tournament(
    agents: Sequence[Agent],
    rules: GameRules = BASELINE_RULES,
    seed: int = 0,
    keep_hands: bool = True,
    button_start: int | None = None,
    record_latency: bool = False,
) -> TournamentResult:
    """Run one sit-and-go to completion.

    ``agents`` are seated in list order at seats 0..n-1. Determinism: all
    randomness comes from ``random.Random(seed)``; each agent receives its own
    per-seat seed through ``TableInfo``.
    """
    n = rules.players
    if len(agents) != n:
        raise ValueError(f"need exactly {n} agents, got {len(agents)}")
    rng = random.Random(seed)
    adapters = [
        AgentAdapter(a, rules.decision_deadline_ms, rules.deadline_mode, record_latency) for a in agents
    ]
    seat_seeds = [rng.getrandbits(32) for _ in range(n)]
    for s, ad in enumerate(adapters):
        ad.reset(TableInfo(seat=s, num_players=n, starting_stack=rules.starting_stack,
                           rules_name=rules.name, seed=seat_seeds[s]))
    stacks = [rules.starting_stack] * n
    button = rng.randrange(n) if button_start is None else button_start
    bstart = button
    evaluator = rules.ranking.evaluator()
    payouts = rules.payouts

    positions: list[float] = [0.0] * n
    points: list[float] = [0.0] * n
    elimination_order: list[int] = []
    next_position = n  # worst open finishing position
    hands: list[HandRecord] = []
    hands_played = 0

    for hand_number in range(rules.max_hands):
        live = [s for s in range(n) if stacks[s] > 0]
        if len(live) <= 1:
            break
        start_stacks = list(stacks)
        rec = play_hand(rules, evaluator, stacks, button, hand_number, adapters, rng)
        hands_played += 1
        if keep_hands:
            hands.append(rec)
        busted = [s for s in live if stacks[s] == 0]
        if busted:
            for s, pos, pts in assign_finishes(busted, start_stacks, next_position, payouts):
                positions[s] = pos
                points[s] = pts
                elimination_order.append(s)
            next_position -= len(busted)
        # Move the button to the next player with chips.
        b = (button + 1) % n
        while stacks[b] == 0:
            b = (b + 1) % n
        button = b

    survivors = [s for s in range(n) if stacks[s] > 0]
    icm_applied = False
    if len(survivors) == 1:
        positions[survivors[0]] = 1.0
        points[survivors[0]] = payouts.for_position(1)
    else:
        icm_applied = True
        remaining_pay = [payouts.for_position(p) for p in range(1, len(survivors) + 1)]
        eq = icm_equities([stacks[s] for s in survivors], remaining_pay)
        # Report an expected finishing position too (informational only).
        from .icm import place_probabilities

        probs = place_probabilities([stacks[s] for s in survivors])
        for i, s in enumerate(survivors):
            points[s] = eq[i]
            positions[s] = sum(probs[i][p] * (p + 1) for p in range(len(survivors)))

    result = TournamentResult(
        seed=seed, rules_name=rules.name, hands_played=hands_played, final_stacks=list(stacks),
        positions=positions, points=points, icm_applied=icm_applied, icm_survivors=survivors,
        elimination_order=elimination_order, agent_stats=[a.stats() for a in adapters],
        hands=hands, button_start=bstart,
    )
    result.record_hash = _hash_hands(hands, result.final_stacks, result.points) if keep_hands else ""
    if record_latency:
        result.agent_stats = [dict(a.stats(), latencies_ns=a.latencies_ns) for a in adapters]
    return result


# --------------------------------------------------------------------------
# Scored rounds (rule 4.3 / 4.7)
# --------------------------------------------------------------------------
AgentFactory = Callable[[], Agent]


@dataclass
class RoundScore:
    bot_names: list[str]
    tables: int
    avg_points: list[float]  # per bot, average points per table
    hands_total: int
    seed: int


def run_round(
    factories: Sequence[AgentFactory],
    names: Sequence[str],
    tables: int,
    seed: int,
    rules: GameRules = BASELINE_RULES,
) -> RoundScore:
    """Play ``tables`` sit-and-gos. With exactly 8 bots, every table seats all
    eight in a random order (rule 4.3). With fewer than 8 bots, empty seats
    are filled with random copies that earn no points (rule 4.6)."""
    nb = len(factories)
    if nb > rules.players:
        raise NotImplementedError("more than 8 bots: table assignment not implemented")
    rng = random.Random(seed)
    totals = [0.0] * nb
    hands_total = 0
    for t in range(tables):
        ids = list(range(nb))
        while len(ids) < rules.players:
            ids.append(rng.randrange(nb))  # filler copy
        rng.shuffle(ids)
        agents = [factories[i]() for i in ids]
        res = run_tournament(agents, rules, seed=rng.getrandbits(32), keep_hands=False)
        hands_total += res.hands_played
        seen = set()
        for seat, bid in enumerate(ids):
            if bid in seen:
                continue  # filler copy earns nothing; first occurrence scores
            seen.add(bid)
            totals[bid] += res.points[seat]
    return RoundScore(list(names), tables, [x / tables for x in totals], hands_total, seed)


ROUND_WEIGHTS = (1, 2, 3, 4, 5, 6)


def final_score(round_scores: Sequence[float], weights: Sequence[int] = ROUND_WEIGHTS) -> float:
    """Rule 4.7: sum of T_i * i for the six scored tournaments."""
    if len(round_scores) != len(weights):
        raise ValueError("need one score per scored tournament")
    return float(sum(s * w for s, w in zip(round_scores, weights)))
