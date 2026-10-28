"""Concealed rule-mutation reserve and generator.

``generate(seed)`` returns a ``Mutation``: one rule changed relative to the
baseline game, with machine-readable rules, a human briefing, a legal-action
definition, an independent correctness check over tournament records, a
per-table *signal* that must shift versus baseline, and the pair of
reference bots (adapted vs rule-naive) used to price the adaptation.

The two P0 variants (flush > full house; pot-limit) are excluded from the
reserve on purpose: the competitor has seen them.

Only mutations the engine executes exactly are listed. Not in the reserve
(engine does not support them): deck composition, hole-card count other
than 2 (sparring bots assume two cards), lowball/split showdowns, wild
cards, information restrictions. See docs/arena.md.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Callable

from ..checks import InvariantError, check_tournament
from ..evaluator import CATEGORY_NAMES, FLUSH, STANDARD_STRENGTH, STRAIGHT, TRIPS, TWO_PAIR, Evaluator
from ..rules import (BASELINE_RULES, BettingRules, BlindSchedule, GameRules, HandRanking,
                     PayoutSchedule, SYNTHETIC_BLIND_SCHEDULE, rules_from_dict,
                     rules_to_dict)
from ..tournament import TournamentResult
from . import independent_eval as IE

Check = Callable[[TournamentResult, GameRules], None]
Signal = Callable[[TournamentResult, GameRules], float]


@dataclass
class Mutation:
    family: str
    name: str
    seed: int
    params: dict
    rules: GameRules
    headline: str                       # one sentence: what changed
    invalidated: list[str]              # conventional assumptions that no longer hold
    legal_actions: str                  # text definition
    check: Check = field(repr=False)
    signal: Signal = field(repr=False)
    signal_name: str = ""
    signal_kind: str = "mean"           # "mean": per-table mean shifts; "pooled": total count over tables
    adapted_ref: str = "tag"            # bot spec that adapts via configure(rules)
    naive_ref: str = "pokergym.arena.naive_refs:NaiveTag"
    reveal_notes: list[str] = field(default_factory=list)

    # --- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "family": self.family, "name": self.name, "seed": self.seed, "params": self.params,
            "rules": rules_to_dict(self.rules), "headline": self.headline, "invalidated": self.invalidated,
            "legal_actions": self.legal_actions, "signal_name": self.signal_name,
            "adapted_ref": self.adapted_ref, "naive_ref": self.naive_ref, "reveal_notes": self.reveal_notes,
        }

    @staticmethod
    def from_dict(d: dict) -> "Mutation":
        m = FAMILIES[d["family"]](d["seed"], d["params"])
        # Rebuild from the stored rules (not from the generator) so that a
        # revealed file is authoritative even if the generator changes later.
        m.rules = rules_from_dict(d["rules"])
        return m

    def fingerprint(self) -> str:
        import json

        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    def briefing(self) -> str:
        return render_briefing(self)


# --------------------------------------------------------------------------
# Shared pieces
# --------------------------------------------------------------------------
_LEGAL_ACTIONS_NL = (
    "On your turn the observation gives you: `to_call`, `can_check`, `can_raise`, `min_raise_to`, "
    "`max_raise_to`. Legal replies: FOLD always; CHECK iff `can_check`; CALL iff not `can_check` "
    "(calls for less when you are short, automatically); RAISE(amount) iff `can_raise` and "
    "`min_raise_to <= amount <= max_raise_to`, where `amount` is the TOTAL bet-to for this street. "
    "Anything else, an exception, or a decision over the deadline is replaced by CHECK if legal else FOLD "
    "and counted against you."
)


def _mean_pot_bb(res: TournamentResult, rules: GameRules) -> float:
    tot = 0.0
    n = 0
    for h in res.hands:
        pot = sum(a for a, _, _ in h.pots)
        tot += pot / h.blinds[1]
        n += 1
    return tot / max(1, n)


def _base_check(res: TournamentResult, rules: GameRules) -> None:
    check_tournament(res, rules)


# --------------------------------------------------------------------------
# Family 1: hand ranking
# --------------------------------------------------------------------------
# Safe re-orderings only: categories detected by different code paths in the
# engine evaluator (the independent check verifies this empirically).
_RANK_OPTIONS = {
    # name: (strength overrides {canonical category: new strength}, "X", "Y") read as "X now beats Y"
    "two-pair-beats-trips": ({TWO_PAIR: 3, TRIPS: 2}, "two pair", "three of a kind"),
    "trips-beat-straight": ({TRIPS: 4, STRAIGHT: 3}, "three of a kind", "a straight"),
    "trips-beat-straight-and-flush": ({TRIPS: 5, STRAIGHT: 3, FLUSH: 4}, "three of a kind", "both a straight and a flush"),
    "two-pair-beats-trips-and-straight": ({TWO_PAIR: 4, TRIPS: 2, STRAIGHT: 3}, "two pair", "both three of a kind and a straight"),
}
# Measured and rejected (showdowns decided differently per table with the
# sparring roster): straight > flush 0.06, straight > full house 0.08,
# quads > straight flush and flush > quads ~0. Too rare to produce an
# observable strategic difference even over a 10,000-table round, so they
# are not in the reserve. Only categories detected by different code paths
# in the engine evaluator may be re-ordered (the independent check verifies).


def _ranking(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        name = rng.choice(sorted(_RANK_OPTIONS))
        params = {"option": name}
    name = params["option"]
    overrides, hi, lo = _RANK_OPTIONS[name]
    strength = list(STANDARD_STRENGTH)
    for cat, st in overrides.items():
        strength[cat] = st
    assert sorted(strength) == list(range(9)), strength
    ranking = HandRanking(strength=tuple(strength), name=name)
    order = [CATEGORY_NAMES[c] for c in sorted(range(9), key=lambda c: strength[c])]
    rules = BASELINE_RULES.with_(
        name=f"arena-ranking-{name}",
        description=f"NLHE with one hand-ranking change ({name}).",
        ranking=ranking,
    )

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        n_checked = 0
        for h in res.hands:
            if h.showdown_values is None:
                continue
            board = tuple(h.board)
            for amount, eligible, won in h.pots:
                if len(eligible) < 2:
                    continue
                hands = {s: tuple(h.hole[s]) + board for s in eligible}
                exp = IE.winners(hands, r.ranking.strength)
                if set(won) != exp:
                    raise InvariantError(f"hand {h.hand_number}: pot winners {won} != independent {sorted(exp)}")
                n_checked += 1
        if res.hands and n_checked == 0:
            raise InvariantError("no contested showdown to check")

    std = Evaluator()

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        """Number of contested showdowns whose winner set differs from the
        standard ranking's (pooled over tables; identically 0 at baseline)."""
        diff = n = 0
        for h in res.hands:
            if h.showdown_values is None:
                continue
            board = tuple(h.board)
            for amount, eligible, won in h.pots:
                if len(eligible) < 2:
                    continue
                vals = {s: std.evaluate(tuple(h.hole[s]) + board) for s in eligible}
                top = max(vals.values())
                std_w = {s for s in eligible if vals[s] == top}
                n += 1
                diff += std_w != set(won)
        return float(diff)

    return Mutation(
        family="hand_ranking", name=name, seed=seed, params=params, rules=rules,
        headline=f"Hand ranking changed: {hi} now beats {lo}. "
                 f"Full order, weakest first: {' < '.join(order)}.",
        invalidated=[
            f"{lo[0].upper()}{lo[1:]} no longer beats {hi}; relative hand values, "
            f"draw values and nut detection built for standard poker are wrong around this boundary.",
            "Any preflop/postflop equity numbers you remember assume the standard order.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL,
        check=check, signal=signal, signal_name="showdowns decided differently from the standard ranking",
        signal_kind="pooled", adapted_ref="tag", naive_ref="pokergym.arena.naive_refs:NaiveTag",
        reveal_notes=["The local simulator's evaluator implements the new order; `rules.ranking.strength` "
                      "is the permutation (index = standard category id, value = strength)."],
    )


# --------------------------------------------------------------------------
# Family 2: betting constraints (raise cap per street)
# --------------------------------------------------------------------------
def _raise_cap(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        params = {"cap": rng.choice([1, 2])}  # cap 3 measured as rarely binding vs the roster: excluded
    cap = params["cap"]
    rules = BASELINE_RULES.with_(
        name=f"arena-raise-cap-{cap}",
        description=f"No-limit hold'em but at most {cap} bet/raise(s) per street (preflop the big blind counts as the first).",
        betting=BettingRules(raise_cap_per_street=cap),
    )

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        for h in res.hands:
            per_street: dict[int, int] = {0: 1}  # BB is the first "raise" preflop
            for st, seat, kind, amt in h.actions:
                if kind == 3:
                    per_street[st] = per_street.get(st, 0) + 1
                    if per_street[st] > cap:
                        raise InvariantError(f"hand {h.hand_number}: {per_street[st]} raises on street {st} > cap {cap}")

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        """Hands in which some street saw more than ``cap`` bets/raises
        (pooled; identically 0 under the variant, positive at baseline)."""
        n = 0
        for h in res.hands:
            per_street: dict[int, int] = {0: 1}
            for st, seat, kind, amt in h.actions:
                if kind == 3:
                    per_street[st] = per_street.get(st, 0) + 1
            if max(per_street.values()) > cap:
                n += 1
        return float(n)

    return Mutation(
        family="betting", name=f"raise-cap-{cap}", seed=seed, params=params, rules=rules,
        headline=f"Betting is capped: at most {cap} bet or raise per street "
                 f"({'the big blind is the only preflop raise; nobody can raise preflop' if cap == 1 else 'preflop the big blind counts as the first'}). "
                 f"Sizes are still no-limit.",
        invalidated=[
            "You cannot always re-raise: 3-bets/4-bets may be illegal, so `can_raise` is False more often.",
            "Aggression cannot be escalated; the last legal raise locks the price for everyone.",
            "Protection by re-raising and 'raise to isolate' lines may be unavailable.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL + f" In this variant `can_raise` becomes False once {cap} bet/raise(s) have "
                      "been made on the street (big blind included preflop); CALL/CHECK/FOLD stay legal.",
        check=check, signal=signal, signal_name="hands where the cap would have been exceeded", signal_kind="pooled",
    )


# --------------------------------------------------------------------------
# Family 3: antes
# --------------------------------------------------------------------------
def _antes(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        params = {"frac": rng.choice([0.25, 0.5])}  # ante as a fraction of the big blind
    frac = params["frac"]
    ante = tuple(max(1, int(round(bb * frac))) for _, bb in SYNTHETIC_BLIND_SCHEDULE.levels)
    blinds = BlindSchedule(levels=SYNTHETIC_BLIND_SCHEDULE.levels, hands_per_level=SYNTHETIC_BLIND_SCHEDULE.hands_per_level,
                           ante=ante, label=SYNTHETIC_BLIND_SCHEDULE.label + f"; ante = {frac:g} x BB every hand (synthetic)")
    rules = BASELINE_RULES.with_(name=f"arena-antes-{frac:g}bb",
                                 description=f"NLHE with an ante of {frac:g} x big blind from every player each hand.",
                                 blinds=blinds)

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        for h in res.hands:
            a = r.blinds.ante_for_hand(h.hand_number)
            if h.ante != a:
                raise InvariantError(f"hand {h.hand_number}: ante {h.ante} != schedule {a}")
            live = [s for s in range(len(h.start_stacks)) if h.start_stacks[s] > 0]
            forced = sum(min(a, h.start_stacks[s]) for s in live)
            pot = sum(x for x, _, _ in h.pots)
            if pot < forced:
                raise InvariantError(f"hand {h.hand_number}: pot {pot} < antes {forced}")
            for s in live:
                # a player who folded without voluntary chips loses at least the ante
                acted = [k for st, seat, k, amt in h.actions if seat == s]
                if acted and acted[0] == 0 and s not in (h.sb_seat, h.bb_seat) and -h.net[s] < min(a, h.start_stacks[s]):
                    raise InvariantError(f"hand {h.hand_number}: seat {s} folded but lost {-h.net[s]} < ante")

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        """Dead money (blinds + antes) per hand in big blinds: the price of
        folding, which is what should move ranges."""
        tot = 0.0
        for h in res.hands:
            live = sum(1 for st in h.start_stacks if st > 0)
            tot += (h.blinds[0] + h.blinds[1] + h.ante * live) / h.blinds[1]
        return tot / max(1, len(res.hands))

    return Mutation(
        family="antes", name=f"antes-{frac:g}bb", seed=seed, params=params, rules=rules,
        headline=f"Every player posts an ante of {frac:g} x the big blind each hand ({ante[0]} chips at 10/20). "
                 f"Antes are in `obs.ante` and in `obs.pot`; they are not part of `obs.bets`.",
        invalidated=[
            "Preflop pots are larger, so folding is dearer and stealing is cheaper: open/defend ranges should widen.",
            "Pot odds computed from blinds only are wrong; use `obs.pot`.",
            "Stacks shrink every hand even when you never play: waiting is not free.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL + " Antes are posted automatically before cards are dealt.",
        check=check, signal=signal, signal_name="dead money per hand in big blinds",
    )


# --------------------------------------------------------------------------
# Family 4: blind structure
# --------------------------------------------------------------------------
def _blinds(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        params = {"hands_per_level": rng.choice([10, 15])}
    hpl = params["hands_per_level"]
    n_levels = (BASELINE_RULES.max_hands + hpl - 1) // hpl
    base = list(SYNTHETIC_BLIND_SCHEDULE.levels)
    levels = list(base)
    while len(levels) < n_levels:  # keep roughly doubling every two levels
        sb, bb = levels[-1]
        levels.append((int(sb * 1.5), int(bb * 1.5)))
    blinds = BlindSchedule(levels=tuple(levels[:n_levels]), hands_per_level=hpl,
                           label=f"turbo: level every {hpl} hands (synthetic ladder)")
    rules = BASELINE_RULES.with_(name=f"arena-turbo-{hpl}",
                                 description=f"NLHE with blinds rising every {hpl} hands instead of 25.",
                                 blinds=blinds)

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        for h in res.hands:
            exp = levels[min(h.hand_number // hpl, len(levels) - 1)]
            if tuple(h.blinds) != tuple(exp):
                raise InvariantError(f"hand {h.hand_number}: blinds {h.blinds} != {exp}")

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        return float(res.hands_played)

    return Mutation(
        family="blinds", name=f"turbo-{hpl}", seed=seed, params=params, rules=rules,
        headline=f"Blinds rise every {hpl} hands (not 25); the ladder reaches "
                 f"{levels[n_levels-1][0]}/{levels[n_levels-1][1]} by the hand cap. Starting stack is still 2,000.",
        invalidated=[
            "Effective stacks fall roughly twice as fast: push/fold thresholds arrive far earlier.",
            "A 'wait for a hand' plan loses more to blinds than usual.",
            "Hand-cap ICM is reached less often because tables finish sooner.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL,
        check=check, signal=signal, signal_name="hands played per table",
    )


# --------------------------------------------------------------------------
# Family 5: payout distribution
# --------------------------------------------------------------------------
_PAYOUT_OPTIONS = {
    "winner-take-all": (100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "top-heavy": (150.0, 60.0, 25.0, 10.0, 5.0, 3.0, 2.0, 0.0),
    "flat-top-four": (40.0, 40.0, 40.0, 40.0, 0.0, 0.0, 0.0, 0.0),
    "survival": (60.0, 55.0, 50.0, 45.0, 40.0, 30.0, 20.0, 0.0),
}


def _payouts(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        params = {"option": rng.choice(sorted(_PAYOUT_OPTIONS))}
    name = params["option"]
    pts = _PAYOUT_OPTIONS[name]
    payouts = PayoutSchedule(points=pts, label=f"variant payout '{name}' (synthetic numbers)")
    rules = BASELINE_RULES.with_(name=f"arena-payout-{name}",
                                 description=f"NLHE scored with the '{name}' payout table.", payouts=payouts)

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        n = r.players
        for s in res.elimination_order:
            pos = res.positions[s]
            if pos == int(pos):  # untied elimination: exact table lookup
                if abs(res.points[s] - pts[int(pos) - 1]) > 1e-9:
                    raise InvariantError(f"seat {s} finished {int(pos)} with {res.points[s]} != {pts[int(pos)-1]}")
        if abs(sum(res.points) - sum(pts)) > 1e-6:
            raise InvariantError("points not conserved")
        if not res.icm_applied and n:
            w = max(range(n), key=lambda s: res.final_stacks[s])
            if res.points[w] != pts[0]:
                raise InvariantError("winner points wrong")

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        """Winner's points minus everyone else's: the shape of the payout."""
        top = max(res.points)
        return top - (sum(res.points) - top)

    return Mutation(
        family="payouts", name=f"payout-{name}", seed=seed, params=params, rules=rules,
        headline=f"Payout table changed to '{name}': {', '.join(f'{p:g}' for p in pts)} points for 1st..8th. "
                 f"ICM at the hand cap uses this table.",
        invalidated=[
            "Risk/reward of survival vs chip accumulation changed: ICM pressure is " +
            ("gone (chips are everything; play for first)." if name == "winner-take-all" else
             "very different; the bubble and the value of laddering moved."),
            "Default 'top-half cashes' intuition does not hold.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL,
        check=check, signal=signal, signal_name="winner's points minus the field's",
        adapted_ref="icm", naive_ref="pokergym.arena.naive_refs:NaiveIcm",
        reveal_notes=["The payout table is in `payouts.json` and `rules.payouts.points`; the ICM calculator is in the kit."],
    )


# --------------------------------------------------------------------------
# Family 6: community-card distribution
# --------------------------------------------------------------------------
_BOARD_OPTIONS = {
    "two-two-one": (2, 2, 1),
    "four-one": (4, 1),
    "all-five": (5,),
}
# "three-two" (3+2) was measured and rejected: the first postflop decision
# still sees three cards, so nothing observable changes versus hold'em
# except one fewer betting round.


def _board(seed: int, params: dict | None) -> Mutation:
    rng = random.Random(seed)
    if params is None:
        params = {"option": rng.choice(sorted(_BOARD_OPTIONS))}
    name = params["option"]
    streets = _BOARD_OPTIONS[name]
    rules = BASELINE_RULES.with_(name=f"arena-board-{name}",
                                 description=f"Hold'em with community cards dealt {'+'.join(map(str, streets))} instead of 3+1+1.",
                                 board_streets=streets)
    n_streets = len(streets) + 1

    def check(res: TournamentResult, r: GameRules) -> None:
        _base_check(res, r)
        cum = [0]
        for c in streets:
            cum.append(cum[-1] + c)
        for h in res.hands:
            if len(h.board) != cum[-1]:
                raise InvariantError(f"hand {h.hand_number}: board has {len(h.board)} cards != {cum[-1]}")
            for st, seat, kind, amt in h.actions:
                if st >= n_streets:
                    raise InvariantError(f"hand {h.hand_number}: action on street {st} but only {n_streets} streets")

    def signal(res: TournamentResult, rules_: GameRules) -> float:
        """Board cards visible at the first postflop decision (3 in hold'em)."""
        tot = n = 0
        for h in res.hands:
            post = [st for st, *_ in h.actions if st > 0]
            if post:
                tot += sum(rules_.board_streets[: min(post)])
                n += 1
        return tot / n if n else 0.0

    return Mutation(
        family="board", name=f"board-{name}", seed=seed, params=params, rules=rules,
        headline=f"Community cards are dealt {' then '.join(map(str, streets))} ({n_streets} betting rounds, not 4). "
                 f"Five board cards in total; showdown is unchanged. `obs.street` runs 0..{n_streets-1}.",
        invalidated=[
            "Street names flop/turn/river do not apply; `len(obs.board)` is the truth.",
            "Draw and outs arithmetic (e.g. '2 cards to come on the flop') is wrong.",
            "Fewer or more betting rounds change how much can be bet before showdown.",
        ],
        legal_actions=_LEGAL_ACTIONS_NL,
        check=check, signal=signal, signal_name="board cards seen at the first postflop decision",
    )


FAMILIES: dict[str, Callable[[int, dict | None], Mutation]] = {
    "hand_ranking": _ranking,
    "betting": _raise_cap,
    "antes": _antes,
    "blinds": _blinds,
    "payouts": _payouts,
    "board": _board,
}


def generate(seed: int, family: str | None = None) -> Mutation:
    """Deterministic: the same seed always yields the same mutation."""
    rng = random.Random(("arena-mutation", seed).__repr__())
    fam = family or rng.choice(sorted(FAMILIES))
    return FAMILIES[fam](seed, None)


def reserve() -> list[Mutation]:
    """Every distinct mutation the generator can produce (for tests/audits)."""
    out = []
    for name in sorted(_RANK_OPTIONS):
        out.append(_ranking(0, {"option": name}))
    for cap in (1, 2):
        out.append(_raise_cap(0, {"cap": cap}))
    for frac in (0.25, 0.5):
        out.append(_antes(0, {"frac": frac}))
    for hpl in (10, 15):
        out.append(_blinds(0, {"hands_per_level": hpl}))
    for opt in sorted(_PAYOUT_OPTIONS):
        out.append(_payouts(0, {"option": opt}))
    for opt in sorted(_BOARD_OPTIONS):
        out.append(_board(0, {"option": opt}))
    return out


# --------------------------------------------------------------------------
# Briefing
# --------------------------------------------------------------------------
def render_briefing(m: Mutation) -> str:
    r = m.rules
    lines = [
        f"# Challenge briefing: {m.name}",
        "",
        "REHEARSAL. This is a Poker Gym rehearsal variant, not the organizer's. Payout and blind "
        "numbers marked synthetic are invented.",
        "",
        "## What changed (one rule)",
        "",
        m.headline,
        "",
        "## What did not change",
        "",
        f"- {r.players} players, {r.starting_stack} chips, {r.max_hands}-hand cap, ICM at the cap, state reset per table.",
        "- Two hole cards; five community cards in total; best five-card hand wins; standard ties split.",
        f"- {r.decision_deadline_ms:g} ms per decision; on error/timeout: check if legal else fold.",
        "",
        "## Conventional assumptions that are now wrong",
        "",
        *[f"- {x}" for x in m.invalidated],
        "",
        "## Legal actions",
        "",
        m.legal_actions,
        "",
        "## Blinds",
        "",
        f"Level every {r.blinds.hands_per_level} hands: " + ", ".join(f"{sb}/{bb}" for sb, bb in r.blinds.levels)
        + (f"; ante per level: {', '.join(map(str, r.blinds.ante))}" if r.blinds.ante else "; no ante")
        + f". ({r.blinds.label})",
        "",
        "## Payouts (points by finishing position, 1st..8th)",
        "",
        ", ".join(f"{p:g}" for p in r.payouts.points) + f". ({r.payouts.label})",
        "",
        "## Where it lives in the kit",
        "",
        "- `variant.json` is the machine-readable rules; `kit.load_rules()` returns a `GameRules`.",
        "- The local simulator (`kit/`) executes this variant; the hidden evaluator uses the same engine.",
        *[f"- {n}" for n in m.reveal_notes],
        "",
    ]
    return "\n".join(lines)
