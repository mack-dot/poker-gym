import random

from ..agent import CALL, CHECK, FOLD, Action, Observation, TableInfo, raise_to


class RandomBot:
    """Uniformly random legal policy; raise sizes uniform in the legal range.

    Randomness is seeded from ``TableInfo.seed`` so tournaments stay
    reproducible. ``fold_weight`` lets tests bias the policy."""

    name = "random"

    def __init__(self, p_raise: float = 0.3, p_fold: float = 0.15):
        self.p_raise = p_raise
        self.p_fold = p_fold
        self.rng = random.Random(0)

    def reset(self, table: TableInfo) -> None:
        self.rng = random.Random(table.seed)

    def act(self, obs: Observation) -> Action:
        r = self.rng.random()
        if obs.can_raise and r < self.p_raise:
            return raise_to(self.rng.randint(obs.min_raise_to, obs.max_raise_to))
        if not obs.can_check and r > 1.0 - self.p_fold:
            return FOLD
        return CHECK if obs.can_check else CALL
