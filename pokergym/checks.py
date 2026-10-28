"""Reusable invariant checkers over tournament records.

Used by the tests, by the CLI ``--verify`` flag, and by the fault-detection
tests (which feed deliberately corrupted records and expect failures).
Every checker raises ``InvariantError`` with a precise message.
"""
from __future__ import annotations

from .cards import DECK_SIZE
from .engine import HandRecord
from .rules import GameRules
from .tournament import TournamentResult


class InvariantError(AssertionError):
    pass


def _fail(msg: str):
    raise InvariantError(msg)


def check_card_conservation(rec: HandRecord) -> None:
    cards = [c for h in rec.hole if h is not None for c in h] + list(rec.board)
    if len(cards) != len(set(cards)):
        _fail(f"hand {rec.hand_number}: duplicate card dealt: {cards}")
    if any(c < 0 or c >= DECK_SIZE for c in cards):
        _fail(f"hand {rec.hand_number}: card out of range: {cards}")
    live = [s for s, st in enumerate(rec.start_stacks) if st > 0]
    for s in live:
        if rec.hole[s] is None:
            _fail(f"hand {rec.hand_number}: live seat {s} has no hole cards")
    for s, h in enumerate(rec.hole):
        if rec.start_stacks[s] == 0 and h is not None:
            _fail(f"hand {rec.hand_number}: busted seat {s} was dealt cards")


def check_chip_conservation(rec: HandRecord) -> None:
    if sum(rec.start_stacks) != sum(rec.stacks_after):
        _fail(
            f"hand {rec.hand_number}: chips not conserved {sum(rec.start_stacks)} -> {sum(rec.stacks_after)}"
        )
    if sum(rec.net) != 0:
        _fail(f"hand {rec.hand_number}: net does not sum to zero: {rec.net}")
    for s in range(len(rec.net)):
        if rec.start_stacks[s] + rec.net[s] != rec.stacks_after[s]:
            _fail(f"hand {rec.hand_number}: seat {s} start+net != after")
        if rec.stacks_after[s] < 0:
            _fail(f"hand {rec.hand_number}: negative stack at seat {s}")
    pot_total = sum(a for a, _, _ in rec.pots)
    gained = sum(x for x in rec.net if x > 0)
    lost = -sum(x for x in rec.net if x < 0)
    if gained != lost:
        _fail(f"hand {rec.hand_number}: gains {gained} != losses {lost}")
    if pot_total < lost:
        _fail(f"hand {rec.hand_number}: pots {pot_total} smaller than chips lost {lost}")


def check_rotation(result: TournamentResult, rules: GameRules) -> None:
    """Button moves to the next seat with chips; SB/BB follow (heads-up: button = SB)."""
    n = rules.players
    prev_button = None
    for rec in result.hands:
        live = [s for s in range(n) if rec.start_stacks[s] > 0]
        if rec.button not in live:
            _fail(f"hand {rec.hand_number}: button on a busted seat {rec.button}")
        if prev_button is not None:
            b = (prev_button + 1) % n
            while rec.start_stacks[b] == 0:
                b = (b + 1) % n
            if rec.button != b:
                _fail(f"hand {rec.hand_number}: button {rec.button} expected {b} (prev {prev_button})")
        prev_button = rec.button
        k = len(live)

        def nxt(s):
            s = (s + 1) % n
            while rec.start_stacks[s] == 0:
                s = (s + 1) % n
            return s

        if k == 2:
            exp_sb, exp_bb = rec.button, nxt(rec.button)
        else:
            exp_sb = nxt(rec.button)
            exp_bb = nxt(exp_sb)
        if (rec.sb_seat, rec.bb_seat) != (exp_sb, exp_bb):
            _fail(f"hand {rec.hand_number}: blinds ({rec.sb_seat},{rec.bb_seat}) expected ({exp_sb},{exp_bb})")
        # The first voluntary preflop action must come from the seat after the BB
        # (heads-up: the button) unless everyone before is all-in.
        exp_blinds = rules.blinds.blinds_for_hand(rec.hand_number)
        if rec.blinds != exp_blinds:
            _fail(f"hand {rec.hand_number}: blinds {rec.blinds} expected {exp_blinds}")


def check_blind_schedule(result: TournamentResult, rules: GameRules) -> None:
    for rec in result.hands:
        lvl = rec.hand_number // rules.blinds.hands_per_level
        exp = rules.blinds.levels[min(lvl, len(rules.blinds.levels) - 1)]
        if rec.blinds != exp:
            _fail(f"hand {rec.hand_number}: blinds {rec.blinds} != schedule {exp}")


def check_termination(result: TournamentResult, rules: GameRules) -> None:
    alive = sum(1 for s in result.final_stacks if s > 0)
    if result.hands_played > rules.max_hands:
        _fail(f"played {result.hands_played} > max {rules.max_hands}")
    if alive == 1 and result.icm_applied:
        _fail("ICM applied with a single survivor")
    if alive > 1 and result.hands_played < rules.max_hands:
        _fail(f"stopped after {result.hands_played} hands with {alive} players alive")
    if alive > 1 and not result.icm_applied:
        _fail("hand cap reached but ICM not applied")
    if sum(result.final_stacks) != rules.starting_stack * rules.players:
        _fail("final chips not conserved")


def check_points(result: TournamentResult, rules: GameRules) -> None:
    total = sum(rules.payouts.points)
    if abs(sum(result.points) - total) > 1e-6:
        _fail(f"points sum {sum(result.points)} != payout total {total}")
    n = rules.players
    # Eliminated players: positions are consistent with elimination order
    # (earlier out => worse position, ties allowed).
    pos_by_elim = [result.positions[s] for s in result.elimination_order]
    for a, b in zip(pos_by_elim, pos_by_elim[1:]):
        if a < b:
            _fail(f"elimination order inconsistent with positions: {pos_by_elim}")
    for s in range(n):
        if result.final_stacks[s] > 0 and s in result.elimination_order:
            _fail(f"seat {s} eliminated but has chips")
        if result.final_stacks[s] == 0 and s not in result.elimination_order:
            _fail(f"seat {s} busted but not in elimination order")
    if not result.icm_applied:
        winner = max(range(n), key=lambda s: result.final_stacks[s])
        if result.positions[winner] != 1.0 or result.points[winner] != rules.payouts.for_position(1):
            _fail("winner did not receive first-place points")


def check_tournament(result: TournamentResult, rules: GameRules) -> None:
    """Run every record-level invariant on a tournament result with hands kept."""
    if not result.hands:
        _fail("result has no hand records; run with keep_hands=True")
    for rec in result.hands:
        check_card_conservation(rec)
        check_chip_conservation(rec)
    check_rotation(result, rules)
    check_blind_schedule(result, rules)
    check_termination(result, rules)
    check_points(result, rules)
