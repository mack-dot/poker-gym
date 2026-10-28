from pokergym.agent import Observation
from pokergym.bots import features as F
from pokergym.cards import parse_cards


def feats(hole, board):
    return F.hand_features(parse_cards(hole), parse_cards(board))


def test_made_hand_classes():
    assert feats("AsKd", "Kh7c2d").made == F.MADE_TOP_PAIR
    assert feats("AsKd", "Kh7c2d").kicker_good
    assert feats("Ks4d", "Kh7c2d").made == F.MADE_TOP_PAIR
    assert not feats("Ks4d", "Kh7c2d").kicker_good
    assert feats("QsQd", "Jh7c2d").made == F.MADE_OVERPAIR
    assert feats("9s9d", "Jh7c2d").made == F.MADE_MID_PAIR
    assert feats("5s5d", "Jh7c2d").made == F.MADE_WEAK_PAIR
    assert feats("As7d", "Jh7c2d").made == F.MADE_MID_PAIR
    assert feats("As2s", "Jh7c2d").made == F.MADE_WEAK_PAIR
    assert feats("Js7d", "Jh7c2d").made == F.MADE_TWO_PAIR_PLUS
    assert feats("7s7d", "Jh7c2d").made == F.MADE_TWO_PAIR_PLUS  # set
    assert feats("Ts9d", "Jh8c7d").made == F.MADE_NUTTISH  # straight
    assert feats("AsKs", "Qs9s2s").made == F.MADE_NUTTISH  # flush
    assert feats("As3d", "Jh7c2d").made == F.MADE_NONE


def test_board_pair_does_not_inflate():
    # Board pair + one pair = "two pair" category, but effectively one pair.
    f = feats("AsKd", "Kh7c7d")
    assert f.category == 2  # TWO_PAIR by category
    assert f.made == F.MADE_TOP_PAIR
    # Pocket pair under a paired board: a mid pair
    f = feats("9s9d", "Kh7c7d")
    assert f.made == F.MADE_MID_PAIR
    # Unpaired hole cards on a paired board: nothing
    assert feats("As3d", "Kh7c7d").made == F.MADE_NONE
    # Board plays: five-card board makes the hand without us
    f = feats("7s2d", "AhAcAdKsKh")
    assert f.plays_board and f.made == F.MADE_NONE


def test_draws_and_outs():
    f = feats("As5s", "Ks9s2c")
    assert f.flush_draw and f.outs >= 9
    f = feats("JsTd", "9h8c2d")
    assert f.oesd and not f.gutshot and f.outs >= 8
    f = feats("JsTd", "9h7c2d")
    assert f.gutshot and f.outs >= 4
    f = feats("JsTs", "9s8s2d")
    assert f.flush_draw and f.oesd and f.outs >= 13
    f = feats("As3d", "Kh7c2d")
    assert not f.flush_draw and not f.oesd and not f.gutshot
    # No draws when already made
    f = feats("JsTd", "9h8c7d")
    assert not f.oesd and f.outs == 0
    assert F.draw_equity(feats("As5s", "Ks9s2c"), 1) > 0.3
    assert F.draw_equity(feats("As5s", "Ks9s2c7d"), 2) > 0.15
    assert F.draw_equity(feats("As5s", "Ks9s2c7d3h"), 3) == 0


def test_board_texture_flags():
    assert feats("As3d", "Kh7h2h").board_flush3
    assert feats("As3d", "Kh7h2h4h").board_flush4
    assert feats("As3d", "9h8c7d").board_straighty
    assert not feats("As3d", "Kh7c2d").board_straighty
    assert feats("As3d", "Kh7c7d").board_paired


def _obs(seat, button, stacks, committed=None, in_hand=None):
    n = len(stacks)
    committed = committed or [0] * n
    in_hand = in_hand or [s > 0 for s in stacks]
    return Observation(0, 0, seat, button, 10, 20, 0, (0, 1), (), tuple(stacks), tuple([0] * n),
                       tuple(committed), tuple(in_hand), tuple([False] * n), 30, 20, False, True, 40, 2000, (), n, n)


def test_table_position_full_ring():
    stacks = [2000] * 8
    pos = F.table_position(_obs(seat=3, button=0, stacks=stacks))
    assert pos.order == [1, 2, 3, 4, 5, 6, 7, 0]
    assert pos.index == 2 and pos.bucket == 0  # UTG
    assert pos.behind == 7  # 4 more before the button, then SB, BB
    assert F.table_position(_obs(0, 0, stacks)).is_button
    assert F.table_position(_obs(1, 0, stacks)).is_sb
    assert F.table_position(_obs(2, 0, stacks)).is_bb
    assert F.table_position(_obs(1, 0, stacks)).behind == 1
    assert F.table_position(_obs(2, 0, stacks)).behind == 0
    assert F.table_position(_obs(0, 0, stacks)).behind == 2


def test_table_position_skips_busted_and_handles_heads_up():
    stacks = [2000, 0, 0, 2000, 0, 2000, 0, 2000]
    pos = F.table_position(_obs(seat=5, button=3, stacks=stacks))
    assert pos.order == [5, 7, 0, 3]
    assert pos.is_sb and pos.players == 4
    # busted seat with chips committed this hand still counts as dealt in
    stacks2 = [2000, 0, 0, 2000, 0, 0, 0, 2000]
    pos2 = F.table_position(_obs(seat=0, button=3, stacks=stacks2, committed=[0, 0, 0, 0, 0, 20, 0, 0]))
    assert 5 in pos2.order
    hu = F.table_position(_obs(seat=3, button=3, stacks=[0, 0, 0, 1000, 0, 0, 0, 3000]))
    assert hu.order == [3, 7] and hu.is_button and hu.is_sb and hu.bucket == 2 and hu.behind == 1
    hu2 = F.table_position(_obs(seat=7, button=3, stacks=[0, 0, 0, 1000, 0, 0, 0, 3000]))
    assert hu2.bucket == 4 and hu2.behind == 0
